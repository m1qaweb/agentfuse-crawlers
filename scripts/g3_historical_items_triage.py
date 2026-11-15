"""G3: real-Nov04-Items-backed offline source prioritization, NOT crawl readiness.

Reads three EXACT, SHA-256 pinned 2026-11-04 Zyte Items exports.
Preserves raw user files locally; exports only bounded source IDs, status
metadata, counts and diagnostics. DOES NOT export original scraped text,
tables, prices, released dates, original HTML, job secrets or any new
permission, and never contacts Zyte or publishers.

Historical parser "captured" != independent accuracy or current reliability.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.validation_access import digest
from scripts.audit_nov04_inventory import BASELINES, MANIFEST_SHA
from scripts.full_inventory_readiness import WAVES
from scripts.g0_priority_review_queue import CATEGORY_QUOTAS, CORE_PROVIDERS
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)

KIND = "g3_pinned_real_nov04_zyte_item_diagnostics_NOT_CRAWL_PERMISSION"
SCHEMA = "1.0"
HISTORICAL_OBSERVED_ON = "2026-11-04"
STATUS = frozenset({
    "captured", "needs_review", "partial_capture", "rejected_redirect",
    "http_error", "source_quarantined",
})
# Source-specific caution signals from G1 (not legal conclusions or a blanket
# prohibition). Preserve these source IDs in all denominator accounting.
G1_ELEVATED_TERMS_REVIEW = {
    "cursor_changelog": "g1_cursor_terms_scraping_restriction_unresolved",
    "vercel_ai_gateway_docs": "g1_vercel_website_extraction_terms_unresolved",
}
COLUMNS = (
    "historical_review_rank", "source_id", "provider", "category",
    "source_url", "historical_status_NOT_CURRENT",
    "historical_http_status_NOT_CURRENT",
    "historical_error", "historical_diagnostic_codes",
    "historical_triage_bucket_NOT_ACCURACY",
    "historical_pricing_observation_count_NOT_COMPARABLE",
    "historical_pricing_inventory_complete_NOT_PUBLISHER_GOLD",
    "historical_release_recent_event_count_NOT_VERIFIED",
    "historical_release_window_complete_NOT_PUBLISHER_GOLD",
    "historical_documentation_scope_NOT_WHOLE_CORPUS",
    "g1_elevated_terms_review_hint",
    "original_frozen_18_source_ID", "top_300_historical_REVIEW_ONLY",
    "supplemental_24_source_human_review_NOT_A_RUN_LIST",
    "publisher_permission_independently_verified",
    "approved_for_advisor", "next_manual_step",
)
SUFFIX = {
    "documentation": "items_official_documentation_15.json",
    "pricing": "items_official_pricing_11.json",
    "changelog": "items_official_changelogs_16.json",
}
CATEGORIES = ("documentation", "pricing", "changelog")
EXPECTED = {"documentation": 194, "pricing": 177, "changelog": 89}
REASON = re.compile(r"^[a-z][a-z0-9_]{1,100}$")
MAX_FILE_BYTES = 16_000_000


def _integer(value, name, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("Invalid historical count " + name)
    return value


def read_pinned_items(directory, *, manifest=None):
    """Only accept byte-exact historical source Items; no live permissions."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Existing original source Items directory required")
    sources = load_sources() if manifest is None else manifest
    if (len(sources) != 460 or len({s["id"] for s in sources}) != 460
            or manifest_sha256(sources) != MANIFEST_SHA):
        raise ValueError("Pinned November 4 460-source manifest changed")
    by_id = {s["id"]: s for s in sources}
    result = {}
    file_digests = {}
    for category in CATEGORIES:
        name = SUFFIX[category]
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing original Nov 4 Items export: " + name)
        raw = path.read_bytes()
        if not 2 <= len(raw) <= MAX_FILE_BYTES:
            raise ValueError("Original Nov 4 Items export exceeds size budget")
        fingerprint = hashlib.sha256(raw).hexdigest()
        if fingerprint != BASELINES[category]["sha"]["items"]:
            raise ValueError("Original Nov 4 Items SHA mismatch: " + name)
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Malformed original Nov 4 Items JSON") from exc
        if not isinstance(data, list) or len(data) != EXPECTED[category]:
            raise ValueError("Nov 4 Items per-category denominator changed")
        seen = set()
        for row in data:
            if not isinstance(row, dict):
                raise ValueError("Original source Item is not a JSON object")
            sid = row.get("source_id")
            source = by_id.get(sid)
            if (sid in seen or source is None
                    or source["category"] != category
                    or row.get("source_url") != source["url"]
                    or row.get("provider") != source["provider"]
                    or row.get("category") != category
                    or row.get("manifest_sha256") != MANIFEST_SHA
                    or row.get("zyte_job_id") != BASELINES[category]["job"]
                    or row.get("approved_for_advisor") is not False
                    or row.get("status") not in STATUS):
                raise ValueError("Historical source identity/status drift")
            seen.add(sid)
            result[sid] = row
        file_digests[name] = fingerprint
    if len(result) != 460 or set(result) != set(by_id):
        raise ValueError("Missing historical source IDs from original manifest")
    return sources, result, file_digests


