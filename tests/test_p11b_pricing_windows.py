"""P11B: full recognized-table accounting using small, human-run table windows.

All inputs are original synthetic markup and fake job identities, NOT source
truth labels. Do not treat a complete table union as global vendor coverage.
"""
import copy
import hashlib
from datetime import datetime, timezone

import pytest
from scrapy.http import HtmlResponse

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.pricing_evidence import MAX_SELECTED_TABLES
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.spiders.official import ChangelogSpider, PricingSpider
from scripts.assemble_pricing_windows import assemble_items, assemble_source_windows
from scripts.compare_exports import _compatible_source, _healthy
from scripts.evaluate_run import _source_identity

SRC = next(x for x in load_sources() if x["id"] == "openai_api_pricing")


def html_tables(num):
    return (
        "<html><body><main>"
        "<p>All prices are in USD.</p>"
        + "".join(
            f"<h2>Region: Global</h2><h3>Tier: Standard</h3>"
            f"<table><caption>USD per 1M tokens</caption>"
            f"<tr><th>Model</th><th>Input price</th></tr>"
            f"<tr><th>Model Synthetic-{i}</th><td>USD 0.50</td></tr>"
            f"</table>"
            for i in range(num)
        )
        + "</main></body></html>"
    )


def extract(num, offset, limit=16):
    page = html_tables(num)
    return extract_evidence(
        page, SRC["url"], category="pricing", source_id=SRC["id"],
        pricing_table_window={"table_offset": offset, "table_limit": limit},
    )


def row(num, offset, limit, job_num):
    ev = extract(num, offset, limit)
    return {
        **ev,
        "source_id": SRC["id"], "source_url": SRC["url"],
        "provider": SRC["provider"], "category": "pricing",
        "zyte_job_id": f"883514/3/{job_num}",
        "manifest_sha256": "a" * 64,
        "source_registry_sha256": "b" * 64,
        "deployment_revision": "c" * 64,
        "http_status": 200,
        "status": "captured" if ev["pricing_inventory_complete"]
        else "partial_capture",
        "review_status": "unverified",
        "approved_for_advisor": False,
    }


def test_default_pricing_window_preserves_legacy_64_table_cap_and_partial_status():
    ev = extract(89, 0, MAX_SELECTED_TABLES)
    assert ev["pricing_table_relevant"] == 89
    assert ev["pricing_table_selected"] == 64
    assert ev["pricing_table_omitted_relevant"] == 25
    assert ev["pricing_table_window_start"] == 0
    assert ev["pricing_table_window_end"] == 64
    assert len(ev["pricing_table_window_selected_indices"]) == 64
    assert ev["pricing_table_window_cards_included"] is True
    assert ev["pricing_inventory_complete"] is False


def test_giant_sources_can_be_accounted_in_six_nonoverlapping_review_windows():
    windows = [row(89, offset, 16, 100 + offset) for offset in range(0, 89, 16)]
    assert len(windows) == 6
    assert all(not w["pricing_inventory_complete"] for w in windows)
    merged = assemble_source_windows(windows)
    assert merged["recognized_relevant_tables"] == 89
    assert merged["covered_recognized_relevant_tables"] == 89
    assert merged["price_observation_count"] == 89
    assert merged["separate_job_count"] == 6
    assert merged["approved_for_advisor"] is False
    assert merged["publisher_catalog_completeness_verified"] is False
    assert merged["rate_comparison_eligible"] is False
    assert len({o["observation_id"] for o in merged["price_observations"]}) == 89


def test_missing_middle_window_is_not_silently_marked_complete():
    windows = [row(40, offset, 16, 100 + offset) for offset in (0, 32)]
    with pytest.raises(ValueError, match="Missing, overlapping"):
        assemble_source_windows(windows)


def test_overlap_and_duplicate_job_ids_are_blocked():
    windows = [row(35, offset, 16, 100 + offset) for offset in (0, 16, 32)]
    conflict = copy.deepcopy(windows)
    conflict[1]["pricing_table_window_start"] = 8
    conflict[1]["pricing_table_window_end"] = 24
    with pytest.raises(ValueError, match="Missing, overlapping"):
        assemble_source_windows(conflict)
    repeat_job = copy.deepcopy(windows)
    repeat_job[1]["zyte_job_id"] = repeat_job[0]["zyte_job_id"]
    with pytest.raises(ValueError, match="independent Zyte job IDs"):
        assemble_source_windows(repeat_job)


