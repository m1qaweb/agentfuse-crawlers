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


def test_request_starts_from_exact_manifest_url_even_on_repeated_runs():
    spider = ChangelogSpider(source_ids="openai_api_changelog")

    async def run():
        return [r async for r in spider.start()]

    run1, run2 = asyncio.run(run()), asyncio.run(run())
    assert len(run1) == len(run2) == 1
    assert run1[0].url == run2[0].url
    assert run1[0].dont_filter and run2[0].dont_filter
    assert run1[0].meta["dont_redirect"] is True


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


def test_same_host_redirect_is_followed_and_path_movement_reviewed():
    source = load_sources()[0]
    spider = DocumentationSpider(source_ids=source["id"])
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


def test_same_path_slash_redirect_remains_eligible_for_capture():
    source = load_sources()[0]
    spider = DocumentationSpider(source_ids=source["id"])
    first = list(spider.parse_page(response(source, 301, source["url"] + "/"), source))
    assert isinstance(first[0], Request)
    body = "<main><h1>Official Docs</h1><p>" + (
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
