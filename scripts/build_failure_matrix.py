"""P15A: deterministic, multi-axis evidence matrix for pinned Zyte Items.

Dashboard Items are *post-extraction observations*, not the publisher's
original HTML and not proof of the accuracy of an individual fact. This
module does not fetch URLs, authorize sources, or write any advisor facts.
"""
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.diagnostics import derive_diagnostics
from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources, select_sources

CATEGORIES = ("documentation", "pricing", "changelog")
SPIDERS = {
    "documentation": "official_documentation",
    "pricing": "official_pricing",
    "changelog": "official_changelogs",
}
EXPECTED = {"documentation": 194, "pricing": 177, "changelog": 89}
SHA = re.compile(r"^[0-9a-f]{64}$")
JOB = re.compile(r"^[0-9]+/[0-9]+/[0-9]+$")
MAX_ITEMS_BYTES = 400_000_000
MAX_SOURCE_MATRIX = 460

# Review workload suggestions, never publisher permission or fact approvals.
PILOT_IDS = frozenset({
    "openai_api_pricing", "anthropic_api_pricing", "gemini_api_pricing",
    "xai_pricing", "aws_bedrock_pricing", "openai_api_docs",
    "kiro_docs", "google_cloud_ai_docs", "kiro_changelog",
    "devin_changelog", "openai_api_changelog",
})
MATRIX_FIELDS = (
    "source_id", "category", "provider", "official_source_url",
    "job_id", "source_status", "http_status", "content_sha256",
    "package_sha256", "acquisition_method", "page_family_hint",
    "priority", "review_owner", "status_requires_review",
    "policy_not_fetched", "fetch_access_issue", "redirect_identity_issue",
    "canonical_product_issue", "stale_or_cache_issue",
    "content_or_excerpt_clipping", "semantic_scope_issue",
    "pricing_observations_retained", "pricing_observations_detected",
    "pricing_region_unknown", "pricing_currency_unknown",
    "pricing_plan_unknown", "pricing_unit_unknown",
    "pricing_composite_observations",
    "pricing_comparable_candidates", "pricing_review_quotes",
    "pricing_tables_relevant", "pricing_tables_omitted",
    "documentation_topic_candidates", "documentation_nav_links_detected",
    "documentation_nav_links_omitted", "documentation_scope_status",
    "documentation_profile_status", "documentation_js_shell",
    "release_events_retained", "release_events_detected",
    "release_events_dated", "release_duplicate_id_surplus",
    "release_identity_collision", "release_window_incomplete",
    "latest_publication_verified", "reason_codes", "review_action",
    "original_publisher_html_archived",
)


def _read_json_array(path):
    path = Path(path)
    if path.stat().st_size > MAX_ITEMS_BYTES:
        raise ValueError("JSON array export too large")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise ValueError("Expected JSON array of objects: " + path.name)
    return data


def _fingerprint(obj):
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _safe_csv(value):
    raw = "" if value is None else str(value)
    return "'" + raw if raw.lstrip().startswith(("=", "+", "-", "@")) else raw


def _bool(value):
    return value is True


def _nonneg_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Invalid nonnegative counter: " + name)
    return value


def _counter(row, name):
    return _nonneg_int(row.get(name, 0) or 0, name)


def _page_family(row):
    if row.get("http_status") != 200:
        return "not_observed"
    category = row["category"]
    if category == "pricing":
        kinds = {
            o.get("evidence_kind") for o in row.get("pricing_observations", [])
            if isinstance(o, dict)
        }
        if "structured_table" in kinds:
            return "structured_pricing_table_observed"
        if kinds:
            return "other_pricing_evidence_observed"
        return "unclassified_pricing_html"
    if category == "documentation":
        if row.get("documentation_static_capture_status") == "javascript_shell_suspected":
            return "javascript_docs_shell_observed"
        if row.get("documentation_scope_status") == "index_only":
            return "documentation_index_observed"
        if row.get("documentation_scope_status") == "scoped_page":
            return "technical_documentation_section_observed"
        return "unclassified_documentation_html"
    if row.get("release_events"):
        return "release_events_in_html_observed"
    return "unclassified_release_html"


