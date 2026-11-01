"""P09A2: card/list pricing capture and truthful overflow accounting.

All markup is original synthetic illustrative HTML. These are regression
examples, NOT real vendor rate truth, publication approval or a benchmark.
"""

import copy

import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.pricing_cards import MAX_CARDS, MAX_ROWS_PER_CARD
from agentfuse_crawlers.pricing_evidence import MAX_OBSERVATIONS
from agentfuse_crawlers.quality import assess_capture
from scripts.compare_exports import compare, review_queue
from scripts.evaluate_run import _pricing_delta, _source_identity

URL = "https://developers.openai.com/api/docs/pricing"
SID = "openai_api_pricing"


def extract(body):
    return extract_evidence(
        "<html><head><title>Example subscription rates</title></head>"
        "<body><main>" + body + "</main></body></html>",
        URL, category="pricing", source_id=SID,
    )


def card(model="Model Atlas", input_rate="USD 1.20 / MTok",
         output_rate="USD 4.10 / MTok", *, cls="pricing-card",
         scopes="<p>Region: Global</p><p>Tier: Standard</p>"):
    return (
        f"<section class='{cls}'><h3>{model}</h3>{scopes}"
        f"<p>Input price: {input_rate}</p>"
        f"<p>Output price: {output_rate}</p></section>"
    )


def test_explicit_cards_without_tables_generate_two_unapproved_typed_prices():
    ev = extract(card() + "<p>" + ("pricing disclosures are unverified. " * 20) + "</p>")
    assert ev["pricing_table_total"] == 0
    assert ev["pricing_card_total"] == ev["pricing_card_selected"] == 1
    assert ev["pricing_card_price_entries_examined"] == 2
    assert ev["pricing_card_observation_count"] == 2
    assert ev["pricing_observation_count"] == 2
    assert ev["pricing_inventory_complete"] is True
    assert ev["pricing_coverage_status"] == "recognized_pricing_cards_scanned"
    assert ev["pricing_parser_revision"] == "evidence_quote_v3_windows"
    obs = ev["pricing_observations"]
    assert {o["price_dimension"] for o in obs} == {"input", "output"}
    assert {o["normalized_amount_decimal"] for o in obs} == {"1.20", "4.10"}
    assert {o["billing_unit"] for o in obs} == {"per_1m_tokens"}
    assert {o["currency"] for o in obs} == {"USD"}
    assert all(o["model_or_service"] == "Model Atlas" for o in obs)
    assert all(o["region"] == "Global" and o["tier_or_plan"] == "Standard" for o in obs)
    assert all(o["review_status"] == "unverified" for o in obs)
    assert all(o["approved_for_advisor"] is False for o in obs)
    assert all(o["scope_provenance_verified"] is False for o in obs)
    assert all(o["evidence_kind"] == "structured_card" for o in obs)
    # 'Captured' is structural only, not publisher fact approval.
    assert assess_capture("pricing", ev, ev["text"]) == ("captured", "")


def test_definition_list_is_not_ignored_by_table_only_extractor():
    ev = extract(
        "<article class='rate-card'><h3>Model Beta</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<dl><dt>Input price</dt><dd>USD 0.20 per MTok</dd>"
        "<dt>Output price</dt><dd>USD 0.90 per MTok</dd></dl></article>"
    )
    assert ev["pricing_observation_count"] == 2
    assert {o["price_dimension"] for o in ev["pricing_observations"]} == {
        "input", "output"
    }
    assert {o["normalized_amount_decimal"] for o in ev["pricing_observations"]} == {
        "0.20", "0.90"
    }


def test_labeled_list_can_supply_rate_amount_without_html_table():
    ev = extract(
        "<div class='plan-card'><h3>Model Gamma</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p><ul>"
        "<li>Input price: USD 1.00 / MTok</li>"
        "<li>Output price: USD 5.00 / MTok</li>"
        "</ul></div>"
    )
    assert ev["pricing_observation_count"] == 2
    assert len({o["observation_id"] for o in ev["pricing_observations"]}) == 2


