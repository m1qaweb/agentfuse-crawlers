"""Source-bound separation of Perplexity tariff cells from cost examples.

Recognize only the exact retained heading/header layouts. Ambiguous or changed
layouts fall back to the generic parser; exclusion never verifies a tariff.
"""
import re

PERPLEXITY_SCOPE = (
    "perplexity_pricing", "https://docs.perplexity.ai/docs/getting-started/pricing",
)
DEFAULT_PRICING_PARSER_REVISION = "evidence_quote_v7_deepseek_transposed_context"
PERPLEXITY_PRICING_REVISION = "evidence_quote_v8_perplexity_non_tariff"


def pricing_parser_revision(source_id, source_url):
    return (PERPLEXITY_PRICING_REVISION
            if (source_id, source_url) == PERPLEXITY_SCOPE
            else DEFAULT_PRICING_PARSER_REVISION)


_DESCRIPTION_LAYOUTS = {
    ("View Agent API Model Pricing > Tool Pricing", ("Tool", "Price", "Description")),
    ("Search API Pricing", ("API", "Price per 1K requests", "Description")),
}
_SEARCH_EXAMPLE = ("Search API Pricing", ("Request", "Billing units", "Cost"))
_COMPONENT_EXAMPLES = {
    "Agent API Web Search": frozenset({"Input tokens", "Output tokens", "web_search", "Total"}),
    "Agent API Research Effort Level": frozenset({
        "Model input tokens", "Model output tokens", "web_search (Fast Search)",
        "fetch_url (base fee)", "Total",
    }),
}
_SCENARIO = re.compile(r"(?:One POST /search with .+|[0-9][0-9,]* successful (?:standard|Fast Search) requests in a month)")
_PLAIN_DOLLAR = re.compile(r"\$[0-9]+(?:\.[0-9]+)?")


def non_tariff_reason(*, source_id, source_url, heading_context, headers, row, column):
    """Classify a specific cell; caller validates a complete, unmerged row.

    Row-local recognition is intentional: same-snapshot bounded row replay
    must classify a cell identically even when other data rows are removed.
    """
    if ((source_id, source_url) != PERPLEXITY_SCOPE or not headers
            or len(row) != len(headers) or not 0 < column < len(row)):
        return None
    layout = heading_context, tuple(headers)
    if layout in _DESCRIPTION_LAYOUTS and column == 2:
        return "explanatory_description_not_independent_tariff"
    if layout == _SEARCH_EXAMPLE and column == 2 and _SCENARIO.fullmatch(row[0]):
        return "worked_request_cost_not_independent_tariff"
    if (tuple(headers) == ("Component", "Cost") and column == 1
            and row[0] in _COMPONENT_EXAMPLES.get(heading_context, ())
            and _PLAIN_DOLLAR.fullmatch(row[column])):
        return "worked_component_cost_not_independent_tariff"
    return None
