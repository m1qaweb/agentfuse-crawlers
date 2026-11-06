"""Official fresh-fetch contract and bounded same-host redirects."""

import asyncio

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse

from agentfuse_crawlers.spiders.official import (
    ChangelogSpider, DocumentationSpider, PricingSpider, _allowed_redirect
)
from agentfuse_crawlers.sources import load_sources


def response(source, code=200, location=None, html="<main>Release notes</main>", url=None, meta=None):
    headers = {"Content-Type": "text/html"}
    if location is not None:
        headers["Location"] = location
    request = Request(url or source["url"], meta=meta or {})
    return HtmlResponse(
        url=url or source["url"], status=code,
        headers=headers, body=html.encode(), encoding="utf-8", request=request,
    )


def test_only_three_spiders_are_used():
    assert [s.name for s in (DocumentationSpider, PricingSpider, ChangelogSpider)] == [
        "official_documentation", "official_pricing", "official_changelogs"
    ]


def test_unreviewed_single_source_is_held_on_every_run():
    spider = ChangelogSpider(source_ids="openai_api_changelog")

    async def run():
        return [r async for r in spider.start()]

    run1, run2 = asyncio.run(run()), asyncio.run(run())
    assert len(run1) == len(run2) == 1
    assert all(not isinstance(x[0], Request) for x in (run1, run2))
    assert run1[0]["source_id"] == run2[0]["source_id"] == "openai_api_changelog"
    assert run1[0]["status"] == run2[0]["status"] == (
        "source_single_validation_not_approved"
    )
    assert run1[0]["http_status"] is run2[0]["http_status"] is None


def test_cross_host_https_or_http_redirect_is_rejected_without_new_request():
    source = load_sources()[0]
    spider = DocumentationSpider(source_ids=source["id"])
    for dest in (
        "https://platform.claude.com/docs/overview",
        "http://developers.openai.com/docs",
        "https://evil.invalid/phishing",
    ):
        result = list(spider.parse_page(response(source, 302, dest), source))
        assert len(result) == 1 and isinstance(result[0], dict)
        assert result[0]["status"] == "rejected_redirect"


def test_legacy_monitor_mode_redirect_path_movement_requires_review():
    source = load_sources()[0]
    # Test parser-only handling, not permission for a monitoring GET.
    # Single validation instead holds a different target URL (P23B).
    spider = DocumentationSpider(source_ids=source["id"], collection_mode="monitor")
    first = list(spider.parse_page(response(source, 301, "/api/docs-new"), source))
    assert len(first) == 1 and isinstance(first[0], Request)
    assert first[0].meta["source_redirect_depth"] == 1
    body = "<main><h1>New documentation</h1><p>" + (
        "This guide explains the current Responses API and compatibility. " * 30
    ) + "</p></main>"
    moved = list(spider.parse_page(response(
        source, 200, html=body, url=first[0].url, meta=first[0].meta
    ), source))
    assert len(moved) == 1
    assert moved[0]["status"] == "needs_review"
    assert moved[0]["error"] == "source_path_redirected"


def test_legacy_monitor_mode_slash_redirect_preserves_capture_semantics():
    source = load_sources()[0]
    # Parser-only legacy monitor behavior; not a publisher access approval.
    spider = DocumentationSpider(source_ids=source["id"], collection_mode="monitor")
    first = list(spider.parse_page(response(source, 301, source["url"] + "/"), source))
    assert isinstance(first[0], Request)
    # Same-path redirects remain eligible when the fetched page also
    # substantiates the curated source's product identity.
    body = "<main><h1>" + source["provider"] + " Official Docs</h1><p>" + (
        "Current model and feature documentation with implementation details. " * 30
    ) + "</p></main>"
    final = list(spider.parse_page(response(
        source, 200, html=body, url=first[0].url, meta=first[0].meta
    ), source))[0]
    assert final["status"] == "captured"
    assert final["approved_for_advisor"] is False
    assert final["latest_publication_verified"] is False


def test_redirect_with_invalid_port_is_rejected_not_crash():
    source = load_sources()[0]
    assert not _allowed_redirect("https://developers.openai.com:bad/path", source)


def test_incomplete_releases_are_not_silently_captured():
    source = next(s for s in load_sources() if s["id"] == "openai_api_changelog")
    spider = ChangelogSpider(source_ids=source["id"])
    shell = "<main><h1>Recent updates</h1><p>" + (
        "Some announcements about our products and APIs. " * 35
    ) + "</p></main>"
    item = list(spider.parse_page(response(source, html=shell), source))[0]
    assert item["status"] == "needs_review"
    assert item["error"] == "no_release_events_detected"