def test_local_promo_card_not_promoted_to_regular_comparable_price():
    ev = extract(card(input_rate="USD 1.00 promotion", output_rate="Contact sales"))
    values = ev["pricing_observations"]
    assert len(values) == 2
    assert all(v["comparable_candidate"] is False for v in values)
    assert "time_dependent_or_promotional_price" in values[0]["normalization_blockers"]
    assert values[1]["price_state"] == "contact_sales"


def test_missing_region_or_tier_must_not_be_defaulted_for_plan_cards():
    ev = extract(card(scopes="", input_rate="$1.50 / MTok"))
    x = ev["pricing_observations"][0]
    assert x["currency"] is None
    assert x["region"] is None
    assert x["tier_or_plan"] is None
    assert x["normalized_amount_decimal"] is None
    assert x["comparable_candidate"] is False
    assert all(v["approved_for_advisor"] is False for v in ev["pricing_observations"])


def test_generic_card_title_is_not_attributed_as_model_name():
    ev = extract(card(model="Pricing"))
    assert ev["pricing_card_total"] == 1
    assert all(x["model_or_service"] is None for x in ev["pricing_observations"])
    assert all(x["comparable_candidate"] is False for x in ev["pricing_observations"])


def test_card_without_unique_heading_does_not_fabricate_model():
    ev = extract(
        "<div class='pricing-card'><h3>Model A</h3><h3>Model B</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<p>Input price: USD 1.00 per MTok</p></div>"
    )
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_observations"][0]["model_or_service"] is None
    assert ev["pricing_observations"][0]["model_label_provenance"] == "unresolved"


def test_plain_marketing_text_not_scanned_as_card_or_price():
    ev = extract(
        "<p>Our pricing plans save 50% compared to others.</p>"
        "<div><h3>Latest article</h3><p>Save $100 next month!</p></div>"
        "<section class='features'><h3>What is included</h3>"
        "<p>Pricing is competitive and billing is easy.</p></section>"
    )
    assert ev["pricing_card_total"] == 0
    assert ev["pricing_observation_count"] == 0


def test_card_nested_in_grid_is_not_repeated_as_grid_evidence():
    ev = extract(
        "<div class='pricing-card'><div class='pricing-card'>"
        + card(model="Model Inside")
        + "</div></div>"
    )
    assert ev["pricing_card_total"] == 1
    assert ev["pricing_observation_count"] == 2


def test_navigation_or_footer_price_cards_are_not_crawled():
    ev = extract(
        "<nav>" + card() + "</nav><footer>" + card() + "</footer>"
        "<div class='pricing-card'><h3>Model Correct</h3>"
        "<p>Input price: USD 2.00 / MTok</p></div>"
    )
    assert ev["pricing_card_total"] == 1
    assert ev["pricing_observations"][0]["model_or_service"] == "Model Correct"


def test_table_and_card_same_price_are_not_double_counted():
    table = (
        "<h2>Region: Global</h2><h3>Tier: Standard</h3>"
        "<table><caption>USD per 1M tokens</caption>"
        "<tr><th>Model</th><th>Input price</th></tr>"
        "<tr><th>Model Atlas</th><td>USD 1.20</td></tr></table>"
    )
    ev = extract(table + card(input_rate="USD 1.20 / MTok",
                              output_rate="USD 4.10 / MTok"))
    assert ev["pricing_table_relevant"] == 1
    assert ev["pricing_card_total"] == 1
    assert ev["pricing_card_duplicate_rate_count"] == 1
    assert ev["pricing_observation_count"] == 2
    assert ev["pricing_inventory_complete"] is True
    assert len({o["observation_id"] for o in ev["pricing_observations"]}) == 2


def test_table_vs_card_different_amount_same_scope_blocks_source_comparison():
    table = (
        "<h2>Region: Global</h2><h3>Tier: Standard</h3>"
        "<table><caption>USD per 1M tokens</caption>"
        "<tr><th>Model</th><th>Input price</th></tr>"
        "<tr><th>Model Atlas</th><td>USD 1.20</td></tr></table>"
    )
    ev = extract(table + card(input_rate="USD 1.30 / MTok"))
    assert ev["pricing_card_rate_identity_conflict"] is True
    assert ev["pricing_inventory_complete"] is False
    assert assess_capture("pricing", ev, ev["text"])[0] == "partial_capture"


