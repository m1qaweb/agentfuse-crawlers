# P11A — Read-only pricing evidence and quote-scoping upgrade

## Motivation / live audit

The November 1 full-inventory run accounted for all 177 pricing sources but
none yielded fully comparable prices. The latest export includes numerous
numeric prices with missing or ambiguous currency, region, tier, unit,
subscription or promotional conditions. This PR does NOT solve review coverage,
full vendor pricing completeness or price verification.

## Exactly what changes

- New pricing parser revision \`evidence_quote_v3\`; old v2 extracts require a
  **new baseline**, never automatic price-change detection across revisions.
- For each single numeric price cell, retain
  \`observed_single_amount_decimal\` as an unverified observed number.
- \`review_quote_amount_decimal\` and \`review_quote_candidate\` require an
  explicit currency code, billing unit, price dimension and specific model;
  missing region and/or plan remain blockers. No conditional, promotional,
  footnoted, negative or multi-amount quote qualifies.
- \`normalized_amount_decimal\` and \`comparable_candidate\` remain STRICT.
  Unknown currency, region or plan, time-dependent rates, discount and
  footnotes are not promoted. Advisor and alert approvals stay false.
- Every observation marks region/tier applicability as explicit or unspecified,
  and flags unqualified dollar signs rather than inventing USD.
- Exact, publisher-written "Rates are the same across all regions/plans" scoped
  immediately above a specific table can establish a cross-region/plan
  applicability candidate. Contradictory scopes are unresolved.
- "Prices in USD" / "Rates are in EUR" may scope only the NEXT table. A
  publisher's $ symbol or another product's currency never becomes USD.
- Caching write for 30 minutes and 12 hours, cached input reads and generic
  cache writes have distinct rate dimensions. 1,000 queries differs from
  1,000 requests. A plan/month denomination differs from a seat/month.
- Narrow structural subscription plan blocks may be observed without special
  CSS classes, only with a unique named plan heading and a same-container
  exact currency amount/period pair. These remain explicit
  \`subscription_plan_needs_review\` observations, NOT comparable API rates.
- \`scripts.audit_pricing_items\` reports source counts for observed money,
  review-ready quotes and fully comparable rates separately.

## Limitations

- Single-page HTML cannot prove coverage of a publisher's full pricing
  catalog. Dynamic tabs, regional variants, marketing discounts and API
  service rates may be missing.
- Current \`MAX_SELECTED_TABLES=64\` and \`MAX_OBSERVATIONS=300\` still
  explicitly report incomplete giant pricing inventories such as Gemini API
  and AWS Bedrock. P11B will add bounded, independently auditable capture
  windows; do NOT fake completeness by silently raising byte limits.
- In P11A, a page can contain more review-ready quotes while
  \`pricing_comparable_candidate_count\` remains zero. This is expected,
  because observability and comparability are different.
- Synthetic tests are NOT a price accuracy validation corpus and must not
  be used to approve publication or unattended monitoring.

## Manual validation

1. Review code and green CI on Python 3.12 and 3.14; verify all 460 sources
   and same three spiders remain intact.
2. Merge only after review. Confirm actual Zyte deployed package fingerprint
   from P10 before scheduling a canary.
3. With reviewed publisher access, run pin-scoped validation for
   \`anthropic_api_pricing,openai_api_pricing,kiro_pricing,gemini_api_pricing\`.
   Use original deployed source URLs and collect Items, Requests, Logs.
4. Check Kiro plan candidates are review-only, Anthropic has explicit USD
   evidence where present, OpenAI '$' remains currency-unknown, and
   Gemini time-dependent multi-price rates are not normalized.
5. Independently label 200 real pricing examples for quality gates; compare
   parser rate dimensions against official visible evidence before publishing.

No Zyte schedule, source manifest, policy registry, AgentFuse/Supabase data,
or existing production recommendation is changed by this milestone.
