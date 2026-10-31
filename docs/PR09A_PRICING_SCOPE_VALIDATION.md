# PR09A — Evidence-scoped pricing parser repair

**Scope:** one P0 fix motivated by the owner's October 31, 2026 live Zyte audit. All evidence remains **unverified**. **No production crawl, source approval, scheduler change, or database migration.**

## Reproduced failure

Pricing Zyte job 883514/3/6 recorded 177/177 source summaries, 0 captured/comparable sources, and 3,011 raw price observations across 51 source pages. Currency was recognized in 199 observations; unit in 685; tier/plan in 312; geographic region in **zero**.

The user supplied nine real exported Items/Logs/Requests files, but not complete publisher HTML:
- OpenAI API: visible "Prices per 1M tokens." before tables, but no billing denominator inherited by early price cells
- Anthropic: visible "All prices are in USD." in page text; rate cells such as "$12.50 / MTok" lacked explicit currency and denomination after the old parser lost the context
- Gemini: distinct time-bound values in one cell; they MUST remain ambiguous
- AWS Bedrock: regional prices and omitted tables MUST stay distinct or explicitly partial

## What this PR changes

1. A new pricing_scope.py collects **strictly bounded** short, source-cited pricing declarations. Only explicit "ALL prices" currency may apply page-wide (and only if all such statements agree before the first table). Units and labeled tier/region statements apply **only to the immediate next table**; no leakage through unrelated headings or other tables.
2. rate_units.py now recognizes explicit /MTok and per MTok denominations in price *cells*, in addition to table contexts.
3. pricing_evidence.py attaches per-observation scope_declarations (original text, dimension, value, scope, review_status=unverified) and scope_provenance_verified=false. It does **not** promote an unidentified region/plan to Global/Standard or infer USD from a dollar symbol.
4. scripts/audit_pricing_items.py performs a **read-only** source-by-source audit of actual private Item exports, including dimension coverage, normalization blockers, typed observation counts, and unapproved fact anomaly checks.

The mini HTML fixtures are original synthetic examples **informed by real failure shapes**, not original publisher HTML and NOT independent human-labeled vendor accuracy.

## Reproduce locally

Install the project dependencies and run:

    python -m pytest -q
    python -m scripts.audit_pricing_items --items /private/items_official_pricing_6.json --out-dir output/pricing-baseline --expect-all

Outputs: pricing_run_audit.json and pricing_sources.csv. The original Items files remain unchanged and private.

After PR review and publisher-policy checks, run **separate manual validation jobs** with exact IDs and archived Zyte outputs. Example source-ID scopes:

    Spider: official_pricing
    cohort=all
    source_ids=openai_api_pricing
    collection_mode=validation

Then the analogous manual job for source_ids=anthropic_api_pricing. Never schedule automatic monitoring or repeat all 460 yet. Compare old and new per-source audit files and spot-check original publisher HTML. A higher count of comparable candidates is NOT proof of more accurate prices.

**Release conditions remain:** 200+ distinct independently reviewed real vendor rate records, >=99% exact dimensional precision, no false comparables from ambiguous currency/unit/tier/region, and reviewed publisher policy plus two successful repeat validation canaries. No advisor facts are auto-approved.

## Next reviewable PRs

- P09A2: Price cards and prose, model-row attribution, context scope, and 300-observation truncation with original authorized small HTML examples
- P09B: Stable changelog event identity, per-publisher publication dates, and bounded Claude Code recent-window extraction
- P09C: Curated docs profiles, redirects and official target URL migrations
- P09D: Exact deployed Zyte revision and independent human gold acceptance gate

No private publisher HTML, API credentials, changed schedules or database content is committed.
