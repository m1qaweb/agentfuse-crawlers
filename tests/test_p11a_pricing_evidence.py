"""P11A: conservative quote extraction from audited November 1 problem shapes.

Synthetic markup only. NO live publisher price is verified or approved here.
Unknown region/currency/tier never becomes a safe rate-change comparison.
"""
import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.rate_units import analyze_cell, detect_unit
from agentfuse_crawlers.quality import assess_capture

URL = "https://developers.openai.com/api/docs/pricing"


def ev(body, source="openai_api_pricing"):
    return extract_evidence(
        "<html><head><title>Sample pricing</title></head>"
        "<body><main>" + body + "</main></body></html>",
        URL, category="pricing", source_id=source,
    )


def table(amount="USD 12.50 / MTok", caption=""):
    c = f"<caption>{caption}</caption>" if caption else ""
    return ("<table>" + c + "<thead><tr><th>Model</th>"
            "<th>Input price</th></tr></thead><tbody><tr>"
            f"<th>Model A</th><td>{amount}</td></tr></tbody></table>")


def test_anthropic_like_explicit_usd_retains_review_quote_not_comparable_rate():
    page = ev("<p>All prices are in USD.</p>" + table("$12.50 / MTok"))
    x = page["pricing_observations"][0]
    assert x["currency"] == "USD" and x["billing_unit"] == "per_1m_tokens"
    assert x["price_dimension"] == "input" and x["model_or_service"] == "Model A"
    assert x["observed_single_amount_decimal"] == "12.50"
    assert x["review_quote_amount_decimal"] == "12.50"
    assert x["review_quote_candidate"] is True
    assert x["region_applicability"] == "unspecified"
    assert x["tier_applicability"] == "unspecified"
    assert x["normalized_amount_decimal"] is None
    assert x["comparable_candidate"] is False
    assert page["pricing_review_quote_candidate_count"] == 1
    assert page["pricing_unscoped_review_quote_count"] == 1
    assert page["pricing_parser_revision"] == "evidence_quote_v3_windows"
    assert page["approved_for_advisor"] is False


def test_openai_like_dollar_sign_never_becomes_usd_or_review_quote():
    page = ev("<p>Prices per 1M tokens.</p>" + table("$2.00"))
    x = page["pricing_observations"][0]
    assert x["observed_single_amount_decimal"] == "2.00"
    assert x["currency"] is None
    assert x["currency_attribution"] == "unqualified_symbol"
    assert x["review_quote_candidate"] is False
    assert x["review_quote_amount_decimal"] is None
    assert x["comparable_candidate"] is False


def test_next_table_local_currency_is_not_global_or_inferred():
    page = ev(
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<p>Prices per 1M tokens.</p><p>Prices in USD.</p>"
        + table("$1.00")
        + table("$2.00")
    )
    first, second = page["pricing_observations"]
    assert first["currency"] == "USD" and first["comparable_candidate"]
    assert second["currency"] is None
    assert not second["comparable_candidate"]


def test_explicit_cross_region_and_cross_plan_equality_is_scoped_not_guessed():
    page = ev(
        "<p>Prices in USD.</p>"
        "<p>Rates are the same across all regions.</p>"
        "<p>Rates are the same across all plans.</p>"
        "<p>Prices per 1M tokens.</p>"
        + table("$3.00")
    )
    x = page["pricing_observations"][0]
    assert x["region"] == "Global"
    assert x["tier_or_plan"] == "All Plans"
    assert x["normalized_amount_decimal"] == "3.00"
    assert x["comparable_candidate"] is True
    assert x["approved_for_advisor"] is False
    assert {d["dimension"] for d in x["scope_declarations"]} == {
        "currency", "region", "tier_or_plan", "billing_unit",
    }


def test_conflicting_region_or_plan_blocks_unverified_quote():
    page = ev(
        "<p>Prices in USD.</p>"
        "<p>Region: US East</p>"
        "<p>Rates are the same across all regions.</p>"
        "<p>Tier: Standard</p>"
        "<p>Rates are the same across all plans.</p>"
        "<p>Prices per 1M tokens.</p>"
        + table("$3.00")
    )
    x = page["pricing_observations"][0]
    assert x["region"] is None and x["tier_or_plan"] is None
    assert x["comparable_candidate"] is False
    assert x["normalized_amount_decimal"] is None


