"""P14A: bind manually reviewed publisher labels to immutable Zyte job Items.

Offline, read-only, no network/credentials, no publisher fact approval.
Matching archived crawler outputs is NOT independent proof that publisher
prices, feature support, release dates or reviewer labels are true.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import load_archive
from scripts.compare_exports import compare, review_queue
from scripts.quality_gates import RATE_FIELDS, score_human_gold

SHA256 = re.compile(r"^[0-9a-f]{64}$")
RATE_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_ARCHIVES = 60
MAX_REVIEW_PER_CATEGORY = 1200
MAX_REVIEW_PER_SOURCE = 40
KNOWN = {s["id"]: s for s in load_sources()}


def _sha_json(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _source_locator_allowed(candidate, expected):
    if not isinstance(candidate, str) or not isinstance(expected, str):
        return False
    try:
        a, b = urlsplit(candidate), urlsplit(expected)
        return bool(a.scheme == "https" and b.scheme == "https"
                    and a.hostname == b.hostname and b.hostname
                    and not a.username and not a.password
                    and a.port in (None, 443)
                    and not a.query and len(candidate) <= 900)
    except ValueError:
        return False


def load_bound_archives(paths, *, full_inventory_plan=None):
    """Recompute checksums and identity from immutable P07 job directories.

    A full-inventory plan is REQUIRED for batch jobs. The P14A one-source
    path remains fail-closed for unplanned/mixed-source archives.
    """
    paths = list(paths)
    if not 1 <= len(paths) <= MAX_ARCHIVES:
        raise ValueError("Provide 1-60 explicit immutable Zyte archive directories")
    if full_inventory_plan is not None:
        from scripts.full_inventory_plan import validate_full_inventory_plan
        from scripts.audit_full_inventory import audit_full_inventory

        plan = validate_full_inventory_plan(full_inventory_plan)
        if not plan.get("expected_package_sha256"):
            raise ValueError("Batch gold needs a pinned package SHA-256 in the full-inventory plan")
        audit = audit_full_inventory(plan, archive_paths=paths)
        confirmed = [j for j in audit["jobs"] if j["job_id"]]
        if (not confirmed or len(confirmed) != len(paths)
                or any(not j["source_accounting_complete"]
                       or not j["archive_scope_valid"]
                       or not j["item_provenance_valid"]
                       for j in confirmed)
                or not audit["summary"]["package_pinned_and_verified"]):
            raise ValueError("Every batch gold archive needs verified complete planned job accounting")
    by_job = {}
    jobs = {}
    package_hashes = set()
    current_manifest = manifest_sha256()
    current_registry = registry_revision_sha256()
    for path in paths:
        envelope, rows = load_archive(Path(path))
        job = envelope["job"]
        job_id = job["job_id"]
        if job_id in jobs:
            raise ValueError("Duplicate Zyte job ID cannot add evidence: " + job_id)
        if (job.get("state") != "finished" or job.get("close_reason") != "finished"
                or envelope.get("approved_for_advisor") is not False
                or envelope.get("source_evidence_is_unverified") is not True
                or envelope.get("source_scope", {}).get("safe_for_semantic_diff") is not True):
            raise ValueError("Archive is not a complete, unverified finished-job snapshot")
        if full_inventory_plan is None:
            if len(rows) != 1 or envelope.get("source_summary_count") != 1:
                raise ValueError("Archive-bound gold requires one explicitly scoped source per job")
            only = rows[0]
            sid = only["source_id"]
            src = KNOWN.get(sid)
            if src is None:
                raise ValueError("Unknown source ID in gold canary job")
            expected_args = {
                "cohort": "all", "source_ids": sid, "collection_mode": "validation",
                "expected_manifest_sha256": current_manifest,
                "expected_selection_ids_sha256": selection_ids_sha256([src]),
                "expected_source_registry_sha256": current_registry,
            }
            observed_args = job.get("spider_args") or {}
            if (any(observed_args.get(k) != v for k, v in expected_args.items())
                    or job.get("spider") != only.get("spider_name")
                    or only.get("selection_source_count") != 1
                    or only.get("selection_ids_sha256") !=
                       expected_args["expected_selection_ids_sha256"]
                    or only.get("requested_cohort") != "all"
                    or only.get("collection_mode") != "validation"):
                raise ValueError("Gold archive job arguments not pinned to the exact source")
        jobs[job_id] = {
            "job_id": job_id, "category": job["category"],
            "finished_time_ms": job.get("finished_time_ms"),
            "item_count": len(rows),
            "integrity_sha256": envelope["integrity"]["uncompressed_sha256"],
        }
        for row in rows:
            sid = row["source_id"]
            if full_inventory_plan is not None:
                # All 460 IDs remain accounted for by the full campaign
                # auditor. Policy-blocked and failed/empty pages cannot
                # become price/date gold just because their job completed.
                if (sid in full_inventory_plan["expected_policy_skipped_source_ids"]
                        or row.get("status") not in {
                            "captured", "needs_review", "partial_capture"
                        }
                        or row.get("http_status") != 200
                        or not isinstance(row.get("content_sha256"), str)
                        or not SHA256.fullmatch(row["content_sha256"])):
                    continue
            manifest = KNOWN.get(sid)
            if (not manifest or manifest["category"] != row.get("category")
                    or manifest["provider"] != row.get("provider")
                    or manifest["url"] != row.get("source_url")
                    or row.get("manifest_sha256") != current_manifest
                    or row.get("source_registry_sha256") != current_registry
                    or row.get("approved_for_advisor") is not False
                    or row.get("source_policy_status") in {"unresolved", "prohibited_reviewed"}
                    or row.get("source_lifecycle_state") in {"quarantined", "retired"}
                    or row.get("http_status") != 200
                    or row.get("status") not in {
                        "captured", "needs_review", "partial_capture"
                    }
                    or not isinstance(row.get("content_sha256"), str)
                    or not SHA256.fullmatch(row["content_sha256"])):
                raise ValueError("Archive Item cannot be used as live gold evidence: " + sid)
            kind = row.get("deployment_revision_kind")
            fingerprint = row.get("deployment_revision")
            if (kind != "package_py_json_sha256_v1" or not isinstance(fingerprint, str)
                    or not SHA256.fullmatch(fingerprint)):
                raise ValueError("Gold binding needs a verifiable crawler package fingerprint")
            if (row.get("zyte_job_id") not in ("", None, job_id)
                    or row.get("status") in {
                        "http_error", "blocked", "robots_or_policy_denied",
                        "rejected_redirect", "source_quarantined",
                    }):
                raise ValueError("Archived Item is denied or has incompatible job provenance")
            package_hashes.add(fingerprint)
            key = sid, job_id
            if key in by_job:
                raise ValueError("Duplicate source/job in independent gold sample")
            by_job[key] = row
    # Never combine different extractor/package revisions into one accuracy
    # denominator, even if they happen to use the same source URLs.
    if len(package_hashes) != 1:
        raise ValueError("Mixed deployed crawler package revisions require separate gold cohorts")
    return by_job, jobs, next(iter(package_hashes))


def _review_note(row):
    note = row.get("evidence_review_note")
    if not isinstance(note, str) or not 24 <= len(note.strip()) <= 1200:
        raise ValueError("Each independent label needs a substantive publisher evidence review note")


def _source_case(row, by_job, category):
    _review_note(row)
    key = row.get("source_id"), row.get("job_id")
    item = by_job.get(key)
    if not item or item.get("category") != category:
        raise ValueError("Gold case does not match a verified archived source/job/category")
    if (row.get("source_url") != item["source_url"]
            or not _source_locator_allowed(row.get("evidence_url"), item["source_url"])):
        raise ValueError("Gold case evidence URL is not from its exact official source")
    return item


def _observation(item, observation_id):
    if not isinstance(observation_id, str) or not RATE_ID.fullmatch(observation_id):
        raise ValueError("Pricing case requires a typed 32-hex observation ID")
    matches = [
        o for o in item.get("pricing_observations", [])
        if isinstance(o, dict) and o.get("observation_id") == observation_id
    ]
    if len(matches) != 1:
        raise ValueError("Pricing identity missing or ambiguous in archived Item")
    o = matches[0]
    if o.get("approved_for_advisor") is not False:
        raise ValueError("Archived pricing observation unexpectedly approved")
    return o


def _release(item, event_id):
    if (not isinstance(event_id, str)
            or not event_id.startswith(item["source_id"] + ":")):
        raise ValueError("Release gold event must have official source-owned event ID")
    matches = [
        e for e in item.get("release_events", [])
        if isinstance(e, dict) and e.get("event_id") == event_id
    ]
    if len(matches) != 1:
        raise ValueError("Release identity missing or ambiguous in archived Item")
    if matches[0].get("approved_for_advisor") is not False:
        raise ValueError("Archived release event unexpectedly approved")
    return matches[0]


def _observed_rate(obs):
    return {
        "amount": obs.get("normalized_amount_decimal"),
        **{field: obs.get(field) for field in RATE_FIELDS[1:]},
        "comparable_candidate": obs.get("comparable_candidate") is True,
    }


def _same_observed_rate(actual, supplied):
    if not isinstance(supplied, dict) or set(supplied) != set(actual):
        return False
    for key, value in actual.items():
        if supplied.get(key) != value:
            return False
    return True


def _ensure_unique_evidence(category, key, seen):
    full_key = category, *key
    if full_key in seen:
        raise ValueError("Repeated real-world evidence would inflate accuracy denominator")
    seen.add(full_key)


def bind_human_gold(gold, paths, *, full_inventory_plan=None):
    """Verify every self-annotated case against immutable, current-schema Items.

    Does not decide if the human label is true. It prevents forged/extraneous
    crawler-observed values and repeated source observations across jobs.
    """
    # Preserve the existing P08 label syntax checks and exact Decimal scoring.
    score_human_gold(gold)
    by_job, jobs, package_sha = load_bound_archives(
        paths, full_inventory_plan=full_inventory_plan,
    )
    if gold.get("expected_package_sha256") != package_sha:
        raise ValueError("Reviewed gold must pin the actual archived package SHA-256")
    evidence_seen = set()
    bound = Counter()

    for case in gold["pricing_rows"]:
        item = _source_case(case, by_job, "pricing")
        obs = _observation(item, case.get("observation_id"))
        _ensure_unique_evidence("rate", (
            item["source_id"], obs["observation_id"]
        ), evidence_seen)
        if not _same_observed_rate(_observed_rate(obs), case.get("observed")):
            raise ValueError("Reviewer-supplied observed pricing differs from archived crawler output")
        if case["evidence_url"] != obs.get("source_url", item["source_url"]):
            raise ValueError("Pricing evidence URL is not the archived observation locator")
        bound["pricing"] += 1

    for case in gold["negative_rate_rows"]:
        item = _source_case(case, by_job, "pricing")
        obs = _observation(item, case.get("observation_id"))
        _ensure_unique_evidence("rate", (
            item["source_id"], obs["observation_id"]
        ), evidence_seen)
        if (case.get("observed_comparable") is not
                (obs.get("comparable_candidate") is True)):
            raise ValueError("Negative-rate observed comparability differs from archived Item")
        if case["evidence_url"] != obs.get("source_url", item["source_url"]):
            raise ValueError("Negative pricing evidence locator differs from archived Item")
        bound["negative"] += 1

    for case in gold["date_rows"]:
        item = _source_case(case, by_job, "changelog")
        event = _release(item, case.get("event_id"))
        _ensure_unique_evidence("date", (
            item["source_id"], event["event_id"]
        ), evidence_seen)
        if (case.get("observed_day") != event.get("published_at")
                or case.get("event_body_sha256") != event.get("body_sha256")
                or not isinstance(case.get("event_body_sha256"), str)):
            raise ValueError("Reviewer-supplied publication observation differs from archive")
        allowed_locations = {
            item["source_url"], event.get("permalink") or item["source_url"]
        }
        if case["evidence_url"] not in allowed_locations:
            raise ValueError("Date evidence URL is not event-owned or original changelog")
        bound["date"] += 1

    for case in gold["change_safety_rows"]:
        item = _source_case(case, by_job, "changelog")
        scenario = case["scenario"]
        if scenario == "first_baseline":
            baseline = compare({item["source_id"]: item}, {})
            alerts = review_queue({item["source_id"]: item}, {}, baseline)
            key = ("baseline", item["source_id"], item["content_sha256"])
        else:
            prior_key = item["source_id"], case.get("previous_job_id")
            old = by_job.get(prior_key)
            if not old or old.get("category") != "changelog":
                raise ValueError("Reordering safety case requires earlier archived source")
            before = old.get("release_events") or []
            after = item.get("release_events") or []
            event_key = lambda e: (e.get("event_id"), e.get("body_sha256"),
                                   e.get("published_at"))
            if (len(before) < 2 or len(before) != len(after)
                    or [event_key(x) for x in before] ==
                       [event_key(x) for x in after]
                    or sorted(event_key(x) for x in before) !=
                       sorted(event_key(x) for x in after)
                    or not isinstance(jobs[old["zyte_job_id"]]["finished_time_ms"], (int, float))
                    or not isinstance(jobs[item["zyte_job_id"]]["finished_time_ms"], (int, float))
                    or jobs[old["zyte_job_id"]]["finished_time_ms"] >=
                       jobs[item["zyte_job_id"]]["finished_time_ms"]):
                raise ValueError("Reordering scenario lacks independent earlier same-event evidence")
            changes = compare({item["source_id"]: item}, {item["source_id"]: old})
            alerts = review_queue(
                {item["source_id"]: item}, {item["source_id"]: old}, changes,
            )
            key = ("reorder", item["source_id"], old["content_sha256"],
                   item["content_sha256"])
        _ensure_unique_evidence("change", key, evidence_seen)
        found_new = any(row.get("change_type") in {
            "release_event_first_seen", "new_event_candidate",
            "version_first_seen_date_unknown",
        } for row in alerts)
        if case.get("observed_new_release_alert") is not found_new:
            raise ValueError("Change-safety alert result differs from offline replay")
        bound["change"] += 1

    total = sum(bound.values())
    return {
        "report_kind": "offline_real_gold_archive_binding",
        "schema_version": "1.0",
        "reviewed_gold_sha256": _sha_json(gold),
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "package_sha256": package_sha,
        "full_inventory_plan_sha256": (
            full_inventory_plan.get("plan_sha256")
            if full_inventory_plan is not None else None
        ),
        "verified_immutable_job_count": len(jobs),
        "verified_source_job_items": len(by_job),
        "pricing_cases_bound": bound["pricing"],
        "date_cases_bound": bound["date"],
        "negative_cases_bound": bound["negative"],
        "change_cases_bound": bound["change"],
        "total_cases_bound": total,
        "binding_complete": total == sum(len(gold[k]) for k in (
            "pricing_rows", "date_rows", "negative_rate_rows",
            "change_safety_rows",
        )),
        "independent_publisher_truth_confirmed": False,
        "human_label_truth_requires_independent_review": True,
        "auto_crawl_urls_approved": 0,
        "advisor_fact_approvals": 0,
        "deployment_authorized": False,
        "network_requests_performed": 0,
    }


def prepare_review_candidates(paths, *, full_inventory_plan=None):
    """Generate finite unreviewed queue, never fake a human-reviewed gold set."""
    by_job, jobs, package_sha = load_bound_archives(
        paths, full_inventory_plan=full_inventory_plan,
    )
    results = {"pricing": [], "release_dates": [], "documentation": []}
    omitted = Counter()
    seen = set()
    groups = {key: defaultdict(list) for key in results}

    def queue_candidate(kind, sid, row):
        # Do not let one large pricing table or long release timeline crowd
        # every other provider out of the real-world human review queue.
        if len(groups[kind][sid]) < MAX_REVIEW_PER_SOURCE:
            groups[kind][sid].append(row)
        else:
            omitted[kind] += 1

    for (sid, job_id), item in sorted(by_job.items()):
        base = {
            "source_id": sid, "job_id": job_id,
            "source_url": item["source_url"],
            "content_sha256": item.get("content_sha256"),
            "review_status": "unreviewed",
            "reviewer_expected_value": None,
            "approved_for_advisor": False,
        }
        if item["category"] == "pricing":
            for obs in item.get("pricing_observations", []):
                if not isinstance(obs, dict) or not RATE_ID.fullmatch(str(obs.get("observation_id", ""))):
                    continue
                key = ("pricing", sid, obs["observation_id"])
                if key in seen:
                    continue
                seen.add(key)
                row = dict(base, observation_id=obs["observation_id"],
                           raw_displayed_price=str(obs.get("raw_displayed_price") or "")[:130],
                           observed=_observed_rate(obs),
                           normalization_blockers=(obs.get("normalization_blockers") or [])[:12],
                           evidence_url=item["source_url"])
                kind = "pricing"
                queue_candidate(kind, sid, row)
        elif item["category"] == "changelog":
            for evt in item.get("release_events", []):
                if not isinstance(evt, dict) or not evt.get("event_id"):
                    continue
                key = ("date", sid, evt["event_id"])
                if key in seen:
                    continue
                seen.add(key)
                row = dict(base, event_id=evt["event_id"],
                           title=str(evt.get("title") or "")[:190],
                           observed_day=evt.get("published_at"),
                           event_body_sha256=evt.get("body_sha256"),
                           date_evidence_text=str(evt.get("date_evidence_text") or "")[:110],
                           excerpt=str(evt.get("excerpt") or "")[:360],
                           evidence_url=evt.get("permalink") or item["source_url"])
                kind = "release_dates"
                queue_candidate(kind, sid, row)
        elif item["category"] == "documentation":
            for sec in item.get("documentation_topic_candidates", []):
                if not isinstance(sec, dict) or not sec.get("candidate_id"):
                    continue
                key = ("docs", sid, sec["candidate_id"])
                if key in seen:
                    continue
                seen.add(key)
                row = dict(base, candidate_id=sec["candidate_id"],
                           product_scope=item.get("documentation_product_scope"),
                           topic_hint=sec.get("topic_hint"),
                           section_id=sec.get("section_id"),
                           section_sha256=sec.get("section_sha256"),
                           excerpt=str(sec.get("excerpt") or "")[:360])
                kind = "documentation"
                queue_candidate(kind, sid, row)
    # Deterministic breadth-first sampling: one distinct candidate per
    # source, then a second per source, and so on. This is a review workload
    # balance, NOT statistical representativeness or fact verification.
    for kind, per_source in groups.items():
        depth_limit = max((len(rows) for rows in per_source.values()), default=0)
        for depth in range(depth_limit):
            for sid in sorted(per_source):
                if depth >= len(per_source[sid]):
                    continue
                if len(results[kind]) < MAX_REVIEW_PER_CATEGORY:
                    results[kind].append(per_source[sid][depth])
                else:
                    omitted[kind] += 1
    return {
        "schema_version": "1.0",
        "kind": "unreviewed_offline_publisher_evidence_candidates_not_gold",
        "sampling_strategy": "bounded_source_round_robin_unreviewed",
        "per_source_candidate_limit": MAX_REVIEW_PER_SOURCE,
        "source_diversity_counts": {
            kind: len({entry["source_id"] for entry in values})
            for kind, values in results.items()
        },
        "package_sha256": package_sha,
        "verified_immutable_archive_count": len(jobs),
        "samples": results,
        "omitted_by_bounded_sample": dict(omitted),
        "human_review_completed": False,
        "independently_verified_vendor_facts": 0,
        "advisor_fact_approvals": 0,
        "auto_crawls_performed": 0,
        "not_for_release_quality_gates": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, nargs="+", required=True)
    parser.add_argument("--full-inventory-plan", type=Path,
                        help="Mandatory exact plan for multi-source batch archives")
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument("--prepare-review", type=Path, metavar="OUTPUT_JSON")
    option.add_argument("--reviewed-gold", type=Path, metavar="ANNOTATIONS_JSON")
    parser.add_argument("--out", type=Path, default=Path("output/private/gold_binding.json"))
    args = parser.parse_args()
    plan = (
        json.loads(args.full_inventory_plan.read_text(encoding="utf-8"))
        if args.full_inventory_plan else None
    )
    if args.prepare_review:
        path = args.prepare_review
        report = prepare_review_candidates(
            args.archives, full_inventory_plan=plan,
        )
    else:
        path = args.out
        gold = json.loads(args.reviewed_gold.read_text(encoding="utf-8"))
        report = bind_human_gold(
            gold, args.archives, full_inventory_plan=plan,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({
        "report_kind": report.get("report_kind", report.get("kind")),
        "verified_archives": report.get("verified_immutable_job_count",
                                        report.get("verified_immutable_archive_count")),
        "auto_crawls_performed": 0,
        "advisor_fact_approvals": 0,
        "output": str(path),
    }, indent=2))


if __name__ == "__main__":
    main()
