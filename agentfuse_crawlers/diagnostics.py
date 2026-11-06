"""Multi-axis, non-authorizing diagnostics for crawler Items.

A single legacy status/error remains compatible, but it must not erase other
observed problems (for example canonical mismatch AND insufficient docs).
All evidence is unverified; this module never grants alert/monitor/advisor use.
"""

import re
from urllib.parse import urlsplit

SCHEMA_VERSION = "1.0"
AXES = (
    "fetch_status",
    "access_policy_status",
    "source_identity_status",
    "freshness_status",
    "content_capture_status",
    "semantic_evidence_status",
    "completeness_status",
    "alert_eligibility",
)
SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
LIMIT_REASONS = 24

FAIL_FETCH = {
    "fetch_error", "http_error", "robots_or_policy_denied",
    "unsupported_content_type", "extraction_error",
    "source_access_limited",
}
SKIPPED = {
    "source_quarantined", "source_retired",
    "source_not_validated_for_monitor",
    "source_bulk_validation_not_approved",
    "source_single_validation_not_approved",
}


def _canonical_path_differs(record):
    official = record.get("source_url")
    canonical = record.get("canonical_url")
    if not isinstance(official, str) or not isinstance(canonical, str) or not canonical:
        return False
    try:
        source, target = urlsplit(official), urlsplit(canonical)
        if (target.scheme != "https" or source.hostname != target.hostname
                or target.username or target.password):
            return False  # Foreign canonicals were already rejected.
        if (record.get("category") == "documentation"
                and record.get("documentation_canonical_relation") == "equivalent_path"):
            return False
        return source.path.rstrip("/") != target.path.rstrip("/")
    except ValueError:
        return False


def _path_redirected(record):
    chain = record.get("redirect_chain") or []
    source_url, final_url = record.get("source_url"), record.get("final_url")
    if not chain or not isinstance(source_url, str) or not isinstance(final_url, str):
        return False
    try:
        return urlsplit(source_url).path.rstrip("/") != urlsplit(final_url).path.rstrip("/")
    except ValueError:
        return False