@pytest.mark.parametrize(("header", "expected"), [
    ("Prompt caching | 30m write", "cache_write_30m"),
    ("Prompt caching | 12h write", "cache_write_12h"),
    ("Cached input", "cached_input"),
    ("Cache write", "cache_write"),
])
def test_cache_write_ttl_not_conflated_with_read_or_generic_write(header, expected):
    x = analyze_cell(
        "USD 1.20 / MTok", model_label="Model A", column_header=header,
        row_header="Model A", table_context="Region: Global",
        table_caption="Tier: Standard",
    )
    assert x["price_dimension"] == expected
    assert x["normalized_amount_decimal"] == "1.20"


def test_1000_queries_not_confused_with_1000_requests_or_million_tokens():
    assert detect_unit("Price per 1,000 queries") == "per_1k_queries"
    assert detect_unit("Price per 1,000 requests") == "per_1k_requests"
    assert detect_unit("Price per 1M tokens") == "per_1m_tokens"
    assert detect_unit("Prices per 1,000 queries and per 1M tokens") is None


def test_negative_price_number_never_reinterpreted_as_positive_amount():
    x = analyze_cell(
        "-USD 1.50", model_label="Model A", column_header="Input price",
        row_header="Model A", table_context="Region: Global",
        table_caption="Tier: Standard; per 1M tokens",
    )
    assert x["observed_single_amount_decimal"] is None
    assert x["normalized_amount_decimal"] is None
    assert x["review_quote_candidate"] is False
    assert "negative_or_discount_amount" in x["normalization_blockers"]


def test_date_transition_and_footnotes_still_block_quotes():
    a = ev("<p>Prices in USD.</p><p>Region: Global</p>"
           "<p>Tier: Standard</p><p>Prices per 1M tokens.</p>"
           + table("$2.00 through 2026-11-30; $4.00 starting 2026-12-01"))
    assert a["pricing_observations"][0]["review_quote_candidate"] is False
    b = ev("<p>Prices in USD.</p><p>Region: Global</p>"
           "<p>Tier: Standard</p><p>Prices per 1M tokens.</p>"
           + table("$2.00*"))
    assert b["pricing_observations"][0]["review_quote_candidate"] is False


def test_unmarked_plan_block_with_adjacent_exact_price_and_period_is_review_only():
    page = ev(
        "<section><h3>Pro</h3><div><span>USD 20</span>"
        "<span>per user / month</span></div><p>Includes agent tools.</p></section>"
    )
    assert page["pricing_card_total"] == 1
    assert page["pricing_card_observation_count"] == 1
    x = page["pricing_observations"][0]
    assert x["raw_displayed_price"] == "USD 20 per user / month"
    assert x["billing_unit"] == "per_user_month"
    assert x["price_dimension"] == "subscription"
    assert x["tier_or_plan"] == "Pro"
    assert x["card_plan_heading"] is True
    assert x["model_or_service"] == "subscription_plan:Pro"
    assert x["comparable_candidate"] is False
    assert x["review_quote_candidate"] is False
    assert "subscription_plan_needs_review" in x["normalization_blockers"]
    assert page["approved_for_advisor"] is False


def test_unmarked_promotional_sibling_price_not_a_plan_quote():
    page = ev(
        "<section><h3>Pro</h3><div><span>Save $100 next month!</span>"
        "<span>per month</span></div></section>"
    )
    assert page["pricing_observation_count"] == 0


def test_anonymous_marketing_page_not_rate_card():
    page = ev(
        "<article><h3>Special offer</h3><div><span>USD 30</span>"
        "<span>per month</span></div><p>Limited-time promotion.</p></article>"
    )
    assert page["pricing_card_total"] == 0
    assert page["pricing_comparable_candidate_count"] == 0


def test_review_quote_not_usable_by_typed_price_delta_without_full_context():
    from scripts.evaluate_run import _priced_map, _pricing_delta
    page = ev("<p>All prices are in USD.</p>" + table("$12.50 / MTok"))
    item = {
        "category": "pricing", "source_id": "openai_api_pricing",
        "pricing_evidence_schema": "1.0",
        "pricing_parser_revision": page["pricing_parser_revision"],
        "pricing_inventory_complete": True,
        "pricing_observations": page["pricing_observations"],
    }
    assert _priced_map(item) == {}
    assert _pricing_delta(item, item) == []
