"""P17B1 synthetic-only exact-source family, inline rate and cap safety."""
from copy import deepcopy
import hashlib

import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.pricing_adapters import (
    FAMILIES, REVISION, explicit_inline_components, family_for_source,
    family_profiles,
)

SOURCE_URLS = {
    "openai_api_pricing": "https://developers.openai.com/api/docs/pricing",
    "together_ai_pricing": "https://www.together.ai/pricing",
    "fireworks_ai_pricing": "https://docs.fireworks.ai/serverless/pricing",
    "gemini_api_pricing": "https://ai.google.dev/gemini-api/docs/pricing",
    "aws_bedrock_pricing": "https://aws.amazon.com/bedrock/pricing/",
    "cursor_pricing": "https://cursor.com/pricing",
    "supabase_pricing": "https://supabase.com/pricing",
}
COMPOUND = (
    "Input: USD 1.50 / 1M tokens; "
    "Cached input: USD 0.30 / 1M tokens; "
    "Output: USD 4.50 / 1M tokens"
)


def parse(rows, *, sid="openai_api_pricing", caption="USD per 1M tokens",
          headings="<h2>Region: Global</h2><h3>Tier: Standard</h3>",
          header="Rates"):
    markup = (
        "<html><head><title>Official synthetic pricing fixture</title></head>"
        "<body><main>" + headings + "<table><caption>" + caption +
        "</caption><thead><tr><th>Model</th><th>" + header +
        "</th></tr></thead><tbody>" + rows +
        "</tbody></table></main></body></html>"
    )
    return extract_evidence(
        markup, SOURCE_URLS[sid], category="pricing", source_id=sid,
    )


def row(raw, *, model="Model Alpha", marked=True):
    if marked:
        name = "<strong>" + model + "</strong>"
    else:
        name = model
    return "<tr><th>" + name + "</th><td>" + raw + "</td></tr>"


def test_family_profiles_are_exact_source_review_only_and_never_approve_prices():
    profiles = family_profiles()
    assert len(profiles) == sum(len(v) for v in FAMILIES.values())
    assert len(profiles) == 19
    assert len(set(profiles)) == 19
    assert profiles["openai_api_pricing"]["page_family_candidate"] == (
        "model_token_matrix"
    )
    assert profiles["aws_bedrock_pricing"]["page_family_candidate"] == (
        "cloud_regional_matrix"
    )
    assert profiles["cursor_pricing"]["page_family_candidate"] == (
        "subscription_plan_cards"
    )
    assert profiles["pinecone_pricing"]["page_family_candidate"] == (
        "request_credit_metering"
    )
    for p in profiles.values():
        assert p["family_review_status"] == (
            "unverified_pending_original_publisher_gold"
        )
        assert p["publisher_product_identity_verified"] is False
        assert p["new_fetch_permission"] is False
        assert p["automatic_provider_adapter_authorized"] is False
        assert p["advisor_fact_approvals"] == 0
    assert family_for_source(
        "supabase_pricing", SOURCE_URLS["supabase_pricing"]
    ) is None
    with pytest.raises(ValueError, match="pinned manifest"):
        family_for_source("openai_api_pricing", "https://evil.invalid/pricing")


def test_explicit_three_amounts_become_three_unapproved_typed_review_rows():
    ev = parse(row(COMPOUND))
    assert ev["pricing_parser_revision"] == (
        "evidence_quote_v5_inline_labeled_components"
    )
    assert ev["pricing_inline_adapter_revision"] == REVISION
    assert ev["pricing_inline_adapter_family"] == "model_token_matrix"
    assert ev["pricing_inline_rate_cells_split"] == 1
    assert ev["pricing_inline_component_extra_observations"] == 2
    assert ev["pricing_price_cells_examined"] == 1
    assert ev["pricing_observation_total_detected"] == 3
    assert ev["pricing_observation_count"] == 3
    assert ev["pricing_observation_limit_reached"] is False
    assert ev["pricing_inline_multi_amount_cells_unresolved"] == 0
    assert ev["pricing_comparable_candidate_count"] == 0
    assert ev["pricing_review_quote_candidate_count"] == 0
    assert ev["pricing_inventory_complete"] is True
    observations = ev["pricing_observations"]
    assert len({x["observation_id"] for x in observations}) == 3
    assert len({x["source_evidence_sha256"] for x in observations}) == 3
    assert {x["price_dimension"] for x in observations} == {
        "input", "cached_input", "output"
    }
    assert {
        x["observed_single_amount_decimal"] for x in observations
    } == {"1.50", "0.30", "4.50"}
    assert [x["inline_component_index"] for x in observations] == [0, 1, 2]
    assert all(
        x["raw_parent_cell_text"] == COMPOUND
        and x["inline_component_count"] == 3
        and x["currency"] == "USD"
        and x["region"] == "Global"
        and x["tier_or_plan"] == "Standard"
        and x["billing_unit"] == "per_1m_tokens"
        and x["model_or_service"] == "Model Alpha"
        and x["evidence_kind"] == "structured_table_labeled_inline_component"
        and x["inline_component_parent_identity_review_status"] ==
            "unverified_composite_cell"
        and x["family_adapter_candidate_only"] is True
        and x["source_product_owner_verified"] is False
        and x["normalization_blockers"] == [
            "inline_component_requires_independent_publisher_gold"
        ]
        and x["normalized_amount_decimal"] is None
        and x["review_quote_candidate"] is False
        and x["comparable_candidate"] is False
        and x["approved_for_advisor"] is False
        for x in observations
    )
    assert ev["approved_for_advisor"] is False


