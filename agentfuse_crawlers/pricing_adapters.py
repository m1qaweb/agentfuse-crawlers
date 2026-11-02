"""P17B1: bounded *review-only* pricing-family candidates and inline rate labels.

Most publisher prices are NOT a set of independently comparable numbers.
A family is an unreviewed hypothesis pinned to an exact first-party source,
not a valid product owner, operator permission, or vendor rate.

The only executable P17B1 family transformation is a strict literal
"Input: USD X; Cached input: USD Y; Output: USD Z" cell parser. It produces
independent unapproved evidence *candidates*. It intentionally does not
make composite cells safe for cost rankings without real P15B gold.
"""
import hashlib
import re
from functools import lru_cache

from agentfuse_crawlers.rate_units import (
    PRICE_MARKER, TEMPORAL, CONDITIONAL, FOOTNOTE_MARK,
    analyze_cell, clean,
)
from agentfuse_crawlers.sources import load_sources

REVISION = "p17b1_review_only_price_family_v1"
MAX_SEGMENTS = 4
MAX_RAW_CELL = 700
MAX_RATE_SEGMENT = 210
# These are SOURCE SCOPE HYPOTHESES: not independently reviewed ownership,
# not a new list of URLs or an approval to run additional Scrapy requests.
FAMILIES = {
    "model_token_matrix": (
        "openai_api_pricing", "anthropic_api_pricing", "xai_pricing",
        "gemini_api_pricing", "together_ai_pricing", "fireworks_ai_pricing",
    ),
    "cloud_regional_matrix": (
        "aws_bedrock_pricing", "azure_ai_search_pricing",
    ),
    "subscription_plan_cards": (
        "cursor_pricing", "claude_code_pricing", "kiro_pricing",
        "github_copilot_pricing", "devin_pricing", "replit_pricing",
    ),
    "request_credit_metering": (
        "cloudflare_workers_ai_pricing", "pinecone_pricing",
        "qdrant_pricing", "weaviate_pricing", "openrouter_pricing",
    ),
}
# No provider-specific default currency, region, plan or unit exists.
# No pricing quote from these mappings is automatically trusted.
FIELD_LABELS = {
    "input": "input",
    "output": "output",
    "cached input": "cached_input",
    "batch input": "batch_input",
    "batch output": "batch_output",
    "cache write": "cache_write",
}
LABEL_RE = re.compile(
    r"^\s*(cached input|batch input|batch output|cache write|input|output)"
    r"\s*:\s*(.{1,210})\s*$", re.I,
)
PART_SEPARATOR = re.compile(r"\s*;\s*")
UNSAFE_SCOPE_WORDS = re.compile(
    r"\b(?:starting|before|after|through|effective|until|"
    r"if|when|up\s+to|over|under|discount|promo|trial|"
    r"varies|variable|long\s+context|short\s+context|"
    r"depending|minimum|commitment|tiered|first\s+\d+)\b",
    re.I,
)
DATE_OR_CONDITION = re.compile(
    r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b"
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
    r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b"
    r"|[<>≥≤]\s*[\d,.]+\s*[km]?\s*tokens?",
    re.I,
)


@lru_cache(maxsize=1)
def family_profiles():
    """Validate every exact source ID against the current 460-ID manifest."""
    known = {x["id"]: x for x in load_sources()}
    if len(known) != 460:
        raise ValueError("Current official manifest is not the pinned 460-source inventory")
    profiles = {}
    for name, ids in FAMILIES.items():
        for sid in ids:
            source = known.get(sid)
            if sid in profiles or not source or source["category"] != "pricing":
                raise ValueError("Unknown, repeated, or non-pricing P17B pilot source")
            profiles[sid] = {
                "source_id": sid,
                "source_url": source["url"],
                "provider": source["provider"],
                "page_family_candidate": name,
                "family_review_status": "unverified_pending_original_publisher_gold",
                "publisher_product_identity_verified": False,
                "new_fetch_permission": False,
                "automatic_provider_adapter_authorized": False,
                "advisor_fact_approvals": 0,
            }
    return profiles


