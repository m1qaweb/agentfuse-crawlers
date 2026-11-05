"""P22B2 synthetic rate-scope/cross-page conflict contract regression.

This is not vendor HTML, a publisher permission grant or human gold.
The visible HTML declares conflicting currencies; no parser may invent one.
Human reference unit aliases are strictly SAME-denominator strings.
"""
import copy

import pytest
from lxml import html

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.pricing_scope import table_declarations
from scripts.adjudicate_cross_category_accuracy import (
    _price_field_exact, _pricing_gold_complete,
)
from scripts.pricing_review_units import (
    CANONICAL_RATE_UNITS, REVIEW_UNIT_ALIASES, canonical_review_unit,
)
from scripts.reconcile_cross_category_reviews import _rate_scope

URL = "https://developers.openai.com/api/docs/pricing"
SID = "openai_api_pricing"


def _table(model="Fake Model Alpha", amount="$1.25 / MTok",
           caption="Prices per 1M tokens"):
    return (
        "<table><caption>" + caption + "</caption>"
        "<tr><th>Model</th><th>Input price</th></tr>"
        "<tr><th>" + model + "</th><td>" + amount + "</td></tr>"
        "</table>"
    )


def _context():
    return (
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<p>Prices per 1M tokens.</p>"
    )


def _parse(*parts):
    source = (
        "<html><head><title>Fictional synthetic pricing source</title></head>"
        "<body><main>" + "".join(parts) + "</main></body></html>"
    )
    return extract_evidence(source, URL, category="pricing", source_id=SID)


def _gold(unit="per_million_tokens"):
    return {
        "amount_decimal": "1.25", "currency": "USD",
        "billing_unit": unit, "price_dimension": "input",
        "model_or_service": "Fake Model Alpha",
        "region": "Global", "region_applicability": "explicit",
        "tier_or_plan": "Standard", "tier_applicability": "explicit",
        "conditions": None,
    }


def _observed(unit="per_1m_tokens"):
    return {
        "normalized_amount_decimal": "1.2500", "currency": "USD",
        "billing_unit": unit, "price_dimension": "input",
        "model_or_service": "Fake Model Alpha",
        "region": "Global", "tier_or_plan": "Standard",
    }


@pytest.mark.parametrize("later", [
    "<p>All prices are in EUR.</p>" + _context() + _table(
        model="Fake Model Beta"),
    "<h2>Second pricing section</h2>"
    "<p>All prices are in EUR.</p>",
    "<section class='pricing-card'>"
    "<h3>Other Fake Plan</h3><p>All prices are in EUR.</p>"
    "<p>Input price: $3.00 / MTok</p></section>",
])
def test_later_visible_contradictory_all_currency_disqualifies_earlier_table(later):
    ev = _parse(
        "<p>All prices are in USD.</p>",
        _context(), _table(), later,
    )
    first = ev["pricing_observations"][0]
    assert first["currency"] is None
    assert first["normalized_amount_decimal"] is None
    assert first["comparable_candidate"] is False
    assert "missing_explicit_currency" in first["normalization_blockers"]
    assert all(x["approved_for_advisor"] is False
               for x in ev["pricing_observations"])


def test_conflicting_later_currency_cannot_leak_to_second_unqualified_table():
    ev = _parse(
        "<p>All prices are in USD.</p>",
        _context(), _table(),
        "<p>All prices are in EUR.</p>",
        _context(), _table(model="Fake Model Beta"),
    )
    tables = [
        x for x in ev["pricing_observations"]
        if x["evidence_kind"] == "structured_table"
    ]
    assert len(tables) == 2
    assert all(x["currency"] is None and x["comparable_candidate"] is False
               for x in tables)


def test_visible_same_currency_repeated_after_table_preserves_pretable_scope():
    ev = _parse(
        "<p>All prices are in USD.</p>",
        _context(), _table(),
        "<p>All prices are in USD.</p>",
        _context(), _table(model="Fake Model Beta"),
    )
    table_rows = [
        x for x in ev["pricing_observations"]
        if x["evidence_kind"] == "structured_table"
    ]
    assert len(table_rows) == 2
    assert all(x["currency"] == "USD" for x in table_rows)
    assert table_rows[0]["comparable_candidate"] is True
    assert table_rows[0]["scope_declarations"][0]["scope"] == "page_all_prices"
    assert table_rows[0]["approved_for_advisor"] is False


def test_hidden_later_contradiction_does_not_poison_visible_scope():
    ev = _parse(
        "<p>All prices are in USD.</p>",
        _context(), _table(),
        "<section hidden><p>All prices are in EUR.</p></section>",
    )
    first = ev["pricing_observations"][0]
    assert first["currency"] == "USD"
    assert first["comparable_candidate"] is True
    assert ev["pricing_explicitly_hidden_subtrees_omitted"] >= 1


