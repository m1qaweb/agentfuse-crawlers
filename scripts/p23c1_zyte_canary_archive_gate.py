"""P23C1: offline, attrition-aware Zyte canary archive accession.

Binds the frozen P20A 18-source/36-round denominator to P23B's exact
single-source publisher-access reviews and the existing immutable Zyte
Items archive format. No request, credential, Zyte job, policy approval,
HTML collection, human gold or trustworthy publisher-fact claim is created.

A Zyte Items archive proves internal byte consistency only. Independently
inspected Requests, Logs, original publisher HTML, remote deployment and
operator authorization remain mandatory before claiming a clean canary.
"""
import argparse
import csv
import io
import json
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.validation_access import (
    _utc, digest, load_access_registry, validate_access_registry,
    validation_access_decision, validation_access_revision_sha256,
)
from scripts.accession_cross_category_html import frozen_plan, validate_plan
from scripts.archive_jobs import JOB_ID, SPIDERS, archive_path, load_archive
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)

VERSION = "1.0"
KIND = "p23c1_frozen_18_source_zyte_item_archive_gate_NOT_CRAWL_AUTHORIZATION"
LEDGER_KIND = "p23c1_blank_or_private_operator_36_job_receipt_index"
ROUND_FIELDS = frozenset({"round", "zyte_job_id"})
ROW_FIELDS = frozenset({
    "source_id", "source_url", "category", "wave", "rounds",
})
LEDGER_FIELDS = frozenset({
    "schema_version", "kind", "frozen_plan_sha256",
    "manifest_sha256", "source_registry_sha256",
    "expected_package_sha256", "approved_for_advisor", "rows",
})
CSV_FIELDS = (
    "wave", "source_id", "category", "round", "policy_access_status",
    "slot_state", "zyte_job_id", "http_status", "observed_item_status",
    "archive_item_integrity_checked", "original_html_verified",
    "requests_and_logs_independently_inspected",
)


def _clock(now=None):
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise ValueError("Operator audit timestamp must be timezone-aware")
    return clock.astimezone(timezone.utc)


def _source_map(plan):
    validate_plan(plan)
    src = {s["id"]: s for s in load_sources()}
    if len(src) != 460 or len(plan["sources"]) != 18:
        raise ValueError("Frozen 460 / 18 source denominator changed")
    if any(
        src[s["source_id"]]["url"] != s["source_url"]
        or src[s["source_id"]]["category"] != s["category"]
        for s in plan["sources"]
    ):
        raise ValueError("Frozen P20A source ID/URL/category changed")
    return src


def blank_receipts(plan=None):
    """Never prefill a purported job ID, policy decision or real receipt."""
    plan = frozen_plan() if plan is None else plan
    _source_map(plan)
    return {
        "schema_version": VERSION,
        "kind": LEDGER_KIND,
        "frozen_plan_sha256": plan["plan_sha256"],
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "expected_package_sha256": package_fingerprint(),
        "approved_for_advisor": False,
        "rows": [{
            "source_id": row["source_id"], "source_url": row["source_url"],
            "category": row["category"], "wave": row["wave"],
            "rounds": [
                {"round": 1, "zyte_job_id": None},
                {"round": 2, "zyte_job_id": None},
            ],
        } for row in plan["sources"]],
    }


def _validate_receipts(plan, receipts):
    expected = blank_receipts(plan)
    if (not isinstance(receipts, dict)
            or set(receipts) != LEDGER_FIELDS
            or any(receipts[k] != expected[k] for k in
                   LEDGER_FIELDS - {"rows"})
            or not isinstance(receipts["rows"], list)
            or len(receipts["rows"]) != 18):
        raise ValueError("Missing/stale/privileged frozen P23C1 receipt ledger")
    seen_jobs = set()
    for expected_row, row in zip(expected["rows"], receipts["rows"]):
        if (not isinstance(row, dict) or set(row) != ROW_FIELDS
                or any(row[k] != expected_row[k] for k in
                       ROW_FIELDS - {"rounds"})
                or not isinstance(row["rounds"], list)
                or len(row["rounds"]) != 2):
            raise ValueError("P20A original source, wave, or rounds replaced")
        for round_no, slot in enumerate(row["rounds"], start=1):
            if (not isinstance(slot, dict)
                    or set(slot) != ROUND_FIELDS
                    or type(slot["round"]) is not int
                    or slot["round"] != round_no):
                raise ValueError("A frozen source round is missing/reordered")
            job_id = slot["zyte_job_id"]
            if job_id is not None:
                if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
                    raise ValueError("Invalid exact Zyte job key in private receipt")
                if job_id in seen_jobs:
                    raise ValueError("One Zyte job cannot satisfy two evidence rounds")
                seen_jobs.add(job_id)
        if (row["rounds"][0]["zyte_job_id"] is None
                and row["rounds"][1]["zyte_job_id"] is not None):
            raise ValueError("Second round cannot precede first-round accession")
    return receipts


