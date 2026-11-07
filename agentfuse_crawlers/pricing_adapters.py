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

REVISION = "p23d4_review_only_price_family_v2"
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
        # Offline extract_evidence() also supports arbitrary synthetic
        # sources. Mismatched source ownership must fall back to generic
        # review-only extraction, not crash the spider or use an adapter.
        return None
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



# P23D4: Cloudflare's verified *historical Items* contained many cells of
# the literal form "$0.027 per M input tokens $0.201 per M output tokens".
# Source HTML has not been independently reauthenticated; this is STRICTLY
# a review-only extraction shape for the exact manifest URL and table header.
# M is the publisher's literal million-token denominator, not a guessed unit.
_CF_RATE = r"\$\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,8})?\s+per\s+M"
CLOUDFLARE_TOKEN_COMPONENTS = re.compile(
    rf"^\s*({_CF_RATE}\s+input\s+tokens)\s+"
    rf"(?:({_CF_RATE}\s+cached\s+input\s+tokens)\s+)?"
    rf"({_CF_RATE}\s+output\s+tokens)\s*$",
    re.I,
)


def cloudflare_explicit_token_components(raw_cell, *, column_header,
                                        model_label, row_header,
                                        table_context, table_caption,
                                        footnotes, family_profile):
    """Only directly labeled Cloudflare token rates, NEVER cost rankings.

    Do not transform neuron-metered rates, 1k-neuron denominators, plan
    totals, mixed currencies, temporal rates, arbitrary multi-price cells,
    changed source paths or another publisher's pricing HTML.
    """
    if (family_profile is None
            or family_profile.get("source_id") != "cloudflare_workers_ai_pricing"
            or family_profile.get("page_family_candidate") !=
                "request_credit_metering"
            or not isinstance(raw_cell, str)
            or not 1 <= len(raw_cell) <= MAX_RAW_CELL
            or clean(column_header, 100).casefold() != "price in tokens"
            or not isinstance(model_label, str)
            or not model_label.startswith("@cf/")
            or not model_label[4:]
            or footnotes
            or TEMPORAL.search(raw_cell)
            or CONDITIONAL.search(raw_cell)
            or UNSAFE_SCOPE_WORDS.search(raw_cell)
            or DATE_OR_CONDITION.search(raw_cell)
            or FOOTNOTE_MARK.search(raw_cell)):
        return None
    # A conflicting nearby table unit cannot be silently replaced with
    # the "per M tokens" denominator visible inside each exact segment.
    from agentfuse_crawlers.rate_units import detect_unit
    explicit_context_unit = detect_unit(table_caption, table_context)
    if explicit_context_unit not in (None, "per_1m_tokens"):
        return None
    match = CLOUDFLARE_TOKEN_COMPONENTS.fullmatch(raw_cell)
    if match is None:
        return None
    pairs = [("input", match.group(1))]
    if match.group(2) is not None:
        pairs.append(("cached_input", match.group(2)))
    pairs.append(("output", match.group(3)))
    if len(PRICE_MARKER.findall(raw_cell)) != len(pairs):
        return None

    results = []
    for index, (dimension, visible_rate) in enumerate(pairs):
        cell = analyze_cell(
            visible_rate, model_label=model_label,
            column_header=dimension.replace("_", " "),
            row_header=row_header, table_context=table_context,
            table_caption=table_caption, footnotes="",
        )
        if (cell["price_state"] != "numeric_candidate"
                or cell["price_dimension"] != dimension
                or cell["observed_single_amount_decimal"] is None
                or cell["billing_unit"] not in (None, "per_1m_tokens")):
            return None

        # "per M <component> tokens" is an explicit local denominator.
        # CURRENCY REMAINS UNKNOWN when the source prints only "$";
        # never silently infer USD even though this is a US company.
        cell["billing_unit"] = "per_1m_tokens"
        cell["billing_unit_literal"] = (
            "per M " + dimension.replace("_", " ") + " tokens"
        )
        cell["normalization_blockers"] = [
            reason for reason in cell["normalization_blockers"]
            if reason != "missing_explicit_billing_unit"
        ]
        cell.update({
            "raw_parent_cell_text": clean(raw_cell, MAX_RAW_CELL),
            "inline_component_label": dimension.replace("_", " "),
            "inline_component_index": index,
            "inline_component_count": len(pairs),
            "inline_component_evidence_sha256": hashlib.sha256(
                (raw_cell + "|" + dimension + "|" + visible_rate).encode("utf-8")
            ).hexdigest(),
            "inline_component_parent_identity_review_status":
                "unverified_cloudflare_literal_token_component",
            "family_adapter_revision": REVISION,
            "family_adapter_candidate_only": True,
            "source_product_owner_verified": False,
            "approved_for_advisor": False,
        })
        cell["normalized_amount_decimal"] = None
        cell["comparable_candidate"] = False
        cell["review_quote_amount_decimal"] = None
        cell["review_quote_candidate"] = False
        cell["normalization_blockers"] = list(dict.fromkeys([
            *cell["normalization_blockers"],
            "cloudflare_literal_tokens_require_independent_publisher_gold",
        ]))
        results.append(cell)
    return results


