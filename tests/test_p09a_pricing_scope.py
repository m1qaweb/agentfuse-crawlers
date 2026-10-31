"""P09A regression suite inspired by observed Zyte prices, never vendor gold.

The real October 31 Zyte Items showed 3,011 raw price observations but zero
comparable candidates. These tiny original examples check context inheritance
without shipping original publisher HTML or asserting any real vendor rate.
"""

import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.rate_units import analyze_cell, detect_unit

OPENAI_URL = "https://developers.openai.com/api/docs/pricing"
ANTHROPIC_URL = "https://platform.claude.com/docs/en/about-claude/pricing"


def pricing(body, *, sid="openai_api_pricing", url=OPENAI_URL):
    return extract_evidence(
        "<html><head><title>Synthetic billing test</title></head>"
        "<body><main>" + body + "</main></body></html>",
        url, category="pricing", source_id=sid,
    )


def rate_table(*, amount="$1.20", model="Model Alpha", unit_caption=""):
    caption = f"<caption>{unit_caption}</caption>" if unit_caption else ""
    return (
        f"<table>{caption}<tr><th>Model</th><th>Input price</th></tr>"
        f"<tr><th>{model}</th><td>{amount}</td></tr></table>"
    )


def test_openai_like_unit_preamble_is_attached_without_fabricated_usd_region_or_tier():
    # The observed OpenAI page had 'Prices per 1M tokens' separated from
    # its HTML tables; earlier code discarded this explicit denomination.
    ev = pricing("<p>Prices per 1M tokens.</p>" + rate_table())
    obs = ev["pricing_observations"][0]
    assert obs["billing_unit"] == "per_1m_tokens"
    assert obs["currency"] is None
    assert obs["region"] is None
    assert obs["tier_or_plan"] is None
    assert obs["normalized_amount_decimal"] is None
    assert obs["comparable_candidate"] is False
    assert "missing_explicit_currency" in obs["normalization_blockers"]
    assert "missing_explicit_region" in obs["normalization_blockers"]
    assert obs["scope_declarations"] == [{
        "dimension": "billing_unit", "value": "per_1m_tokens",
        "scope": "adjacent_preceding_text",
        "evidence_text": "Prices per 1M tokens.",
        "review_status": "unverified",
    }]
    assert ev["pricing_scoped_table_count"] == 1
    assert ev["approved_for_advisor"] is False


def test_anthropic_like_global_currency_and_cell_mtok_are_preserved():
    html = (
        "<p>All prices are in USD.</p><h2>Model pricing</h2>"
        + rate_table(amount="$12.50 / MTok")
    )
    ev = pricing(html, sid="anthropic_api_pricing", url=ANTHROPIC_URL)
    obs = ev["pricing_observations"][0]
    assert obs["currency"] == "USD"
    assert obs["billing_unit"] == "per_1m_tokens"
    assert obs["region"] is None
    assert obs["tier_or_plan"] is None
    assert obs["comparable_candidate"] is False
    assert obs["scope_declarations"][0]["scope"] == "page_all_prices"
    assert obs["scope_declarations"][0]["evidence_text"] == "All prices are in USD."
    assert obs["approved_for_advisor"] is False


def test_complete_explicit_local_scope_is_comparable_but_remains_unapproved():
    markup = (
        "<p>All prices are in USD.</p>"
        "<h2>Technical billing reference</h2>"
        "<p>Region: Global</p>"
        "<p>Tier: Standard</p>"
        "<p>Prices per 1M tokens.</p>"
        + rate_table()
    )
    ev = pricing(markup)
    obs = ev["pricing_observations"][0]
    assert obs["currency"] == "USD"
    assert obs["billing_unit"] == "per_1m_tokens"
    assert obs["region"] == "Global"
    assert obs["tier_or_plan"] == "Standard"
    assert obs["normalized_amount_decimal"] == "1.20"
    assert obs["comparable_candidate"] is True
    assert obs["scope_provenance_verified"] is False
    assert obs["approved_for_advisor"] is False
    assert len(obs["scope_declarations"]) == 4


def test_unknown_currency_never_inferred_from_dollar_sign():
    ev = pricing("<p>Region: Global</p><p>Tier: Standard</p>"
                 "<p>Prices per 1M tokens.</p>" + rate_table())
    obs = ev["pricing_observations"][0]
    assert obs["currency"] is None
    assert obs["normalized_amount_decimal"] is None
    assert "missing_explicit_currency" in obs["normalization_blockers"]