def _diagnostics(row):
    reasons = row.get("diagnostic_reason_codes") or []
    if (not isinstance(reasons, list) or len(reasons) > 40
            or any(not isinstance(s, str) or not REASON.fullmatch(s)
                   for s in reasons)):
        raise ValueError("Unbounded or unexpected diagnostic reasons")
    return sorted(set(reasons))


def _priority(source, item):
    """Parser-observation triage, never probability or rights certification."""
    status = item["status"]
    cat = source["category"]
    http = item.get("http_status")
    if http is not None and (type(http) is not int or not 100 <= http <= 599):
        raise ValueError("Malformed historical HTTP status")
    price_obs = _integer(item.get("pricing_observation_count", 0) or 0,
                         "pricing observations", 500)
    recent = _integer(item.get("release_recent_event_count", 0) or 0,
                       "release events", 100)
    if status == "captured":
        bucket = "A_historically_captured_unverified"
        order = 0
    elif status == "partial_capture":
        bucket = "B_historical_partial_needs_gold"
        order = 1
    elif cat == "pricing" and http == 200 and price_obs > 0:
        bucket = "C_pricing_structural_observations_UNVERIFIED"
        order = 2
    elif status == "needs_review" and http == 200:
        bucket = "D_http200_parser_unresolved"
        order = 3
    elif status == "rejected_redirect":
        bucket = "E_redirect_requires_separate_review"
        order = 4
    elif status == "http_error":
        bucket = "F_http_error_no_reliable_capture"
        order = 5
    elif status == "source_quarantined":
        bucket = "G_lifecycle_quarantined"
        order = 6
    else:
        bucket = "D_other_unverified"
        order = 3
    # Policy warnings outrank attractive historical capture statuses in the
    # operator review shortlist but never remove a source from the 460 count.
    policy_hint = bool(G1_ELEVATED_TERMS_REVIEW.get(source["id"]))
    docs_scope = item.get("documentation_scope_status", "")
    docs_not_scoped = (
        cat == "documentation" and status == "captured"
        and docs_scope != "scoped_page"
    )
    release_incomplete = (
        cat == "changelog" and status == "captured"
        and item.get("release_window_complete") is not True
    )
    # These are deterministic ordinal triage *heuristics*: historical status
    # and explicit published metadata, never a confidence percentage.
    key = (
        policy_hint, order, docs_not_scoped, release_incomplete,
        source["provider"] not in CORE_PROVIDERS,
        -min(price_obs, 50) if cat == "pricing" else 0,
        -min(recent, 30) if cat == "changelog" else 0,
        source["id"],
    )
    return key, bucket, price_obs, recent


