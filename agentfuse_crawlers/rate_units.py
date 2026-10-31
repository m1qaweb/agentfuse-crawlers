"""Strict, deterministic pricing-unit and amount parsing.

No implicit USD, no currency inferred from an unqualified '$', no dates
invented from scrape timestamps. Incomplete dimensions remain unverified raw
evidence; only explicitly scoped values produce an unapproved Decimal string.
"""

import re
from decimal import Decimal, InvalidOperation

CURRENCY_CODES = frozenset({"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "INR", "CHF"})
CURRENCY_RE = re.compile(r"(?<![A-Z])(?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF)(?![A-Z])", re.I)
PRICE = re.compile(
    r"(?<![\w.])(?:(USD|EUR|GBP|CAD|AUD|JPY|INR|CHF)\s*)?"
    r"([$€£¥])?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,8})?|\d+(?:\.\d{1,8})?)"
    r"\s*(USD|EUR|GBP|CAD|AUD|JPY|INR|CHF)?(?![\w.])", re.I,
)
PRICE_MARKER = re.compile(r"(?:[$€£¥]\s*\d|\b(?:USD|EUR|GBP|CAD|AUD|JPY|INR|CHF)\s*\d)", re.I)
NON_NUMERIC = [
    ("not_available", re.compile(r"\b(?:not available|n/?a|unavailable|not offered)\b", re.I)),
    ("contact_sales", re.compile(r"\b(?:contact sales|talk to sales|contact us for pricing|request a quote)\b", re.I)),
    ("custom", re.compile(r"\b(?:custom pricing|custom quote|negotiated pricing|bespoke pricing)\b", re.I)),
    ("free", re.compile(r"^\s*(?:free|no charge|\$0(?:\.0+)?|0(?:\.0+)?)\s*$", re.I)),
    ("usage_based", re.compile(r"\b(?:pay[- ]as[- ]you[- ]go|usage.based|variable usage)\b", re.I)),
]
TEMPORAL = re.compile(
    r"\b(?:through|starting|until|before|after|effective|promo(?:tional)?|"
    r"discount(?:ed)?|limited.time|expires?|first \d+ months?|trial)\b", re.I
)
CONDITIONAL = re.compile(
    r"\b(?:up to|greater than|less than|over \d|under \d|tiered|"
    r"volume(?: discount| pricing)?|varies|based on usage|from \$)\b", re.I
)
FOOTNOTE_MARK = re.compile(r"(?:\*|†|‡|\[\d+\])\s*$")

# More specific units must match before less specific ones.
UNIT_PATTERNS = [
    ("per_1m_tokens", re.compile(
        r"(?:\bper\b|/)\s*(?:1\s*m(?:illion)?|one million|million)\s*"
        r"(?:input |output |cached )?tokens?\b", re.I)),
    ("per_1k_tokens", re.compile(
        r"(?:\bper\b|/)\s*(?:1[, ]?000|1\s*k|thousand)\s*"
        r"(?:input |output )?tokens?\b", re.I)),
    ("per_token", re.compile(r"(?:\bper\b|/)\s*(?:input |output )?token\b", re.I)),
    ("per_1m_characters", re.compile(
        r"(?:\bper\b|/)\s*(?:1\s*m(?:illion)?|million)\s*characters?\b", re.I)),
    ("per_1k_requests", re.compile(
        r"(?:\bper\b|/)\s*(?:1[, ]?000|1\s*k|thousand)\s*requests?\b", re.I)),
    ("per_request", re.compile(r"(?:\bper\b|/)\s*request\b", re.I)),
    ("per_image", re.compile(r"(?:\bper\b|/)\s*image\b", re.I)),
    ("per_user_month", re.compile(
        r"(?:\bper\b|/)\s*(?:user|seat)\s*(?:per|/)?\s*month\b", re.I)),
    ("per_gpu_hour", re.compile(
        r"(?:\bper\b|/)\s*(?:GPU|GPU[- ]hour)\s*(?:per|/)?\s*hour\b|/\s*GPU[- ]hour\b", re.I)),
    ("per_ocpu_hour", re.compile(
        r"(?:\bper\b|/)\s*OCPU\s*(?:per|/)?\s*hour\b", re.I)),
    ("per_vcpu_hour", re.compile(
        r"(?:\bper\b|/)\s*vCPU\s*(?:per|/)?\s*hour\b", re.I)),
    ("per_hour", re.compile(r"(?:\bper\b|/)\s*hour\b", re.I)),
    ("per_minute", re.compile(r"(?:\bper\b|/)\s*minute\b", re.I)),
]
DIMENSION_PATTERNS = [
    ("batch_cached_input", re.compile(r"\bbatch\b.*\bcach(?:ed|ing)?\b.*\binput\b", re.I)),
    ("batch_output", re.compile(r"\bbatch\b.*\boutput\b", re.I)),
    ("batch_input", re.compile(r"\bbatch\b.*\binput\b", re.I)),
    ("cache_write", re.compile(r"\b(?:cache (?:write|creation)|write to cache)\b", re.I)),
    ("cached_input", re.compile(r"\b(?:cached input|input cach(?:ed|ing)?|context caching)\b", re.I)),
    ("input", re.compile(r"\binput\b", re.I)),
    ("output", re.compile(r"\boutput\b", re.I)),
    ("subscription", re.compile(r"\b(?:seat|user)\b.*\bmonth\b", re.I)),
    ("usage", re.compile(r"\b(?:unit price|usage price|request price|hourly rate|rate)\b", re.I)),
]
REGION_RE = re.compile(
    r"\b(?:region|location)\s*[:=]\s*"
    r"(global|worldwide|us-east-\d|us-west-\d|eu-[a-z]+-\d|"
    r"ap-[a-z]+-\d|US East|US West|EU West|EU Central|Asia Pacific)\b", re.I,
)
TIER_RE = re.compile(
    r"\b(?:tier|plan)\s*[:=, -]+\s*(free|paid|standard|priority|enterprise|"
    r"pro|business|batch|on[- ]demand|provisioned)\b"
    r"|\b(free|paid|enterprise|standard|priority|business|on[- ]demand|"
    r"provisioned)\s+tier\b", re.I,
)


def clean(value, limit=500):
    return " ".join(str(value or "").split()).strip()[:limit]


def detect_unit(*scopes):
    """Only accept unambiguous units explicitly printed in a relevant scope."""
    for scope in scopes:
        hits = {name for name, pattern in UNIT_PATTERNS if pattern.search(clean(scope, 1500))}
        if len(hits) == 1:
            return next(iter(hits))
        if len(hits) > 1:
            return None
    return None


def detect_dimension(*scopes):
    for scope in scopes:
        found = [name for name, pattern in DIMENSION_PATTERNS
                 if pattern.search(clean(scope, 600))]
        if found:
            # A column with combined input/output or overlapping billing
            # modes is not a single independent rate.
            found = list(dict.fromkeys(found))
            if found[0] in {"batch_cached_input", "batch_input", "batch_output", "cache_write",
                            "cached_input", "subscription"}:
                return found[0]
            if "input" in found and "output" in found:
                return None
            return found[0]
    return None


def detect_currency(raw_cell, *scopes):
    raw = clean(raw_cell, 400)
    explicit_cell = {x.upper() for x in CURRENCY_RE.findall(raw)}
    if len(explicit_cell) > 1:
        return None
    if explicit_cell:
        return next(iter(explicit_cell))
    # Euro/pound signs are distinct, while dollar and yen signs alone are not.
    if "€" in raw:
        return "EUR"
    if "£" in raw:
        return "GBP"
    for scope in scopes:
        currencies = {x.upper() for x in CURRENCY_RE.findall(clean(scope, 1300))}
        if len(currencies) == 1:
            return next(iter(currencies))
        if len(currencies) > 1:
            return None
    return None


def _extract_one(pattern, scopes):
    for scope in scopes:
        s = clean(scope, 350)
        hits = [x.group(1) or x.group(2) for x in pattern.finditer(s)]
        hits = [clean(x, 80) for x in hits if x]
        if len(set(hits)) == 1:
            return hits[0]
        if len(set(hits)) > 1:
            return None
    return None


def detect_region(*scopes):
    return _extract_one(REGION_RE, scopes)


def detect_tier(*scopes):
    return _extract_one(TIER_RE, scopes)


def analyze_cell(raw_cell, *, model_label, column_header, row_header,
                 table_context, table_caption, footnotes=""):
    """Separate observable text from a safely comparable Decimal candidate."""
    raw = clean(raw_cell, 900)
    context = clean(table_context, 1200)
    heading = clean(column_header, 500)
    row_name = clean(row_header, 350)
    currency = detect_currency(raw, heading, table_caption, context)
    unit = detect_unit(heading, row_name, table_caption, context)
    dimension = detect_dimension(heading, row_name)
    region = detect_region(heading, row_name, table_caption, context)
    tier = detect_tier(heading, row_name, table_caption, context)
    model = clean(model_label, 180) or None
    reasons = []
    state = "not_displayed"
    for name, pattern in NON_NUMERIC:
        if pattern.search(raw):
            state = name
            break
    normalized = None
    displayed_amount = None
    amounts = list(PRICE.finditer(raw))
    # If the vendor uses an unadorned number under a labeled currency column,
    # a single number is an observable candidate; do not infer missing currency.
    if state == "not_displayed" and len(amounts) == 1:
        match = amounts[0]
        amount = match.group(3)
        displayed_amount = match.group(0).strip()
        state = "numeric_candidate"
        if not currency:
            reasons.append("missing_explicit_currency")
        if not unit:
            reasons.append("missing_explicit_billing_unit")
        if not dimension:
            reasons.append("missing_price_dimension")
        if not region:
            reasons.append("missing_explicit_region")
        if not tier:
            reasons.append("missing_explicit_tier_or_plan")
        if not model:
            reasons.append("missing_model_or_service")
        if TEMPORAL.search(raw) or TEMPORAL.search(heading):
            reasons.append("time_dependent_or_promotional_price")
        if CONDITIONAL.search(raw) or CONDITIONAL.search(heading):
            reasons.append("conditional_or_tiered_price")
        if FOOTNOTE_MARK.search(raw) or (footnotes and
                ("*" in raw or "†" in raw or "‡" in raw)):
            reasons.append("unresolved_footnote")
        if not reasons:
            try:
                normalized = str(Decimal(amount.replace(",", "")))
            except InvalidOperation:
                reasons.append("invalid_numeric_amount")
    elif state == "not_displayed" and len(amounts) > 1:
        state = "multiple_or_time_dependent"
        reasons.append("multiple_amounts_in_cell")
    elif state == "not_displayed" and not raw:
        state = "not_displayed"
    elif state == "not_displayed" and raw:
        state = "unparsed"
        reasons.append("no_single_price_amount")
    if state != "numeric_candidate" and not reasons:
        reasons.append("non_numeric_or_unresolved_state")
    return {
        "raw_displayed_price": raw,
        "raw_amount_text": displayed_amount,
        "price_state": state,
        "currency": currency,
        "billing_unit": unit,
        "price_dimension": dimension,
        "model_or_service": model,
        "region": region,
        "tier_or_plan": tier,
        "normalized_amount_decimal": normalized,
        "normalization_blockers": reasons,
        "comparable_candidate": bool(normalized is not None and not reasons),
    }