# P17B1 extension: exact first-party, nearby legend-backed pricing triplets.
# The official Fireworks source explicitly describes the rates in a Standard
# or Priority cell as input / cached input / output, in that order. The old
# 2026-11-02 exported Items have only "$3 / $0.3 / $15" and NOT the original
# raw HTML section paragraph, so the adapter MUST confirm that paragraph
# again in the current DOM. Parsed historical Items cannot retroactively
# authenticate the legend, determine prices, or activate recommendations.
FIREWORKS_TRIPLE = re.compile(
    r"^\s*(\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{1,8})?|\$\s*\d+(?:\.\d{1,8})?)"
    r"\s*/\s*"
    r"(\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{1,8})?|\$\s*\d+(?:\.\d{1,8})?)"
    r"\s*/\s*"
    r"(\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{1,8})?|\$\s*\d+(?:\.\d{1,8})?)"
    r"\s*$"
)
FIREWORKS_EXPLICIT_LEGEND = re.compile(
    r"\bin each standard or priority cell,\s*prices are\s*"
    r"input\s*/\s*cached input\s*/\s*output\s*"
    r"\(\s*USD\s+per\s+1\s*m(?:illion)?\s+tokens\s*\),"
    r"\s*in that order\b",
    re.I,
)
FIREWORKS_HEADING = re.compile(
    r"^text and vision models$", re.I,
)


def fireworks_scoped_legend(main, table, heading_context, family_profile):
    """Find publisher's exact ordered-unit legend within THIS table section.

    Never search whole-page text: the same source has decision models,
    embeddings, non-token rates and other billing dimensions.
    """
    if (family_profile is None
            or family_profile["source_id"] != "fireworks_ai_pricing"
            or "text and vision models" not in
               str(heading_context).replace("\u200b", "").casefold()):
        return None
    active = False
    preceding = []
    for node in main.iter():
        if node is table:
            break
        if not isinstance(getattr(node, "tag", None), str):
            continue
        tag = node.tag.lower()
        if tag in {"h2", "h3"}:
            heading = clean(node.text_content(), 150).replace("\u200b", "")
            active = bool(FIREWORKS_HEADING.fullmatch(heading))
            preceding.clear()
        if (active and tag == "p"
                and not node.xpath("ancestor::table|ancestor::nav|ancestor::footer")):
            text = clean(node.text_content(), 330)
            if text:
                preceding.append(text)
                if len(preceding) > 6:
                    preceding.pop(0)
    if not active:
        return None
    matching = [p for p in preceding if FIREWORKS_EXPLICIT_LEGEND.search(p)]
    # Multiple inconsistent apparent legends cannot safely define order.
    if len(matching) != 1:
        return None
    return matching[0]


def fireworks_triplet_components(raw_cell, *, column_header, model_label,
                                 row_header, table_context, table_caption,
                                 footnotes, legend, family_profile):
    """Three independent REVIEW candidates only after exact nearby legend.

    "Standard" and "Priority" are literal table headers. EUR pricing,
    missing legend, missing caption, varied order, footnotes, unit changes,
    mixed rate families or non-exact row money syntax cannot be split.
    """
    if (not isinstance(raw_cell, str) or len(raw_cell) > MAX_RAW_CELL
            or family_profile is None
            or family_profile["source_id"] != "fireworks_ai_pricing"
            or not isinstance(legend, str)
            or not FIREWORKS_EXPLICIT_LEGEND.search(legend)
            or column_header not in {"Standard", "Priority"}
            or footnotes
            or TEMPORAL.search(raw_cell)
            or CONDITIONAL.search(raw_cell)
            or UNSAFE_SCOPE_WORDS.search(raw_cell)
            or DATE_OR_CONDITION.search(raw_cell)):
        return None
    prices = FIREWORKS_TRIPLE.fullmatch(raw_cell)
    if prices is None:
        return None
    labels = ["input", "cached input", "output"]
    components = []
    # Both the position-to-dimension legend and denominator/currency must
    # appear in the same bounded first-party page section. This does not
    # certify whether publisher facts are current or universally applicable.
    for idx, (label, value) in enumerate(zip(labels, prices.groups())):
        candidate = analyze_cell(
            value, model_label=model_label, column_header=label,
            row_header=row_header,
            table_context=table_context,
            table_caption=(
                table_caption + " Tier: " + column_header +
                " USD per 1M tokens"
            ),
            footnotes="",
        )
        if (candidate["price_state"] != "numeric_candidate"
                or candidate["price_dimension"] != FIELD_LABELS[label]):
            return None
        candidate.update({
            "raw_parent_cell_text": clean(raw_cell, MAX_RAW_CELL),
            "inline_component_label": label,
            "inline_component_index": idx,
            "inline_component_count": len(prices.groups()),
            "inline_component_evidence_sha256": hashlib.sha256(
                (raw_cell + "|" + label + "|" + value + "|" + legend
                ).encode("utf-8")
            ).hexdigest(),
            "inline_component_parent_identity_review_status":
                "unverified_fireworks_legend_triplet",
            "family_adapter_revision": REVISION,
            "family_adapter_candidate_only": True,
            "source_product_owner_verified": False,
            "publisher_legend_evidence_text": legend[:280],
            "publisher_legend_evidence_sha256": hashlib.sha256(
                legend.encode("utf-8")
            ).hexdigest(),
            "approved_for_advisor": False,
        })
        candidate["normalized_amount_decimal"] = None
        candidate["comparable_candidate"] = False
        candidate["review_quote_amount_decimal"] = None
        candidate["review_quote_candidate"] = False
        candidate["normalization_blockers"] = list(dict.fromkeys([
            *candidate["normalization_blockers"],
            "fireworks_triplet_requires_independent_publisher_gold",
        ]))
        components.append(candidate)
    return components
