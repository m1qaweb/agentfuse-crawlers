"""Offline comparison of two operator-run Zyte canaries against a pinned plan.

Consumes immutable, verified P07 job archives only. Never launches, approves,
or schedules a crawl. Historical 'proven' is NOT reviewed collection eligibility.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import load_archive
from scripts.canary_rollout import ROUNDS, SPIDERS
from scripts.evaluate_run import _healthy_for_typed_diffs


def load_mapping(path):
    """CSV with source_id,round,archive_path. Paths are local private data."""
    mapping = {}
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not {"source_id", "round", "archive_path"} <= set(reader.fieldnames or []):
            raise ValueError("Mapping requires source_id,round,archive_path")
        for entry in reader:
            sid = entry["source_id"]
            try:
                round_number = int(entry["round"])
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid canary round") from exc
            key = (sid, round_number)
            if (key in mapping or round_number not in range(1, ROUNDS + 1)
                    or not entry["archive_path"]):
                raise ValueError("Duplicate/invalid canary mapping")
            mapping[key] = Path(entry["archive_path"])
    return mapping


def _preflight(plan):
    if (not isinstance(plan, dict) or plan.get("schema_version") != "1.0"
            or plan.get("kind") != "manual_validation_canary_plan"
            or plan.get("execution_permitted") is not False
            or plan.get("repeats") != ROUNDS
            or plan.get("network_requests_performed") != 0
            or plan.get("approved_for_advisor") is not False):
        raise ValueError("Canary plan must be an unapproved two-round dry run")
    catalog = load_sources()
    known = {s["id"]: s for s in catalog}
    if (plan.get("manifest_sha256") != manifest_sha256(catalog)
            or plan.get("source_registry_sha256") != registry_revision_sha256()):
        raise ValueError("Manifest or policy registry changed after canary plan creation")
    ids = plan.get("source_ids")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 9
            or len(set(ids)) != len(ids)
            or any(x not in known for x in ids)):
        raise ValueError("Invalid or unknown source selection in canary plan")
    if (plan.get("source_count") != len(ids)
            or plan.get("total_expected_jobs") != ROUNDS * len(ids)):
        raise ValueError("Canary source count does not match exact job scope")
    expected = {(sid, round_number) for sid in ids
                for round_number in range(1, ROUNDS + 1)}
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != len(expected):
        raise ValueError("Incomplete or duplicate canary job specifications")
    actual = {}
    for job in jobs:
        key = (job.get("source_id"), job.get("round"))
        if key not in expected or key in actual:
            raise ValueError("Unexpected/duplicate canary job specification")
        src = known[key[0]]
        expected_args = {
            "cohort": "all", "source_ids": src["id"],
            "collection_mode": "validation",
            "expected_manifest_sha256": plan["manifest_sha256"],
            "expected_selection_ids_sha256": selection_ids_sha256([src]),
            "expected_source_registry_sha256": plan["source_registry_sha256"],
        }
        if (job.get("spider") != SPIDERS[src["category"]]
                or job.get("category") != src["category"]
                or job.get("source_url") != src["url"]
                or job.get("spider_args") != expected_args
                or job.get("execution_status")
                    != "not_scheduled_requires_operator_authorization"):
            raise ValueError("Unpinned or unauthorized canary job arguments")
        permitted, reason = collection_decision(src, "validation")
        if not permitted:
            raise ValueError("Quarantined/blocked source cannot be a canary")
        actual[key] = job
    return known, actual


def _same_host(url, source_url):
    try:
        parsed = urlsplit(url)
        expected = urlsplit(source_url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname == expected.hostname
            and not parsed.username and not parsed.password
            and parsed.port in (None, 443)
        )
    except (TypeError, ValueError):
        return False


def score_canaries(plan, archives):
    """Return precise diagnostic counts; no approved facts or permissions."""
    known, jobs = _preflight(plan)
    if any(key not in jobs for key in archives):
        raise ValueError("Archive mapping contains an unplanned source or round")
    outcomes = []
    finished_times = {}
    reviewed_eligible = {
        sid for sid in plan["source_ids"]
        if collection_decision(known[sid], "monitor")[0]
    }
    for job in plan["jobs"]:
        sid, round_number = job["source_id"], job["round"]
        key = sid, round_number
        path = archives.get(key)
        if path is None:
            outcomes.append({
                "source_id": sid, "round": round_number,
                "status": "missing_archive", "usable": False,
                "job_id": None, "job_identity_valid": False,
                "reviewed_collection_eligible": sid in reviewed_eligible,
                "policy_violation": False, "unapproved_fact_count": 0,
                "memory_peak_bytes": None, "reason": "no_completed_job_archive",
            })
            continue
        envelope, items = load_archive(path)  # Throws on checksum corruption.
        official_job = envelope["job"]
        scope = envelope.get("source_scope") or {}
        expected_args = job["spider_args"]
        exact_args = official_job.get("spider_args") or {}
        identity_ok = bool(
            official_job.get("spider") == job["spider"]
            and official_job.get("category") == job["category"]
            and official_job.get("state") == "finished"
            and official_job.get("close_reason") == "finished"
            and all(exact_args.get(k) == v for k, v in expected_args.items())
            and len(items) == 1
            and envelope.get("source_summary_count") == 1
            and scope.get("safe_for_semantic_diff") is True
        )
        item = items[0] if len(items) == 1 else None
        if item is not None:
            identity_ok = identity_ok and bool(
                item.get("source_id") == sid
                and item.get("category") == job["category"]
                and item.get("provider") == known[sid]["provider"]
                and item.get("source_url") == known[sid]["url"]
                and item.get("manifest_sha256") == plan["manifest_sha256"]
                and item.get("source_registry_sha256") == plan["source_registry_sha256"]
                and item.get("selection_ids_sha256")
                    == expected_args["expected_selection_ids_sha256"]
                and item.get("selection_source_count") == 1
                and item.get("requested_cohort") == "all"
                and item.get("collection_mode") == "validation"
                and item.get("spider_name") == job["spider"]
            )
        policy_violation = bool(
            item and (
                item.get("source_policy_status") in {"unresolved", "prohibited_reviewed"}
                or item.get("source_lifecycle_state") in {"quarantined", "retired"}
            )
        )
        final_url = (item or {}).get("final_url") or known[sid]["url"]
        identity_ok = identity_ok and _same_host(final_url, known[sid]["url"])
        approved_count = int(bool(item and item.get("approved_for_advisor") is not False))
        usable = bool(
            identity_ok and not policy_violation and approved_count == 0
            and item and _healthy_for_typed_diffs(item)
        )
        finished_times[key] = official_job.get("finished_time_ms")
        memory = official_job.get("stats", {}).get("memusage/max")
        outcomes.append({
            "source_id": sid, "round": round_number,
            "status": (item or {}).get("status") or "unknown",
            "usable": usable,
            "job_id": official_job.get("job_id"),
            "job_identity_valid": identity_ok,
            "reviewed_collection_eligible": sid in reviewed_eligible,
            "policy_violation": policy_violation,
            "unapproved_fact_count": approved_count,
            "memory_peak_bytes": memory,
            "reason": "usable_unverified_capture" if usable
                      else "source_or_job_not_comparable",
        })
    unique_jobs = [row["job_id"] for row in outcomes if row["job_id"]]
    duplicate_job = len(set(unique_jobs)) != len(unique_jobs)
    ordered = True
    for sid in plan["source_ids"]:
        older = finished_times.get((sid, 1))
        newer = finished_times.get((sid, 2))
        if older is not None and newer is not None and (
            not isinstance(older, (int, float)) or
            not isinstance(newer, (int, float)) or newer <= older
        ):
            ordered = False

    eligible_rounds = [x for x in outcomes if x["reviewed_collection_eligible"]]
    denom = len(reviewed_eligible) * ROUNDS
    rate = (
        round(sum(x["usable"] for x in eligible_rounds) / denom, 5)
        if denom else None
    )
    problems = (
        duplicate_job or not ordered
        or any(row["policy_violation"] or row["unapproved_fact_count"]
               or not row["job_identity_valid"] for row in outcomes)
    )
    eligible_complete = bool(
        denom and len(eligible_rounds) == denom
        and all(row["job_id"] for row in eligible_rounds)
    )
    return {
        "schema_version": "1.0",
        "report_kind": "offline_two_round_canary_score",
        "synthetic_only": False,
        "manifest_sha256": plan["manifest_sha256"],
        "source_registry_sha256": plan["source_registry_sha256"],
        "network_requests_performed_by_evaluator": 0,
        "source_count": len(plan["source_ids"]),
        "expected_jobs": len(jobs),
        "observed_archives": len(unique_jobs),
        "archive_mapping_complete": len(unique_jobs) == len(jobs),
        "duplicate_job_id": duplicate_job,
        "strict_round_order": ordered,
        "source_accounting_complete": bool(
            len(unique_jobs) == len(jobs)
            and all(x["job_identity_valid"] for x in outcomes)
            and not duplicate_job
        ),
        "policy_violation_count": sum(x["policy_violation"] for x in outcomes),
        "advisor_approval_anomaly_count": sum(x["unapproved_fact_count"] for x in outcomes),
        "usable_diagnostic_captures": sum(x["usable"] for x in outcomes),
        "reviewed_collection_eligible_sources": len(reviewed_eligible),
        "reviewed_eligible_rounds": denom,
        "reviewed_eligible_usable_rate": rate,
        "two_round_95pct_gate": bool(
            eligible_complete and not problems and rate is not None
            and rate >= .95 and len(unique_jobs) == len(jobs)
        ),
        "max_memory_peak_bytes": max(
            (x["memory_peak_bytes"] for x in outcomes
             if isinstance(x["memory_peak_bytes"], (int, float))), default=None
        ),
        "outcomes": outcomes,
        "approved_for_advisor": False,
        "notice": (
            "Canary captures are unverified. Successful manual validation does "
            "not grant publisher collection approval. Zero reviewed-eligible "
            "sources means the 95% gate is NOT EVALUATED, never passed."
        ),
    }


def write_score(report, out_dir):
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "canary_score.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (target / "canary_source_outcomes.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        columns = [
            "source_id", "round", "status", "usable", "job_id",
            "job_identity_valid", "reviewed_collection_eligible",
            "policy_violation", "unapproved_fact_count",
            "memory_peak_bytes", "reason",
        ]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(report["outcomes"])
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--archives", type=Path,
                        help="CSV: source_id,round,archive_path")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/canary-score"))
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    mapping = load_mapping(args.archives) if args.archives else {}
    report = score_canaries(plan, mapping)
    write_score(report, args.out_dir)
    print(json.dumps({
        "expected_jobs": report["expected_jobs"],
        "observed_archives": report["observed_archives"],
        "reviewed_eligible_sources": report["reviewed_collection_eligible_sources"],
        "two_round_95pct_gate": report["two_round_95pct_gate"],
    }, indent=2))


if __name__ == "__main__":
    main()