@pytest.mark.parametrize("sid", [
    "openai_api_pricing", "together_ai_pricing",
    "fireworks_ai_pricing", "gemini_api_pricing",
])
def test_adapter_model_token_family_pilot_only(sid):
    ev = parse(row(COMPOUND), sid=sid)
    assert ev["pricing_inline_rate_cells_split"] == 1
    assert ev["pricing_comparable_candidate_count"] == 0
    assert ev["pricing_publisher_completeness_verified"] is False


@pytest.mark.parametrize("sid", ["aws_bedrock_pricing", "cursor_pricing",
                                "supabase_pricing"])
def test_other_families_do_not_execute_token_split_automatically(sid):
    ev = parse(row(COMPOUND), sid=sid)
    assert ev["pricing_inline_rate_cells_split"] == 0
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_comparable_candidate_count"] == 0
    assert ev["pricing_inline_multi_amount_cells_unresolved"] == 1
    assert ev["pricing_observations"][0]["raw_displayed_price"] == COMPOUND
    assert not ev["pricing_observations"][0]["approved_for_advisor"]


@pytest.mark.parametrize("raw", [
    "USD 3.00 / USD 0.30 / USD 15.00",
    "Input USD 2.00 / 1M tokens; Output USD 6.00 / 1M tokens",
    "Input: USD 2.00 / 1M tokens; Cached: USD 0.50 / 1M tokens",
    "Input: USD 2.00 / 1M tokens; Input: USD 3.00 / 1M tokens",
    "Input: USD 2.00; Output: USD 6.00; Contact sales for cache writes",
    "Input: USD 2.00 starting December 1; Output: USD 6.00",
    "Input: USD 2.00 < 200k tokens; Output: USD 6.00",
    "Input: USD 2.00 per 1M tokens; Output: USD 6.00 10% discount",
    "Input: USD 2.00; Output: USD 6.00; Input: USD 2.25",
    "Input: USD 2.00; Output: USD 6.00; Extra fee 5%",
])
def test_unlabeled_duplicate_conditional_or_tiered_price_never_split(raw):
    ev = parse(row(raw))
    assert ev["pricing_inline_rate_cells_split"] == 0
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_comparable_candidate_count"] == 0
    assert ev["pricing_observations"][0]["normalized_amount_decimal"] is None
    assert not ev["approved_for_advisor"]


def test_realistic_fireworks_unlabeled_triplets_must_remain_unresolved():
    ev = parse(
        row("$3.00 / $0.30 / $15.00"),
        sid="fireworks_ai_pricing", caption="USD per 1M tokens",
        header="Standard",
    )
    assert ev["pricing_inline_rate_cells_split"] == 0
    assert ev["pricing_inline_multi_amount_cells_unresolved"] == 1
    assert ev["pricing_observations"][0]["price_state"] == (
        "multiple_or_time_dependent"
    )


def test_realistic_together_adjacent_cached_price_is_not_assigned_by_position():
    ev = parse(row("$3.00$0.30 (cached)"), sid="together_ai_pricing")
    assert ev["pricing_inline_rate_cells_split"] == 0
    assert ev["pricing_comparable_candidate_count"] == 0
    assert not ev["pricing_observations"][0]["review_quote_candidate"]


def test_gemini_effective_date_cells_not_split_into_fake_current_price():
    ev = parse(row(
        "Input: USD 2.00 through November 30, 2026; "
        "Input: USD 4.00 starting December 1, 2026"
    ), sid="gemini_api_pricing")
    assert ev["pricing_inline_rate_cells_split"] == 0
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_comparable_candidate_count"] == 0


def test_missing_currency_plan_and_region_remain_unspecified_in_components():
    ev = parse(
        row("Input: $1.00 / 1M tokens; Output: $4.00 / 1M tokens"),
        caption="per 1M tokens", headings="<h2>Model pricing</h2>",
    )
    assert ev["pricing_inline_rate_cells_split"] == 1
    assert ev["pricing_review_quote_candidate_count"] == 0
    for candidate in ev["pricing_observations"]:
        assert candidate["currency"] is None
        assert candidate["tier_or_plan"] is None
        assert candidate["region"] is None
        assert candidate["normalized_amount_decimal"] is None
        assert not candidate["comparable_candidate"]