def _source_row(row, *, eligible):
    d = derive_diagnostics(row)
    reasons = d["diagnostic_reason_codes"]
    reason_set = set(reasons)
    category = row["category"]
    obs = row.get("pricing_observations") or []
    events = row.get("release_events") or []
    docs = row.get("documentation_topic_candidates") or []
    for name, value in (
        ("pricing_observations", obs), ("release_events", events),
        ("documentation_topic_candidates", docs),
    ):
        if not isinstance(value, list):
            raise ValueError("Malformed source evidence list: " + name)
    for e in obs + events + docs:
        if not isinstance(e, dict) or e.get("approved_for_advisor") is not False:
            raise ValueError("Unverified observation not safe to include in baseline")
    ids = [e.get("event_id") for e in events if e.get("event_id")]
    dup_events = len(ids) - len(set(ids))
    status = row.get("status", "unknown")
    canonical = bool(
        {"canonical_path_differs", "documentation_product_scope_ambiguous",
         "documentation_product_scope_not_demonstrated",
         "documentation_product_marker_only_in_body",
         "documentation_source_profile_url_mismatch",
         "documentation_canonical_migration_requires_review"} & reason_set
    )
    price_region = sum(o.get("region") in (None, "") for o in obs)
    price_currency = sum(o.get("currency") in (None, "") for o in obs)
    price_plan = sum(o.get("tier_or_plan") in (None, "") for o in obs)
    price_unit = sum(o.get("billing_unit") in (None, "") for o in obs)
    composite = sum(
        o.get("price_state") == "multiple_or_time_dependent"
        or "multiple_amounts_in_cell" in (o.get("normalization_blockers") or [])
        for o in obs
    )
    release_window_incomplete = category == "changelog" and (
        row.get("release_window_complete") is not True
    )
    site_clipping = bool(
        row.get("text_truncated") or row.get("sections_truncated")
        or row.get("tables_truncated") or row.get("historical_text_truncated")
        or row.get("pricing_evidence_lost_to_item_budget")
        or row.get("pricing_table_omitted_relevant")
        or row.get("documentation_item_budget_truncated")
        or row.get("documentation_nav_candidate_omitted")
        or row.get("release_events_truncated")
    )
    semantic = bool(
        (category == "pricing" and (
            not row.get("pricing_comparable_candidate_count")
            or not row.get("pricing_inventory_complete")
        ))
        or (category == "documentation" and (
            row.get("documentation_scope_status") != "scoped_page"
            or row.get("documentation_product_scope_signal") !=
               "explicit_marker_found"
            or row.get("documentation_requires_product_review")
        ))
        or (category == "changelog" and (
            row.get("release_event_identity_collision")
            or release_window_incomplete
            or not row.get("latest_release_date_candidate")
        ))
    ) if eligible else False
    policy_skip = not eligible
    access = bool(
        status in {"http_error", "source_access_limited",
                   "robots_or_policy_denied", "blocked", "fetch_error"}
        or (not policy_skip and row.get("http_status") != 200)
    )
    redirect = status in {"rejected_redirect", "redirect_needs_review"} or bool(
        {"source_path_redirected", "source_redirect_requires_review",
         "cross_host_or_non_https_redirect"} & reason_set
    )
    stale = bool(
        any("cache" in reason or "clock" in reason for reason in reasons)
        or any("cache" in str(flag).lower()
               for flag in row.get("scrapy_response_flags") or [])
    )
    if policy_skip:
        priority, action = "policy_blocked", "do_not_fetch_without_reviewed_permission"
    elif row["source_id"] in PILOT_IDS:
        priority, action = "P0_candidate", "independently_label_exact_source_evidence"
    elif access or redirect or canonical:
        priority, action = "P1", "resolve_source_identity_or_access_before_fact_parsing"
    elif semantic or site_clipping:
        priority, action = "P1", "review_extraction_completeness_and_semantics"
    else:
        priority, action = "P2", "human_review_unverified_source_observations"
    result = {
        "source_id": row["source_id"], "category": category,
        "provider": row["provider"], "official_source_url": row["source_url"],
        "job_id": row["zyte_job_id"], "source_status": status,
        "http_status": row.get("http_status"),
        "content_sha256": row.get("content_sha256") or "",
        "package_sha256": row["deployment_revision"],
        "acquisition_method": (
            "not_fetched_by_source_policy" if policy_skip
            else "static_http_response_observed_unverified"
            if row.get("http_status") == 200 else "fetch_failed_or_unverified"
        ),
        "page_family_hint": _page_family(row),
        "priority": priority, "review_owner": "",
        "status_requires_review": status != "captured",
        "policy_not_fetched": policy_skip,
        "fetch_access_issue": access,
        "redirect_identity_issue": redirect,
        "canonical_product_issue": canonical,
        "stale_or_cache_issue": stale,
        "content_or_excerpt_clipping": site_clipping,
        "semantic_scope_issue": semantic,
        "pricing_observations_retained": len(obs),
        "pricing_observations_detected": _counter(row, "pricing_observation_total_detected"),
        "pricing_region_unknown": price_region,
        "pricing_currency_unknown": price_currency,
        "pricing_plan_unknown": price_plan,
        "pricing_unit_unknown": price_unit,
        "pricing_composite_observations": composite,
        "pricing_comparable_candidates": _counter(row, "pricing_comparable_candidate_count"),
        "pricing_review_quotes": _counter(row, "pricing_review_quote_candidate_count"),
        "pricing_tables_relevant": _counter(row, "pricing_table_relevant"),
        "pricing_tables_omitted": _counter(row, "pricing_table_omitted_relevant"),
        "documentation_topic_candidates": len(docs),
        "documentation_nav_links_detected": _counter(row, "documentation_nav_candidate_total_detected"),
        "documentation_nav_links_omitted": _counter(row, "documentation_nav_candidate_omitted"),
        "documentation_scope_status": row.get("documentation_scope_status") or "",
        "documentation_profile_status": row.get("documentation_profile_status") or "",
        "documentation_js_shell": row.get("documentation_static_capture_status") ==
                                   "javascript_shell_suspected",
        "release_events_retained": len(events),
        "release_events_detected": _counter(row, "release_event_count"),
        "release_events_dated": sum(bool(e.get("published_at")) for e in events),
        "release_duplicate_id_surplus": dup_events,
        "release_identity_collision": _bool(row.get("release_event_identity_collision")),
        "release_window_incomplete": release_window_incomplete,
        "latest_publication_verified": _bool(row.get("latest_publication_verified")),
        "reason_codes": ",".join(sorted(reasons)),
        "review_action": action,
        "original_publisher_html_archived": False,
    }
    return result