def _ensure_archive(root, job_id):
    folder = archive_path(root, job_id)
    if (not folder.is_dir() or folder.is_symlink()
            or any(p.is_symlink() for p in folder.parents)):
        raise ValueError("Missing or symlinked private Zyte job archive")
    # A one-source archive is bounded. Check sizes before deserializing any
    # archive, including its otherwise unauthenticated envelope metadata.
    for name, max_bytes in (
        ("envelope.json", 2_000_000),
        ("index.json", 2_000_000),
        ("items.jsonl.gz", 3_000_000),
    ):
        file = folder / name
        if (not file.is_file() or file.is_symlink()
                or not 0 < file.stat().st_size <= max_bytes):
            raise ValueError("Missing, linked, empty or oversized Zyte archive file")
    return folder


def _audit_archive(root, job_id, source, access, now):
    envelope, records = load_archive(_ensure_archive(root, job_id))
    job = envelope["job"]
    scope = envelope["source_scope"]
    if (job["job_id"] != job_id or job["state"] != "finished"
            or job["spider"] != {
                "documentation": "official_documentation",
                "pricing": "official_pricing",
                "changelog": "official_changelogs",
            }[source["category"]]
            or job["category"] != source["category"]
            or job.get("expected_item_count") != 1
            or envelope["source_summary_count"] != 1
            or len(records) != 1
            or envelope.get("approved_for_advisor") is not False
            or envelope.get("source_evidence_is_unverified") is not True
            or job.get("unrecorded_argument_names") != []
            or scope.get("safe_for_semantic_diff") is not True):
        raise ValueError("Zyte archive is not one complete, unverified exact-source job")
    args = job["spider_args"]
    if (set(args) - {
                "cohort", "source_ids", "collection_mode",
                "expected_manifest_sha256", "expected_selection_ids_sha256",
                "expected_source_registry_sha256",
            }
            or args.get("cohort") != "all"
            or args.get("collection_mode") != "validation"
            or args.get("source_ids") != source["id"]
            or args.get("expected_manifest_sha256") != manifest_sha256()
            or args.get("expected_selection_ids_sha256") !=
                selection_ids_sha256([source])
            or args.get("expected_source_registry_sha256") !=
                registry_revision_sha256()):
        raise ValueError("Archived Zyte job lacks exact pinned P20A single-source UI args")
    item = records[0]
    if (item.get("source_id") != source["id"]
            or item.get("source_url") != source["url"]
            or item.get("provider") != source["provider"]
            or item.get("category") != source["category"]
            or item.get("spider_name") != job["spider"]
            or item.get("collection_mode") != "validation"
            or item.get("validation_scope") != "single_exact_source"
            or item.get("single_validation_access_required") is not True
            or item.get("bulk_validation_required") is not False
            or item.get("run_scope_explicit") is not True
            or item.get("selection_source_count") != 1
            or item.get("selection_ids_sha256") != selection_ids_sha256([source])
            or item.get("manifest_sha256") != manifest_sha256()
            or item.get("source_registry_sha256") != registry_revision_sha256()
            or item.get("bulk_access_registry_sha256") !=
                validation_access_revision_sha256(access)
            or item.get("deployment_revision") != package_fingerprint()
            or item.get("zyte_job_id") != job_id
            or item.get("approved_for_advisor") is not False):
        raise ValueError("Zyte Item is not bound to exact reviewed P23B deployed scope")
    started = _utc(item.get("run_started_at_utc"))
    if started > now + timedelta(minutes=5):
        raise ValueError("Zyte archive claims future job start time")
    review = access["reviews"].get(source["id"])
    if review is None or not (
            _utc(review["reviewed_at_utc"]) <= started
            < _utc(review["expires_at_utc"])):
        raise ValueError("Source access review did not cover archived job start")
    permitted_then, _ = validation_access_decision(
        source, registry=access, scope="single_validation", now=started,
    )
    if not permitted_then:
        raise ValueError("Archived job was outside reviewed source access scope")
    status = item.get("status")
    http = item.get("http_status")
    if http is not None and (type(http) is not int or not 100 <= http <= 599):
        raise ValueError("Invalid archived source HTTP status")
    if (http == 200 and item.get("final_url") == source["url"]
            and status in {"captured", "partial_capture", "needs_review"}):
        state = "http200_item_observed_NOT_ORIGINAL_HTML_VERIFIED"
    elif http is None and status in {
        "source_single_validation_not_approved", "source_quarantined",
        "source_not_validated_for_monitor", "source_retired",
    }:
        state = "held_item_no_publisher_response"
    elif http is None:
        state = "no_publisher_response_observed"
    else:
        state = "publisher_response_unusable_or_scope_changed"
    return {
        "job_id": job_id, "job_started_at_utc": started,
        "http_status": http, "observed_item_status": status,
        "slot_state": state,
    }


