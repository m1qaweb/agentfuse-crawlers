"""Scrapy 2.18+ async start must schedule only approved manifest URLs."""

import asyncio

import pytest
import scrapy

from agentfuse_crawlers.sources import select_sources
from agentfuse_crawlers.source_lifecycle import collection_decision
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
    for output, source in zip(requests, expected):
        permitted, reason = collection_decision(source, "validation")
        # P21B: technically selectable is NOT permission to fetch multiple
        # publisher URLs. Both Git-reviewed registries are empty today.
        assert isinstance(output, dict)
        assert output["source_id"] == source["id"]
        assert output["http_status"] is None
        assert output["approved_for_advisor"] is False
        assert output["validation_scope"] == "bulk_reviewed_plan_required"
        if not permitted:
            assert output["status"] == "source_quarantined"
            assert output["error"] == reason
        else:
            assert output["status"] == "source_bulk_validation_not_approved"
            assert output["error"] == "bulk_run_plan_not_present"
            assert output["policy_observation"] == (
                "not_fetched_by_bulk_source_access_gate"
            )


def test_limit_one_requires_bulk_review_but_exact_single_id_remains_available():
    async def collect(spider):
        return [request async for request in spider.start()]
    # Using limit is not a safe substitute for selecting ONE exact URL.
    limited = PricingSpider(source_ids="openai_api_pricing", limit="1")
    blocked = asyncio.run(collect(limited))
    assert len(blocked) == 1 and not isinstance(blocked[0], scrapy.Request)
    assert blocked[0]["status"] == "source_bulk_validation_not_approved"
    explicit = PricingSpider(source_ids="openai_api_pricing")
    request = asyncio.run(collect(explicit))
    assert len(request) == 1 and isinstance(request[0], scrapy.Request)
    assert request[0].cb_kwargs["source"]["id"] == "openai_api_pricing"



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

    outputs = asyncio.run(collect())
    expected = select_sources(category, cohort="candidate", offset=15, limit=15)
    assert [row["source_id"] for row in outputs] == [
        source["id"] for source in expected
    ]
    assert all(not isinstance(row, scrapy.Request) for row in outputs)
    assert all(row["status"] == "source_bulk_validation_not_approved"
               for row in outputs)
    assert all(row["http_status"] is None for row in outputs)
    assert spider.offset == 15
    assert len(outputs) == 15



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
