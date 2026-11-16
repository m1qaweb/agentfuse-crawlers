"""P25: 3-category 200-300 URL immutable Items archive reconciliation.

This fills the gap where legacy P14B full-inventory audits expected extra
pinned spider arguments but P23E0's safe full-category mode uses exactly
three arguments. Reuses the existing CHECKSUM-VERIFIED P07 archive reader.
Does not make HTTP requests, infer source truth, or approve downstream facts.
"""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.run_context import selection_ids_sha256
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.validation_access import digest
from scripts.archive_jobs import load_archive
from scripts.p25_large_campaign import ORDER, SPIDERS, build_campaign, read_g3_review_csv
from scripts.plan_documentation_children import _private_new_directory, _write_private

KIND = "p25_full_campaign_immutable_items_coverage_NOT_ACCURACY"
EXPECTED_ARGS = {
    "cohort": "all", "collection_mode": "validation",
    "confirm_full_inventory": "yes",
}
HELD_STATUSES = frozenset({
    "source_bulk_validation_not_approved", "source_quarantined",
    "source_retired",
})
FETCHED_REVIEW = frozenset({"captured", "needs_review", "partial_capture"})
BARRIERS = frozenset({
    "robots_or_policy_denied", "rejected_redirect", "redirect_needs_review",
})


def audit_archives(g3_rows, target, archive_dirs, *, access=None, plans=None,
                   now=None, package_sha=None, loader=load_archive):
    campaign = build_campaign(
        g3_rows, target, access=access, plans=plans, now=now,
        package_sha=package_sha,
    )
    if (not campaign["local_policy_and_three_plan_scope_complete"]
            or campaign["missing_current_source_access_reviews"] != 0):
        raise ValueError("Campaign archive audit requires the matching reviewed as-run package")
    paths = list(archive_dirs)
    if len(paths) != 3 or len({str(Path(p).resolve()) for p in paths}) != 3:
        raise ValueError("Exactly 3 distinct full-category immutable archives required")
    manifest = {s["id"]: s for s in load_sources()}
    by_category = {job["category"]: job for job in campaign["jobs"]}
    discovered, seen_source, job_ids = {}, set(), set()
    for path in paths:
        path = Path(path)
        if path.is_symlink():
            raise ValueError("Archive path symlink is not allowed")
        envelope, rows = loader(path)
        job = envelope.get("job") or {}
        category = job.get("category")
        expected = by_category.get(category)
        if (expected is None or category in discovered
                or job.get("spider") != SPIDERS[category]
                or job.get("spider_args") != EXPECTED_ARGS
                or job.get("unrecorded_argument_names")
                or job.get("state") != "finished"
                or job.get("job_id") in job_ids
                or not isinstance(job.get("job_id"), str)
                or (envelope.get("source_scope") or {}).get(
                    "safe_for_semantic_diff") is not True):
            raise ValueError("Archive job is not one verifiable P25 full-category run")
        job_ids.add(job["job_id"])
        cat_sources = select_sources(category, "all")
        expected_ids = {s["id"] for s in cat_sources}
        target_ids = set(expected["target_source_ids_manifest_order"])
        found, counted, good200, captured, barrier = set(), Counter(), 0, 0, 0
        for row in rows:
            sid = row.get("source_id") if isinstance(row, dict) else None
            source = manifest.get(sid) if isinstance(sid, str) else None
            if (source is None or sid not in expected_ids
                    or sid in seen_source or sid in found
                    or row.get("category") != category
                    or row.get("provider") != source["provider"]
                    or row.get("source_url") != source["url"]
                    or row.get("spider_name") != job["spider"]
                    or row.get("approved_for_advisor") is not False
                    or row.get("collection_mode") != "validation"
                    or row.get("requested_cohort") != "all"
                    or row.get("manifest_sha256") != campaign["manifest_sha256"]
                    or row.get("source_registry_sha256") !=
                        campaign["source_registry_sha256"]
                    or row.get("selection_ids_sha256") !=
                        selection_ids_sha256(cat_sources)
                    or row.get("selection_source_count") != len(cat_sources)
                    or row.get("zyte_job_id") != job["job_id"]
                    or row.get("deployment_revision") !=
                        campaign["local_package_sha256_NOT_REMOTE_PROOF"]):
                raise ValueError("Unexpected/duplicate P25 source, scope or deployment provenance")
            found.add(sid)
            seen_source.add(sid)
            status = row.get("status")
            counted[str(status)] += 1
            if sid not in target_ids:
                if (status not in HELD_STATUSES
                        or row.get("http_status") is not None
                        or not str(row.get("policy_observation") or "").startswith(
                            "not_fetched_by_")):
                    raise ValueError("Non-target source has an unauthorized request/Item: " + sid)
            else:
                if status in HELD_STATUSES or status == "source_single_validation_not_approved":
                    raise ValueError("Selected source was not authorized under P25: " + sid)
                good200 += int(row.get("http_status") == 200)
                captured += int(status == "captured")
                barrier += int(status in BARRIERS or row.get("http_status") in (
                    401, 403, 407, 429,
                ))
        discovered[category] = {
            "job_id": job["job_id"], "close_reason": job.get("close_reason"),
            "expected_manifest_items": len(cat_sources),
            "observed_items": len(found),
            "manifest_items_accounted_for": found == expected_ids,
            "target_primary_urls": len(target_ids),
            "target_http200_items_NOT_ACCURACY": good200,
            "target_captured_status_NOT_VERIFIED": captured,
            "target_access_barrier_count": barrier,
            "observed_statuses": dict(sorted(counted.items())),
            "archive_scope_verified": True,
        }
    if set(discovered) != set(ORDER):
        raise ValueError("Missing category archive")
    complete = all(
        j["manifest_items_accounted_for"] and j["close_reason"] == "finished"
        for j in discovered.values()
    ) and len(seen_source) == 460
    barriers = sum(j["target_access_barrier_count"] for j in discovered.values())
    result = {
        "schema_version": "1.0", "kind": KIND,
        "status": (
            "NO_GO_ARCHIVED_ITEMS_COMPLETE_NOT_REQUESTS_OR_GOLD"
            if complete and barriers == 0 else
            "NO_GO_INCOMPLETE_OR_ACCESS_BARRIER"
        ),
        "campaign_sha256": campaign["campaign_sha256"],
        "target_primary_urls": target,
        "total_manifest_slots": 460,
        "manifest_slots_observed": len(seen_source),
        "category_archive_count": len(discovered),
        "full_campaign_items_coverage_complete": complete,
        "target_http200_items_NOT_ACCURACY": sum(
            j["target_http200_items_NOT_ACCURACY"] for j in discovered.values()
        ),
        "target_captured_items_NOT_PUBLISHER_GOLD": sum(
            j["target_captured_status_NOT_VERIFIED"] for j in discovered.values()
        ),
        "target_access_barrier_count": barriers,
        "categories": discovered,
        "requests_and_logs_independently_reconciled": False,
        "publisher_html_and_human_gold_independently_verified": False,
        "independently_verified_fully_comparable_pricing_sources": 0,
        "approved_for_advisor": False,
        "current_package_metadata_not_a_remote_signature": True,
        "new_zyte_jobs": 0, "publisher_requests_performed_now": 0,
    }
    result["report_sha256"] = digest(result)
    return result