def build_triage(sources, items, file_sha):
    """Create explicit non-authorizing all-460/300/24 review materials."""
    if (len(sources) != 460 or set(items) != {s["id"] for s in sources}
            or set(file_sha) != set(SUFFIX.values())):
        raise ValueError("Full 460-source exact historical accounting required")
    frozen = [sid for wave in WAVES for sid, _ in wave]
    if len(frozen) != 18 or len(set(frozen)) != 18:
        raise ValueError("Original frozen 18-source denominator drift")
    frozen = set(frozen)
    sortable = []
    for source in sources:
        item = items[source["id"]]
        if (item.get("source_id") != source["id"]
                or item.get("source_url") != source["url"]
                or item.get("category") != source["category"]
                or item.get("status") not in STATUS
                or item.get("approved_for_advisor") is not False):
            raise ValueError("Injected historical row does not match pinned source")
        reasons = _diagnostics(item)
        key, bucket, price_obs, events = _priority(source, item)
        sortable.append((key, source, item, reasons, bucket, price_obs, events))
    selected, shortlist = set(), set()
    for cat in CATEGORIES:
        group = sorted((r for r in sortable if r[1]["category"] == cat),
                       key=lambda x: x[0])
        if len(group) != EXPECTED[cat]:
            raise ValueError("Unexpected category count")
        selected.update(x[1]["id"] for x in group[:CATEGORY_QUOTAS[cat]])
        # 8 *separate supplemental* operator-review candidates / category.
        # Original frozen research is unchanged, with denied subjects retained.
        candidates = [x for x in group if x[1]["id"] not in frozen
                      and x[1]["id"] not in G1_ELEVATED_TERMS_REVIEW]
        if len(candidates) < 8:
            raise ValueError("No candidate canary review sources in category")
        shortlist.update(x[1]["id"] for x in candidates[:8])
    if len(selected) != 300 or len(shortlist) != 24:
        raise ValueError("Historical queue numerator drift")
    ordered = (sorted((x for x in sortable if x[1]["id"] in selected),
                      key=lambda x: x[0])
               + sorted((x for x in sortable if x[1]["id"] not in selected),
                        key=lambda x: x[0]))
    rows = []
    for rank, (_, source, item, reasons, bucket, obs, events) in enumerate(
            ordered, start=1):
        sid = source["id"]
        status = item["status"]
        next_step = (
            "Independently review current publisher terms/robots/rights; "
            "inspect permitted original HTML and compare current parser output"
        )
        if sid in G1_ELEVATED_TERMS_REVIEW:
            next_step = "Resolve G1 publisher website extraction restrictions; no automatic fetch"
        if status == "rejected_redirect":
            next_step = "Independently review current canonical target and rights; no redirect following"
        if status in ("http_error", "source_quarantined"):
            next_step = "Review access/lifecycle causes before any new publisher GET"
        rows.append({
            "historical_review_rank": rank,
            "source_id": sid,
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "historical_status_NOT_CURRENT": status,
            "historical_http_status_NOT_CURRENT": item.get("http_status"),
            "historical_error": str(item.get("error") or "")[:110],
            "historical_diagnostic_codes": "|".join(reasons),
            "historical_triage_bucket_NOT_ACCURACY": bucket,
            "historical_pricing_observation_count_NOT_COMPARABLE": obs,
            "historical_pricing_inventory_complete_NOT_PUBLISHER_GOLD":
                item.get("pricing_inventory_complete") is True,
            "historical_release_recent_event_count_NOT_VERIFIED": events,
            "historical_release_window_complete_NOT_PUBLISHER_GOLD":
                item.get("release_window_complete") is True,
            "historical_documentation_scope_NOT_WHOLE_CORPUS":
                str(item.get("documentation_scope_status") or "")[:70],
            "g1_elevated_terms_review_hint": G1_ELEVATED_TERMS_REVIEW.get(sid, ""),
            "original_frozen_18_source_ID": sid in frozen,
            "top_300_historical_REVIEW_ONLY": sid in selected,
            "supplemental_24_source_human_review_NOT_A_RUN_LIST": sid in shortlist,
            "publisher_permission_independently_verified": False,
            "approved_for_advisor": False,
            "next_manual_step": next_step,
        })
    report = {
        "schema_version": SCHEMA, "kind": KIND,
        "status": "NO_GO_HISTORICAL_EVIDENCE_ONLY",
        "source_manifest_sha256": MANIFEST_SHA,
        "historical_export_date": HISTORICAL_OBSERVED_ON,
        "historical_items_sha256": dict(sorted(file_sha.items())),
        "source_count": 460, "selected_300_review_only": 300,
        "supplemental_canary_review_24_not_authorized": 24,
        "frozen_original_source_count": 18,
        "frozen_study_round_denominator_unchanged": 36,
        "category_counts": dict(Counter(x["category"] for x in rows)),
        "historical_status_counts": dict(sorted(
            Counter(x["historical_status_NOT_CURRENT"] for x in rows).items())),
        "historical_captured_by_category_NOT_ACCURACY": dict(sorted(
            Counter(x["category"] for x in rows
                    if x["historical_status_NOT_CURRENT"] == "captured").items())),
        "historical_pricing_http200": sum(
            x["category"] == "pricing" and x["historical_http_status_NOT_CURRENT"] == 200
            for x in rows),
        "historical_pricing_trusted_rates_claimed": 0,
        "new_source_approvals": 0, "new_zyte_jobs": 0, "publisher_requests_now": 0,
        "new_licensed_html_claims": 0, "approved_for_advisor": False,
        "separate_original_frozen_study_retained": True,
        "historical_items_are_current_accurate_or_licensed": False,
        "next_action": (
            "Resolve true source-specific access and deployed Zyte/account budget, "
            "then run a separately approved single source/round. Real HTML and human "
            "gold are needed before changing the 200-300 URL crawl GO/NO-GO."
        ),
    }
    report["report_sha256"] = digest(report)
    return report, rows, rows[:300], [x for x in rows if
        x["supplemental_24_source_human_review_NOT_A_RUN_LIST"]]