def audit_receipts(receipts, archive_root, *, access_registry=None, now=None,
                   plan=None):
    """Verify only supplied existing archives; never contact Zyte/publishers."""
    plan = frozen_plan() if plan is None else plan
    sources = _source_map(plan)
    _validate_receipts(plan, receipts)
    clock = _clock(now)
    access = load_access_registry() if access_registry is None else access_registry
    validate_access_registry(access, now=clock)
    root = Path(archive_root)
    if (not root.is_dir() or root.is_symlink()
            or any(p.is_symlink() for p in root.parents)):
        raise ValueError("Existing private non-symlink archive root required")
    rows, source_pairs, counts = [], [], Counter()
    for entry in receipts["rows"]:
        source = sources[entry["source_id"]]
        reviewed, reason = validation_access_decision(
            source, registry=access, scope="single_validation", now=clock,
        )
        starts = []
        round_states = []
        for slot in entry["rounds"]:
            rid = slot["zyte_job_id"]
            if rid is not None and not reviewed:
                raise ValueError(
                    "Archive submitted for source without CURRENT reviewed single "
                    "access: " + source["id"] + ": " + reason
                )
            result = None if rid is None else _audit_archive(
                root, rid, source, access, clock,
            )
            if result is not None:
                starts.append(result["job_started_at_utc"])
                state = result["slot_state"]
            else:
                state = (
                    "held_" + reason
                    if not reviewed else "reviewed_but_no_archived_job_supplied"
                )
            counts[state] += 1
            round_states.append(state)
            rows.append({
                "wave": entry["wave"],
                "source_id": source["id"], "category": source["category"],
                "round": slot["round"], "policy_access_status": (
                    "local_review_attestation_present_NOT_permission"
                    if reviewed else reason
                ),
                "slot_state": state, "zyte_job_id": rid,
                "http_status": None if result is None else result["http_status"],
                "observed_item_status": (
                    None if result is None else result["observed_item_status"]
                ),
                "archive_item_integrity_checked": result is not None,
                "original_html_verified": False,
                "requests_and_logs_independently_inspected": False,
                "approved_for_advisor": False,
            })
        if len(starts) == 2 and not starts[0] < starts[1]:
            raise ValueError(
                "Second source round must start after first independent job"
            )
        source_pairs.append({
            "source_id": source["id"], "category": source["category"],
            "wave": entry["wave"],
            "two_distinct_archived_job_rounds": len(starts) == 2,
            "both_item_http200_observed": round_states == [
                "http200_item_observed_NOT_ORIGINAL_HTML_VERIFIED"
            ] * 2,
            "original_html_reviewed": False,
            "requests_logs_verified": False,
        })
    if len(rows) != 36 or len(source_pairs) != 18:
        raise ValueError("P20A 18-source / 36-round denominator truncated")
    report = {
        "schema_version": VERSION, "kind": KIND,
        "status": "NO_GO",
        "frozen_plan_sha256": plan["plan_sha256"],
        "source_manifest_sha256": manifest_sha256(),
        "source_lifecycle_registry_sha256": registry_revision_sha256(),
        "source_access_registry_sha256": validation_access_revision_sha256(access),
        "expected_local_package_fingerprint_NOT_REMOTE_PROOF": package_fingerprint(),
        "original_selected_sources": 18,
        "original_source_round_denominator": 36,
        "source_rounds_with_immutable_item_archives": sum(
            bool(r["archive_item_integrity_checked"]) for r in rows
        ),
        "source_rounds_with_http200_item_candidate": sum(
            r["slot_state"] == "http200_item_observed_NOT_ORIGINAL_HTML_VERIFIED"
            for r in rows
        ),
        "sources_with_two_distinct_archived_jobs": sum(
            p["two_distinct_archived_job_rounds"] for p in source_pairs
        ),
        "sources_with_two_http200_items": sum(
            p["both_item_http200_observed"] for p in source_pairs
        ),
        "source_round_status_counts": dict(sorted(counts.items())),
        "all_36_rounds": rows,
        "source_pair_summaries": source_pairs,
        "remote_zyte_deployment_independently_attested": False,
        "publisher_permission_independently_authenticated": False,
        "requests_and_logs_independently_inspected": False,
        "original_publisher_html_bytes_supplied": False,
        "two_round_canary_ready_for_full_inventory": False,
        "human_gold_accuracy_measured": False,
        "network_requests_performed": 0, "zyte_jobs_created": 0,
        "source_permissions_granted": 0, "approved_for_advisor": False,
        "next_required_evidence": [
            "Independent exact-source publisher access and retention review",
            "Actual Zyte deployment package fingerprint confirmed by operator",
            "Two genuine distinct manually initiated source-specific Zyte jobs",
            "Private full Requests and Logs archives examined independently",
            "Privately captured original publisher HTML and two human reviews",
        ],
    }
    report["report_sha256"] = digest(report)
    return report, rows


