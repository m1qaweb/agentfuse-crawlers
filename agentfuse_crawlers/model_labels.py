"""P17A: conservative DOM-aware model identifier hygiene for pricing tables.

The first price-table cell frequently contains <strong>model ID</strong>
followed by a marketing paragraph. lxml's .text_content() joins adjacent
fragments without whitespace, yielding fictional model IDs such as
'grok-4.7Long context ...'. This module preserves original raw text,
extracts an explicitly prominent *leading* model identity, and refuses
ambiguous/contaminated identity. It never guesses a vendor's model catalog.

All extracted rates remain unverified; unknown USD/region/plan scope stays
unknown. These functions never approve prices or enable new crawl URLs.
"""
import re
from lxml import etree

from agentfuse_crawlers.rate_units import PRICE_MARKER, clean

MAX_MODEL_LABEL = 100
MAX_VISIBLE_CELL = 750
MAX_CANDIDATES = 15
DESCRIPTIVE_JOIN = re.compile(
    r"(?:[a-z0-9])(?:For\s+(?:demanding|long|developers?|reasoning|"
    r"complex|better|production|enterprise)|Long\s+context\b|"
    r"The\s+best\s+combination\b|Built\s+for\b|"
    r"Designed\s+for\b)"
    r"|\b(?:For\s+(?:demanding|long|developers?|enterprise)|"
    r"Long\s+context\s+[≥><]|The\s+best\s+combination|"
    r"Built\s+for\s+(?:developers?|teams?))\b",
    re.I,
)
GENERIC_LABEL = re.compile(
    r"^(?:(?:model|service|name|pricing|price|rates?|costs?|"
    r"input|output|cached|base|unit|description|features?)"
    r"(?:\s+(?:name|pricing|rate|price|cost|unit|tokens?))?)$",
    re.I,
)
MODEL_CLASS = re.compile(
    r"(?:^|[\s_-])(?:model|service)[_-]?(?:name|id|label)(?:$|[\s_-])",
    re.I,
)
NON_MODEL_PHRASE = re.compile(
    r"\b(?:per\s+(?:1m|million|token|month)|subscribe now|"
    r"for demanding|learn more|contact sales|free trial|"
    r"pricing plan|usd|eur|gbp)\b", re.I
)


def visible_cell_text(cell):
    """Insert space between distinct DOM text nodes; never silently glue IDs.

    The original HTML remains the source; the result is an unverified human
    reading aid. Splitting an inline numeric token may *reduce* parseability
    but cannot create a trusted price from a hidden element.
    """
    if not isinstance(getattr(cell, "tag", None), str):
        raise ValueError("Expected a table cell element")
    fragments = [
        clean(fragment, MAX_VISIBLE_CELL) for fragment in cell.itertext()
        if str(fragment).strip()
    ]
    return clean(" ".join(fragments), MAX_VISIBLE_CELL)


def suspected_model_description_join(label):
    """Risk heuristic for *review triage*, not an authoritative model name."""
    raw = clean(label, MAX_VISIBLE_CELL)
    if not raw:
        return False
    if DESCRIPTIVE_JOIN.search(raw):
        return True
    # Long prose is unlikely to be a precise API model identifier. Do not
    # trim it to an imagined correct model: require publisher review instead.
    return len(raw) > 105 and len(raw.split()) >= 10


def _model_like(value):
    raw = clean(value, MAX_MODEL_LABEL + 50)
    if not 2 <= len(raw) <= MAX_MODEL_LABEL:
        return False
    if len(raw.split()) > 8 or GENERIC_LABEL.fullmatch(raw):
        return False
    if PRICE_MARKER.search(raw) or NON_MODEL_PHRASE.search(raw):
        return False
    if suspected_model_description_join(raw):
        return False
    if not re.search(r"[A-Za-z]", raw):
        return False
    if re.search(r"[<>@=?!{}\[\]\n\r]", raw):
        return False
    if raw.endswith((".", ":", ",", ";")):
        return False
    return True


def _candidate_nodes(cell):
    """Prominent *leading* DOM markers; reject multiple distinct owners."""
    found = []
    for node in cell.iterdescendants():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        klass = (node.get("class") or "")[:180]
        if tag not in {"strong", "b", "code"} and not MODEL_CLASS.search(klass):
            continue
        # A code token inside unrelated pricing help/footnotes is not a row
        # identity. Confirm the candidate is itself the leading visible text.
        raw = visible_cell_text(node)
        if raw and raw not in found:
            found.append(raw)
        if len(found) > MAX_CANDIDATES:
            return []
    return found


def inspect_model_cell(cell):
    """Return an explicit model label or a fail-closed observation status.

    A label must be anchored in the model cell's FIRST visible phrase;
    later emphasized descriptions cannot be promoted to model IDs.
    """
    raw = visible_cell_text(cell)
    candidates = _candidate_nodes(cell)
    matching = [
        label for label in candidates
        if _model_like(label) and (
            raw.casefold() == label.casefold()
            or raw.casefold().startswith(label.casefold() + " ")
        )
    ]
    different = {x.casefold() for x in matching}
    prominent = {x.casefold() for x in candidates if _model_like(x)}
    if len(different) > 1 or len(prominent) > 1:
        return {
            "label": None,
            "status": "ambiguous_multiple_prominent_models",
            "raw_cell_text": raw,
            "requires_review": True,
            "description_present": bool(raw),
        }
    if len(matching) == 1:
        picked = matching[0]
        description = raw[len(picked):].strip()
        return {
            "label": picked,
            "status": (
                "explicit_leading_dom_label_with_description"
                if description else "explicit_leading_dom_label"
            ),
            "raw_cell_text": raw,
            "requires_review": False,
            "description_present": bool(description),
        }
    if suspected_model_description_join(raw):
        return {
            "label": None,
            "status": "suspected_model_description_contamination",
            "raw_cell_text": raw,
            "requires_review": True,
            "description_present": True,
        }
    # Without trustworthy DOM prominence, retain the original cell text and
    # let the existing generic _model_label() choose or reject as before.
    return {
        "label": None,
        "status": "unresolved_plain_row_cell",
        "raw_cell_text": raw,
        "requires_review": False,
        "description_present": False,
    }
