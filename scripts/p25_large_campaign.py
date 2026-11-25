"""P25: deterministic 200-300 publisher-URL campaign across 3 full-category jobs.

This is a *real* bulk-campaign scope builder for the existing P21B/P23E0
spiders, not authorization or an independent Zyte deployment audit. A
review-only G3 300-source CSV defines candidates; the installed, separately
Git-reviewed per-URL access and 3 full-category run plans define permission.
"""

import argparse
import csv
import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.run_context import manifest_sha256, package_fingerprint, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import collection_decision, registry_revision_sha256
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.validation_access import (
    authorize_bulk_run, bulk_plan_revision_sha256, digest,
    load_access_registry, load_run_plan_registry,
    validate_access_registry, validate_plan_registry,
    _utc, validation_access_revision_sha256,
)
from scripts.audit_nov04_inventory import MANIFEST_SHA
from scripts.g3_historical_items_triage import (
    COLUMNS as G3_COLUMNS, STATUS as G3_STATUS,
)
from scripts.plan_documentation_children import _private_new_directory, _write_private

COMPACT_ARGS = {"cohort": "all", "confirm_full_inventory": "yes", "collection_mode": "validation"}
PIN_FIELDS = ("bulk_run_plan_id", "expected_bulk_plan_sha256",
              "expected_deployment_package_sha256")


def pinned_spider_args(campaign, job, plans):
    """Exact runtime identity, independently checked by the existing P21B gate."""
    pid = job["matching_plan_id_NOT_REMOTE_PROOF"]
    if job["reviewed_plan_authorization_status"] != "exact_approved_subset" or not pid:
        raise ValueError("Cannot pin a job without an exact approved plan")
    plan = plans["plans"][pid]
    return {**COMPACT_ARGS, "bulk_run_plan_id": pid,
            "expected_bulk_plan_sha256": digest(plan),
            "expected_deployment_package_sha256": campaign["local_package_sha256_NOT_REMOTE_PROOF"]}


def exact_pinned_args_shape(args):
    from agentfuse_crawlers.validation_access import PLAN_ID, SHA256
    return (isinstance(args, dict) and set(args) == set(COMPACT_ARGS) | set(PIN_FIELDS)
            and all(args[k] == v for k, v in COMPACT_ARGS.items())
            and all(isinstance(args[k], str) for k in PIN_FIELDS)
            and PLAN_ID.fullmatch(args["bulk_run_plan_id"]) is not None
            and SHA256.fullmatch(args["expected_bulk_plan_sha256"]) is not None
            and SHA256.fullmatch(args["expected_deployment_package_sha256"]) is not None)

KIND = "p25_200_300_full_category_campaign_NOT_CRAWL_PERMISSION"
VERSION = "1.0"
ORDER = ("pricing", "documentation", "changelog")
QUOTA_300 = {"documentation": 120, "pricing": 120, "changelog": 60}
MANIFEST_COUNTS = {"documentation": 194, "pricing": 177, "changelog": 89}
SPIDERS = {
    "documentation": "official_documentation",
    "pricing": "official_pricing",
    "changelog": "official_changelogs",
}
G3_FILENAME = "g3_historical_top300_NOT_RUN_LIST.csv"
G3_ALL_FILENAME = "g3_historical_triage_all460_REVIEW_ONLY.csv"
MAX_G3_BYTES = 2_000_000


def _target(value):
    if type(value) is not int or not 200 <= value <= 300 or value % 5:
        raise ValueError("Campaign target must be 200 through 300, in increments of five")
    return value


def _manifest():
    sources = load_sources()
    if (len(sources) != 460
            or Counter(s["category"] for s in sources) != MANIFEST_COUNTS
            or manifest_sha256(sources) != MANIFEST_SHA):
        raise ValueError("Current publisher URL manifest differs from original pinned 460")
    return sources