def write_audit(report, out_dir):
    if (report.get("kind") != KIND or not str(report.get("status", "")).startswith("NO_GO")
            or report.get("approved_for_advisor") is not False
            or report.get("requests_and_logs_independently_reconciled") is not False
            or report.get("new_zyte_jobs") != 0
            or report.get("report_sha256") != digest({
                k: v for k, v in report.items() if k != "report_sha256"
            })):
        raise ValueError("Invalid promoted full-campaign archive audit")
    directory = _private_new_directory(out_dir)
    try:
        _write_private(directory / "p25_immutable_items_full_campaign_NO_GO.json",
                       (json.dumps(report, indent=2, sort_keys=True) + "\n").encode())
    except Exception:
        shutil.rmtree(directory)
        raise
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--g3-top300", type=Path, required=True)
    parser.add_argument("--target", type=int, choices=range(200, 301, 5),
                        default=300)
    parser.add_argument("--archive", type=Path, action="append", required=True,
                        help="Repeat exactly 3 times: verified immutable job archive dir")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = audit_archives(read_g3_review_csv(args.g3_top300),
                            args.target, args.archive)
    path = write_audit(result, args.out_dir)
    print(json.dumps({
        "status": result["status"], "coverage_complete":
            result["full_campaign_items_coverage_complete"],
        "observed": result["manifest_slots_observed"],
        "archive_count": result["category_archive_count"],
        "request_log_gold_independently_verified": False,
        "output": str(path),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
