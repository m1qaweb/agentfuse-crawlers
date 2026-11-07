"""P23D4: specific archived Cloudflare token-cell semantics, review-only.

These synthetic HTML examples imitate a structural form observed in the
original Nov 4 user-supplied Zyte Items, not source-owned gold labels.
No publisher requests, currency inference or advisor approval.
"""

from copy import deepcopy

import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.sources import load_sources
from scripts.assemble_pricing_windows import assemble_source_windows
from scripts.compare_exports import _compatible_source, compare, review_queue

CF = next(s for s in load_sources()
          if s["id"] == "cloudflare_workers_ai_pricing")
OTHER = next(s for s in load_sources() if s["id"] == "openai_api_pricing")
TWO = "$0.027 per M input tokens $0.201 per M output tokens"
THREE = ("$0.440 per M input tokens "
         "$0.014 per M cached input tokens "
         "$1.320 per M output tokens")


def capture(rate=TWO, *, sid=CF["id"], url=CF["url"],
            header="Price in Tokens", model="@cf/acme/demo-1",
            caption="", footnote=""):
    table = (
        "<html><head><title>Pricing</title></head><body><main>"
        "<h2>LLM model pricing</h2><table>"
        + ("<caption>" + caption + "</caption>" if caption else "")
        + "<thead><tr><th>Model</th><th>" + header + "</th></tr></thead>"
        "<tbody><tr><th><strong>" + model + "</strong></th>"
        "<td>" + rate + "</td></tr></tbody>"
        + ("<tfoot><tr><td colspan='2'>" + footnote +
           "</td></tr></tfoot>" if footnote else "")
        + "</table></main></body></html>"
    )
    return extract_evidence(table, url, category="pricing", source_id=sid)


@pytest.mark.parametrize("raw,dims,amounts", [
    (TWO, ["input", "output"], ["0.027", "0.201"]),
    (THREE, ["input", "cached_input", "output"],
     ["0.440", "0.014", "1.320"]),
])
def test_source_exact_literal_token_components_are_distinct_unapproved_rows(
        raw, dims, amounts):
    data = capture(raw)
    assert data["pricing_parser_revision"] == (
        "evidence_quote_v6_cloudflare_literal_components"
    )
    assert data["pricing_inline_adapter_family"] == "request_credit_metering"
    assert data["pricing_price_cells_examined"] == 1
    assert data["pricing_inline_rate_cells_split"] == 1
    assert data["pricing_cloudflare_explicit_token_cells_split"] == 1
    assert data["pricing_inline_component_extra_observations"] == len(dims) - 1
    assert data["pricing_observation_total_detected"] == len(dims)
    assert data["pricing_observation_count"] == len(dims)
    assert data["pricing_inline_multi_amount_cells_unresolved"] == 0
    assert data["pricing_inventory_complete"] is True
    assert data["pricing_comparable_candidate_count"] == 0
    assert data["pricing_review_quote_candidate_count"] == 0
    assert data["approved_for_advisor"] is False
    rows = data["pricing_observations"]
    assert [x["price_dimension"] for x in rows] == dims
    assert [x["observed_single_amount_decimal"] for x in rows] == amounts
    assert len({x["observation_id"] for x in rows}) == len(rows)
    assert len({x["source_evidence_sha256"] for x in rows}) == len(rows)
    for idx, row in enumerate(rows):
        assert row["raw_parent_cell_text"] == raw
        assert row["inline_component_count"] == len(dims)
        assert row["inline_component_index"] == idx
        assert row["model_or_service"] == "@cf/acme/demo-1"
        assert row["billing_unit"] == "per_1m_tokens"
        assert row["currency"] is None   # A dollar symbol is not USD evidence.
        assert row["region"] is None and row["tier_or_plan"] is None
        assert row["currency_attribution"] == "unqualified_symbol"
        assert row["price_state"] == "numeric_candidate"
        assert row["normalized_amount_decimal"] is None
        assert row["review_quote_amount_decimal"] is None
        assert row["review_quote_candidate"] is False
        assert row["comparable_candidate"] is False
        assert row["approved_for_advisor"] is False
        assert row["source_product_owner_verified"] is False
        assert row["family_adapter_candidate_only"] is True
        assert row["review_status"] == "unverified"
        assert row["evidence_kind"] == (
            "structured_table_labeled_inline_component"
        )
        assert row["inline_component_parent_identity_review_status"] == (
            "unverified_cloudflare_literal_token_component"
        )
        assert row["billing_unit_literal"].startswith("per M ")
        assert "cloudflare_literal_tokens_require_independent_publisher_gold" in (
            row["normalization_blockers"]
        )
        assert "missing_explicit_currency" in row["normalization_blockers"]