def read_g3_review_csv(path):
    """No raw HTML/Items, only existing G3 ranked REVIEW ONLY source metadata."""
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.name not in (
            G3_FILENAME, G3_ALL_FILENAME):
        raise ValueError("Require a genuine named G3 top300 or all460 review CSV")
    raw = file.read_bytes()
    if not 100 <= len(raw) <= MAX_G3_BYTES:
        raise ValueError("G3 review CSV outside bounded size")
    try:
        table = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if table.fieldnames != list(G3_COLUMNS):
            raise ValueError("G3 CSV schema changed or extra spreadsheet columns")
        rows = list(table)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Malformed G3 review CSV") from exc
    expected_count = 300 if file.name == G3_FILENAME else 460
    if len(rows) != expected_count:
        raise ValueError("G3 review CSV row count differs from its declared scope")
    sources = _manifest()
    known = {s["id"]: s for s in sources}
    counts, seen = Counter(), set()
    for idx, row in enumerate(rows, 1):
        sid = row.get("source_id")
        source = known.get(sid)
        if (sid in seen or source is None
                or row.get("historical_review_rank") != str(idx)
                or row.get("source_url") != source["url"]
                or row.get("category") != source["category"]
                or row.get("provider") != source["provider"]
                or row.get("top_300_historical_REVIEW_ONLY") != (
                    "True" if idx <= 300 else "False")
                or row.get("publisher_permission_independently_verified") != "False"
                or row.get("approved_for_advisor") != "False"
                or row.get("historical_status_NOT_CURRENT") not in G3_STATUS):
            raise ValueError("G3 historic review CSV cannot change exact source bindings")
        seen.add(sid)
        counts[source["category"]] += 1
    expected_quotas = QUOTA_300 if expected_count == 300 else MANIFEST_COUNTS
    if counts != expected_quotas:
        raise ValueError("G3 ranked review category quotas changed")
    return rows


def _campaign_identity(target, category_ids, package_sha, access_sha, plan_sha):
    return digest({
        "version": VERSION, "target": target, "manifest_sha256": MANIFEST_SHA,
        "category_ids_in_manifest_order": category_ids,
        "running_package_sha256": package_sha,
        "installed_access_review_registry_sha256": access_sha,
        "installed_bulk_plan_registry_sha256": plan_sha,
    })