@pytest.mark.parametrize("unit_line", [
    "Prices per 1M tokens.",
    "Prices per million tokens.",
    "Rates per 1M input tokens.",
])
def test_explicit_local_unit_phrasings_are_parsed(unit_line):
    ev = pricing("<p>All prices are in USD.</p><p>Region: Global</p>"
                 "<p>Tier: Standard</p><p>" + unit_line + "</p>"
                 + rate_table())
    assert ev["pricing_observations"][0]["billing_unit"] == "per_1m_tokens"


@pytest.mark.parametrize("raw", [
    "$10 / MTok", "$10/MTok", "$10 per MTok", "$10 / million tokens",
])
def test_raw_explicit_million_token_unit_does_not_require_guessing(raw):
    assert detect_unit(raw) == "per_1m_tokens"


def test_conflicting_explicit_all_currency_declarations_fail_closed():
    ev = pricing(
        "<p>All prices are in USD.</p>"
        "<p>All prices are in EUR.</p>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<p>Prices per 1M tokens.</p>" + rate_table()
    )
    obs = ev["pricing_observations"][0]
    assert obs["currency"] is None
    assert obs["normalized_amount_decimal"] is None


def test_conflicting_local_region_never_guesses_one():
    ev = pricing(
        "<p>All prices are in USD.</p>"
        "<p>Region: Global</p><p>Region: US East</p>"
        "<p>Tier: Standard</p><p>Prices per 1M tokens.</p>"
        + rate_table()
    )
    obs = ev["pricing_observations"][0]
    assert obs["region"] is None
    assert not obs["comparable_candidate"]


def test_stale_local_unit_does_not_leak_into_next_table():
    ev = pricing(
        "<p>All prices are in USD.</p>"
        "<p>Prices per 1M tokens.</p>"
        + rate_table(model="Model A")
        + rate_table(model="Model B")
    )
    first, second = ev["pricing_observations"]
    assert first["billing_unit"] == "per_1m_tokens"
    assert second["billing_unit"] is None
    assert second["currency"] == "USD"


def test_new_h2_breaks_local_unit_scope():
    ev = pricing(
        "<p>Prices per 1M tokens.</p>"
        "<h2>Unrelated billing service</h2>"
        + rate_table()
    )
    assert ev["pricing_observations"][0]["billing_unit"] is None


def test_explicit_table_caption_overrides_no_page_unit_and_keeps_provenance():
    ev = pricing(
        "<p>All prices are in USD.</p>"
        + rate_table(unit_caption="USD per 1k tokens")
    )
    obs = ev["pricing_observations"][0]
    assert obs["billing_unit"] == "per_1k_tokens"
    assert obs["currency"] == "USD"
    assert obs["scope_declarations"][0]["dimension"] == "currency"


def test_units_from_two_contradictory_sources_remain_unknown():
    ev = pricing(
        "<p>Prices per 1M tokens.</p>"
        + rate_table(unit_caption="USD per 1k tokens")
    )
    assert ev["pricing_observations"][0]["billing_unit"] is None
    assert not ev["pricing_observations"][0]["comparable_candidate"]


def test_marketing_claim_is_not_structured_rate_scope():
    ev = pricing(
        "<p>All regions have great value, save 90% on subscriptions.</p>"
        "<p>Prices from $1.20 per million tokens, terms apply.</p>"
        + rate_table()
    )
    obs = ev["pricing_observations"][0]
    assert obs["region"] is None
    assert obs["currency"] is None
    assert obs["billing_unit"] is None


def test_navigation_and_table_cell_declarations_cannot_be_inherited():
    ev = pricing(
        "<nav><p>All prices are in USD.</p></nav>"
        "<p>Prices per 1M tokens.</p>"
        + rate_table()
    )
    obs = ev["pricing_observations"][0]
    assert obs["currency"] is None
    assert obs["billing_unit"] == "per_1m_tokens"


def test_page_wide_currency_declaration_after_first_table_not_applied():
    ev = pricing(
        rate_table(model="Model A")
        + "<p>All prices are in USD.</p>"
        + rate_table(model="Model B")
    )
    assert all(o["currency"] is None for o in ev["pricing_observations"])


def test_conditional_gemini_prices_still_blocked_even_with_complete_scope():
    ev = pricing(
        "<p>All prices are in USD.</p>"
        "<p>Region: Global</p><p>Tier: Paid</p>"
        "<p>Prices per 1M tokens.</p>"
        + rate_table(amount="$2.00 through Nov 30. $4.00 starting Dec 1.")
    )
    obs = ev["pricing_observations"][0]
    assert obs["comparable_candidate"] is False
    assert obs["normalized_amount_decimal"] is None
    assert obs["price_state"] == "multiple_or_time_dependent"
