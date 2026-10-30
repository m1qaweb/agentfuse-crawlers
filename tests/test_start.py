"""Prevent empty Scrapy 2.18 runs caused by removed start_requests hook."""

import asyncio

import scrapy
import pytest

from agentfuse_crawlers.spiders.official import (
    ChangelogSpider,
    DocumentationSpider,
    PricingSpider,
)


@pytest.mark.parametrize(
    ("spider_cls", "category"),
    [
        (ChangelogSpider, "changelog"),
        (DocumentationSpider, "documentation"),
        (PricingSpider, "pricing"),
    ],
)
def test_each_spider_schedules_three_provider_requests(spider_cls, category):
    spider = spider_cls()

    async def collect_start_requests():
        return [request async for request in spider.start()]

    requests = asyncio.run(collect_start_requests())

    assert len(requests) == 3
    assert all(isinstance(req, scrapy.Request) for req in requests)
    assert all(req.url.startswith("https://") for req in requests)
    assert {req.cb_kwargs["source"]["provider"] for req in requests} == {
        "OpenAI", "Anthropic", "Google Gemini"
    }
    assert all(req.cb_kwargs["source"]["category"] == category for req in requests)
    assert all(req.callback == spider.parse_page for req in requests)
    assert all(req.errback == spider.record_failure for req in requests)