def build_campaign(g3_rows, target, *, access=None, plans=None, now=None,
                   package_sha=None):
    """Full 460 manifest coverage; exact 200-300 subset requires 3 reviewed plans."""
    target = _target(target)
    sources = _manifest()
    if len(g3_rows) not in (300, 460) or any(
            not isinstance(r, dict) for r in g3_rows):
        raise ValueError("Expected 300 or 460 inspected G3 ranking rows")
    # Verify review inputs even when tests inject synthetic in-memory policies.
    access = load_access_registry() if access is None else access
    plans = load_run_plan_registry() if plans is None else plans
    validate_access_registry(access, now=now)
    validate_plan_registry(plans, now=now)
    pkg = package_fingerprint() if package_sha is None else package_sha
    if not isinstance(pkg, str) or len(pkg) != 64 or any(c not in "0123456789abcdef" for c in pkg):
        raise ValueError("Invalid installed-package content fingerprint")
    quotas = {
        "documentation": 2 * target // 5,
        "pricing": 2 * target // 5,
        "changelog": target // 5,
    }
    known = {s["id"]: s for s in sources}
    ranking_ids = [r.get("source_id") for r in g3_rows]
    if len(set(ranking_ids)) != len(g3_rows) or any(
            x not in known for x in ranking_ids):
        raise ValueError("Invalid G3 source ID ranking")
    # Fully check ranked 300 or 460 category coverage. All-460 allows
    # genuine alternative reviews to fill a 300-URL campaign.
    expected_pool = QUOTA_300 if len(g3_rows) == 300 else MANIFEST_COUNTS
    if Counter(known[sid]["category"] for sid in ranking_ids) != expected_pool:
        raise ValueError("G3 ranked source-category accounting mismatch")
    # Choose among the ranked 300 with a practical approved-source fallback:
    # for a 200- or 250-URL campaign a historic high-ranked denied publisher
    # must not prevent using a *different* already-reviewed candidate from
    # the SAME category. All G3 rankings remain review hints, never licenses.
    # P21B independently rechecks every selected URL and exact 3-plan scope.
    # The registry has already been schema/URL/terms validated ONCE above.
    # This lookup is only a deterministic RANKING HINT, not authorization.
    # Revalidating all ~300 reviews for EACH of 460 candidate IDs is O(N^2)
    # and significantly increases full-campaign startup time. The existing
    # authorize_bulk_run() below remains the authoritative, fail-closed
    # per-source security boundary and rechecks all approved source URLs.
    clock = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    currently_reviewed = {}
    for sid in ranking_ids:
        review = access["reviews"].get(sid)
        currently_reviewed[sid] = bool(
            review and review["decision"] == "allowed_reviewed"
            and "bulk_validation" in review["scopes"]
            and _utc(review["reviewed_at_utc"]) <= clock < _utc(review["expires_at_utc"])
            and collection_decision(known[sid], "validation")[0]
        )
    chosen = set()
    for cat, n in quotas.items():
        ranked = [sid for sid in ranking_ids if known[sid]["category"] == cat]
        # Current reviewed + lifecycle-approved sources first; then the
        # original ranking for pending reviews, preserving determinism.
        ordered = [sid for sid in ranked if currently_reviewed[sid]]
        ordered += [sid for sid in ranked if not currently_reviewed[sid]
                    and collection_decision(known[sid], "validation")[0]]
        ordered += [sid for sid in ranked if not currently_reviewed[sid]
                    and not collection_decision(known[sid], "validation")[0]]
        chosen.update(ordered[:n])
    if len(chosen) != target:
        raise ValueError("Non-unique or incomplete target campaign")
    category_ids = {}
    jobs = []
    selected_reviewed = 0
    issues = []
    for category in ORDER:
        whole = select_sources(category, "all")
        ids = [s["id"] for s in whole if s["id"] in chosen]
        category_ids[category] = ids
        if len(ids) != quotas[category]:
            raise ValueError("Requested source quota does not match manifest")
        invalid_lifecycle = [s["id"] for s in whole if s["id"] in chosen
                             and not collection_decision(s, "validation")[0]]
        reviewed = [s["id"] for s in whole
                    if s["id"] in chosen and currently_reviewed[s["id"]]]
        selected_reviewed += len(reviewed)
        matched = [(pid, p) for pid, p in plans["plans"].items()
                   if p["category"] == category and p["cohort"] == "all"
                   and p["collection_mode"] == "validation"
                   and p["source_ids"] == [s["id"] for s in whole]]
        plan_status = "no_reviewed_full_category_plan"
        pid = None
        accepted = []
        if len(matched) == 1:
            pid, candidate = matched[0]
            # This is the EXISTING PRODUCTION authorization gate, reused
            # verbatim with exact installed policy, plan, package and time.
            try:
                decision = authorize_bulk_run(
                    selected=whole, category=category, cohort="all",
                    collection_mode="validation", plan_id=pid,
                    expected_plan_sha256=digest(candidate),
                    expected_package_sha256=pkg,
                    current_package_sha256=pkg,
                    access_registry=access, run_plans=plans, now=now,
                )
                accepted = [s["id"] for s in whole
                            if s["id"] in decision["authorized_source_ids"]]
                plan_status = ("exact_approved_subset" if accepted == ids
                               else "authorized_subset_does_not_match_campaign")
            except ValueError:
                plan_status = "invalid_expired_or_wrong_scope_run_plan"
        elif len(matched) > 1:
            plan_status = "ambiguous_full_category_run_plans"
        if plan_status != "exact_approved_subset":
            issues.append(category + ":" + plan_status)
        if invalid_lifecycle:
            issues.append(category + ":target_contains_lifecycle_held_source")
        if len(reviewed) != len(ids):
            issues.append(category + ":missing_current_bulk_url_access_reviews")
        jobs.append({
            "category": category, "spider": SPIDERS[category],
            "requested_manifest_items": len(whole),
            "target_authorized_primary_urls": len(ids),
            "target_source_ids_manifest_order": ids,
            "held_manifest_items_target": len(whole) - len(ids),
            "reviewed_bulk_access_count": len(reviewed),
            "lifecycle_held_target_ids": invalid_lifecycle,
            "matching_plan_id_NOT_REMOTE_PROOF": pid or "",
            "reviewed_plan_authorization_status": plan_status,
            "spider_args": {
                "cohort": "all",
                "confirm_full_inventory": "yes",
                "collection_mode": "validation",
            },
            "job_units": 1, "job_priority": 2,
        })
    access_sha = validation_access_revision_sha256(access)
    plans_sha = bulk_plan_revision_sha256(plans)
    report = {
        "schema_version": VERSION, "kind": KIND,
        "status": "NO_GO_UNTIL_PUBLISHER_ACCOUNT_AND_DEPLOYMENT_VERIFIED",
        "target_primary_urls": target,
        "historical_review_candidate_pool": len(g3_rows),
        "total_accounted_manifest_source_ids": 460,
        "category_quotas": quotas,
        "planned_full_category_jobs": 3,
        "target_held_manifest_items": 460-target,
        "reviewed_bulk_source_count_in_campaign": selected_reviewed,
        "missing_current_source_access_reviews": target-selected_reviewed,
        "local_policy_and_three_plan_scope_complete": not issues,
        "blockers": issues,
        "manifest_sha256": MANIFEST_SHA,
        "source_registry_sha256": registry_revision_sha256(),
        "access_registry_sha256": access_sha,
        "bulk_run_registry_sha256": plans_sha,
        "local_package_sha256_NOT_REMOTE_PROOF": pkg,
        "g3_historical_ranking_not_publisher_permission": True,
        "reviewed_first_with_same_category_historical_fallback": True,
        "remote_deployment_independently_verified": False,
        "account_billing_spend_ceiling_verified": False,
        "publisher_terms_independently_verified_by_this_tool": False,
        "readiness_to_launch_from_this_report": False,
        "new_scrapy_cloud_jobs": 0,
        "publisher_requests_performed": 0,
        "approved_for_advisor": False,
        "jobs": jobs,
    }
    report["campaign_sha256"] = _campaign_identity(
        target, category_ids, pkg, access_sha, plans_sha,
    )
    for job in jobs:
        job["pinned_spider_args"] = (pinned_spider_args(report, job, plans)
                                     if job["reviewed_plan_authorization_status"] == "exact_approved_subset"
                                     else None)
    report["report_sha256"] = digest(report)
    return report


