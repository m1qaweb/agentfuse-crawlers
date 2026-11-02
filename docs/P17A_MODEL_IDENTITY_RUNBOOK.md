# P17A — Exact Pricing Model Identity Guard

**Goal:** fix a real, measured source attribution defect before trying to
normalize more prices or run another full 460-source crawl.

## Actual baseline: November 2 Zyte pricing Items

The frozen \`items_official_pricing_10.json\` has 177 pricing source
summaries with 3,050 retained price observations, 110 quote candidates
and **zero fully comparable rates**. Independent local triage found:

- **42 of the 110 quote candidates** have model labels matching a
  high-confidence *possible marketing-description contamination* pattern.
- **32** of those are in \`xai_pricing\` (e.g. observed
  \`grok-4.7Long context ≥ 200k tokens\`).
- **10** are in \`anthropic_api_pricing\` (e.g.
  \`Claude Fable 5.1For demanding reasoning...\`).

The 42 is an *unreviewed risk count from historical extracted Items*, not
42 verified incorrect rates. These records show why accurate model identity
must precede provider-specific price normalization. P16A's title/product
check cannot detect contamination inside an otherwise correct pricing table.

## What P17A changes

- \`agentfuse_crawlers/model_labels.py\` adds structural, DOM-aware model
  label detection. A **single, prominent, leading** model name in a table
  cell (\`<strong>\`, \`<code>\` or explicit model-name CSS marker) may
  separate a model identity from adjacent product description text.
- Multiple prominent candidate model identities, an unstructured
  concatenated marketing description or very long prose are **review
  required**, never canonical model IDs. The visible raw row evidence
  remains available for human inspection.
- Pricing table text fragments no longer silently glue neighboring HTML
  node strings together. However, no guess is made about a model name if
  the markup does not independently identify one.
- The parser emits \`model_label_hygiene_status\`,
  \`model_label_requires_review\`,
  \`pricing_model_label_recovered_rows\` and
  \`pricing_model_identity_review_rows\`, preserving the raw source
  evidence locator. Unresolved identity blocks numeric comparability
  and quote eligibility.
- Extractor revision becomes
  \`evidence_quote_v4_model_identity\`; the bounded pricing-window
  assembler checks that same revision. Historical P11B/P14A jobs must
  not be compared as if their model identity keys were unchanged.

**IMPORTANT:** This does **not** impute USD from \`$\`, assign Global
to an unspecified region, invent the Standard tier, combine input/output
prices, resolve footnotes, or treat a source table as complete. The vendor
fact still requires human-reviewed source evidence before AgentFuse may
publish a rate or compare two models.

## Operator-only historical risk audit (no Zyte run)

\`\`\`bash
python -m scripts.triage_pricing_model_identity \
  --pricing-items /private/items_official_pricing_10.json \
  --out-dir output/private/p17a-model-label-audit
\`\`\`

The tool requires all 177 current pinned pricing source IDs from the
same \`cohort=all\`, registry, package and Zyte job. It outputs:
- \`pricing_model_identity_risks.json\`: all-source risk totals, and
  the source IDs with contaminated review quotes.
- \`pricing_model_identity_review_queue.csv\`: prioritized review actions
  and at most two quoted raw model labels per source.

No source/page content or private Items are written to GitHub. It is a
**post-extraction** risk report, not a re-parse of the original publisher
HTML. It cannot establish that P17A improved real accuracy.

## Verification, rollout, next step

CI synthetic regression cases cover:
- Claude-style prominent model plus adjacent descriptive span;
- xAI-style model-name marker plus long-context description;
- two bold model identities in one row (reject);
- concatenated prose without a leading DOM marker (reject);
- numeric cell text-node whitespace, column dimensions and stable rate
  identity, while retaining unverified status;
- default currency/region/tier missing (still block);
- strict 177-source provenance and absence of unauthorized approvals.

To measure actual accuracy improvement, save **permitted original pricing
HTML** for a small varied cohort, replay both P17A and the previous
package against the exact same bytes, and use P15B independent publisher
gold to assess model identifiers and rates. Dashboard JSON Items alone
cannot re-run DOM parsing and are not ground truth.

The next P17B stage can address provider-specific rate schedules,
*explicitly observed* currency/units, time-dependent prices and
regional pricing across independently labeled genuine publisher pages.
Do not globally loosen required dimensions to turn zero comparable rates
into a misleading high score.

**No live Zyte job, no source registry change, no migration, no
monitor-mode promotion and no production AgentFuse database writes.**
Merging a PR to \`main\` may still auto-deploy a new package to Zyte;
review CI and release policy before merge.


### Context-condition refinement

An explicitly separated model-name cell can also contain pricing
**conditions** such as \`Long context ≥ 200k tokens\` in an ordinary
\`span\`, not only a footnote. P17A preserves the correct model ID but
adds \`model_row_price_scope_qualifier_unresolved\` and blocks numeric
comparison and price-review quotes until the publisher's exact context
schedule is independently established. More text or better model naming
must never erase long-context/batch/cache rate dimensions.
