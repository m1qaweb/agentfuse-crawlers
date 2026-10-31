"""P04 pricing regressions: publisher-like synthetic fixtures, never factual prices."""

import copy
from decimal import Decimal

import pytest
from scrapy.http import HtmlResponse

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.pricing_evidence import (
    MAX_SELECTED_TABLES, MAX_ITEM_BYTES, compact_pricing_record, serialized_size,
)
from agentfuse_crawlers.rate_units import (
    analyze_cell, detect_currency, detect_unit, detect_tier, detect_region,
)
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.spiders.official import PricingSpider
from scripts.compare_exports import compare, review_queue

URL = "https://developers.openai.com/api/docs/pricing"
SID = "openai_api_pricing"


def table(rows, *, scope="Region: Global", tier="Tier: Standard",
          caption="USD per 1M tokens", columns=None):
    cols = columns or ("Model", "Input price", "Output price")
    return (
        f"<h2>{scope}</h2><h3>{tier}</h3><table>"
        f"<caption>{caption}</caption><thead><tr>"
        + "".join(f"<th>{x}</th>" for x in cols) + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<th>{value}</th>" if idx == 0
                              else f"<td>{value}</td>"
                              for idx, value in enumerate(row)) + "</tr>"
            for row in rows
        ) + "</tbody></table>"
    )


def extract(markup, *, source_id=SID, url=URL):
    return extract_evidence(
        "<html><head><title>Pricing</title></head><body><main>"
        + markup + "</main></body></html>",
        url, category="pricing", source_id=source_id,
    )


def base_model_rates():
    return table([("Model Alpha", "$1.50", "$4.50"),
                  ("Model Beta", "$0.15", "$0.60")])


def test_independent_model_input_output_rates_are_unverified_but_scoped():
    ev = extract(base_model_rates())
    assert ev["pricing_evidence_schema"] == "1.0"
    assert ev["pricing_table_total"] == ev["pricing_table_relevant"] == 1
    assert ev["pricing_inventory_complete"] is True
    assert ev["pricing_comparable_candidate_count"] == 4
    rates = {(o["model_or_service"], o["price_dimension"]): o
             for o in ev["pricing_observations"]}
    one = rates[("Model Alpha", "input")]
    assert one["normalized_amount_decimal"] == "1.50"
    assert one["currency"] == "USD"
    assert one["billing_unit"] == "per_1m_tokens"
    assert one["region"] == "Global"
    assert one["tier_or_plan"] == "Standard"
    assert one["source_url"] == URL and one["source_evidence_sha256"]
    assert one["approved_for_advisor"] is False
    assert rates[("Model Alpha", "output")]["normalized_amount_decimal"] == "4.50"


@pytest.mark.parametrize("changes,missing", [
    ({"caption": "per 1M tokens"}, "missing_explicit_currency"),
    ({"scope": "Pricing"}, "missing_explicit_region"),
    ({"tier": "Pricing"}, "missing_explicit_tier_or_plan"),
    ({"caption": "USD billing"}, "missing_explicit_billing_unit"),
])
def test_missing_required_dimensions_prevents_numeric_normalization(changes, missing):
    ev = extract(table([("Model Alpha", "$1.50", "$4.50")], **changes))
    assert ev["pricing_comparable_candidate_count"] == 0
    assert all(o["normalized_amount_decimal"] is None for o in ev["pricing_observations"])
    assert all(missing in o["normalization_blockers"] for o in ev["pricing_observations"])


def test_gemini_like_conditional_prices_in_one_cell_are_not_single_rate():
    markup = (
        "<h2>Gemini Example Model</h2>"
        "<table><caption>Region: Global</caption><thead><tr>"
        "<th>Dimension</th><th>Free Tier</th>"
        "<th>Paid Tier, per 1M tokens in USD</th></tr></thead>"
        "<tbody><tr><th>Input price</th><td>Not available</td>"
        "<td>$2.00 through November 30, 2026. "
        "$4.00 starting December 1, 2026.</td></tr></tbody></table>"
    )
    ev = extract(markup, source_id="gemini_api_pricing",
                 url="https://ai.google.dev/gemini-api/docs/pricing")
    assert ev["pricing_inventory_complete"] is True
    assert ev["pricing_comparable_candidate_count"] == 0
    assert any(o["price_state"] == "multiple_or_time_dependent"
               for o in ev["pricing_observations"])