def _write_json(root, name, data):
    _write_private(
        root / name,
        (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def prepare(out_dir):
    root = _private_new_directory(out_dir)
    try:
        _write_json(root, "frozen_p20a_plan.json", frozen_plan())
        _write_json(root, "zyte_canary_job_receipts_BLANK.json", blank_receipts())
        _write_private(
            root / "READ_ME_NO_CRAWL.txt",
            ("These 18 sources and 36 job slots are NOT crawl approvals.\n"
             "Fill job IDs only for genuinely completed, individually permitted "
             "Zyte jobs, after verifying exact deployed P23B source review.\n"
             "Keep filled receipts and private archives OFF GitHub and CI.\n"
             "Each job must be archived with scripts.archive_jobs first.\n"
             "This P23C1 audit cannot validate Requests, Logs, original HTML, "
             "legal permission or publisher data accuracy.\n").encode("utf-8"),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def write_audit(report, rows, out_dir):
    root = _private_new_directory(out_dir)
    try:
        _write_json(root, "zyte_canary_36_rounds_NO_GO.json", report)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: _safe_csv(row.get(field, "")) for field in CSV_FIELDS
            })
        _write_private(
            root / "all_36_rounds.csv",
            stream.getvalue().encode("utf-8-sig"),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def _read_json(path):
    file = Path(path)
    if (not file.is_file() or file.is_symlink()
            or file.stat().st_size > 250_000):
        raise ValueError("Invalid, linked, missing or oversized private receipt")
    return json.loads(file.read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--audit", action="store_true")
    p.add_argument("--private-receipts", type=Path)
    p.add_argument("--archive-root", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    if args.prepare:
        if args.private_receipts is not None or args.archive_root is not None:
            p.error("--prepare must not accept private evidence")
        out = prepare(args.out_dir)
        info = {"mode": "blank_only", "status": "NO_GO",
                "sources": 18, "rounds": 36}
    else:
        if args.private_receipts is None or args.archive_root is None:
            p.error("--audit requires private receipts and archive root")
        report, rows = audit_receipts(
            _read_json(args.private_receipts), args.archive_root,
        )
        out = write_audit(report, rows, args.out_dir)
        info = {
            "mode": "offline_archive_audit", "status": report["status"],
            "job_rounds_supplied": report[
                "source_rounds_with_immutable_item_archives"
            ],
            "full_crawl_ready": False,
        }
    print(json.dumps({**info, "out_dir": str(out)}, sort_keys=True))


if __name__ == "__main__":
    main()
