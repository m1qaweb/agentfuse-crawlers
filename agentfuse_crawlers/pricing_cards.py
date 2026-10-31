"""Conservative, bounded, non-table pricing-card evidence.

Only explicit pricing/plan card structure is considered. Publisher HTML, marketing
text, navigation and unrelated articles are not a numeric-price database.
No currency, region, tier, model, or unit may be guessed. All candidates remain
unverified and must survive a human check against original first-party content.
"""

import hashlib
import re

from agentfuse_crawlers.pricing_scope import (
    ALL_CURRENCY, _citation, _statement_declarations, scoped_text,
)
from agentfuse_crawlers.rate_units import (
    CURRENCY_CODES, PRICE_MARKER, NON_NUMERIC, analyze_cell, clean,
)

MAX_CARDS = 120
MAX_ROWS_PER_CARD = 24
MAX_CARD_OBSERVATIONS = 300
MAX_CARD_TEXT_CHARS = 4000
CARD_MARKERS = (
    "pricing-card", "price-card", "plan-card", "rate-card", "tier-card",
    "subscription-card", "pricing-tier", "pricing-plan", "pricing-tile",
    "plan-tile", "pricing-panel", "pricing-package", "pricing-model",
)
VALUE_MARKERS = (
    "price", "price-value", "price-amount", "rate-amount", "rate-value",
)
ROW_MARKERS = ("rate-row", "price-row", "pricing-row")
LABEL = re.compile(
    r"^(?:(?:(?:batch|cached|cache write|long.context|fast|ultrafast)"
    r"\s+)?(?:input|output)\s+)?(?:price|cost|rate)"
    r"(?:\s+per\s+[A-Za-z0-9 /_-]{1,45})?$"
    r"|^(?:input|output|cached input|cached output|batch input|batch output)$"
    r"|^(?:monthly|subscription|annual|hourly)\s+(?:price|cost|rate)$",
    re.I,
)
GENERIC_CARD_TITLES = frozenset({
    "pricing", "pricing plans", "plans", "compare plans", "features",
    "billing", "rate", "rates", "input price", "output price",
    "monthly pricing", "subscriptions", "plans and pricing",
})
BANNED_ANCESTORS = "ancestor::nav|ancestor::footer|ancestor::header|ancestor::aside|ancestor::form|ancestor::table"
EXCLUDED_CONTENT = re.compile(
    r"\b(?:free trial for \d+ days|save \d+%|discount|promo(?:tion)?|"
    r"customer story|our customers)\b", re.I,
)


def _tag(node):
    return node.tag.lower() if isinstance(node.tag, str) else ""


def _attr_text(node):
    return clean(" ".join(node.get(x, "") for x in (
        "class", "data-testid", "data-component", "id",
    )), 250).lower().replace("_", "-")


def _is_card(node):
    if _tag(node) not in {"article", "section", "div"}:
        return False
    value = _attr_text(node)
    return any(re.search(
        r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", value
    ) for word in CARD_MARKERS)


def _eligible(node):
    if node.xpath(BANNED_ANCESTORS) or node.xpath(".//table"):
        return False
    if len(node.text_content()) > MAX_CARD_TEXT_CHARS:
        return False
    # Parent grid is not itself a card; nested cards are separate.
    if any(_is_card(child) for child in node.iterdescendants()):
        return False
    return True


def _heading(node):
    h = node.xpath(".//h2|.//h3")
    if not h:
        h = node.xpath(".//h4")
    # Two competing product titles are ambiguous, not an inferred model.
    if len(h) != 1:
        return None
    value = clean(h[0].text_content(), 180)
    if (not 2 <= len(value) <= 150
            or value.lower() in GENERIC_CARD_TITLES
            or PRICE_MARKER.search(value)):
        return None
    return value


def _is_value(text):
    return bool(
        PRICE_MARKER.search(text) or
        any(pattern.search(text) for _, pattern in NON_NUMERIC)
    )


def _card_declarations(card):
    """Only standalone, card-local explicit scope; no unrelated page text."""
    raw = []
    for node in card.xpath(".//p|.//li|.//small|.//span|.//div"):
        if node.xpath("ancestor::table|ancestor::nav|ancestor::footer"):
            continue
        if any(_tag(x) in {"p", "li", "small", "span", "div", "table", "h2", "h3"}
               for x in node.iterdescendants()):
            continue
        s = clean(node.text_content(), 200)
        if not s or len(s) > 180 or EXCLUDED_CONTENT.search(s):
            continue
        match = ALL_CURRENCY.fullmatch(s.rstrip("."))
        if match and match.group(1).upper() in CURRENCY_CODES:
            raw.append(_citation(
                name="currency", value=match.group(1).upper(),
                scope="within_pricing_card", text=s,
            ))
        for name, value in _statement_declarations(s):
            raw.append(_citation(
                name=name, value=value,
                scope="within_pricing_card", text=s,
            ))
    buckets = {}
    for row in raw:
        buckets.setdefault(row["dimension"], []).append(row)
    conflict = any(
        len({v["value"].casefold() for v in values}) != 1
        for values in buckets.values()
    )
    declarations = [
        values[-1] for values in buckets.values()
        if len({v["value"].casefold() for v in values}) == 1
    ]
    return declarations[:4], bool(conflict or len(declarations) > 4)


def _price_label(text):
    return LABEL.fullmatch(clean(text, 110)) is not None