def test_unverified_compound_is_not_safely_comparable_even_if_scope_explicit():
    ev = parse(row(COMPOUND))
    assert all(x["normalization_blockers"] == [
        "inline_component_requires_independent_publisher_gold"
    ] for x in ev["pricing_observations"])
    assert ev["pricing_observation_count"] == 3
    assert ev["pricing_review_quote_candidate_count"] == 0
    assert ev["pricing_comparable_candidate_count"] == 0


def test_model_name_ambiguity_blocks_inline_rate_identity():
    ev = parse(row(COMPOUND, model="Model Alpha For demanding technical tasks"))
    assert ev["pricing_inline_rate_cells_split"] == 1
    assert ev["pricing_model_identity_review_rows"] == 1
    for obs in ev["pricing_observations"]:
        assert obs["model_or_service"] is None
        assert "missing_model_or_service" in obs["normalization_blockers"]
        assert obs["normalized_amount_decimal"] is None


def test_single_amount_hash_and_shape_remain_unchanged():
    ev = parse(row("USD 2.50"), header="Input price")
    assert ev["pricing_inline_rate_cells_split"] == 0
    assert ev["pricing_observation_total_detected"] == 1
    obs = ev["pricing_observations"][0]
    label = " ".join(("Region: Global > Tier: Standard", "USD per 1M tokens", ""))
    expected = hashlib.sha256(
        ("USD 2.50|Input price|Model Alpha|" + label).encode("utf-8")
    ).hexdigest()
    assert obs["source_evidence_sha256"] == expected
    assert obs["evidence_kind"] == "structured_table"
    assert obs["model_or_service"] == "Model Alpha"
    assert obs["raw_displayed_price"] == "USD 2.50"
    assert "inline_component_count" not in obs


def test_multiple_labeled_model_rows_have_stable_distinct_evidence_ids():
    ev = parse(
        row(COMPOUND, model="Model Alpha")
        + row(COMPOUND.replace("1.50", "2.50"), model="Model Beta")
    )
    assert ev["pricing_inline_rate_cells_split"] == 2
    assert ev["pricing_observation_total_detected"] == 6
    assert ev["pricing_observation_count"] == 6
    assert len({x["observation_id"] for x in ev["pricing_observations"]}) == 6
    assert all(x["approved_for_advisor"] is False
               for x in ev["pricing_observations"])


def test_cap_stays_partial_when_inline_components_exceed_300():
    ev = parse(
        "".join(row(COMPOUND, model=f"Model {n}") for n in range(125))
    )
    assert ev["pricing_price_cells_examined"] == 125
    assert ev["pricing_inline_rate_cells_split"] == 125
    assert ev["pricing_inline_component_extra_observations"] == 250
    assert ev["pricing_observation_total_detected"] == 375
    assert ev["pricing_observation_count"] == 300
    assert ev["pricing_observation_limit_reached"]
    assert not ev["pricing_inventory_complete"]
    assert ev["pricing_coverage_status"] == "recognized_pricing_inventory_partial"


def test_inline_splitting_respects_existing_table_window_partition():
    from lxml import html
    from agentfuse_crawlers.pricing_evidence import extract_pricing_evidence
    markup = (
        "<main>"
        "<h2>Region: Global</h2><h3>Tier: Standard</h3>"
        + "<table><caption>USD per 1M tokens</caption>"
        "<thead><tr><th>Model</th><th>Rates</th></tr></thead>"
        "<tbody>" + row(COMPOUND) + "</tbody></table>"
        + "<table><caption>USD per 1M tokens</caption>"
        "<thead><tr><th>Model</th><th>Rates</th></tr></thead>"
        "<tbody>" + row(COMPOUND, model="Model Beta") + "</tbody></table>"
        "</main>"
    )
    main = html.fromstring(markup)
    a = extract_pricing_evidence(main, SOURCE_URLS["openai_api_pricing"],
                                 "openai_api_pricing", table_offset=0,
                                 table_limit=1)
    b = extract_pricing_evidence(main, SOURCE_URLS["openai_api_pricing"],
                                 "openai_api_pricing", table_offset=1,
                                 table_limit=1)
    assert a["pricing_observation_count"] == b["pricing_observation_count"] == 3
    assert a["pricing_table_window_selected_indices"] == [0]
    assert b["pricing_table_window_selected_indices"] == [1]
    assert a["pricing_inventory_complete"] is False
    assert b["pricing_inventory_complete"] is False
    assert not (
        set(o["observation_id"] for o in a["pricing_observations"])
        & set(o["observation_id"] for o in b["pricing_observations"])
    )
