"""Regression: Scrapy 2.18+ async start must queue each configured URL."""

import asyncio

import pytest
import scrapy

from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.spiders.official import (
    ChangelogSpider, DocumentationSpider, PricingSpider
)


@pytest.mark.parametrize(
    ("spider_cls", "category"),
    [
        (ChangelogSpider, "changelog"),
        (DocumentationSpider, "documentation"),
        (PricingSpider, "pricing"),
    ],
)
def test_all_manifest_sources_generate_requests(spider_cls, category):
    spider = spider_cls()

    async def collect_requests():
        return [request async for request in spider.start()]

    requests = asyncio.run(collect_requests())
    expected = [s for s in load_sources() if s["category"] == category]
    assert len(requests) == len(expected)
    assert {r.url for r in requests} == {s["url"] for s in expected}
    assert all(isinstance(r, scrapy.Request) for r in requests)
    assert all(r.url.startswith("https://") for r in requests)
    assert all(r.cb_kwargs["source"]["category"] == category for r in requests)
    assert all(r.callback == spider.parse_page for r in requests)
    assert all(r.errback == spider.record_failure for r in requests)
