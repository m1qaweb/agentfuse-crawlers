"""Fail-closed crawl quality checks. A captured page is *not* a verified claim."""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

PRICE_NUMBER = re.compile(
    r"(?:[$€£¥]\s*\d+(?:[.,]\d+)?|\b(?:USD|EUR|GBP|JPY)\s*\d+"
    r"|\b\d+(?:[.,]\d+)?\s*(?:USD|EUR|GBP)\b)", re.I
)
BILLING_WORDS = re.compile(
    r"\b(?:per million|per 1m|pricing|billing|subscription|"
    r"free tier|free plan|credits|pay.as.you.go)\b", re.I
)
BLOCK_MARKERS = (
    "verify you are human", "checking your browser before accessing",
    "enable javascript and cookies", "captcha challenge",
    "just a moment... cloudflare", "cloudflare challenge",
    "sign in to continue", "log in to continue",
    "403 forbidden", "access denied",
)
JS_SHELL_MARKERS = (
    "enable javascript to view this", "this app requires javascript",
    "you need to enable javascript to run this app",
    "javascript is required to view this page",
)
HARD_TEXT_LIMIT = 250_000


def http_date_candidate(value):
    """RFC 7231 HTTP Date; a server claim, never an independent freshness proof."""
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return ""
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return ""


def response_freshness(headers, now=None):
    """Parse untrusted cache metadata for an operator, without inventing a publish date."""
    def read(name):
        raw = headers.get(name.encode("ascii"), b"")
        return raw.decode("latin-1", errors="replace").strip()[:250]

    age_raw = read("Age")
    age_seconds = int(age_raw) if age_raw.isdigit() and len(age_raw) < 11 else None
    now = now or datetime.now(timezone.utc)
    server_date = http_date_candidate(read("Date"))
    warnings = []
    if age_seconds is not None and age_seconds > 86_400:
        warnings.append("reported_cache_age_over_one_day")
    if server_date:
        when = datetime.fromisoformat(server_date)
        if (when - now).total_seconds() > 300:
            warnings.append("server_date_in_future")
    return {
        "origin_response_date": server_date,
        "reported_cache_age_seconds": age_seconds,
        "cache_control": read("Cache-Control"),
        "freshness_warnings": warnings,
        "network_fetch_requested": True,
        "latest_publication_verified": False,
    }


def assess_capture(category, evidence, text, *, cache_warnings=(), cached=False):
    """Return (capture_status, stable reason code).

    Complete enough to compare != true or latest. Fail closed on obvious shells,
    historical truncation, site indexes without substantive content and stale CDN.
    """
    lowered = (evidence.get("title", "") + " " + text[:6000]).lower()
    if any(marker in lowered for marker in BLOCK_MARKERS):
        return "blocked", "access_or_login_challenge"
    if any(marker in lowered for marker in JS_SHELL_MARKERS):
        return "needs_review", "javascript_only_shell"
    if cached:
        return "needs_review", "scrapy_cache_response_not_fresh"
    if "reported_cache_age_over_one_day" in cache_warnings:
        return "needs_review", "server_cached_response_over_one_day"
    if "server_date_in_future" in cache_warnings:
        return "needs_review", "invalid_future_server_date"
    if evidence.get("word_count", 0) < 45:
        return "needs_review", "insufficient_substantive_text"
    if len(text) > HARD_TEXT_LIMIT:
        return "partial_capture", "text_exceeds_capture_limit"
    if category == "pricing" and evidence.get("tables_truncated"):
        return "partial_capture", "pricing_tables_truncated"
    if category == "changelog" and evidence.get("sections_truncated"):
        return "partial_capture", "changelog_sections_truncated"
    if category == "documentation" and evidence.get("sections_truncated"):
        return "partial_capture", "documentation_sections_truncated"

    if category == "changelog":
        if evidence.get("release_events_schema") == "1.0":
            if evidence.get("release_events_truncated"):
                return "partial_capture", "release_event_limit_reached"
            if evidence.get("release_event_identity_collision"):
                return "needs_review", "release_event_identity_collision"
            if not evidence.get("release_event_count"):
                return "needs_review", "no_release_events_detected"
            if not evidence.get("release_dated_event_count"):
                return "needs_review", "release_events_missing_publication_dates"
            # A dated old release is not proof that a newer undated release
            # was not skipped. Refuse to label this a comparable timeline.
            if not evidence.get("latest_release_date_candidate"):
                return "needs_review", "latest_release_date_ambiguous"
        elif not evidence.get("visible_latest_date_candidate"):
            # Legacy parser/test contract retained for backwards compatibility.
            return "needs_review", "no_dated_release_section_detected"
    elif category == "pricing":
        if not PRICE_NUMBER.search(text) and not (
            BILLING_WORDS.search(text) and
            evidence.get("tables", []) and
            evidence.get("prose_paragraphs", 0) > 0
        ):
            return "needs_review", "no_price_or_billing_detail_detected"
    elif category == "documentation":
        if (evidence.get("main_link_text_ratio", 0) > 0.85 and
                evidence.get("prose_paragraphs", 0) < 2):
            return "needs_review", "documentation_link_index_only"
    return "captured", ""
