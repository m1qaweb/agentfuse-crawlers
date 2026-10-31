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
    spider = klass(
        cohort=cohort,
        confirm_full_inventory="yes" if cohort == "all" else None,
    )

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



def test_fresh_capture_settings_preserve_robots_txt_redirect_handling():
    from scrapy.utils.project import get_project_settings
    settings = get_project_settings()
    assert settings.getbool("ROBOTSTXT_OBEY")
    assert not settings.getbool("HTTPCACHE_ENABLED")
    assert settings.getbool("REDIRECT_ENABLED")
    assert not settings.getbool("METAREFRESH_ENABLED")
    assert settings.get("DEFAULT_REQUEST_HEADERS")["Cache-Control"] == "no-cache"



@pytest.mark.parametrize(("klass", "category"), [
    (ChangelogSpider, "changelog"),
    (DocumentationSpider, "documentation"),
    (PricingSpider, "pricing"),
])
def test_later_candidate_batch_schedules_exact_urls(klass, category):
    spider = klass(cohort="candidate", offset="15", limit="15")

    async def collect():
        return [r async for r in spider.start()]

    requests = asyncio.run(collect())
    expected = select_sources(category, cohort="candidate", offset=15, limit=15)
    assert [r.url for r in requests] == [s["url"] for s in expected]
    assert spider.offset == 15
    assert len(requests) == 15



@pytest.mark.parametrize(("klass", "category"), [
    (ChangelogSpider, "changelog"),
    (DocumentationSpider, "documentation"),
    (PricingSpider, "pricing"),
])
def test_implicit_run_is_only_three_historical_proven_urls(klass, category):
    spider = klass()
    assert spider.cohort == "proven"
    assert len(spider.selected) == 3
    assert spider.run_context["requested_cohort"] == "proven"
    assert spider.run_context["run_scope_explicit"] is False
    assert spider.run_context["selection_source_count"] == 3


@pytest.mark.parametrize("klass", [ChangelogSpider, DocumentationSpider, PricingSpider])
def test_full_inventory_requires_explicit_confirmation(klass):
    with pytest.raises(ValueError, match="confirm_full_inventory=yes"):
        klass(cohort="all")
    with pytest.raises(ValueError, match="confirm_full_inventory=yes"):
        klass(cohort="all", limit="10")
    with pytest.raises(ValueError, match="confirm_full_inventory"):
        klass(cohort="all", confirm_full_inventory="true")


def test_explicit_source_ids_remain_bounded_without_full_run_confirmation():
    spider = ChangelogSpider(cohort="all", source_ids="cursor_changelog")
    assert [s["id"] for s in spider.selected] == ["cursor_changelog"]
    assert spider.run_context["requested_cohort"] == "all"
    assert spider.run_context["run_scope_explicit"] is True