def test_gemini_model_scope_from_heading_when_row_is_dimension():
    markup = (
        "<h2>Gemini Example Model</h2>"
        "<table><caption>Region: Global; USD per 1M tokens</caption>"
        "<thead><tr><th>Dimension</th><th>Paid Tier</th></tr></thead>"
        "<tbody><tr><th>Input price</th><td>$2.00</td></tr>"
        "<tr><th>Output price</th><td>$10.00</td></tr></tbody></table>"
    )
    ev = extract(markup, source_id="gemini_api_pricing",
                 url="https://ai.google.dev/gemini-api/docs/pricing")
    assert ev["pricing_comparable_candidate_count"] == 2
    assert {o["model_or_service"] for o in ev["pricing_observations"]} == {
        "Gemini Example Model"}
    assert {o["price_dimension"] for o in ev["pricing_observations"]} == {
        "input", "output"}


def test_oracle_generic_price_list_scope_does_not_become_genai():
    markup = (
        table([("Compute A", "$0.25", "$0.50")],
              scope="Data Science Jobs")
        + table([("Cohere Example", "$0.10", "$0.30")],
                scope="OCI Generative AI Region: Global")
    )
    ev = extract(markup, source_id="oracle_oci_generative_ai_pricing",
                 url="https://www.oracle.com/cloud/price-list/")
    assert ev["pricing_table_total"] == 2
    assert ev["pricing_table_relevant"] == 1
    assert all(o["model_or_service"] == "Cohere Example"
               for o in ev["pricing_observations"])


def test_oracle_without_explicit_product_scope_needs_review():
    ev = extract(table([("Compute", "$0.10", "$0.40")],
                       scope="Data Science Jobs"),
                 source_id="oracle_oci_generative_ai_pricing",
                 url="https://www.oracle.com/cloud/price-list/")
    assert ev["pricing_product_scope_unresolved"] is True
    ev["word_count"] = 100
    assert assess_capture("pricing", ev, "Official pricing details " * 60) == (
        "needs_review", "pricing_product_scope_unresolved")


def test_relevant_table_after_40_irrelevant_tables_is_not_missed():
    irrelevant = (
        "<table><tr><th>Service</th><th>Description</th></tr>"
        "<tr><td>Compute</td><td>Architecture guide</td></tr></table>"
    ) * 53
    ev = extract(irrelevant + base_model_rates())
    assert ev["pricing_table_total"] == 54
    assert ev["pricing_table_relevant"] == 1
    assert ev["pricing_inventory_complete"] is True
    assert ev["pricing_comparable_candidate_count"] == 4


def test_selected_table_cap_is_explicit_instead_of_silent():
    ev = extract("".join(
        table([(f"Model{i}", "$1.00", "$2.00")])
        for i in range(MAX_SELECTED_TABLES + 3)
    ))
    assert ev["pricing_table_selected"] == MAX_SELECTED_TABLES
    assert ev["pricing_table_omitted_relevant"] == 3
    assert ev["pricing_inventory_complete"] is False
    ev["word_count"] = 100
    assert assess_capture("pricing", ev, "Pricing table data " * 65) == (
        "partial_capture", "pricing_table_inventory_incomplete")


def test_large_table_more_than_250_rows_must_be_partial():
    ev = extract(table(
        [(f"Model{i}", "$1.20", "$4.80") for i in range(270)]
    ))
    assert ev["pricing_table_rows_incomplete"] is True
    assert ev["pricing_inventory_complete"] is False


def test_raw_table_excerpt_is_not_claimed_complete_when_rates_were_scanned():
    ev = extract(table(
        [(f"Model{i}", "$0.10", "$0.20") for i in range(100)]
    ))
    raw = ev["pricing_legacy_table_excerpts"][0]
    assert raw["raw_excerpt_only"] is True
    assert raw["rows_truncated"] is True
    assert len(raw["rows"]) <= 12
    assert ev["pricing_inventory_complete"] is True
    assert ev["pricing_observation_count"] == 200


def test_non_numeric_states_preserved_independently():
    ev = extract(table([("Model A", "Free", "Contact sales"),
                        ("Model B", "Not available", "Custom pricing")]))
    assert {o["price_state"] for o in ev["pricing_observations"]} == {
        "free", "contact_sales", "not_available", "custom"}
    assert ev["pricing_comparable_candidate_count"] == 0