def test_page_edit_between_windows_is_not_merged():
    a, b = row(20, 0, 16, 100), row(20, 16, 16, 116)
    b["content_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="changed between windows"):
        assemble_source_windows([a, b])


def test_truncated_window_and_observation_cap_are_never_hidden():
    a, b = row(30, 0, 16, 100), row(30, 16, 16, 116)
    b["pricing_observation_limit_reached"] = True
    with pytest.raises(ValueError, match="omitted, clipped"):
        assemble_source_windows([a, b])
    b = row(30, 16, 16, 116)
    b["pricing_observation_total_detected"] = 99
    with pytest.raises(ValueError, match="observation count"):
        assemble_source_windows([a, b])


def test_one_window_does_not_claim_full_source_when_later_tables_exist():
    w = row(33, 0, 16, 101)
    assert w["pricing_inventory_complete"] is False
    assert _healthy(w) is False
    with pytest.raises(ValueError, match="Not all"):
        assemble_source_windows([w])


def test_cards_only_in_first_window_and_no_duplicate_card_rates():
    markup = (
        "<html><body><main>"
        "<section class='pricing-card'><h3>Model Synthetic Card</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<p>Input price: USD 1.00 / MTok</p></section>"
        + "".join(
            f"<table><caption>USD per 1M tokens</caption>"
            f"<tr><th>Model</th><th>Input price</th></tr>"
            f"<tr><td>Model T{i}</td><td>USD 0.40</td></tr></table>"
            for i in range(18)
        ) + "</main></body></html>"
    )
    first = extract_evidence(
        markup, SRC["url"], category="pricing", source_id=SRC["id"],
        pricing_table_window={"table_offset": 0, "table_limit": 16},
    )
    other = extract_evidence(
        markup, SRC["url"], category="pricing", source_id=SRC["id"],
        pricing_table_window={"table_offset": 16, "table_limit": 16},
    )
    assert first["pricing_card_observation_count"] == 1
    assert other["pricing_card_observation_count"] == 0
    assert first["pricing_table_window_cards_included"]
    assert not other["pricing_table_window_cards_included"]


def test_price_window_is_part_of_diff_compatibility_identity():
    a = row(30, 0, 16, 101)
    b = row(30, 16, 16, 102)
    assert _compatible_source(a, a)
    assert not _compatible_source(a, b)
    assert _source_identity(a) != _source_identity(b)


@pytest.mark.parametrize("args", [
    {"pricing_table_offset": "-1"},
    {"pricing_table_limit": "0"},
    {"pricing_table_limit": "65"},
    {"pricing_table_offset": "701"},
    {"pricing_table_offset": "1.5"},
    {"pricing_table_limit": "16oops"},
    {"pricing_table_offset": "1", "pricing_table_limit": "-5"},
])
def test_spider_rejects_bad_or_unbounded_pricing_window_args(args):
    with pytest.raises(ValueError, match="pricing table"):
        PricingSpider(source_ids=SRC["id"], **args)


def test_spider_schedules_only_one_original_source_for_window():
    spider = PricingSpider(
        cohort="all", source_ids=SRC["id"],
        pricing_table_offset="16", pricing_table_limit="16",
    )
    assert len(spider.selected) == 1
    assert spider.pricing_table_offset == 16
    assert spider.pricing_table_limit == 16
    assert spider.run_context["requested_cohort"] == "all"


def test_one_source_summary_per_window_and_same_original_url():
    spider = PricingSpider(
        cohort="all", source_ids=SRC["id"],
        pricing_table_offset="16", pricing_table_limit="16",
    )
    page = html_tables(40)
    response = HtmlResponse(
        url=SRC["url"], body=page.encode(), encoding="utf-8",
        headers={"Content-Type": "text/html"}, status=200,
    )
    results = list(spider.parse_page(response, SRC))
    assert len(results) == 1
    x = results[0]
    assert x["source_id"] == SRC["id"]
    assert x["pricing_table_window_start"] == 16
    assert x["pricing_table_window_end"] == 32
    assert x["pricing_inventory_complete"] is False
    assert x["status"] == "partial_capture"
    assert x["approved_for_advisor"] is False


def test_assembled_record_never_usable_as_new_source_item_or_price_alert():
    windows = [row(32, offset, 16, 100 + offset) for offset in (0, 16)]
    merged = assemble_items(windows)[0]
    assert merged["kind"] == "offline_pricing_table_window_union_unverified"
    assert merged["approved_for_advisor"] is False
    assert merged["rate_comparison_eligible"] is False
    assert "status" not in merged
    assert "pricing_inventory_complete" not in merged
