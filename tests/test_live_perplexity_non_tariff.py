"""Synthetic regressions for the retained Perplexity non-tariff layouts."""
from lxml import html
import pytest

from agentfuse_crawlers.pricing_evidence import extract_pricing_evidence
from agentfuse_crawlers.pricing_perplexity import (
    DEFAULT_PRICING_PARSER_REVISION, PERPLEXITY_PRICING_REVISION,
    PERPLEXITY_SCOPE, non_tariff_reason, pricing_parser_revision,
)

SID, URL = PERPLEXITY_SCOPE


def table(headers, rows):
    return ("<table><thead><tr>" + "".join("<th>" + h + "</th>" for h in headers)
            + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join("<td>" + v + "</td>" for v in row)
                      + "</tr>" for row in rows) + "</tbody></table>")


def extract(markup, sid=SID, url=URL, **kwargs):
    return extract_pricing_evidence(
        html.fromstring("<main>" + markup + "</main>"), url, sid, **kwargs)


TOOL = "<h2>View Agent API Model Pricing</h2><h3>Tool Pricing</h3>"
TOOL_HEADERS = ("Tool", "Price", "Description")
TOOL_ROWS = (("example_tool", "$0.03 per invocation", "Example $30 per 1,000 invocations"),)


def test_description_is_not_an_independent_tariff_but_raw_evidence_survives():
    result = extract(TOOL + table(TOOL_HEADERS, TOOL_ROWS))
    assert result["pricing_parser_revision"] == PERPLEXITY_PRICING_REVISION
    assert result["pricing_non_tariff_cells_excluded"] == 1
    assert result["pricing_price_cells_examined"] == result["pricing_observation_total_detected"] == 1
    assert result["pricing_observation_count"] == 1
    assert result["pricing_observations"][0]["raw_displayed_price"] == "$0.03 per invocation"
    assert result["pricing_observations"][0]["approved_for_advisor"] is False
    assert result["pricing_legacy_table_excerpts"][0]["rows"][1][2]["text"] == TOOL_ROWS[0][2]
    assert result["pricing_table_evidence"][0]["non_tariff_cells_excluded"] == {
        "explanatory_description_not_independent_tariff": 1}
    assert result["pricing_publisher_completeness_verified"] is False
    assert result["approved_for_advisor"] is False


def test_request_examples_are_distinct_from_actual_rate_table():
    result = extract(
        "<h2>Search API Pricing</h2>"
        + table(("API", "Price per 1K requests", "Description"),
                (("Example API", "$3.00", "Synthetic explanation"),))
        + table(("Request", "Billing units", "Cost"),
                (("One POST /search with an example query", "1", "$3.00 / 1000 = $0.003"),
                 ("2,000 successful standard requests in a month", "2000", "$6.00")))
    )
    assert result["pricing_non_tariff_cells_excluded"] == 2
    assert result["pricing_observation_count"] == 1
    assert result["pricing_observations"][0]["raw_displayed_price"] == "$3.00"
    assert result["pricing_table_evidence"][1]["non_tariff_cells_excluded"] == {
        "worked_request_cost_not_independent_tariff": 2}


@pytest.mark.parametrize("context,row_label", [
    ("Agent API Web Search", "Input tokens"),
    ("Agent API Research Effort Level", "Model input tokens"),
])
def test_known_example_component_does_not_become_tariff_in_row_slice(context, row_label):
    # No dependency on a trailing Total row, which a row-window view may omit.
    result = extract("<h2>" + context + "</h2>"
                     + table(("Component", "Cost"), ((row_label, "$0.03"),)))
    assert result["pricing_observation_count"] == 0
    assert result["pricing_non_tariff_cells_excluded"] == 1
    assert result["pricing_legacy_table_excerpts"][0]["rows"][1][1]["text"] == "$0.03"
    assert result["approved_for_advisor"] is False


@pytest.mark.parametrize("markup,sid,url", [
    (TOOL + table(TOOL_HEADERS, TOOL_ROWS), "other_pricing", URL),
    (TOOL + table(TOOL_HEADERS, TOOL_ROWS), SID, URL + "/other"),
    ("<h2>Different layout</h2>" + table(TOOL_HEADERS, TOOL_ROWS), SID, URL),
    (TOOL + table(("Tool", "Price", "Extra price"), TOOL_ROWS), SID, URL),
    ("<h2>Agent API Web Search</h2>"
     + table(("Component", "Cost"), (("Input tokens", "$0.03 per 1M tokens"),)), SID, URL),
    ("<h2>Search API Pricing</h2>"
     + table(("Request", "Billing units", "Cost"), (("Unknown rate", "1", "$0.03"),)), SID, URL),
])
def test_unknown_layout_source_or_unit_falls_back(markup, sid, url):
    result = extract(markup, sid, url)
    assert result["pricing_non_tariff_cells_excluded"] == 0
    assert result["pricing_observation_count"] >= 1
    assert result["pricing_parser_revision"] == pricing_parser_revision(sid, url)
    if (sid, url) != PERPLEXITY_SCOPE:
        assert result["pricing_parser_revision"] == DEFAULT_PRICING_PARSER_REVISION


def test_merged_rows_not_silently_classified():
    result = extract(TOOL + "<table><thead><tr><th>Tool</th><th>Price</th>"
                     "<th>Description</th></tr></thead><tbody>"
                     "<tr><td>example</td><td colspan='2'>$0.03</td></tr>"
                     "</tbody></table>")
    assert result["pricing_non_tariff_cells_excluded"] == 0
    assert result["pricing_observation_count"] == 1


def test_unknown_row_coordinates_are_not_classified():
    for col in (-1, 0, 3):
        assert non_tariff_reason(source_id=SID, source_url=URL,
                                 heading_context="View Agent API Model Pricing > Tool Pricing",
                                 headers=TOOL_HEADERS, row=TOOL_ROWS[0], column=col) is None