def _csv(fields, records):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
    writer.writeheader()
    for row in records:
        writer.writerow({name: _safe_csv(row.get(name, "")) for name in fields})
    return stream.getvalue().encode("utf-8-sig")


def write_triage(report, rows, top, shortlist, out_dir):
    if (report.get("kind") != KIND or report.get("status") !=
            "NO_GO_HISTORICAL_EVIDENCE_ONLY"
            or report.get("new_source_approvals") != 0
            or report.get("new_zyte_jobs") != 0
            or report.get("publisher_requests_now") != 0
            or report.get("approved_for_advisor") is not False
            or report.get("report_sha256") != digest({
                k: v for k, v in report.items() if k != "report_sha256"
            }) or len(rows) != 460 or len(top) != 300
            or len(shortlist) != 24):
        raise ValueError("Refusing unsafe or incomplete historical review artifact")
    root = _private_new_directory(out_dir)
    try:
        files = {
            "g3_historical_empirical_summary_NO_GO.json": (
                json.dumps(report, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8"),
            "g3_historical_triage_all460_REVIEW_ONLY.csv": _csv(COLUMNS, rows),
            "g3_historical_top300_NOT_RUN_LIST.csv": _csv(COLUMNS, top),
            "g3_historical_shortlist24_NOT_AUTHORIZED.csv": _csv(COLUMNS, shortlist),
        }
        for filename, contents in files.items():
            _write_private(root / filename, contents)
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="PRIVATE directory containing only three unmodified Nov04 Items exports")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="NEW private output directory; never checked into Git")
    args = parser.parse_args()
    result = build_triage(*read_pinned_items(args.input_dir))
    root = write_triage(*result, args.out_dir)
    print(json.dumps({
        "status": result[0]["status"], "sources": len(result[1]),
        "review_candidates": len(result[3]), "zyte_jobs_created": 0,
        "publisher_requests": 0, "output": str(root),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
