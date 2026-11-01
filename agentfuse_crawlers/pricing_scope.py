"""Bounded, evidence-linked pricing scope declarations from a single HTML page.

This module *does not* infer a region, tier, currency, or billing unit from a
provider's identity, domain, dollar symbol, scrape date, or other prices.
The only page-wide declaration allowed is explicitly "ALL prices are in USD"
(or a similarly precise supported currency). Table-local unit declarations
apply to exactly the next table; they cannot leak into subsequent tables.

Any extracted scope is a raw, unverified candidate with a source excerpt.
"""

import re

from agentfuse_crawlers.rate_units import (
    CURRENCY_CODES, clean, detect_region, detect_tier, detect_unit,
)

CODES = r"(?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF)"
ALL_CURRENCY = re.compile(
    rf"\b(?:all|every)\s+(?:(?:listed|displayed|quoted)\s+)?"
    rf"(?:prices?|rates?|charges?)\s+(?:are|is)\s+"
    rf"(?:listed\s+|shown\s+|quoted\s+|displayed\s+|denominated\s+)?"
    rf"in\s+({CODES})\b",
    re.I,
)
LOCAL_UNIT = re.compile(
    r"^(?:all\s+)?(?:prices?|rates?|pricing|costs?)\s*"
    r"(?:(?:are|is)\s+)?(?:(?:listed|quoted|shown)\s+)?"
    r"(?:(?:in\s+(?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF))\s+)?"
    r"(?:per\s+|/\s*)(?:1\s*m(?:illion)?|million|1,?000,?000|"
    r"1\s*k|1,?000|thousand)\s*(?:input\s+|output\s+|cached\s+)?"
    r"(?:tokens?|characters?|requests?)\s*\.?$",
    re.I,
)
LOCAL_CURRENCY = re.compile(
    rf"^(?:prices?|rates?|pricing|costs?)\s+(?:are|is\s+)?"
    rf"(?:(?:shown|listed|quoted|denominated)\s+)?in\s+({CODES})\s*\.?$",
    re.I,
)
LOCAL_ALL_REGIONS = re.compile(
    r"^(?:all\s+)?(?:prices?|rates?)\s+(?:are\s+)?(?:the\s+)?"
    r"same\s+(?:in|across|for)\s+all\s+regions\s*\.?$",
    re.I,
)
LOCAL_ALL_PLANS = re.compile(
    r"^(?:all\s+)?(?:prices?|rates?)\s+(?:are\s+)?(?:the\s+)?"
    r"same\s+(?:in|across|for)\s+all\s+(?:plans|tiers)\s*\.?$",
    re.I,
)
LOCAL_LABEL = re.compile(
    r"^(?:region|location|tier|plan)\s*[:=]\s*[A-Za-z0-9 _-]{2,45}$",
    re.I,
)
EXCEPTION = re.compile(
    r"\b(?:except|unless|excluding|depending|subject to|some|up to|from)\b",
    re.I,
)
TEXT_TAGS = frozenset({"p", "div", "span", "small", "strong", "b", "li"})
STOP_TAGS = frozenset({"h2", "table"})
MAX_CONTEXT_NODES = 7
MAX_DECLARATIONS_PER_TABLE = 4


def _tag(node):
    return node.tag.lower() if isinstance(node.tag, str) else ""


def _leaf_statement(node):
    tag = _tag(node)
    if tag not in TEXT_TAGS or node.xpath("ancestor::table|ancestor::nav|ancestor::footer"):
        return ""
    # Never read a wrapper that may span multiple pricing tables, and never
    # treat embedded headings/nav as a page-wide scope declaration.
    if any(_tag(child) in TEXT_TAGS | {"table", "h1", "h2", "h3", "h4", "nav"}
           for child in node.iterdescendants()):
        return ""
    value = clean(node.text_content(), 220)
    if len(value) < 8 or len(value) > 180 or EXCEPTION.search(value):
        return ""
    return value


