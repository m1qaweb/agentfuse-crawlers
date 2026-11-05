"""Conservative, bounded, non-table pricing-card evidence.

Only explicit pricing/plan card structure is considered. Publisher HTML, marketing
text, navigation and unrelated articles are not a numeric-price database.
No currency, region, tier, model, or unit may be guessed. All candidates remain
unverified and must survive a human check against original first-party content.
"""

import hashlib
import re

from agentfuse_crawlers.pricing_scope import (
    ALL_CURRENCY, _citation, _leaf_statement,
    _statement_declarations, scoped_text,
)
from agentfuse_crawlers.pricing_visibility import in_explicitly_nonvisible_context
from agentfuse_crawlers.rate_units import (
    CURRENCY_CODES, PRICE_MARKER, NON_NUMERIC, analyze_cell, clean,
    detect_unit,
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
# A classless card is accepted only for a narrow named subscription tier,
# with one explicit local monetary price and billing-period label. Marketing
# sections, navigation and feature comparisons must not become price cards.
PLAN_HEADING = re.compile(
    r"^(?:(?:[A-Za-z][A-Za-z0-9+_.-]{1,24})\s+)?"
    r"(?:free|starter|basic|plus|pro\+?|pro\s+max|premium|"
    r"ultra|power|project|researcher|pay\s+as\s+you\s+go|"
    r"team|teams|business|enterprise)$", re.I,
)
BARE_MONEY = re.compile(
    r"^(?:(?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF)\s*)?"
    r"[$€£¥]?\s*(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,8})?"
    r"(?:\s*(?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF))?$",
    re.I,
)
BILLING_PERIOD = re.compile(
    r"^(?:per|/)\s*(?:(?:user|seat)\s*(?:/|per)\s*)?"
    r"(?:month|hour|year|annum)$",
    re.I,
)
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
    if (_tag(node) not in {"article", "section", "div"}
            or in_explicitly_nonvisible_context(node)):
        return False
    value = _attr_text(node)
    if any(re.search(
        r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", value
    ) for word in CARD_MARKERS):
        return True
    # Precisely scoped structural fallback, never an arbitrary $-sign scan.
    if node.xpath(".//table|ancestor::nav|ancestor::footer|ancestor::header"):
        return False
    if len(node.text_content()) > 2200:
        return False
    headings = node.xpath(".//h2|.//h3")
    if len(headings) != 1 or not PLAN_HEADING.fullmatch(
        clean(headings[0].text_content(), 130)
    ):
        return False
    return any(
        _tag(child) in {"div", "p", "span", "small", "strong"}
        and PRICE_MARKER.search(clean(child.text_content(), 120))
        and not any(_tag(sub) in {"h2", "h3", "h4", "p", "li"}
                    for sub in child.iterdescendants())
        for child in node.iterdescendants()
    ) and any(
        BILLING_PERIOD.fullmatch(clean(child.text_content(), 90))
        for child in node.iterdescendants()
        if _tag(child) in {"p", "span", "small", "div"}
    )


def _eligible(node):
    if (in_explicitly_nonvisible_context(node)
            or node.xpath(BANNED_ANCESTORS) or node.xpath(".//table")):
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


def _page_currency_preface(main, first_card):
    """A page-wide ALL-prices claim must precede cards AND be uncontradicted.

    A conflicting ALL-prices statement after another card makes the entire
    publisher's page currency scope ambiguous, not globally USD.
    """
    if first_card is None:
        return None, False
    preface, declared = [], set()
    before_card = True
    for node in main.iter():
        if node is first_card:
            before_card = False
        line = _leaf_statement(node)
        if not line or EXCLUDED_CONTENT.search(line):
            continue
        match = ALL_CURRENCY.search(line)
        if match and match.group(1).upper() in CURRENCY_CODES:
            value = match.group(1).upper()
            declared.add(value)
            if before_card:
                preface.append(_citation(
                    name="currency", value=value,
                    scope="page_all_prices", text=line,
                ))
    if len(declared) > 1:
        return None, True
    return (preface[-1] if preface else None), False


def _card_declarations(card, *, page_currency=None, page_conflict=False):
    """Only standalone, card-local explicit scope; no unrelated page text."""
    raw = [page_currency] if page_currency else []
    for node in card.xpath(".//p|.//li|.//small|.//span|.//div"):
        if (in_explicitly_nonvisible_context(node)
                or node.xpath("ancestor::table|ancestor::nav|ancestor::footer")):
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
    conflict = bool(page_conflict or any(
        len({v["value"].casefold() for v in values}) != 1
        for values in buckets.values()
    ))
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
                used.update(id(child) for child in dd.iterdescendants())
                yield label, value, dd
    # Explicit, paired rate rows are common in tableless developer pricing
    # pages: <div class="rate-row"><span>Input</span><span>USD 1 / MTok</span>.
    # Only exact two-cell labels are admitted, never arbitrary nearby numbers.
    for row in card.xpath(".//div|.//li"):
        if not any(w in _attr_text(row) for w in ROW_MARKERS):
            continue
        children = [child for child in row
                    if _tag(child) in {"span", "strong", "b", "small"}]
        if len(children) != 2 or any(
            _tag(x) in {"table", "li", "div"} for x in row.iterdescendants()
        ):
            continue
        label, value = (
            clean(children[0].text_content(), 100),
            clean(children[1].text_content(), 260),
        )
        if _price_label(label) and _is_value(value):
            used.add(id(row))
            used.update(id(child) for child in row.iterdescendants())
            yield label, value, row

    # One price and one *adjacent exact* billing denominator within the same
    # parent: e.g. <span>USD 20</span><span>per user / month</span>.
    # Do not join prices with distant text or infer a term from an ad banner.
    for parent in card.xpath(".//div|.//p|.//li"):
        if id(parent) in used or parent.xpath("ancestor::table|ancestor::nav|ancestor::footer"):
            continue
        children = [
            child for child in parent if _tag(child) in {
                "span", "strong", "b", "small",
            } and not list(child)
        ]
        if len(children) != 2 or len(parent) != 2:
            continue
        texts = [clean(x.text_content(), 150) for x in children]
        price_positions = [i for i, t in enumerate(texts) if PRICE_MARKER.search(t)]
        period_positions = [
            i for i, t in enumerate(texts)
            if BILLING_PERIOD.fullmatch(t) and detect_unit(t)
        ]
        if len(price_positions) != 1 or len(period_positions) != 1:
            continue
        rate = texts[price_positions[0]]
        period = texts[period_positions[0]]
        if (len(rate) > 85 or len(rate.split()) > 6
                or not BARE_MONEY.fullmatch(rate)
                or EXCLUDED_CONTENT.search(rate) or EXCLUDED_CONTENT.search(period)):
            continue
        label = (
            "Price per seat/month" if "user" in period.lower()
            or "seat" in period.lower() else "Monthly price"
            if "month" in period.lower() else "Price"
        )
        if label == "Price":
            continue  # Do not invent hourly/annual dimensions.
        used.add(id(parent))
        used.update(id(child) for child in children)
        yield label, rate + " " + period, parent

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
            used.update(id(child) for child in node.iterdescendants())
            yield (*pair, node)
            continue
        cls = _attr_text(node)
        if (any(re.search(
            r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", cls
        ) for w in VALUE_MARKERS)
                and _is_value(text) and not EXCLUDED_CONTENT.search(text)
                and not any(_tag(d) in {"li", "p", "div", "span"}
                            for d in node.iterdescendants())):
            # A bare amount has an unknown dimension. The narrow exception
            # is an explicitly printed seat/user per month denominator.
            # This is textual evidence, not an inferred subscription plan.
            label = (
                "Price per seat/month"
                if re.search(
                    r"(?:\bper\b|/)\s*(?:seat|user)\s*(?:/|per)\s*month\b",
                    text, re.I,
                ) else "Price"
            )
            used.add(id(node))
            used.update(id(child) for child in node.iterdescendants())
            yield label, text, node


def _card_rate(source_id, source_url, heading, cid, idx, label, raw,
               declarations, scope_conflict, *, plan_heading=False):
    scoped = scoped_text(declarations)
    obs = analyze_cell(
        raw, model_label=heading, column_header=label,
        row_header=heading or "", table_context=scoped,
        table_caption="", footnotes="",
    )
    if (plan_heading and heading and not obs.get("tier_or_plan")
            and obs.get("price_dimension") == "subscription"):
        # An explicitly printed named PLAN heading is a tier label, not a
        # guessed provider default or model name. Even then region/currency
        # remain unknown until the publisher states them.
        obs["tier_or_plan"] = heading
        obs["tier_applicability"] = "explicit_plan_heading"
        obs["model_or_service"] = "subscription_plan:" + heading
        obs["normalized_amount_decimal"] = None
        obs["comparable_candidate"] = False
        obs["review_quote_amount_decimal"] = None
        obs["review_quote_candidate"] = False
        # A plan is not an API model. Keep it review-only until supported
        # subscription comparison modes have their own identity rules.
        obs["normalization_blockers"] = list(dict.fromkeys([
            *obs["normalization_blockers"], "subscription_plan_needs_review",
        ]))
    if scope_conflict:
        obs["normalized_amount_decimal"] = None
        obs["review_quote_amount_decimal"] = None
        obs["review_quote_candidate"] = False
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
        "card_plan_heading": bool(plan_heading),
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
    candidates = []
    oversized = 0
    for node in main.iter():
        if not _is_card(node) or node.xpath(BANNED_ANCESTORS):
            continue
        # A wrapper around other cards is not another independent card.
        if any(_is_card(child) for child in node.iterdescendants()):
            continue
        if node.xpath(".//table"):
            continue  # Table observations are inventoried by the table parser.
        if len(node.text_content()) > MAX_CARD_TEXT_CHARS:
            oversized += 1  # Never silently treat an oversized card as complete.
            continue
        candidates.append(node)
    selected = candidates[:MAX_CARDS]
    global_currency, page_conflict = _page_currency_preface(
        main, candidates[0] if candidates else None
    )
    observations, exemplars = [], []
    examined, row_omitted = 0, 0
    for i, card in enumerate(selected):
        title = _heading(card)
        plan_heading = bool(
            title and PLAN_HEADING.fullmatch(title)
            and (_tag(card) in {"div", "article", "section"})
        )
        raw_id = clean(card.get("id"), 110)
        cid = raw_id if re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", raw_id) else (
            f"card-{i+1}"
        )
        declarations, conflict = _card_declarations(
            card, page_currency=global_currency, page_conflict=page_conflict
        )
        entries = list(_pairs(card))
        examined += len(entries)
        if len(entries) > MAX_ROWS_PER_CARD:
            row_omitted += len(entries) - MAX_ROWS_PER_CARD
        for j, (label, raw, node) in enumerate(entries[:MAX_ROWS_PER_CARD]):
            if len(observations) < MAX_CARD_OBSERVATIONS:
                observations.append(_card_rate(
                    source_id, source_url, title, cid, j, label,
                    raw, declarations, conflict, plan_heading=plan_heading,
                ))
            else:
                row_omitted += 1
        if len(exemplars) < 20 and entries:
            exemplars.append({
                "card_id": cid, "heading": title, "rate_entries": len(entries),
                "scope_conflict": conflict, "review_status": "unverified",
            })
    return {
        "card_total": len(candidates) + oversized,
        "card_selected": len(selected),
        "card_omitted": len(candidates) - len(selected) + oversized,
        "card_oversized": oversized,
        "card_entries_examined": examined,
        "card_entries_omitted": row_omitted,
        "card_scan_truncated": bool(
            len(candidates) > MAX_CARDS or row_omitted or oversized
        ),
        "card_observations": observations,
        "card_evidence_excerpts": exemplars,
    }