def test_row_and_col_span_headers_do_not_duplicate_rates():
    markup = (
        "<h2>Region: Global</h2><h3>Tier: Standard</h3>"
        "<table><caption>USD per 1M tokens</caption><thead>"
        '<tr><th rowspan="2">Model</th><th colspan="2">Rates</th></tr>'
        "<tr><th>Input price</th><th>Output price</th></tr>"
        "</thead><tbody><tr><th>Model One</th>"
        "<td>$1.00</td><td>$3.00</td></tr></tbody></table>"
    )
    ev = extract(markup)
    assert ev["pricing_inventory_complete"] is True
    assert ev["pricing_observation_count"] == 2
    assert {o["price_dimension"] for o in ev["pricing_observations"]} == {
        "input", "output"}


def test_unresolved_footnote_blocks_clean_rate():
    ev = extract(table([("Model Alpha", "$1.50*", "$4.50")]))
    inp = [o for o in ev["pricing_observations"] if o["price_dimension"] == "input"]
    assert len(inp) == 1
    assert "unresolved_footnote" in inp[0]["normalization_blockers"]


def test_distinct_batch_cached_and_plain_rates():
    ev = extract(table(
        [("Model A", "$1.00", "$2.00")],
        columns=("Model", "Batch input price", "Cached input price"),
    ))
    assert {o["price_dimension"] for o in ev["pricing_observations"]} == {
        "batch_input", "cached_input"}


def test_mixed_input_and_output_heading_is_ambiguous():
    row = analyze_cell(
        "$1.00", model_label="Model Alpha",
        column_header="Input and Output price", row_header="Model Alpha",
        table_context="Region: Global",
        table_caption="USD per 1M tokens; Tier: Standard",
    )
    assert row["price_dimension"] is None
    assert row["normalized_amount_decimal"] is None


@pytest.mark.parametrize("source,expected", [
    ("USD per 1M tokens", "per_1m_tokens"),
    ("USD per 1M characters", "per_1m_characters"),
    ("per 1k tokens", "per_1k_tokens"),
    ("per OCPU per hour", "per_ocpu_hour"),
    ("per vCPU per hour", "per_vcpu_hour"),
    ("per GPU per hour", "per_gpu_hour"),
    ("per seat / month", "per_user_month"),
    ("per request", "per_request"),
    ("per hour", "per_hour"),
    ("token prices are listed", None),
])
def test_billing_units_never_conflate_distinct_denominators(source, expected):
    assert detect_unit(source) == expected


def test_currency_region_tier_require_explicit_evidence():
    assert detect_currency("$1.50") is None
    assert detect_currency("$1.50", "All prices USD") == "USD"
    assert detect_currency("€1.50") == "EUR"
    assert detect_currency("¥1.50") is None
    assert detect_currency("$1.50", "USD EUR") is None
    assert detect_region("Region: Global") == "Global"
    assert detect_region("All regions") is None
    assert detect_tier("Tier: Standard") == "Standard"


@pytest.mark.parametrize("raw", [
    "$2.00 through Nov 30, then $4.00 starting Dec 1",
    "$2.00 starting December 1, 2026",
    "$2.00 discounted trial",
    "$2.00 up to 10M tokens",
])
def test_multiple_or_time_dependent_prices_cannot_normalize(raw):
    info = analyze_cell(
        raw, model_label="Model Alpha", column_header="Input price",
        row_header="Model Alpha", table_context="Region: Global",
        table_caption="Tier: Standard; USD per 1M tokens",
    )
    assert info["normalized_amount_decimal"] is None
    assert info["comparable_candidate"] is False


def test_per_user_month_plan_rate_never_becomes_token_rate():
    row = analyze_cell(
        "USD 12.00", model_label="Business plan",
        column_header="Price per seat/month", row_header="Business plan",
        table_context="Region: Global; Plan: Business",
        table_caption="Subscriptions",
    )
    assert row["billing_unit"] == "per_user_month"
    assert row["price_dimension"] == "subscription"
    assert row["normalized_amount_decimal"] == "12.00"