def _statement_declarations(text):
    found = []
    currency = LOCAL_CURRENCY.fullmatch(text)
    if currency:
        found.append(("currency", currency.group(1).upper()))
    if LOCAL_ALL_REGIONS.fullmatch(text):
        found.append(("region", "Global"))
    if LOCAL_ALL_PLANS.fullmatch(text):
        found.append(("tier_or_plan", "All Plans"))
    unit = detect_unit(text) if LOCAL_UNIT.fullmatch(text) else None
    if unit is not None:
        found.append(("billing_unit", unit))
    if LOCAL_LABEL.fullmatch(text):
        region = detect_region(text)
        tier = detect_tier(text)
        if region is not None:
            found.append(("region", region))
        if tier is not None:
            found.append(("tier_or_plan", tier))
    return found


def _citation(*, name, value, scope, text):
    return {
        "dimension": name, "value": value, "scope": scope,
        "evidence_text": text[:180], "review_status": "unverified",
    }


def table_declarations(main):
    """Return {id(table): [scoped raw source citations]} for direct tables.

    Table-local declarations are limited to recent standalone text nodes.
    Any intervening unrelated table or new h2 prevents inheritance. Multiple
    incompatible declarations for the same dimension remain unresolved.
    The page-wide ALL currency declaration is accepted only if all explicit
    ALL-currency declarations on this page agree and precede the first table.
    """
    tables = main.xpath(".//table[not(ancestor::table)]")
    if not tables:
        return {}
    first_table = tables[0]
    global_currencies = []
    # Check the document preface, never a price table, header cell or footer.
    for node in main.iter():
        if node is first_table:
            break
        statement = _leaf_statement(node)
        if statement:
            match = ALL_CURRENCY.search(statement)
            if match:
                value = match.group(1).upper()
                if value in CURRENCY_CODES:
                    global_currencies.append(_citation(
                        name="currency", value=value,
                        scope="page_all_prices", text=statement,
                    ))
    page_currency = (
        global_currencies[0] if global_currencies
        and len({c["value"] for c in global_currencies}) == 1 else None
    )
    result = {}
    pending = []
    recent = 0
    for node in main.iter():
        tag = _tag(node)
        if tag == "h2" or (
            tag == "table" and node.xpath("ancestor::table")
        ):
            if tag == "h2":
                pending.clear()
                recent = 0
            continue
        if tag == "table":
            # A table inherits only recent source declarations; once consumed
            # they are reset to prevent leakage into different price schedules.
            scoped = []
            if page_currency:
                scoped.append(page_currency)
            # Multiple values for one dimension are ambiguous, not first wins.
            by_dimension = {}
            for d in pending:
                by_dimension.setdefault(d["dimension"], []).append(d)
            for group in by_dimension.values():
                if len({row["value"].lower() for row in group}) == 1:
                    scoped.append(group[-1])
            result[id(node)] = scoped[:MAX_DECLARATIONS_PER_TABLE]
            pending.clear()
            recent = 0
            continue
        statement = _leaf_statement(node)
        if statement:
            recent += 1
            if recent > MAX_CONTEXT_NODES:
                pending.clear()
                recent = 1
            for dimension, value in _statement_declarations(statement):
                pending.append(_citation(
                    name=dimension, value=value,
                    scope="adjacent_preceding_text", text=statement,
                ))
        elif tag in {"p", "li"} and not node.xpath("ancestor::table"):
            # A substantive unrelated paragraph separates a pricing note
            # from a later table, even when it has no recognized declaration.
            if clean(node.text_content(), 200):
                recent += 1
                if recent > MAX_CONTEXT_NODES:
                    pending.clear()
                    recent = 1
    return result


def scoped_text(declarations):
    """Use original observed words so every inferred dimension is auditable."""
    return " ".join(row["evidence_text"] for row in declarations)