def write_report(report, out_dir):
    if (report.get("kind") != KIND or report.get("status") !=
            "NO_GO_UNTIL_PUBLISHER_ACCOUNT_AND_DEPLOYMENT_VERIFIED"
            or report.get("readiness_to_launch_from_this_report") is not False
            or report.get("new_scrapy_cloud_jobs") != 0
            or report.get("publisher_requests_performed") != 0
            or report.get("report_sha256") != digest({
                k: v for k, v in report.items() if k != "report_sha256"
            })):
        raise ValueError("Refusing a privileged or edited campaign report")
    root = _private_new_directory(out_dir)
    try:
        _write_private(root / "p25_full_campaign_plan_NO_GO.json",
                       (json.dumps(report, indent=2) + "\n").encode("utf-8"))
    except Exception:
        import shutil
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    ranked = parser.add_mutually_exclusive_group(required=True)
    ranked.add_argument("--g3-top300", type=Path)
    ranked.add_argument("--g3-all460", type=Path)
    parser.add_argument("--target", type=int, choices=range(200, 301, 5), default=300)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    csv_path = args.g3_all460 or args.g3_top300
    report = build_campaign(read_g3_review_csv(csv_path), args.target)
    root = write_report(report, args.out_dir)
    print(json.dumps({
        "out_dir": str(root), "campaign_sha256": report["campaign_sha256"],
        "target": report["target_primary_urls"],
        "currently_reviewed": report["reviewed_bulk_source_count_in_campaign"],
        "full_category_jobs": 3, "local_policy_scope_ready":
            report["local_policy_and_three_plan_scope_complete"],
        "zyte_jobs_created": 0, "readiness_to_launch": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
