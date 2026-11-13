"""P23B: single-source validation access is NOT authorized by source_ids.

All positive reviews below are IN-MEMORY synthetic policy fixtures. Tests call
Scrapy spider.start()/parse_page() directly; they perform ZERO publisher GETs.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse
from scrapy.settings import Settings
from scrapy.downloadermiddlewares.retry import RetryMiddleware

import agentfuse_crawlers.validation_access as access
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.spiders.official import (
    DocumentationSpider, PricingSpider, ChangelogSpider,
)

NOW = datetime.now(timezone.utc)
NOTE = (
    "SYNTHETIC TEST FIXTURE ONLY, NOT ACTUAL ACCESS PERMISSION. A real human "
    "must separately review the exact official URL, ownership, publisher "
    "terms, robots and private retention before attempting a request."
)
SPIDERS = (
    (DocumentationSpider, "openai_api_docs"),
    (PricingSpider, "openai_api_pricing"),
    (ChangelogSpider, "openai_api_changelog"),
)


def _timestamp(delta):
    return (NOW + delta).isoformat(timespec="seconds")


def _source(sid):
    return next(s for s in load_sources() if s["id"] == sid)


def _review(source, scopes=("single_validation",)):
    host = urlsplit(source["url"]).hostname
    return {
        "source_url": source["url"],
        "category": source["category"],
        "decision": "allowed_reviewed",
        "scopes": list(scopes),
        "reviewed_by": "Synthetic Test Reviewer",
        "reviewed_at_utc": _timestamp(timedelta(hours=-1)),
        "expires_at_utc": _timestamp(timedelta(days=5)),
        "ownership_evidence_url": source["url"],
        "publisher_access_policy_url": "https://" + host + "/terms",
        "robots_url": "https://" + host + "/robots.txt",
        "publisher_terms_reviewed": True,
        "robots_reviewed": True,
        "private_retention_reviewed": True,
        "evidence_note": NOTE,
    }


def _registry(source=None, scopes=("single_validation",)):
    return {
        "schema_version": access.SCHEMA,
        "kind": access.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": (
            {source["id"]: _review(source, scopes)} if source is not None else {}
        ),
    }


def _patch(monkeypatch, registry):
    access.validate_access_registry(registry, now=NOW)
    monkeypatch.setattr(access, "load_access_registry", lambda: registry)


async def _start(spider):
    return [x async for x in spider.start()]


@pytest.mark.parametrize("spider_type,source_id", SPIDERS)
def test_original_empty_registry_never_fetches_even_single_explicit_id(
        spider_type, source_id):
    spider = spider_type(cohort="all", source_ids=source_id)
    emitted = asyncio.run(_start(spider))
    assert len(emitted) == 1 and isinstance(emitted[0], dict)
    row = emitted[0]
    assert row["source_id"] == source_id
    assert row["status"] == "source_single_validation_not_approved"
    assert row["error"] == "single_source_policy_not_reviewed"
    assert row["http_status"] is None
    assert row["final_url"] == ""
    assert row["policy_observation"] == "not_fetched_by_single_source_access_gate"
    assert row["single_validation_access_required"] is True
    assert row["bulk_validation_required"] is False
    assert row["approved_for_advisor"] is False
    assert row["quality_axes"]["fetch_status"] == (
        "not_attempted_by_single_source_access_policy"
    )
    assert row["quality_axes"]["access_policy_status"] == (
        "single_validation_unapproved"
    )
    assert row["quality_axes"]["content_capture_status"] == "not_fetched"


@pytest.mark.parametrize("spider_type,source_id", SPIDERS)
def test_current_single_scope_review_allows_only_exact_initial_source(
        monkeypatch, spider_type, source_id):
    source = _source(source_id)
    _patch(monkeypatch, _registry(source))
    spider = spider_type(cohort="all", source_ids=source_id)
    emitted = asyncio.run(_start(spider))
    assert len(emitted) == 1 and isinstance(emitted[0], Request)
    req = emitted[0]
    assert req.url == source["url"]
    assert req.cb_kwargs["source"]["id"] == source_id
    assert req.meta["dont_redirect"] is True
    assert req.meta["dont_retry"] is True
    assert spider.single_validation_required is True
    assert spider.bulk_validation_required is False
    assert spider.bulk_plan_id == ""
    assert spider.bulk_authorized_ids == frozenset()


@pytest.mark.parametrize("case,reason", [
    ("bulk_scope_only", "single_source_review_scope_not_approved"),
    ("expired", "single_source_policy_review_expired"),
    ("denied", "single_source_policy_denied_or_deferred"),
    ("deferred", "single_source_policy_denied_or_deferred"),
])
def test_denied_expired_or_wrong_scope_review_yields_one_held_item(
        monkeypatch, case, reason):
    source = _source("openai_api_docs")
    review = _review(source)
    if case == "bulk_scope_only":
        review["scopes"] = ["bulk_validation"]
    elif case == "expired":
        review["reviewed_at_utc"] = _timestamp(timedelta(days=-10))
        review["expires_at_utc"] = _timestamp(timedelta(days=-1))
    else:
        review.update({
            "decision": "prohibited_reviewed" if case == "denied" else "deferred",
            "scopes": [],
            "publisher_terms_reviewed": False,
            "robots_reviewed": False,
            "private_retention_reviewed": False,
        })
    registry = _registry()
    registry["reviews"][source["id"]] = review
    _patch(monkeypatch, registry)
    outputs = asyncio.run(_start(DocumentationSpider(
        cohort="all", source_ids=source["id"],
    )))
    assert len(outputs) == 1 and isinstance(outputs[0], dict)
    assert outputs[0]["status"] == "source_single_validation_not_approved"
    assert outputs[0]["error"] == reason
    assert outputs[0]["approved_for_advisor"] is False
    assert outputs[0]["http_status"] is None


@pytest.mark.parametrize("tamper", [
    "source_url", "category", "robots_url", "ownership_evidence_url",
    "publisher_access_policy_url", "private_retention_reviewed",
    "reviewed_at_utc", "scopes",
])
def test_forged_registry_or_future_review_cannot_issue_a_request(
        monkeypatch, tamper):
    source = _source("openai_api_docs")
    registry = _registry(source)
    review = registry["reviews"][source["id"]]
    if tamper == "source_url":
        review[tamper] = "https://evil.invalid/moved"
    elif tamper == "category":
        review[tamper] = "pricing"
    elif tamper == "robots_url":
        review[tamper] = "https://evil.invalid/robots.txt"
    elif tamper == "ownership_evidence_url":
        review[tamper] = "https://evil.invalid/owner"
    elif tamper == "publisher_access_policy_url":
        review[tamper] = "http://example.invalid/terms"
    elif tamper == "private_retention_reviewed":
        review[tamper] = False
    elif tamper == "reviewed_at_utc":
        review[tamper] = _timestamp(timedelta(days=1))
    else:
        review[tamper] = ["single_validation", "single_validation"]
    monkeypatch.setattr(access, "load_access_registry", lambda: registry)
    with pytest.raises(ValueError):
        spider = DocumentationSpider(cohort="all", source_ids=source["id"])
        asyncio.run(_start(spider))


@pytest.mark.parametrize("source_id", [
    "v0_docs", "v0_pricing", "v0_changelog",
])
def test_synthetic_positive_review_cannot_override_quarantined_source(
        monkeypatch, source_id):
    source = _source(source_id)
    _patch(monkeypatch, _registry(source))
    spider_type = dict(
        documentation=DocumentationSpider,
        pricing=PricingSpider,
        changelog=ChangelogSpider,
    )[source["category"]]
    emitted = asyncio.run(_start(spider_type(
        cohort="all", source_ids=source_id,
    )))
    assert len(emitted) == 1
    assert isinstance(emitted[0], dict)
    assert emitted[0]["status"] == "source_quarantined"
    assert emitted[0]["http_status"] is None


@pytest.mark.parametrize("location", [
    "/new-path", "https://code.claude.com/elsewhere",
    "?token=secret",
])
def test_different_redirect_target_is_held_without_network_request(
        monkeypatch, location):
    source = _source("claude_code_changelog")
    _patch(monkeypatch, _registry(source))
    spider = ChangelogSpider(cohort="all", source_ids=source["id"])
    first = asyncio.run(_start(spider))
    assert len(first) == 1 and isinstance(first[0], Request)
    response = HtmlResponse(
        url=source["url"], request=first[0], status=302,
        headers={"Location": location, "Content-Type": "text/html"},
        body=b"<main>Moved</main>", encoding="utf-8",
    )
    results = list(spider.parse_page(response, source))
    assert len(results) == 1 and not isinstance(results[0], Request)
    assert results[0]["status"] == "redirect_needs_review"
    assert results[0]["error"] == "single_source_redirect_target_requires_review"
    assert results[0]["http_status"] == 302
    assert results[0]["approved_for_advisor"] is False


def test_review_expired_between_first_get_and_redirect_blocks_secondary_request(
        monkeypatch):
    source = _source("openai_api_docs")
    registry = _registry(source)
    _patch(monkeypatch, registry)
    spider = DocumentationSpider(cohort="all", source_ids=source["id"])
    primary = asyncio.run(_start(spider))[0]
    assert isinstance(primary, Request)
    # Simulate the policy review expiring before a redirect is followed.
    review = registry["reviews"][source["id"]]
    review["reviewed_at_utc"] = _timestamp(timedelta(days=-10))
    review["expires_at_utc"] = _timestamp(timedelta(days=-1))
    response = HtmlResponse(
        url=source["url"], request=primary, status=302,
        headers={"Location": source["url"], "Content-Type": "text/html"},
        body=b"<main>Moved</main>", encoding="utf-8",
    )
    emitted = list(spider.parse_page(response, source))
    assert len(emitted) == 1 and isinstance(emitted[0], dict)
    assert emitted[0]["status"] == "redirect_needs_review"
    assert emitted[0]["error"] == "single_source_policy_review_expired"
    assert emitted[0]["http_status"] == 302


def test_unreviewed_markdown_alternate_is_not_scheduled_for_reviewed_single(
        monkeypatch):
    source = _source("claude_code_changelog")
    _patch(monkeypatch, _registry(source))
    spider = ChangelogSpider(cohort="all", source_ids=source["id"])
    primary = asyncio.run(_start(spider))[0]
    assert isinstance(primary, Request)
    # Static, undated HTML triggers the legacy Markdown fallback condition.
    # The permitted initial HTML URL never grants the .md URL.
    response = HtmlResponse(
        url=source["url"], request=primary, status=200,
        headers={"Content-Type": "text/html"},
        body=b"<html><main><h1>Changes</h1><p>Undated news.</p></main></html>",
        encoding="utf-8",
    )
    emitted = list(spider.parse_page(response, source))
    assert len(emitted) == 1 and isinstance(emitted[0], dict)
    assert emitted[0]["source_id"] == source["id"]
    assert emitted[0]["approved_for_advisor"] is False
    assert not emitted[0].get("markdown_alternate_attempted")


def test_monitor_remains_separate_and_cannot_use_single_source_review(
        monkeypatch):
    source = _source("openai_api_docs")
    _patch(monkeypatch, _registry(source))
    spider = DocumentationSpider(
        source_ids=source["id"], collection_mode="monitor",
    )
    emitted = asyncio.run(_start(spider))
    assert spider.single_validation_required is False
    assert len(emitted) == 1 and isinstance(emitted[0], dict)
    assert emitted[0]["status"] == "source_not_validated_for_monitor"
    assert emitted[0]["approved_for_advisor"] is False


def test_bulk_still_requires_independent_run_plan_not_single_review(
        monkeypatch):
    source = _source("openai_api_docs")
    _patch(monkeypatch, _registry(source))
    spider = DocumentationSpider(cohort="proven")
    rows = asyncio.run(_start(spider))
    assert len(rows) == 3 and all(isinstance(row, dict) for row in rows)
    assert all(row["status"] == "source_bulk_validation_not_approved"
               for row in rows)


def test_denied_single_access_is_separately_counted_in_scrapy_coverage():
    from types import SimpleNamespace
    from agentfuse_crawlers.extensions.coverage import SourceCoverageAudit

    class Stats:
        def __init__(self):
            self.values = {}

        def set_value(self, key, value):
            self.values[key] = value

    spider = DocumentationSpider(cohort="all", source_ids="openai_api_docs")
    row = asyncio.run(_start(spider))[0]
    stats = Stats()
    audit = SourceCoverageAudit(SimpleNamespace(stats=stats))
    audit.item_scraped(row, None, spider)
    audit.summary(spider)
    assert stats.values["agentfuse/coverage/single_access_held_sources"] == 1
    assert stats.values["agentfuse/coverage/bulk_access_held_sources"] == 0
    assert stats.values["agentfuse/coverage/reported_sources"] == 1
    assert stats.values["agentfuse/coverage/missing_sources"] == 0
    assert stats.values["agentfuse/coverage/captured_sources"] == 0
    assert stats.values["agentfuse/run/quality_outcome"] == "no_usable_sources"


def test_single_source_validation_server_error_is_not_automatically_retried(
        monkeypatch):
    """Synthetic-only 503; Scrapy RetryMiddleware must not duplicate a GET."""
    source = _source("openai_api_docs")
    _patch(monkeypatch, _registry(source))
    spider = DocumentationSpider(cohort="all", source_ids=source["id"])
    request = asyncio.run(_start(spider))[0]
    assert isinstance(request, Request)
    assert request.meta["dont_retry"] is True

    response = HtmlResponse(
        url=source["url"], request=request, status=503,
        headers={"Content-Type": "text/html"},
        body=b"<html><body>Temporary upstream failure</body></html>",
        encoding="utf-8",
    )
    retry = RetryMiddleware(Settings({
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 1,
        "RETRY_HTTP_CODES": [500, 502, 503, 504],
        "RETRY_PRIORITY_ADJUST": -1,
    }))
    assert retry.process_response(request, response, spider) is response
    emitted = list(spider.parse_page(response, source))
    assert len(emitted) == 1 and isinstance(emitted[0], dict)
    assert emitted[0]["status"] == "http_error"
    assert emitted[0]["error"] == "HTTP 503"
    assert emitted[0]["approved_for_advisor"] is False


def test_synthetic_monitor_request_does_not_inherit_validation_retry_guard(
        monkeypatch):
    """Monitor lifecycle policy stays separate; no network is performed."""
    import agentfuse_crawlers.spiders.official as official
    monkeypatch.setattr(
        official, "collection_decision",
        lambda _source, _mode: (True, "SYNTHETIC_MONITOR_TEST_ONLY"),
    )
    spider = DocumentationSpider(
        cohort="all", source_ids="openai_api_docs", collection_mode="monitor",
    )
    emitted = asyncio.run(_start(spider))
    assert len(emitted) == 1 and isinstance(emitted[0], Request)
    assert emitted[0].meta["dont_retry"] is False