def test_200_synthetic_price_rows_retain_exact_decimals_without_float_rounding():
    rows = [
        (f"Model{i:03d}", "$" + f"{i/100:.2f}", "$" + f"{i/50:.2f}")
        for i in range(1, 101)
    ]
    ev = extract(table(rows))
    assert ev["pricing_inventory_complete"] is True
    assert ev["pricing_observation_count"] == 200
    assert ev["pricing_comparable_candidate_count"] == 200
    for i in range(1, 101):
        matching = [x for x in ev["pricing_observations"]
                    if x["model_or_service"] == f"Model{i:03d}"
                    and x["price_dimension"] == "input"]
        assert len(matching) == 1
        assert Decimal(matching[0]["normalized_amount_decimal"]) == Decimal(
            f"{i/100:.2f}"
        )


def test_zyte_item_budget_preserves_typed_candidates_and_source_identity():
    ev = extract(table(
        [(f"Model{i}", "$1.50", "$3.50") for i in range(100)]
    ))
    row = dict(ev, source_id=SID, source_url=URL, category="pricing",
               status="captured", requested_cohort="proven",
               approved_for_advisor=False)
    row.pop("text")
    full = "Historic cloud price list details. " * 25000
    item = compact_pricing_record(row, full)
    assert serialized_size(item) <= MAX_ITEM_BYTES
    assert item["text_total_characters"] == len(full)
    assert len(item["text"]) <= 16000
    assert item["pricing_inventory_complete"] is True
    assert len(item["pricing_observations"]) == 200
    assert item["approved_for_advisor"] is False


def test_prose_only_price_needs_review_but_raw_evidence_is_kept():
    ev = extract("<p>" + ("Price per million tokens $1.50, subject to terms. " * 40)
                 + "</p>")
    assert ev["pricing_observation_count"] == 0
    assert assess_capture("pricing", ev, ev["text"]) == (
        "needs_review", "pricing_no_structured_rate_evidence")


def _snapshot(ev):
    return {
        "source_id": SID, "source_url": URL, "provider": "OpenAI",
        "category": "pricing", "status": "captured",
        "content_sha256": ev["content_sha256"],
        "pricing_evidence_schema": "1.0",
        "pricing_inventory_complete": ev["pricing_inventory_complete"],
        "pricing_comparable_candidate_count": ev["pricing_comparable_candidate_count"],
        "pricing_observations": ev["pricing_observations"], "sections": [],
        "approved_for_advisor": False,
    }


def test_price_changes_require_same_model_tier_region_and_unit():
    before = _snapshot(extract(table([("Model Alpha", "$1.00", "$3.00")])))
    after = _snapshot(extract(table([("Model Alpha", "$1.50", "$3.00")])))
    assert compare({SID: after}, {})[0]["change_type"] == "new_baseline"
    assert review_queue({SID: after}, {}, compare({SID: after}, {})) == []
    q = review_queue({SID: after}, {SID: before},
                     compare({SID: after}, {SID: before}))
    assert [x["change_type"] for x in q] == ["rate_value_changed_candidate"]
    assert q[0]["previous_amount_decimal"] == "1.00"
    assert q[0]["current_amount_decimal"] == "1.50"
    assert q[0]["price_dimension"] == "input"
    assert q[0]["approved_for_advisor"] is False


def test_tier_or_region_difference_does_not_become_price_increase():
    old = _snapshot(extract(table([("Model Alpha", "$1.00", "$3.00")])))
    now = _snapshot(extract(table(
        [("Model Alpha", "$1.50", "$3.00")],
        scope="Region: US East", tier="Tier: Enterprise",
    )))
    q = review_queue({SID: now}, {SID: old},
                     compare({SID: now}, {SID: old}))
    assert not any(x["change_type"] == "rate_value_changed_candidate" for x in q)


def test_unknown_currency_or_partial_table_does_not_generate_rate_alert():
    old = _snapshot(extract(table(
        [("Model Alpha", "$1.00", "$3.00")], caption="per 1M tokens",
    )))
    now = _snapshot(extract(table(
        [("Model Alpha", "$9.00", "$3.00")], caption="per 1M tokens",
    )))
    old["status"] = now["status"] = "needs_review"
    q = review_queue({SID: now}, {SID: old},
                     compare({SID: now}, {SID: old}))
    assert not any("rate_" in x["change_type"] for x in q)
    now = copy.deepcopy(old)
    now["pricing_inventory_complete"] = False
    now["status"] = "partial_capture"
    assert review_queue({SID: now}, {SID: old}, compare({SID: now}, {SID: old})) == []