def derive_diagnostics(record):
    """Return bounded, separate observed axes + stable concurrent reasons.

    Does not reinterpret status as approval, infer publisher facts, or perform
    network access. Recomputable for old exported Items as a forensic report.
    """
    status = str(record.get("status") or "unknown")
    category = record.get("category")
    reasons = []

    def add(code):
        if isinstance(code, str) and SAFE_REASON.fullmatch(code) and code not in reasons:
            reasons.append(code)

    primary = str(record.get("error") or "").strip()
    if primary:
        if re.fullmatch(r"HTTP [1-5]\d{2}", primary):
            add("http_" + primary.split()[-1])
        elif SAFE_REASON.fullmatch(primary):
            add(primary)
        else:
            add("primary_error_requires_review")

    policy_state = record.get("source_policy_status")
    lifecycle = record.get("source_lifecycle_state")
    if status in SKIPPED:
        add(status)
    if lifecycle == "quarantined":
        add("source_quarantined")
    if status in {"robots_or_policy_denied", "source_access_limited"}:
        add("publisher_access_denied_or_limited")

    if status in {"rejected_redirect", "redirect_needs_review"}:
        add("source_redirect_requires_review")
    if _path_redirected(record):
        add("source_path_redirected")
    if _canonical_path_differs(record):
        add("canonical_path_differs")

    if record.get("source_product_identity_schema") == "2.0":
        if record.get("source_product_title_conflict"):
            add("source_product_title_conflict")
        elif record.get("source_title_alias_evidence_status") in {
            "body_only_not_owner_proof", "description_only_not_owner_proof"
        }:
            add("source_product_alias_not_in_title")
        elif (record.get("source_expected_product_id")
              and record.get("source_title_alias_evidence_status") ==
                  "title_does_not_establish_product_owner"):
            add("source_product_title_identity_not_established")

    warnings = record.get("freshness_warnings") or []
    for warning in warnings:
        add(warning)
    flags = record.get("scrapy_response_flags") or []
    scrapy_cache = any("cache" in str(flag).lower() for flag in flags)
    if scrapy_cache:
        add("scrapy_cached_response_not_fresh")

    if record.get("text_truncated"):
        add("text_exceeds_capture_limit")
    if record.get("sections_truncated"):
        add("sections_truncated")
    if record.get("tables_truncated"):
        add("tables_truncated")
    if record.get("release_event_evidence_lost"):
        add("release_event_evidence_lost")
    if record.get("pricing_evidence_lost_to_item_budget"):
        add("pricing_evidence_lost_to_item_budget")
    if record.get("documentation_item_budget_truncated"):
        add("documentation_item_budget_truncated")

    product_review = bool(record.get("source_product_title_conflict"))
    if category == "documentation":
        scope = record.get("documentation_scope_status")
        if scope in ("scope_not_established", "insufficient_content", "index_only"):
            add("documentation_" + scope)
        if record.get("documentation_requires_product_review"):
            add("documentation_product_scope_ambiguous")
            product_review = True
        signal = record.get("documentation_product_scope_signal")
        if signal == "marker_not_found":
            add("documentation_product_scope_not_demonstrated")
            product_review = True
        if signal == "body_only_marker_requires_review":
            add("documentation_product_marker_only_in_body")
            product_review = True
        if record.get("documentation_profile_status") == "profile_url_mismatch":
            add("documentation_source_profile_url_mismatch")
            product_review = True
        if record.get("documentation_canonical_relation") == "same_host_path_differs":
            add("canonical_path_differs")
        if record.get("documentation_topic_candidate_omitted", 0):
            add("documentation_topic_candidates_omitted")
        if record.get("documentation_static_capture_status") == "javascript_shell_suspected":
            add("documentation_javascript_shell_suspected")
        if record.get("documentation_nav_candidates"):
            add("documentation_child_links_not_approved_for_crawl")
        if record.get("documentation_nav_candidate_omitted"):
            add("documentation_review_links_omitted")
        if record.get("documentation_nav_links_scan_truncated"):
            add("documentation_navigation_scan_truncated")
        if record.get("documentation_canonical_migration_status") == "review_required_never_auto_follow":
            add("documentation_canonical_migration_requires_review")
        if scope == "overview_only":
            add("documentation_overview_not_full_corpus")
    elif category == "pricing" and record.get("pricing_evidence_schema"):
        if record.get("pricing_product_scope_unresolved"):
            add("pricing_product_scope_unresolved")
            product_review = True
        if not record.get("pricing_inventory_complete"):
            add("pricing_inventory_incomplete")
        if not record.get("pricing_observation_count"):
            add("pricing_no_structured_rate_evidence")
        elif not record.get("pricing_comparable_candidate_count"):
            add("pricing_rate_dimensions_unresolved")
        if record.get("pricing_rate_identity_collision_count"):
            add("pricing_rate_identity_collision")
    elif category == "changelog" and record.get("release_events_schema"):
        if record.get("release_event_identity_collision"):
            add("release_event_identity_collision")
        if record.get("release_date_scoped_generic_event_count"):
            add("date_scoped_generic_release_identity_requires_review")
        if (record.get("release_individual_date_candidates")
                and not record.get("latest_release_date_candidate")):
            add("individual_release_dates_not_verified_latest")
        if record.get("release_recent_body_loss_count"):
            add("recent_release_body_incomplete")
        if not record.get("release_event_count"):
            add("no_release_events_detected")
        elif not record.get("release_dated_event_count"):
            add("release_events_missing_publication_dates")
        elif not record.get("latest_release_date_candidate"):
            add("latest_release_date_ambiguous")
        if not record.get("release_window_complete"):
            add("release_window_incomplete")

    if status == "source_bulk_validation_not_approved":
        fetch = "not_attempted_by_bulk_access_policy"
    elif status == "source_single_validation_not_approved":
        fetch = "not_attempted_by_single_source_access_policy"
    elif status in SKIPPED:
        fetch = "not_attempted_by_lifecycle"
    elif status in FAIL_FETCH:
        fetch = "failed_or_denied"
    elif isinstance(record.get("http_status"), int):
        fetch = "http_response_observed"
    else:
        fetch = "unknown"

    if lifecycle == "quarantined" or policy_state == "unresolved":
        policy = "quarantined_or_unresolved"
    elif status == "source_bulk_validation_not_approved":
        policy = "bulk_validation_unapproved"
    elif status == "source_single_validation_not_approved":
        policy = "single_validation_unapproved"
    elif status in {"robots_or_policy_denied", "source_access_limited"}:
        policy = "denied_or_limited"
    elif policy_state == "allowed_reviewed":
        policy = "reviewed_allowed"
    elif policy_state == "prohibited_reviewed":
        policy = "reviewed_prohibited"
    else:
        policy = "not_reviewed"

    if (status in {"rejected_redirect", "redirect_needs_review"}
            or _path_redirected(record) or _canonical_path_differs(record)
            or product_review
            or (record.get("source_expected_product_id")
                and record.get("source_product_ownership_verified") is False)):
        identity = "review_required"
    elif fetch == "http_response_observed" and record.get("content_sha256"):
        identity = "page_observed_unverified"
    else:
        identity = "not_established"

    freshness = (
        "cache_or_clock_review" if warnings or scrapy_cache
        else "not_independently_verified" if fetch == "http_response_observed"
        else "not_observed"
    )
    if status in SKIPPED:
        content = "not_fetched"
    elif status in FAIL_FETCH or status in {"rejected_redirect", "redirect_needs_review", "blocked"}:
        content = "unavailable_or_blocked"
    elif (record.get("word_count") is not None
          and record.get("word_count") < 45):
        content = "insufficient_text"
    elif status == "partial_capture":
        content = "partial_observation"
    elif record.get("content_sha256"):
        content = "text_observed_unverified"
    else:
        content = "not_established"

    if category == "pricing" and record.get("pricing_evidence_schema"):
        semantic = (
            "structured_candidate_unverified" if record.get("pricing_comparable_candidate_count")
            else "raw_price_evidence_unresolved" if record.get("pricing_observation_count")
            else "no_structured_rates"
        )
    elif category == "changelog" and record.get("release_events_schema"):
        semantic = (
            "release_identity_review" if record.get("release_event_identity_collision")
            else "release_dates_unresolved" if (not record.get("latest_release_date_candidate"))
            else "dated_events_unverified"
        )
    elif category == "documentation" and record.get("documentation_evidence_schema"):
        semantic = (
            "scoped_topics_unverified" if record.get("documentation_scope_status") == "scoped_page"
            else "overview_only" if record.get("documentation_scope_status") == "overview_only"
            else "scope_unresolved"
        )
    else:
        semantic = "not_established"

    incomplete = bool(
        status == "partial_capture"
        or any(record.get(flag) for flag in (
            "text_truncated", "sections_truncated", "tables_truncated",
            "release_event_evidence_lost", "release_recent_body_loss_count",
            "pricing_evidence_lost_to_item_budget", "documentation_item_budget_truncated",
            "documentation_topic_candidate_omitted",
        ))
        or (category == "pricing" and record.get("pricing_evidence_schema")
            and not record.get("pricing_inventory_complete"))
    )
    if incomplete:
        completeness = "partial"
    elif category == "documentation":
        completeness = "single_url_not_full_corpus"
    elif content == "text_observed_unverified":
        completeness = "bounded_page_observation"
    else:
        completeness = "not_established"

    if len(reasons) > LIMIT_REASONS:
        reasons = reasons[:LIMIT_REASONS - 1] + ["diagnostic_reason_limit_reached"]
    return {
        "diagnostic_schema": SCHEMA_VERSION,
        "quality_axes": {
            "fetch_status": fetch,
            "access_policy_status": policy,
            "source_identity_status": identity,
            "freshness_status": freshness,
            "content_capture_status": content,
            "semantic_evidence_status": semantic,
            "completeness_status": completeness,
            "alert_eligibility": "blocked_unverified",
        },
        "diagnostic_reason_codes": reasons,
        "diagnostic_concurrent_reason_count": len(reasons),
        "diagnostic_review_required": True,
    }