def test_conflicting_card_scopes_block_normalization():
    ev = extract(
        "<div class='pricing-card'><h3>Model A</h3>"
        "<p>Region: Global</p><p>Region: US East</p>"
        "<p>Tier: Standard</p><p>Input price: USD 2.50 per MTok</p>"
        "</div>"
    )
    obs = ev["pricing_observations"][0]
    assert obs["card_scope_conflict"] is True
    assert obs["comparable_candidate"] is False
    assert "card_scope_conflict" in obs["normalization_blockers"]


def test_card_scan_ceiling_is_observable_and_stops_rate_promotion():
    ev = extract("".join(card(model=f"Model {i}") for i in range(MAX_CARDS + 3)))
    assert ev["pricing_card_total"] == MAX_CARDS + 3
    assert ev["pricing_card_omitted"] == 3
    assert ev["pricing_card_scan_truncated"] is True
    assert ev["pricing_inventory_complete"] is False
    assert ev["pricing_observation_count"] <= MAX_OBSERVATIONS
    assert ev["pricing_observation_total_detected"] >= 2 * MAX_CARDS
    assert assess_capture("pricing", ev, ev["text"])[0] == "partial_capture"


def test_rate_candidate_limit_preserves_exact_overflow_diagnostics():
    ev = extract("".join(
        "<section class='pricing-card'><h3>Model %d</h3>" % i
        + "<p>Region: Global</p><p>Tier: Standard</p>"
        + "<p>Input price: USD 1.00 / MTok</p>"
        + "<p>Output price: USD 2.00 / MTok</p>"
        + "<p>Cached input price: USD 0.10 / MTok</p></section>"
        for i in range(105)
    ))
    assert ev["pricing_observation_count"] == MAX_OBSERVATIONS
    assert ev["pricing_observation_limit_reached"] is True
    assert ev["pricing_inventory_complete"] is False
    assert ev["pricing_observation_total_detected"] > MAX_OBSERVATIONS
    assert ev["pricing_card_scan_truncated"] is True


def test_single_card_over_24_rate_rows_remains_incomplete():
    rows = "".join(
        "<li>Input price: USD %d.00 / MTok</li>" % (i + 1)
        for i in range(MAX_ROWS_PER_CARD + 2)
    )
    ev = extract(
        "<section class='pricing-card'><h3>Model Extreme</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p><ul>"
        + rows + "</ul></section>"
    )
    assert ev["pricing_card_price_entries_examined"] == MAX_ROWS_PER_CARD + 2
    assert ev["pricing_card_price_entries_omitted"] == 2
    assert ev["pricing_card_scan_truncated"] is True
    assert ev["pricing_inventory_complete"] is False


def test_card_observation_identity_stable_when_cards_reordered():
    first = extract(card("Model A") + card("Model B"))
    second = extract(card("Model B") + card("Model A"))
    assert {x["observation_id"] for x in first["pricing_observations"]} == {
        x["observation_id"] for x in second["pricing_observations"]
    }


def test_legacy_archives_get_fresh_baseline_after_card_parser_upgrade():
    ev = extract(card() + "<p>" + ("documentation note. " * 40) + "</p>")
    base = {
        "source_id": SID, "source_url": URL, "provider": "OpenAI",
        "category": "pricing", "status": "captured",
        "content_sha256": ev["content_sha256"],
        "pricing_evidence_schema": "1.0",
        "pricing_parser_revision": "structured_cards_v2",
        "pricing_inventory_complete": ev["pricing_inventory_complete"],
        "pricing_comparable_candidate_count": ev["pricing_comparable_candidate_count"],
        "pricing_observations": ev["pricing_observations"],
        "approved_for_advisor": False,
    }
    prior = copy.deepcopy(base)
    prior.pop("pricing_parser_revision")
    assert _source_identity(base) != _source_identity(prior)
    changes = compare({SID: base}, {SID: prior})
    assert [x["change_type"] for x in changes] == ["new_baseline"]
    assert review_queue({SID: base}, {SID: prior}, changes) == []
    assert _pricing_delta(base, prior) == []


def test_card_identical_rate_same_descriptor_is_one_observation():
    ev = extract(card("Model A") + card("Model A"))
    assert ev["pricing_card_duplicate_rate_count"] == 2
    assert ev["pricing_observation_count"] == 2


