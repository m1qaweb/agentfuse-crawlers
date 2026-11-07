# P23D4 — Literal Cloudflare token-rate component recovery (review-only)

**November 7, 2026. No publisher GET or Zyte job was executed in this phase.**

## The demonstrated historical problem

The user's real, SHA-pinned November 4 `items_official_pricing_11.json`
contained 177 pricing source Items, none with a fully captured, trusted
rate inventory. Among them, the exact source `cloudflare_workers_ai_pricing`
produced **42 observed composite token-rate cells** in a column explicitly
labeled **Price in Tokens** (33 with two amounts, nine with three).
Examples of the **structure** (numbers here are arbitrary test values):

- `$0.111 per M input tokens $0.222 per M output tokens`
- `$0.111 per M input tokens $0.012 per M cached input tokens $0.222 per M output tokens`

The old parser kept such a whole cell as one
`multiple_or_time_dependent` observation, losing directly displayed
input/output dimensional structure. Neuron-based rates are a different
billing system and MUST NOT be conflated with monetary token prices.

**Important:** A historical parsed Item is NOT independently authenticated
original publisher HTML, proof of current rates, a legal right to crawl, or
human gold. The 42/33/9 counts describe historical review triage only.

## Deterministic narrow fix

An exact-source `cloudflare_explicit_token_components` adapter activates
only when all conditions hold:

- Configured source ID **and exact first-party manifest URL** match
  `cloudflare_workers_ai_pricing`.
- Table column is exactly `Price in Tokens`.
- The row model is explicitly identified with a `@cf/` model ID.
- The entire cell is exclusively two or three **literal, independently
  labeled** `$ amount per M input tokens`, optionally `cached input tokens`,
  and `$ amount per M output tokens`, in that order.
- No footnote, promotions, threshold, date/condition, changed denominator,
  conflicting local table unit, or additional rate is present.
- No cardinality, size, or archive budget is bypassed.

The output is **two or three independent, unverified review candidates**
with each original displayed amount, exact dimension, the source-owned
parent cell text and independent evidence fingerprint, and literal
`per M <dimension> tokens` unit provenance.

**Not inferred:** currency (a `$` sign is not sufficient evidence
to assign USD); region; tier; account/model authorization; vendor
pricing completeness; site ownership rights. Every emitted component
retains `normalized_amount_decimal=null`,
`review_quote_candidate=false`,
`comparable_candidate=false`,
`approved_for_advisor=false` and a mandatory
`cloudflare_literal_tokens_require_independent_publisher_gold` blocker.

The new field `pricing_cloudflare_explicit_token_cells_split` counts
bounded split cells. The existing global inline observation count,
per-source 300-observation cap and `pricing_inventory_complete` fail-closed
behavior remain in force. For those **same** 42 historical cell shapes,
a future permitted parser replay could produce **93 unverified
review components instead of 42 unresolved combined observations**
(51 additional observations), before considering any changes to the page.
This is a *structural projection*, not a new successful Zyte result.

## Cross-component safety and new baseline

- Bump pricing parser revision to
  `evidence_quote_v6_cloudflare_literal_components` and family adapter
  revision to `p23d4_review_only_price_family_v2`.
- Offline assembled pricing windows now accept only properly bound
  `structured_table_labeled_inline_component` evidence with a valid
  source table, bounded index and component count, parent text and
  64-character component fingerprint. They reject any comparable,
  normalized or quote-promoted inline component.
- Existing `scripts/p22c_same_snapshot_replay.py` uses the new local
  revision; archived v5 Items remain historical evidence and are not
  silently upgraded or retroactively treated as the new parser output.
- A v5-v6 comparison requires a **new observation baseline**; it must not
  create a false price increase/decrease or claim a newly launched rate.
- No source manifest, access registry, bulk run plan, production spider
  selection, HTML rights review, Zyte job, DB write, or advisor fact approval
  is changed.

The test suite uses independent *synthetic HTML*, deliberately mismatched
publisher URLs, neuron meter units, changed order, discounts, wrong table
headers, ambiguous models, tampered component metadata, single/dual/triple
cases and an offline assembly/compare integration. Synthetic correctness
does **not** establish publisher accuracy.

## Next operator action — NOT full Zyte crawl

1. **Merge only after CI + review**; compare the new compiled Python/JSON
   egg fingerprint with the **actual remotely installed Zyte** package.
   Github CI can verify local egg equality, not remote installation.
2. In [Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85),
   obtain a genuine independent exact-URL website terms, robots, ownership,
   commercial data-use and private HTML-retention review before running
   *any* new publisher request.
3. If authorized, start one exact-source manual `single_validation`
   Zyte canary with strictly bounded cost/cadence; archive its real
   Items/Requests/Logs and original HTML where licensed.
4. Repeat a separate second round only if safe. Compare literal token
   component values/units with legally retained original HTML and
   independent human source-owned truth. If the markup differs from
   the historical Item, hold it rather than generalizing the adapter.
5. Then complete cross-category canary review, data-driven corrections,
   reviewed bounded P23E authorizations, and supervised P23F small shards.
   P23G reconciles all **460 configured IDs**, including held/non-fetched
   publisher sources. **Only approved source URLs are ever fetched.**

**FULL ZYTE CRAWL = NO-GO:** currently zero genuine approved source
reviews and zero reviewed bulk run plans. A 460-ID inventory audit is
not authorization for 460 GETs. The user's existing daily readiness
check should alert only when independently verified run criteria hold.

## Verification

```bash
python -m pytest -q tests/test_p23d4_cloudflare_literal_token_components.py
python -m pytest -q tests/test_p17b1_inline_token_rates.py
python -m pytest -q tests/test_p11b_pricing_windows.py
python -m pytest -q
```
