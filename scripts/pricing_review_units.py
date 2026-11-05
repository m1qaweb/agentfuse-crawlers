"""P22B2: exact, review-only billing unit contract for independent price gold.

The deployed parser's unit vocabulary is authoritative. Only explicit
synonyms with the SAME denominator map to that vocabulary. Never convert
prices between 1k and 1m tokens, infer currencies from symbols, infer a
missing human unit, or approve a publisher fact. This is offline ONLY.
"""
from agentfuse_crawlers.rate_units import UNIT_PATTERNS

CANONICAL_RATE_UNITS = frozenset(key for key, _ in UNIT_PATTERNS)

# Exact semantic aliases, NOT numeric denomination conversions.
# These are source-review form vocabulary variants, not guessed vendor units.
REVIEW_UNIT_ALIASES = {
    "per_million_tokens": "per_1m_tokens",
    "per_thousand_tokens": "per_1k_tokens",
    "per_million_characters": "per_1m_characters",
    "per_thousand_requests": "per_1k_requests",
    "per_thousand_queries": "per_1k_queries",
    "per_user_per_month": "per_user_month",
}


def canonical_review_unit(raw, *, strict=True):
    """Return canonical code or None for UNKNOWN; reject unsafe text when strict.

    'per_million_tokens' and 'per_1m_tokens' denote the same unit.
    'per_1k_tokens' is a DIFFERENT unit and never re-scales an amount.
    A human reviewer must supply or hold unknown scope explicitly.
    """
    if raw is None:
        return None
    if not isinstance(raw, str) or not 1 <= len(raw) <= 80:
        if strict:
            raise ValueError("Billing unit must be an explicit supported unit code or null")
        return None
    token = raw.strip().casefold()
    canonical = REVIEW_UNIT_ALIASES.get(token, token)
    if canonical in CANONICAL_RATE_UNITS:
        return canonical
    if strict:
        raise ValueError("Unknown or ambiguous human billing_unit; hold for manual review")
    return None


assert set(REVIEW_UNIT_ALIASES.values()) <= CANONICAL_RATE_UNITS