def family_for_source(source_id, source_url):
    profile = family_profiles().get(source_id)
    if profile is None:
        return None
    if source_url != profile["source_url"]:
        raise ValueError("P17B rate family source URL differs from pinned manifest")
    return profile


def explicit_inline_components(raw_cell, *, model_label, row_header,
                               table_caption, table_context, footnotes,
                               family_profile):
    """Decompose ONLY fully labeled, semicolon-delimited numeric rates.

    Multi-price bundles lacking a legend (e.g. '$3 / $0.30 / $15') must
    stay ONE blocked observation. All returned candidates are marked
    review-only regardless of currency/unit/region/tier completeness.
    """
    if (family_profile is None or
            family_profile["page_family_candidate"] != "model_token_matrix"
            or not isinstance(raw_cell, str)
            or len(raw_cell) > MAX_RAW_CELL
            or raw_cell.count(";") < 1
            or not 2 <= len(PRICE_MARKER.findall(raw_cell)) <= MAX_SEGMENTS):
        return None
    if (TEMPORAL.search(raw_cell) or CONDITIONAL.search(raw_cell)
            or UNSAFE_SCOPE_WORDS.search(raw_cell)
            or DATE_OR_CONDITION.search(raw_cell)
            or FOOTNOTE_MARK.search(raw_cell)
            or footnotes):
        return None
    segments = PART_SEPARATOR.split(raw_cell)
    if not 2 <= len(segments) <= MAX_SEGMENTS:
        return None
    explicit = []
    dimensions = set()
    for index, segment in enumerate(segments):
        if not 1 <= len(segment) <= MAX_RATE_SEGMENT:
            return None
        match = LABEL_RE.fullmatch(segment)
        if not match:
            return None
        label, value = match.group(1).lower(), match.group(2)
        dimension = FIELD_LABELS[label]
        if dimension in dimensions or len(PRICE_MARKER.findall(value)) != 1:
            return None
        if any(x in value for x in (";", "|", "→", "⇒")):
            return None
        # An unlabeled '%' add-on, a second amount, etc. is not an
        # independent quoted rate that may be simplified by this adapter.
        if re.search(r"\d\s*%|\b(?:fee|tax|credit|rebate)\b", value, re.I):
            return None
        cell = analyze_cell(
            value, model_label=model_label, column_header=label,
            row_header=row_header, table_context=table_context,
            table_caption=table_caption, footnotes=footnotes,
        )
        if cell["price_state"] != "numeric_candidate":
            return None
        if cell["price_dimension"] != dimension:
            return None
        # Keep literal input and output cell text separate; do not infer
        # that a price is Global, USD or Standard from the source ID.
        cell.update({
            "raw_parent_cell_text": clean(raw_cell, MAX_RAW_CELL),
            "inline_component_label": label,
            "inline_component_index": index,
            "inline_component_count": len(segments),
            "inline_component_evidence_sha256": hashlib.sha256(
                (raw_cell + "|" + segment).encode("utf-8")
            ).hexdigest(),
            "inline_component_parent_identity_review_status": (
                "unverified_composite_cell"
            ),
            "family_adapter_revision": REVISION,
            "family_adapter_candidate_only": True,
            "source_product_owner_verified": False,
            "approved_for_advisor": False,
        })
        # Conservative guard: a composite cell is not itself an
        # independently gold-verified model/rate identity. Never promote
        # its components to cost ranking, even if every visible dimension
        # appears explicit. This can be relaxed only after P15B gold.
        cell["normalized_amount_decimal"] = None
        cell["comparable_candidate"] = False
        cell["review_quote_amount_decimal"] = None
        cell["review_quote_candidate"] = False
        cell["normalization_blockers"] = list(dict.fromkeys([
            *cell["normalization_blockers"],
            "inline_component_requires_independent_publisher_gold",
        ]))
        explicit.append(cell)
        dimensions.add(dimension)
    return explicit