def _split_rate(text):
    """Only exact label/value pairs, never an unlabeled promotional claim."""
    text = clean(text, 350)
    if ":" in text:
        label, value = text.split(":", 1)
        if _price_label(label) and _is_value(value):
            return clean(label, 100), clean(value, 260)
    # Explicit "Input price USD 1.2 per MTok" without a colon.
    m = re.match(
        r"^((?:(?:batch|cached|cache write|long.context)\s+)?"
        r"(?:input|output)\s+(?:price|cost|rate))\s+"
        r"((?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF|\$|€|£|¥).+)$",
        text, re.I,
    )
    if m and _is_value(m.group(2)):
        return m.group(1), m.group(2)
    return None


def _pairs(card):
    """Yield (label, visible value, local node) without matching table cells."""
    used = set()
    for dt in card.xpath(".//dt"):
        dd = dt.getnext()
        if _tag(dd) == "dd":
            label, value = clean(dt.text_content(), 100), clean(dd.text_content(), 260)
            if _price_label(label) and _is_value(value):
                used.add(id(dd))
                yield label, value, dd
    for node in card.xpath(".//li|.//p|.//div|.//span|.//small"):
        if id(node) in used:
            continue
        if node.xpath("ancestor::table|ancestor::nav|ancestor::footer|ancestor::dl"):
            continue
        text = clean(node.text_content(), 350)
        if not 2 <= len(text) <= 320:
            continue
        # A parent node containing a price row isn't another price row.
        if any(_tag(d) in {"li", "p", "div"} for d in node.iterdescendants()):
            continue
        pair = _split_rate(text)
        if pair:
            used.add(id(node))
            yield (*pair, node)
            continue
        cls = _attr_text(node)
        if (any(re.search(
            r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", cls
        ) for w in VALUE_MARKERS)
                and _is_value(text) and not EXCLUDED_CONTENT.search(text)
                and not any(_tag(d) in {"li", "p", "div", "span"}
                            for d in node.iterdescendants())):
            # An unlabeled displayed price is a RAW observation. Do not
            # manufacture an input/output/subscription dimension.
            yield "Price", text, node


def _card_rate(source_id, source_url, heading, cid, idx, label, raw,
               declarations, scope_conflict):
    scoped = scoped_text(declarations)
    obs = analyze_cell(
        raw, model_label=heading, column_header=label,
        row_header=heading or "", table_context=scoped,
        table_caption="", footnotes="",
    )
    if scope_conflict:
        obs["normalized_amount_decimal"] = None
        obs["comparable_candidate"] = False
        obs["normalization_blockers"] = list(dict.fromkeys([
            *obs["normalization_blockers"], "card_scope_conflict",
        ]))
    dims = (
        "model_or_service", "price_dimension", "billing_unit",
        "currency", "region", "tier_or_plan",
    )
    if obs["comparable_candidate"]:
        identity = source_id + "|" + "|".join(str(obs.get(k) or "") for k in dims)
    else:
        identity = source_id + "|card|" + cid + "|" + str(idx)
    obs.update({
        "observation_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32],
        "source_id": source_id,
        "source_url": source_url,
        "source_evidence_sha256": hashlib.sha256(
            (raw + "|" + label + "|" + (heading or "") + "|" + scoped).encode("utf-8")
        ).hexdigest(),
        "evidence_kind": "structured_card",
        "card_id": cid,
        "card_label": heading,
        "card_price_label": label,
        "table_id": None,
        "row_index": None,
        "column_index": None,
        "scope_declarations": list(declarations),
        "scope_provenance_verified": False,
        "model_label_provenance": "single_card_heading" if heading else "unresolved",
        "card_scope_conflict": scope_conflict,
        "review_status": "unverified",
        "approved_for_advisor": False,
    })
    return obs


def extract_card_evidence(main, source_url, source_id):
    """Extract structurally labeled pricing cards; return counts of any losses."""
    candidates = [node for node in main.iter() if _is_card(node) and _eligible(node)]
    selected = candidates[:MAX_CARDS]
    observations, exemplars = [], []
    examined, row_omitted = 0, 0
    for i, card in enumerate(selected):
        title = _heading(card)
        raw_id = clean(card.get("id"), 110)
        cid = raw_id if re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", raw_id) else (
            f"card-{i+1}"
        )
        declarations, conflict = _card_declarations(card)
        entries = list(_pairs(card))
        examined += len(entries)
        if len(entries) > MAX_ROWS_PER_CARD:
            row_omitted += len(entries) - MAX_ROWS_PER_CARD
        for j, (label, raw, node) in enumerate(entries[:MAX_ROWS_PER_CARD]):
            if len(observations) < MAX_CARD_OBSERVATIONS:
                observations.append(_card_rate(
                    source_id, source_url, title, cid, j, label,
                    raw, declarations, conflict,
                ))
            else:
                row_omitted += 1
        if len(exemplars) < 20 and entries:
            exemplars.append({
                "card_id": cid, "heading": title, "rate_entries": len(entries),
                "scope_conflict": conflict, "review_status": "unverified",
            })
    return {
        "card_total": len(candidates),
        "card_selected": len(selected),
        "card_omitted": len(candidates) - len(selected),
        "card_entries_examined": examined,
        "card_entries_omitted": row_omitted,
        "card_scan_truncated": bool(
            len(candidates) > MAX_CARDS or row_omitted
        ),
        "card_observations": observations,
        "card_evidence_excerpts": exemplars,
    }