def build_failure_matrix(by_category):
    """Fail closed if even one expected source, job or hash is missing.

    This reads exactly three complete category exports, including the
    explicit *no-fetch* Items emitted for publisher-policy quarantines.
    It does not authenticate Zyte Dashboard exports to remote job storage.
    """
    if not isinstance(by_category, dict) or set(by_category) != set(CATEGORIES):
        raise ValueError("Require all three category Item exports")
    manifest = load_sources()
    expected_by_id = {s["id"]: s for s in manifest}
    if len(manifest) != 460 or len(expected_by_id) != 460:
        raise ValueError("460-source manifest not preserved")
    registry_sha = registry_revision_sha256()
    manifest_sha = manifest_sha256(manifest)
    rows = []
    job_ids = {}
    package_shas = set()
    all_ids = set()
    by_cat_summary = {}
    for category in CATEGORIES:
        entries = by_category[category]
        if not isinstance(entries, list) or len(entries) != EXPECTED[category]:
            raise ValueError("Missing or extra source summary Items: " + category)
        selected = select_sources(category, "all")
        expected_ids = {s["id"] for s in selected}
        observed_ids = set()
        context = set()
        counter = Counter()
        for row in entries:
            if not isinstance(row, dict):
                raise ValueError("Malformed Zyte source summary Item")
            sid = row.get("source_id")
            src = expected_by_id.get(sid) if isinstance(sid, str) else None
            if sid not in expected_ids or sid in observed_ids:
                raise ValueError("Duplicate, unknown or wrong-category source ID: " + str(sid))
            if (src["category"] != category or row.get("category") != category
                    or row.get("source_url") != src["url"]
                    or row.get("provider") != src["provider"]
                    or row.get("spider_name") != SPIDERS[category]
                    or row.get("approved_for_advisor") is not False):
                raise ValueError("Source identity or advisor approval invariant violated: " + sid)
            if (row.get("manifest_sha256") != manifest_sha
                    or row.get("source_registry_sha256") != registry_sha
                    or row.get("selection_ids_sha256") !=
                       selection_ids_sha256(selected)
                    or row.get("selection_source_count") != EXPECTED[category]
                    or row.get("requested_cohort") != "all"
                    or row.get("run_scope_explicit") is not True
                    or row.get("collection_mode") != "validation"
                    or row.get("deployment_revision_kind") !=
                       "package_py_json_sha256_v1"
                    or not isinstance(row.get("deployment_revision"), str)
                    or not SHA.fullmatch(row["deployment_revision"])):
                raise ValueError("Crawl scope/publisher registry/package provenance mismatch: " + sid)
            job = row.get("zyte_job_id")
            if not isinstance(job, str) or not JOB.fullmatch(job):
                raise ValueError("Missing/invalid Zyte job identifier: " + sid)
            context.add(job)
            package_shas.add(row["deployment_revision"])
            observed_ids.add(sid)
            eligible, _ = collection_decision(src, "validation")
            if not eligible:
                if (row.get("http_status") is not None
                        or row.get("status") not in {
                            "source_quarantined", "source_retired"
                        }):
                    raise ValueError("Publisher restricted source unexpectedly fetched: " + sid)
            result = _source_row(row, eligible=eligible)
            counter[result["source_status"]] += 1
            rows.append(result)
        if len(context) != 1 or observed_ids != expected_ids:
            raise ValueError("Incomplete category or cross-job source mix: " + category)
        job_ids[category] = next(iter(context))
        by_cat_summary[category] = {
            "configured_sources": EXPECTED[category],
            "source_status_counts": dict(sorted(counter.items())),
        }
        all_ids.update(observed_ids)
    if len(all_ids) != 460 or len(set(job_ids.values())) != 3 or len(package_shas) != 1:
        raise ValueError("Source, job or deployment package identity mismatch")
    rows.sort(key=lambda row: (CATEGORIES.index(row["category"]), row["source_id"]))
    counts = Counter()
    flags = Counter()
    for row in rows:
        counts["http_200_sources"] += int(row["http_status"] == 200)
        counts["policy_skipped_sources"] += int(row["policy_not_fetched"])
        for key in (
            "pricing_observations_retained", "pricing_observations_detected",
            "pricing_region_unknown", "pricing_currency_unknown",
            "pricing_plan_unknown", "pricing_unit_unknown",
            "pricing_composite_observations", "pricing_comparable_candidates",
            "pricing_review_quotes", "pricing_tables_relevant", "pricing_tables_omitted",
            "documentation_topic_candidates", "documentation_nav_links_detected",
            "documentation_nav_links_omitted", "release_events_retained",
            "release_events_detected", "release_events_dated",
            "release_duplicate_id_surplus",
        ):
            counts[key] += row[key]
        for flag in (
            "policy_not_fetched", "fetch_access_issue", "redirect_identity_issue",
            "canonical_product_issue", "stale_or_cache_issue",
            "content_or_excerpt_clipping", "semantic_scope_issue",
            "documentation_js_shell", "release_identity_collision",
            "release_window_incomplete", "latest_publication_verified",
        ):
            flags[flag] += int(row[flag])
    summary = {
        "schema_version": "1.0",
        "report_kind": "reproducible_post_extraction_failure_matrix_not_vendor_truth",
        "manifest_source_count": 460,
        "source_item_count": len(rows),
        "missing_or_duplicate_source_count": 0,
        "job_ids": job_ids,
        "manifest_sha256": manifest_sha,
        "source_registry_sha256": registry_sha,
        "deployed_package_sha256": next(iter(package_shas)),
        "category_metrics": by_cat_summary,
        "observed_counters": dict(sorted(counts.items())),
        "concurrent_source_flags": dict(sorted(flags.items())),
        "full_original_publisher_html_replay_available": False,
        "source_snapshot_integrity_verified_against_zyte_api": False,
        "dashboard_export_byte_hashes_required_for_reproducibility": True,
        "publisher_fact_accuracy_independently_verified": False,
        "advisor_fact_approvals": 0,
        "deployment_authorized": False,
        "network_requests_performed": 0,
    }
    return {"summary": summary, "sources": rows}


def write_failure_matrix(report, out_dir):
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "source_failure_matrix.csv").open(
        "w", newline="", encoding="utf-8-sig",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=MATRIX_FIELDS)
        writer.writeheader()
        writer.writerows({
            key: _safe_csv(row.get(key, "")) for key in MATRIX_FIELDS
        } for row in report["sources"])
    with (output / "source_failure_matrix.jsonl").open(
        "w", encoding="utf-8",
    ) as stream:
        for row in report["sources"]:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    (output / "quality_baseline.json").write_text(
        json.dumps(report["summary"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output