def test_legacy_generic_html_extract_unmodified_without_pricing_category():
    raw = extract_evidence(base_model_rates(), URL)
    assert "pricing_evidence_schema" not in raw
    assert raw["tables"][0]["table_id"] == "table-1"


def test_pricing_spider_emits_only_unapproved_source_snapshot():
    source = {"id": SID, "provider": "OpenAI",
              "category": "pricing", "url": URL}
    spider = PricingSpider(source_ids=SID)
    markup = "<html><body><main>" + base_model_rates() + (
        "<p>Official source content only, requires human price validation.</p>" * 30
    ) + "</main></body></html>"
    response = HtmlResponse(url=URL, status=200, body=markup.encode("utf-8"),
                            headers={"Content-Type": "text/html"}, encoding="utf-8")
    item = list(spider.parse_page(response, source))[0]
    assert item["status"] == "captured"
    assert item["pricing_comparable_candidate_count"] == 4
    assert item["review_status"] == "unverified"
    assert item["approved_for_advisor"] is False
    assert serialized_size(item) <= MAX_ITEM_BYTES




def test_conflicting_currency_and_region_fails_closed():
    common = dict(model_label="Model Alpha", column_header="Input price",
                  row_header="Model Alpha")
    for ctx, caption in [
        ("Region: Global; Tier: Standard", "USD EUR per 1M tokens"),
        ("Region: Global; Region: US East; Tier: Standard", "USD per 1M tokens"),
        ("Region: Global; Tier: Standard; Tier: Paid", "USD per 1M tokens"),
        ("Region: Global; Tier: Standard", "USD per 1M tokens; per user/month"),
    ]:
        row = analyze_cell("$1.50", table_context=ctx,
                           table_caption=caption, **common)
        assert row["normalized_amount_decimal"] is None
        assert row["comparable_candidate"] is False


def test_unrelated_description_containing_price_word_is_not_pricing_table():
    markup = (
        "<table><tr><th>Service</th><th>Description</th></tr>"
        "<tr><td>Analytics</td><td>This is not a price quote.</td></tr></table>"
        + base_model_rates()
    )
    ev = extract(markup)
    assert ev["pricing_table_relevant"] == 1



@pytest.mark.parametrize("header,expected", [
    ("Fast input price", "fast_input"),
    ("Fast output price", "fast_output"),
    ("Ultra-fast input price", "ultrafast_input"),
    ("Ultrafast output price", "ultrafast_output"),
    ("Long-context input price", "long_context_input"),
    ("Extended context output price", "long_context_output"),
    ("Batch input price", "batch_input"),
    ("Batch output price", "batch_output"),
    ("Cached input price", "cached_input"),
    ("Cache write price", "cache_write"),
])
def test_special_pricing_modes_have_distinct_rate_dimensions(header, expected):
    row = analyze_cell(
        "$1.50", model_label="Model Alpha", column_header=header,
        row_header="Model Alpha", table_context="Region: Global",
        table_caption="USD per 1M tokens; Tier: Standard",
    )
    assert row["price_dimension"] == expected
    assert row["normalized_amount_decimal"] == "1.50"


@pytest.mark.parametrize("caption", [
    "USD per 1M tokens; Tier: Standard; effective November 30, 2026",
    "USD per 1M tokens; Tier: Standard; promotional pricing",
    "USD per 1M tokens; Tier: Standard; discounted rate",
])
def test_caption_effective_dates_and_promotions_block_rate_comparability(caption):
    row = analyze_cell(
        "$1.50", model_label="Model Alpha",
        column_header="Input price", row_header="Model Alpha",
        table_context="Region: Global", table_caption=caption,
    )
    assert row["normalized_amount_decimal"] is None
    assert "time_dependent_or_promotional_price" in row["normalization_blockers"]


def test_any_table_footnote_requires_manual_resolution():
    row = analyze_cell(
        "$1.50", model_label="Model Alpha",
        column_header="Input price", row_header="Model Alpha",
        table_context="Region: Global",
        table_caption="USD per 1M tokens; Tier: Standard",
        footnotes="* Volume discounts apply to some prices",
    )
    assert row["normalized_amount_decimal"] is None
    assert "unresolved_footnote" in row["normalization_blockers"]