def test_input_and_output_are_never_conflated_by_service_label():
    ev = extract(card("Plan Pro", input_rate="USD 0.20 per MTok",
                      output_rate="USD 1.00 per MTok"))
    assert {(o["model_or_service"], o["price_dimension"])
            for o in ev["pricing_observations"]} == {
                ("Plan Pro", "input"), ("Plan Pro", "output"),
            }


def test_cross_host_and_credentials_not_generated_from_card_attributes():
    ev = extract(
        "<section class='pricing-card' id='https://evil.invalid/token?secret=1'>"
        "<h3>Model Safe</h3><p>Input price: USD 1.20 per MTok</p>"
        "</section>"
    )
    obs = ev["pricing_observations"][0]
    assert "evil.invalid" not in str(obs)
    assert "secret" not in str(obs)
    assert obs["source_url"] == URL


def test_explicit_page_all_currency_inherited_by_cards_without_guessing_other_dims():
    ev = extract(
        "<p>All prices are in USD.</p>"
        + card("Model Delta", input_rate="$1.20 / MTok",
               output_rate="$2.40 / MTok")
    )
    assert ev["pricing_observation_count"] == 2
    assert all(o["currency"] == "USD" for o in ev["pricing_observations"])
    assert all(o["comparable_candidate"] is True for o in ev["pricing_observations"])
    assert all(any(
        d["dimension"] == "currency" and d["scope"] == "page_all_prices"
        for d in o["scope_declarations"]
    ) for o in ev["pricing_observations"])


def test_later_conflicting_all_prices_currency_blocks_entire_page_inference():
    ev = extract(
        "<p>All prices are in USD.</p>"
        + card("Model A", input_rate="$1.20 / MTok")
        + "<p>All prices are in EUR.</p>"
        + card("Model B", input_rate="$3.20 / MTok")
    )
    assert ev["pricing_card_total"] == 2
    assert all(o["card_scope_conflict"] for o in ev["pricing_observations"])
    assert all(o["comparable_candidate"] is False for o in ev["pricing_observations"])


def test_nested_span_is_not_duplicate_price_statement():
    ev = extract(
        "<section class='pricing-card'><h3>Model Delta</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<p>Input price: <span class='price-amount'>USD 1.00 / MTok</span></p>"
        "</section>"
    )
    assert ev["pricing_card_price_entries_examined"] == 1
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_observations"][0]["price_dimension"] == "input"


def test_subscriber_price_dimension_from_explicit_per_seat_per_month_text():
    ev = extract(
        "<div class='plan-card'><h3>Business plan</h3>"
        "<p>Region: Global</p><p>Plan: Business</p>"
        "<p class='price-amount'>USD 20 per seat/month</p></div>"
    )
    assert ev["pricing_observation_count"] == 1
    o = ev["pricing_observations"][0]
    assert o["price_dimension"] == "subscription"
    assert o["billing_unit"] == "per_user_month"
    assert o["normalized_amount_decimal"] == "20"
    assert o["model_label_provenance"] == "single_card_heading"
    assert o["approved_for_advisor"] is False


def test_bare_amount_without_explicit_rate_dimension_remains_uncomparable():
    ev = extract(
        "<div class='price-card'><h3>Business plan</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<span class='price-amount'>USD 20/month</span></div>"
    )
    o = ev["pricing_observations"][0]
    assert o["price_dimension"] is None
    assert o["comparable_candidate"] is False
    assert "missing_price_dimension" in o["normalization_blockers"]


def test_oversized_price_card_reports_explicit_evidence_loss_not_clean_capture():
    huge = "A pricing note for example product users. " * 140
    ev = extract(
        "<section class='pricing-card'><h3>Model Huge</h3>"
        "<p>Input price: USD 1.00 / MTok</p>"
        "<p>" + huge + "</p></section>"
    )
    assert ev["pricing_card_total"] == 1
    assert ev["pricing_card_selected"] == 0
    assert ev["pricing_card_oversized_count"] == 1
    assert ev["pricing_card_omitted"] == 1
    assert ev["pricing_card_scan_truncated"] is True
    assert ev["pricing_inventory_complete"] is False
    assert assess_capture("pricing", ev, ev["text"])[0] == "partial_capture"