@pytest.mark.parametrize("raw", [
    "$0.011 / 1,000 Neurons",
    "2457 neurons per M input tokens 18252 neurons per M output tokens",
    "$0.027 per M input tokens",
    "$0.027 per M input tokens $0.201",
    "$0.027 per M input tokens $0.02 per M input tokens",
    "$0.027 per M output tokens $0.201 per M input tokens",
    "$0.027 per M input tokens $0.11 per M cached input tokens",
    "$0.027 per M input tokens $0.01 per M output tokens 10% discount",
    "$0.027 per M input tokens $0.201 per M output tokens starting Dec 2026",
    "$0.027 per M input tokens $0.201 per M output tokens*",
    "$0.027 per 1k input tokens $0.201 per 1k output tokens",
    "$0.027 per M input tokens $0.201 per M output tokens $0.10",
    "$0.027 per M input tokens $0.01 per M cached input tokens "
        "$0.201 per M output tokens $0.005 per M image tokens",
    "$0.027 per M input tokens / $0.201 per M output tokens",
])
def test_neuron_conditional_unlabeled_reversed_or_unrecognized_rates_not_split(raw):
    data = capture(raw)
    assert data["pricing_inline_rate_cells_split"] == 0
    assert data["pricing_cloudflare_explicit_token_cells_split"] == 0
    assert len(data["pricing_observations"]) == 1
    assert data["pricing_comparable_candidate_count"] == 0
    assert data["approved_for_advisor"] is False


@pytest.mark.parametrize("overrides", [
    {"header": "Price in Neurons"},
    {"header": "Pricing"},
    {"model": "Workers Paid"},
    {"model": "other/model"},
    {"caption": "USD per 1k tokens"},
    {"footnote": "*Different batch tier rates apply"},
    {"sid": OTHER["id"], "url": OTHER["url"]},
    {"sid": CF["id"], "url": "https://evil.invalid/pricing"},
])
def test_adapter_never_leaks_to_wrong_owner_column_unit_or_footnote(overrides):
    data = capture(TWO, **overrides)
    assert data["pricing_cloudflare_explicit_token_cells_split"] == 0
    assert data["pricing_inline_rate_cells_split"] == 0
    assert data["pricing_comparable_candidate_count"] == 0
    assert data["approved_for_advisor"] is False


def test_two_distinct_models_get_stable_independent_unapproved_component_ids():
    first = capture(THREE)
    repeated = capture(THREE)
    assert [x["observation_id"] for x in first["pricing_observations"]] == [
        x["observation_id"] for x in repeated["pricing_observations"]
    ]
    assert len(set(x["observation_id"]
                   for x in first["pricing_observations"])) == 3


def _as_window(data, job="883514/3/990001"):
    return {
        **data, "source_id": CF["id"], "source_url": CF["url"],
        "category": "pricing", "provider": CF["provider"],
        "zyte_job_id": job,
        "manifest_sha256": "a" * 64,
        "source_registry_sha256": "b" * 64,
        "deployment_revision": "c" * 64,
        "http_status": 200, "status": "captured",
        "review_status": "unverified", "approved_for_advisor": False,
    }


def test_offline_window_assembly_accepts_bound_review_only_inline_components():
    source = _as_window(capture(THREE))
    output = assemble_source_windows([source])
    assert output["pricing_parser_revision"] == (
        "evidence_quote_v6_cloudflare_literal_components"
    )
    assert output["recognized_table_window_coverage_complete"] is True
    assert output["price_observation_count"] == 3
    assert output["rate_comparison_eligible"] is False
    assert output["approved_for_advisor"] is False
    assert all(x["comparable_candidate"] is False
               for x in output["price_observations"])


@pytest.mark.parametrize("mutation", [
    {"inline_component_count": 5},
    {"inline_component_index": 99},
    {"inline_component_evidence_sha256": "invalid"},
    {"raw_parent_cell_text": ""},
    {"comparable_candidate": True},
    {"review_quote_candidate": True},
    {"normalized_amount_decimal": "0.027"},
])
def test_assembled_inline_components_fail_closed_if_tampered(mutation):
    row = _as_window(capture(TWO))
    row["pricing_observations"][0].update(mutation)
    with pytest.raises(ValueError, match="Unsafe or unbound inline"):
        assemble_source_windows([row])


def test_v5_to_v6_new_pricing_baseline_never_looks_like_vendor_price_increase():
    current = _as_window(capture(TWO))
    past = deepcopy(current)
    past["pricing_parser_revision"] = "evidence_quote_v5_inline_labeled_components"
    assert not _compatible_source(current, past)
    assert compare({CF["id"]: current}, {CF["id"]: past})[0][
        "change_type"
    ] != "page_text_changed"
    assert review_queue(
        {CF["id"]: current}, {CF["id"]: past},
        compare({CF["id"]: current}, {CF["id"]: past}),
    ) == []
