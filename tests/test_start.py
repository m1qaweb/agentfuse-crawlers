"""Scrapy 2.18+ async start must schedule only approved manifest URLs."""

import asyncio

import pytest
import scrapy

from agentfuse_crawlers.sources import select_sources
from agentfuse_crawlers.spiders.official import ChangelogSpider, DocumentationSpider, PricingSpider


@pytest.mark.parametrize(('klass', 'category'), [
    (ChangelogSpider, 'changelog'),
    (DocumentationSpider, 'documentation'),
    (PricingSpider, 'pricing'),
])
@pytest.mark.parametrize('cohort', ['all', 'proven'])
def test_spider_starts_with_allowlisted_sources(klass, category, cohort):
    spider = klass(cohort=cohort)

    async def collect():
        return [request async for request in spider.start()]

    requests = asyncio.run(collect())
    expected = select_sources(category, cohort=cohort)
    assert len(requests) == len(expected)
    assert {r.url for r in requests} == {s['url'] for s in expected}
    assert all(isinstance(r, scrapy.Request) for r in requests)
    assert all(r.callback == spider.parse_page and r.errback == spider.record_failure for r in requests)


def test_limit_one_and_explicit_id():
    spider = PricingSpider(source_ids='openai_api_pricing', limit='1')
    async def collect():
        return [request async for request in spider.start()]
    assert [r.cb_kwargs['source']['id'] for r in asyncio.run(collect())] == ['openai_api_pricing']