def test_generic_models_pricing_section_cannot_supply_a_specific_model_identity():
    ev = extract(
        "<h2>Model pricing</h2><p>Region: Global</p>"
        "<table><caption>Tier: Standard; USD per 1M tokens</caption>"
        "<tr><th>Type</th><th>Input price</th></tr>"
        "<tr><th>Input price</th><td>USD 1.00</td></tr></table>"
    )
    assert ev["pricing_observation_count"] == 1
    o = ev["pricing_observations"][0]
    assert o["model_or_service"] is None
    assert o["model_label_provenance"] == "unresolved"
    assert o["comparable_candidate"] is False


def test_specific_gemini_heading_can_still_attribute_model_by_rate_table():
    ev = extract(
        "<h2>Gemini 3.0 Flash</h2><p>Region: Global</p>"
        "<table><caption>Tier: Paid; USD per 1M tokens</caption>"
        "<tr><th>Dimension</th><th>Price</th></tr>"
        "<tr><th>Input price</th><td>USD 1.00</td></tr></table>"
    )
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_observations"][0]["model_or_service"] == "Gemini 3.0 Flash"
    assert ev["pricing_observations"][0]["model_label_provenance"] == "scoped_heading"


def test_two_tables_same_rate_identity_require_review_instead_of_false_delta():
    ev = extract(
        "<h2>Region: Global</h2><h3>Tier: Standard</h3>"
        "<table><caption>USD per 1M tokens</caption>"
        "<tr><th>Model</th><th>Input price</th></tr>"
        "<tr><th>Model Atlas</th><td>USD 1.20</td></tr></table>"
        "<table><caption>USD per 1M tokens</caption>"
        "<tr><th>Model</th><th>Input price</th></tr>"
        "<tr><th>Model Atlas</th><td>USD 2.00</td></tr></table>"
    )
    assert ev["pricing_observation_count"] == 2
    assert ev["pricing_rate_identity_collision_count"] == 1
    assert ev["pricing_inventory_complete"] is False
    assert assess_capture("pricing", ev, ev["text"])[0] == "partial_capture"


@pytest.mark.parametrize("first_label", ["USD 25.00", "$25", "100", "1,000"])
def test_price_or_numeric_table_row_cannot_be_mislabeled_as_a_model(first_label):
    ev = extract(
        "<h2>Model pricing</h2><h3>Region: Global</h3>"
        "<table><caption>Tier: Standard; USD per 1M tokens</caption>"
        "<tr><th>Descriptor</th><th>Input price</th></tr>"
        f"<tr><th>{first_label}</th><td>USD 1.00</td></tr></table>"
    )
    assert ev["pricing_observation_count"] == 1
    o = ev["pricing_observations"][0]
    assert o["model_or_service"] is None
    assert o["normalized_amount_decimal"] is None
    assert "missing_model_or_service" in o["normalization_blockers"]



@pytest.mark.parametrize("kind", ["div", "li"])
def test_explicit_rate_row_two_span_structure_not_ignored_or_double_counted(kind):
    markup = (
        "<div class='pricing-card'><h3>Model Delta</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        f"<{kind} class='rate-row'><span>Input</span>"
        f"<span>USD 0.20 / MTok</span></{kind}>"
        f"<{kind} class='price-row'><span>Output</span>"
        f"<span>USD 1.00 / MTok</span></{kind}>"
        "</div>"
    )
    ev = extract(markup)
    assert ev["pricing_observation_count"] == 2
    assert ev["pricing_card_price_entries_examined"] == 2
    obs = ev["pricing_observations"]
    assert {x["price_dimension"] for x in obs} == {"input", "output"}
    assert {x["normalized_amount_decimal"] for x in obs} == {"0.20", "1.00"}
    assert all(x["model_or_service"] == "Model Delta" for x in obs)
    assert all(x["approved_for_advisor"] is False for x in obs)


def test_unlabeled_paired_rows_are_not_assumed_to_be_input_output_rates():
    ev = extract(
        "<section class='plan-card'><h3>Model Safe</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<div class='rate-row'><span>More information</span>"
        "<span>USD 10.00</span></div></section>"
    )
    assert ev["pricing_observation_count"] == 0
