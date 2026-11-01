"""P14B: audit the whole planned 460-source inventory across Zyte jobs.

Recommended inputs: immutable P07 archives containing official finished-job
metadata and checksum-verified Items. Zyte Dashboard Items JSON can also be
used for *preliminary unverified* coverage triage, never as an approved run.

No network, deployments, source promotions, vendor-fact claims, or DB writes.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.diagnostics import derive_diagnostics
from agentfuse_crawlers.source_lifecycle import collection_decision, source_lifecycle
from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import load_archive
from scripts.full_inventory_plan import (
    FINGERPRINT, validate_full_inventory_plan,
)

MAX_ARCHIVES = 100
MAX_ITEMS_BYTES = 400_000_000
SPIDERS = {
    "documentation": "official_documentation",
    "pricing": "official_pricing",
    "changelog": "official_changelogs",
}
SOURCE_FIELDS = (
    "source_id", "category", "provider", "source_url", "job_key", "zyte_job_id",
    "status", "http_status", "content_sha256", "diagnostic_reason_codes",
    "documentation_scope_status", "documentation_product_scope_signal",
    "pricing_inventory_complete", "pricing_comparable_candidate_count",
    "release_window_complete", "release_event_identity_collision",
    "release_dated_event_count", "quality_classification", "review_action",
)
JOB_FIELDS = (
    "job_key", "spider", "category", "expected_source_count",
    "observed_source_count", "job_id", "close_reason",
    "source_accounting_complete", "archive_scope_valid",
    "item_provenance_valid", "package_fingerprint",
)


def _csv_safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _raw_items(paths):
    rows = []
    for file in paths:
        path = Path(file)
        if path.stat().st_size > MAX_ITEMS_BYTES:
            raise ValueError("Items export exceeds bounded offline input size")
        with path.open(encoding="utf-8-sig") as stream:
            prefix = stream.read(1)
            while prefix and prefix.isspace():
                prefix = stream.read(1)
            stream.seek(0)
            if prefix == "[":
                data = json.load(stream)
                if not isinstance(data, list):
                    raise ValueError("Zyte JSON export must be an array")
                rows.extend(data)
            else:
                for line in stream:
                    if line.strip():
                        rows.append(json.loads(line))
        if len(rows) > 460:
            raise ValueError("Unverified Items contain more than the 460 planned sources")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("All exported Items must be JSON objects")
    return rows


def _source_classes(row, *, eligible):
    """Distinguish source-accounted from publisher-fact-accurate evidence."""
    if not eligible:
        return "policy_skip_accounted", "do_not_retry_without_reviewed_permission"
    if row.get("status") not in {"captured", "partial_capture", "needs_review"}:
        return "fetch_or_access_failed", "review_access_robots_or_source_error"
    category = row["category"]
    if row.get("http_status") != 200:
        return "non_200_unverified", "inspect_http_status_and_original_source"
    if category == "documentation":
        if row.get("documentation_static_capture_status") == "javascript_shell_suspected":
            return "javascript_shell_unverified", "review_publisher_official_static_documentation"
        if row.get("documentation_canonical_relation") == "same_host_path_differs":
            return "canonical_migration_review", "verify_product_and_canonical_officially"
        if row.get("documentation_requires_product_review"):
            return "product_scope_review", "verify_documentation_product_scope"
        if (row.get("documentation_scope_status") == "scoped_page"
                and row.get("documentation_product_scope_signal") ==
                    "explicit_marker_found"
                and row.get("documentation_profile_status") ==
                    "curated_pending_live_validation"):
            return "scoped_unverified", "manual_verify_topic_against_publisher"
        return "docs_scope_unresolved", "review_page_scope_or_navigation_index"
    if category == "pricing":
        if row.get("pricing_evidence_lost_to_item_budget"):
            return "price_evidence_clipped", "review_item_budget_and_table_window"
        if not row.get("pricing_inventory_complete"):
            return "pricing_inventory_partial", "review_relevant_table_windows"
        if row.get("pricing_comparable_candidate_count", 0) > 0:
            return "rate_candidates_unverified", "manual_verify_all_rate_dimensions"
        return "pricing_dimensions_unresolved", "review_currency_unit_tier_region"
    if row.get("release_event_identity_collision"):
        return "release_identity_collision", "review_release_anchors_and_event_titles"
    if not row.get("release_window_complete"):
        return "release_window_partial", "review_changelog_dates_and_history_window"
    if row.get("release_dated_event_count", 0) > 0:
        return "dated_events_unverified", "manual_verify_official_publication_dates"
    return "changelog_dates_unresolved", "review_publisher_datelines_and_event_identity"


def _job_plan_lookup(plan):
    by_sid = {}
    for job in plan["jobs"]:
        for sid in job["source_ids"]:
            if sid in by_sid:
                raise ValueError("Plan has a duplicate source")
            by_sid[sid] = job
    if len(by_sid) != 460:
        raise ValueError("Plan does not account for all 460 source IDs")
    return by_sid


def _verify_record(row, planned, known, *, job_id, require_job_provenance):
    sid = row.get("source_id")
    src = known.get(sid) if isinstance(sid, str) else None
    if src is None or planned.get(sid) is None:
        raise ValueError("Unexpected source Item outside pinned 460 ID manifest")
    job = planned[sid]
    if (row.get("category") != src["category"]
            or row.get("provider") != src["provider"]
            or row.get("source_url") != src["url"]
            or row.get("spider_name") not in (None, job["spider"])
            or row.get("approved_for_advisor") is not False):
        raise ValueError("Source identity, spider, or unverified approval invariant failed: " + sid)
    eligible, _ = collection_decision(src, "validation")
    if not eligible:
        if (row.get("status") not in {"source_quarantined", "source_retired"}
                or row.get("http_status") is not None):
            raise ValueError("Publisher policy-restricted source was fetched: " + sid)
    if require_job_provenance:
        # Source policy is immutable for this deployment. The row cannot claim
        # to have been reviewed/allowed when current pinned registry says it
        # is degraded, unreviewed, or quarantined.
        policy = source_lifecycle(src)
        if (row.get("source_lifecycle_state") != policy["state"]
                or row.get("source_policy_status") != policy["policy_status"]):
            raise ValueError("Archived source lifecycle/policy revision drift: " + sid)
        if (row.get("manifest_sha256") != job["spider_args"]["expected_manifest_sha256"]
                or row.get("source_registry_sha256") !=
                    job["spider_args"]["expected_source_registry_sha256"]
                or row.get("selection_ids_sha256") != job["expected_selection_ids_sha256"]
                or row.get("selection_source_count") != job["requested_count"]
                or row.get("requested_cohort") != "all"
                or row.get("collection_mode") != "validation"
                or row.get("spider_name") != job["spider"]
                or row.get("zyte_job_id") != job_id):
            raise ValueError("Item job selection, cohort or package policy drift: " + sid)
    return eligible


def _summary(plan, rows, job_reports, *, mode):
    known = {s["id"]: s for s in load_sources()}
    lookup = _job_plan_lookup(plan)
    source_rows = []
    by_category = {}
    all_present = set()
    warnings = Counter()
    packages = set()
    for category in SPIDERS:
        by_category[category] = {
            "expected": plan["categories"][category]["manifest_count"],
            "items_received": 0,
            "http_200": 0, "captured": 0, "needs_review": 0,
            "partial_capture": 0, "policy_skipped": 0,
            "scoped_docs_unverified": 0,
            "pricing_full_table_inventory": 0,
            "pricing_rate_candidate_sources": 0,
            "changelog_complete_release_windows": 0,
            "changelog_dated_event_sources": 0,
            "status_counts": {},
            "quality_classifications": {},
        }
    status_counts = {c: Counter() for c in SPIDERS}
    class_counts = {c: Counter() for c in SPIDERS}
    for sid, row in sorted(rows.items()):
        job = lookup[sid]
        category = row["category"]
        cat = by_category[category]
        cat["items_received"] += 1
        status = row.get("status") or "unknown"
        status_counts[category][status] += 1
        if row.get("http_status") == 200:
            cat["http_200"] += 1
        if status in {"captured", "needs_review", "partial_capture"}:
            cat[status] += 1
        eligible = collection_decision(known[sid], "validation")[0]
        if not eligible:
            cat["policy_skipped"] += 1
        classification, action = _source_classes(row, eligible=eligible)
        class_counts[category][classification] += 1
        if category == "documentation" and classification == "scoped_unverified":
            cat["scoped_docs_unverified"] += 1
        if category == "pricing":
            cat["pricing_full_table_inventory"] += int(
                row.get("pricing_inventory_complete") is True
            )
            cat["pricing_rate_candidate_sources"] += int(
                row.get("pricing_comparable_candidate_count", 0) > 0
            )
        if category == "changelog":
            cat["changelog_complete_release_windows"] += int(
                row.get("release_window_complete") is True
            )
            cat["changelog_dated_event_sources"] += int(
                row.get("release_dated_event_count", 0) > 0
            )
        diagnostic = derive_diagnostics(row)
        reasons = diagnostic["diagnostic_reason_codes"]
        warnings.update(set(reasons))
        fingerprint = row.get("deployment_revision")
        if isinstance(fingerprint, str) and FINGERPRINT.fullmatch(fingerprint):
            packages.add(fingerprint)
        else:
            packages.add("unrecorded_or_invalid")
        source_rows.append({
            "source_id": sid, "category": category,
            "provider": known[sid]["provider"],
            "source_url": known[sid]["url"],
            "job_key": job["job_key"],
            "zyte_job_id": row.get("zyte_job_id") or "",
            "status": status,
            "http_status": row.get("http_status"),
            "content_sha256": row.get("content_sha256") or "",
            "diagnostic_reason_codes": ",".join(reasons),
            "documentation_scope_status": row.get("documentation_scope_status", ""),
            "documentation_product_scope_signal": row.get(
                "documentation_product_scope_signal", ""),
            "pricing_inventory_complete": row.get(
                "pricing_inventory_complete", ""),
            "pricing_comparable_candidate_count": row.get(
                "pricing_comparable_candidate_count", ""),
            "release_window_complete": row.get("release_window_complete", ""),
            "release_event_identity_collision": row.get(
                "release_event_identity_collision", ""),
            "release_dated_event_count": row.get(
                "release_dated_event_count", ""),
            "quality_classification": classification,
            "review_action": action,
        })
        all_present.add(sid)
    for category in SPIDERS:
        by_category[category]["status_counts"] = dict(
            sorted(status_counts[category].items())
        )
        by_category[category]["quality_classifications"] = dict(
            sorted(class_counts[category].items())
        )
    missing = sorted(set(lookup) - all_present)
    absent_jobs = sorted(
        row["job_key"] for row in job_reports if not row["job_id"]
    )
    failed_jobs = sorted(
        row["job_key"] for row in job_reports
        if row["job_id"] and (
            not row["source_accounting_complete"]
            or not row["archive_scope_valid"]
            or not row["item_provenance_valid"]
        )
    )
    expected_sha = plan.get("expected_package_sha256")
    package_pinned = bool(
        expected_sha and packages == {expected_sha}
    )
    all_archive_provenance = bool(
        mode == "immutable_archives" and not absent_jobs and not failed_jobs
        and package_pinned
    )
    complete_accounting = bool(
        len(all_present) == 460 and not missing
        and len(job_reports) == plan["planned_jobs"]
        and not absent_jobs and not failed_jobs
    )
    if mode != "immutable_archives":
        label = "raw_export_preliminary_not_verified"
    elif not complete_accounting:
        label = "full_inventory_accounting_incomplete"
    elif not all_archive_provenance:
        label = "full_inventory_accounted_but_package_unverified"
    else:
        label = "full_inventory_accounted_archives_verified_facts_unverified"
    summary = {
        "schema_version": "1.0",
        "kind": "full_manifest_validation_accounting_not_publisher_truth",
        "input_basis": mode,
        "status": label,
        "plan_sha256": plan["plan_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "source_registry_sha256": plan["source_registry_sha256"],
        "expected_package_sha256": expected_sha,
        "actual_package_fingerprints": sorted(packages),
        "package_pinned_and_verified": package_pinned and mode == "immutable_archives",
        "manifest_source_count": 460,
        "accounted_source_count": len(all_present),
        "missing_source_count": len(missing),
        "missing_source_ids": missing,
        "planned_job_count": plan["planned_jobs"],
        "reported_job_count": sum(bool(j["job_id"]) for j in job_reports),
        "missing_job_keys": absent_jobs,
        "incomplete_job_keys": failed_jobs,
        "whole_inventory_accounted": complete_accounting,
        "verified_immutable_archives": all_archive_provenance,
        "expected_policy_skips": plan["expected_policy_skipped_source_ids"],
        "category_metrics": by_category,
        "concurrent_reason_counts": dict(warnings.most_common()),
        "publisher_evidence_accuracy_independently_verified": False,
        "publisher_permission_independently_verified": False,
        "source_policy_promotion_authorized": False,
        "advisor_fact_approvals": 0,
        "deployment_authorized": False,
        "network_requests_performed_by_auditor": 0,
    }
    return {"summary": summary, "sources": source_rows, "jobs": job_reports}


def audit_full_inventory(plan, *, archive_paths=None, items_paths=None):
    """Exactly one immutable job per planned partition; missing jobs are visible."""
    plan = validate_full_inventory_plan(plan)
    if (archive_paths is None) == (items_paths is None):
        raise ValueError("Choose exactly one input mode: archives or raw Items")
    known = {s["id"]: s for s in load_sources()}
    lookup = _job_plan_lookup(plan)
    row_by_sid = {}
    job_reports = [{
        "job_key": job["job_key"],
        "spider": job["spider"],
        "category": job["category"],
        "expected_source_count": job["requested_count"],
        "observed_source_count": 0,
        "job_id": "",
        "close_reason": "",
        "source_accounting_complete": False,
        "archive_scope_valid": False,
        "item_provenance_valid": False,
        "package_fingerprint": "",
    } for job in plan["jobs"]]
    records_by_job = {j["job_key"]: j for j in job_reports}
    if archive_paths is not None:
        files = list(archive_paths)
        if len(files) > min(MAX_ARCHIVES, plan["planned_jobs"]):
            raise ValueError("More archives than distinct planned Zyte jobs")
        seen_job_ids = set()
        seen_keys = set()
        for path in files:
            env, rows = load_archive(Path(path))
            meta = env["job"]
            args = meta.get("spider_args") or {}
            matches = [
                job for job in plan["jobs"]
                if job["spider"] == meta.get("spider")
                and job["spider_args"] == args
            ]
            if len(matches) != 1:
                raise ValueError("Archived job scope does not match exactly one planned job")
            job = matches[0]
            if (job["job_key"] in seen_keys or meta["job_id"] in seen_job_ids
                    or meta.get("unrecorded_argument_names")):
                raise ValueError("Duplicate job or unrecorded extra spider arguments")
            seen_keys.add(job["job_key"])
            seen_job_ids.add(meta["job_id"])
            if meta.get("category") != job["category"]:
                raise ValueError("Archived job category disagrees with pinned spider")
            report = records_by_job[job["job_key"]]
            report.update({
                "job_id": meta["job_id"],
                "close_reason": meta.get("close_reason") or "unknown",
                "observed_source_count": len(rows),
                "archive_scope_valid": bool(
                    env["source_scope"].get("safe_for_semantic_diff")
                    and meta.get("state") == "finished"
                    and meta.get("close_reason") == "finished"
                ),
            })
            expected = set(job["source_ids"])
            seen = set()
            valid = True
            for row in rows:
                sid = row.get("source_id")
                if sid not in expected:
                    raise ValueError("Job returned a source belonging to another partition")
                if sid in seen or sid in row_by_sid:
                    raise ValueError("Duplicate source across archive jobs")
                seen.add(sid)
                eligible = _verify_record(
                    row, lookup, known, job_id=meta["job_id"],
                    require_job_provenance=True,
                )
                fingerprint = row.get("deployment_revision")
                if (not isinstance(fingerprint, str)
                        or not FINGERPRINT.fullmatch(fingerprint)
                        or row.get("deployment_revision_kind") !=
                        "package_py_json_sha256_v1"
                        or (plan.get("expected_package_sha256") is not None
                            and fingerprint != plan["expected_package_sha256"])):
                    valid = False
                if not report["package_fingerprint"]:
                    report["package_fingerprint"] = fingerprint or ""
                elif report["package_fingerprint"] != fingerprint:
                    report["package_fingerprint"] = "multiple_package_revisions"
                    valid = False
                row_by_sid[sid] = row
            report["item_provenance_valid"] = valid and bool(rows)
            report["source_accounting_complete"] = (
                seen == expected and report["archive_scope_valid"]
                and report["item_provenance_valid"]
            )
        mode = "immutable_archives"
    else:
        # A Dashboard Item JSON lacks cryptographic job metadata; it may be
        # useful for coverage triage, but NEVER claim provenance verified.
        raw = _raw_items(items_paths)
        for row in raw:
            sid = row.get("source_id")
            if sid in row_by_sid:
                raise ValueError("Repeated source across raw Item exports")
            _verify_record(row, lookup, known, job_id=None,
                           require_job_provenance=False)
            row_by_sid[sid] = row
        for job in plan["jobs"]:
            report = records_by_job[job["job_key"]]
            report["observed_source_count"] = len(
                set(job["source_ids"]) & set(row_by_sid)
            )
            # Intentionally do not trust summary counts or provenance hashes
            # without a complete archived job envelope.
        mode = "raw_items_unverified"
    return _summary(plan, row_by_sid, job_reports, mode=mode)


def write_full_inventory_audit(report, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(report["summary"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for filename, fields, rows in (
        ("source_quality_triage.csv", SOURCE_FIELDS, report["sources"]),
        ("job_accounting.csv", JOB_FIELDS, report["jobs"]),
    ):
        with (out_dir / filename).open(
            "w", newline="", encoding="utf-8-sig"
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({
                key: _csv_safe(row.get(key, "")) for key in fields
            } for row in rows)
    return out_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archives", type=Path, nargs="+")
    source.add_argument("--items", type=Path, nargs="+")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/p14b-full-inventory-audit"))
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = audit_full_inventory(plan, archive_paths=args.archives,
                                  items_paths=args.items)
    write_full_inventory_audit(report, args.out_dir)
    s = report["summary"]
    print(json.dumps({
        "status": s["status"], "accounted": s["accounted_source_count"],
        "manifest": s["manifest_source_count"],
        "missing_sources": s["missing_source_count"],
        "reported_jobs": s["reported_job_count"],
        "planned_jobs": s["planned_job_count"],
        "package_pinned": s["package_pinned_and_verified"],
        "advisor_fact_approvals": 0, "output": str(args.out_dir),
    }, indent=2))


if __name__ == "__main__":
    main()