def test_later_only_same_currency_still_does_not_retroactively_grant_scope():
    ev = _parse(
        _context(), _table(),
        "<p>All prices are in USD.</p>",
        _context(), _table(model="Fake Model Beta"),
    )
    table_rows = [x for x in ev["pricing_observations"]
                  if x["evidence_kind"] == "structured_table"]
    assert len(table_rows) == 2
    assert all(x["currency"] is None for x in table_rows)
    assert all(x["comparable_candidate"] is False for x in table_rows)


def test_explicit_local_cell_currency_survives_ambiguous_global_scope():
    ev = _parse(
        "<p>All prices are in USD.</p>",
        _context(), _table(amount="USD 1.25 / MTok"),
        "<p>All prices are in EUR.</p>",
    )
    obs = ev["pricing_observations"][0]
    assert obs["currency"] == "USD"  # from local price, not global inference
    assert obs["comparable_candidate"] is True
    assert not any(
        row["scope"] == "page_all_prices"
        for row in obs["scope_declarations"]
    )


def test_scope_helper_has_no_prepage_currency_after_late_global_conflict():
    root = html.fromstring(
        "<main><p>All prices are in USD.</p>"
        + _context() + _table()
        + "<p>All prices are in EUR.</p></main>"
    )
    # Keep lxml element proxy alive for this helper's id(table) key contract.
    first = root.xpath(".//table")[0]
    scopes = table_declarations(root)
    assert id(first) in scopes
    assert all(d["dimension"] != "currency" for d in scopes[id(first)])


def test_all_supported_human_aliases_map_to_same_denominator_only():
    assert REVIEW_UNIT_ALIASES
    for alias, canonical in REVIEW_UNIT_ALIASES.items():
        assert canonical in CANONICAL_RATE_UNITS
        assert alias != canonical
        assert canonical_review_unit(alias) == canonical
        assert canonical_review_unit(canonical) == canonical
        assert canonical_review_unit(alias.upper()) == canonical
    assert canonical_review_unit(None) is None
    assert canonical_review_unit("per_1k_tokens") != canonical_review_unit(
        "per_1m_tokens"
    )
    assert canonical_review_unit("per_1m_tokens") == "per_1m_tokens"


@pytest.mark.parametrize("bad", [
    "", "per_million_token", "per_million_requests", "per_2m_tokens",
    "per_1k_tokens_per_1m_tokens", "one million tokens",
    "per_day", "unknown", "tokens", "$/MTok", "per_1m_tokens/month",
    0, True, ["per_1m_tokens"], {"unit": "per_1m_tokens"},
])
def test_unsupported_human_rate_units_are_not_silently_accepted(bad):
    with pytest.raises(ValueError, match="unit|billing_unit"):
        canonical_review_unit(bad)
    assert canonical_review_unit(bad, strict=False) is None
    bad_gold = _gold()
    bad_gold["billing_unit"] = bad
    with pytest.raises(ValueError, match="unit|billing_unit"):
        _rate_scope("pricing", bad_gold)


def test_null_human_unit_does_not_become_a_comparable_reference():
    x = _rate_scope("pricing", _gold(unit=None))
    assert x["billing_unit"] is None
    assert not _pricing_gold_complete(x)


def test_dual_human_review_ingestion_canonicalizes_unit_before_agreement():
    canonical = _rate_scope("pricing", _gold("per_million_tokens"))
    assert canonical["billing_unit"] == "per_1m_tokens"
    equivalent = _rate_scope("pricing", _gold("per_1m_tokens"))
    assert equivalent == canonical
    assert _pricing_gold_complete(canonical)


def test_true_equivalent_human_unit_does_not_create_fake_metric_false_error():
    raw_gold = _gold("per_million_tokens")
    checks = _price_field_exact(_observed("per_1m_tokens"), raw_gold)
    assert all(checks.values()), checks
    checks_reverse = _price_field_exact(
        _observed("per_million_tokens"), _gold("per_1m_tokens")
    )
    assert checks_reverse == checks


def test_different_denominators_are_never_converted_or_inferred():
    checks = _price_field_exact(
        _observed("per_1k_tokens"), _gold("per_million_tokens")
    )
    assert checks["billing_unit"] is False
    assert checks["amount_decimal"] is True
    assert not all(checks.values())
    # P22B2 NEVER multiplies 1k or 1m denominators into each other.
    assert _rate_scope("pricing", _gold("per_thousand_tokens"))[
        "billing_unit"
    ] == "per_1k_tokens"


def test_unknown_prediction_unit_cannot_match_equally_unknown_human_unit():
    observed = _observed()
    observed["billing_unit"] = "provider_custom_unverified"
    human = _gold()
    human["billing_unit"] = "provider_custom_unverified"
    checks = _price_field_exact(observed, human)
    assert checks["billing_unit"] is False
    assert not _pricing_gold_complete(human)


def test_price_fields_other_than_billing_unit_remain_exact():
    observed = _observed()
    observed["currency"] = "EUR"
    observed["region"] = "US East"
    checks = _price_field_exact(observed, _gold())
    assert checks["billing_unit"] is True
    assert checks["currency"] is False
    assert checks["region"] is False
