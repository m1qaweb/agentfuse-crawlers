# P22B2 — Page-wide pricing currency consensus and human-unit compatibility

**Status:** Narrow production normalization-safety correction + OFFLINE reference-scoring compatibility. **No real publisher page captures, independent A/B gold, Zyte jobs, source-policy grants or trusted AgentFuse rates were supplied or created.**

Follows merged P22B1 #70. This is a targeted code-contract fix, not a claim of measured production pricing accuracy.

## Problem 1: late page-wide currency contradictions

The deployed table scope helper previously inspected global "All prices are in USD" statements only before the *first* visible table, while the pricing card helper correctly considered contradictory "All prices are in EUR" statements later on the page. Thus an unqualified dollar-symbol rate could inherit "USD" even when another visible statement contradicted its supposed page-wide applicability.

**Fix:** A table inherits a global currency declaration only if it was visible *before the first visible table* **and** every visible page-wide ALL-prices declaration anywhere on the page agrees. Contradictions after one or more tables invalidate the inherited global currency for **all** tables. A hidden, inert or non-rendered statement cannot poison a visible price (P22B1), and a late declaration cannot retroactively create scope where none existed.

This change does not erase a currency that is independently explicit in the price cell or a local uncontradicted caption; it only refuses the unsafe page-wide inference.

The synthetic test suite covers late contradictory text before/after additional tables and in cards, hidden contradictions, repeated consistent declarations, literal explicit cell currency, and no retroactive late scope.

## Problem 2: falsely incorrect human-reviewed billing units

The deployed price normalizer uses the canonical code **per_1m_tokens**, whereas the P22A2 human review guide originally suggested **per_million_tokens**. P22A3 compared these strings literally. A third reviewer could correctly associate the same source cell and amount but record a false unit mismatch, resulting in an incorrect matched rate counting as one FP plus one FN.

**Fix:** New offline helper scripts/pricing_review_units.py allows only known canonical unit names already supported by the production normalizer plus a small enumerated set of exact same-denominator aliases. P22A2 normalizes accepted human-review entries before A/B consensus. P22A3 also canonicalizes both sides defensively for older filled human forms and refuses unknown unit names as equal.

Examples:

| Human annotation | Parser code | Result |
|---|---|---|
| per_million_tokens | per_1m_tokens | Same billing unit |
| per_thousand_tokens | per_1k_tokens | Same billing unit |
| per_1k_tokens | per_1m_tokens | **Different units**; incorrect if same price/unit pair |
| null | per_1m_tokens | Unknown; incomplete human scope |
| provider_specific_unknown | provider_specific_unknown | Not a valid comparable billing unit |

This is **lexical equivalence**, NOT a factor conversion. A human rate of USD 1.25 per 1,000 tokens is **not** automatically comparable to USD 1.25 per million tokens. Numeric values, currency, direction, model identity, region and tier still require independently grounded exact agreement.

The P22A2 guide now uses canonical per_1m_tokens and documents the narrow supported alias mechanism. Prior review files can still use an explicitly allowed alias; their normalized consent/reference packet hash changes and P22A3 must be re-prepared with the current scripts.

## Validation and impact

The implementation touches:

- agentfuse_crawlers/pricing_scope.py — deployed page-wide currency conflict guard.
- scripts/pricing_review_units.py — offline explicit unit vocabulary.
- scripts/reconcile_cross_category_reviews.py — P22A2 human unit canonicalization.
- scripts/adjudicate_cross_category_accuracy.py — P22A3 strict unit equality.
- tests/test_p22b2_currency_consensus_review_units.py and existing P22A2/A3 tests.
- The P22A2 and P22A3 private operator runbooks.

All pricing observations remain source-linked, unverified and approved_for_advisor=false. No identity validation, human review, permissions, source URLs, Scrapy spiders, package schedule, database or automated production recommendation is enabled by this PR.

**The deployed package fingerprint CHANGES** because pricing_scope.py is a production module. GitHub CI must pass on Python 3.12 and 3.14. After review and merge, verify that Zyte is actually running that new egg fingerprint before one genuinely authorized single-source manual canary. Successful packaging is not evidence that Zyte deployed it.

Even if all regression tests pass, genuine publisher pricing precision/recall remains unknown without P22A1 permitted original HTML, actual P22A2 independent blind source-wide reviewers, and P22A3 third-person exact evidence adjudication. The next broad 460-source crawl remains ON HOLD until publisher-by-publisher access and safe bounded diagnostic gates are satisfied.

**Next task after P22B2:** stop speculative broad parser changes. Obtain real, permitted original-page evidence for the frozen 18-source pilot (or resolve publisher denials truthfully), run the human review/adjudication workflow and prioritize measured false positives/false negatives. Do not create invented gold or bypass access controls merely to populate a benchmark.
