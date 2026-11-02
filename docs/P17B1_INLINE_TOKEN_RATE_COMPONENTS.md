# P17B1 — Explicitly Labeled Token-Rate Components (Review Only)

## Why this pilot

The 2026-11-02 full pricing export had **177/177 source summary Items**
but **0 fully comparable** rates. Capturing a price number is not the
same as identifying its model, dimension, region, tier, unit, currency,
date and distribution channel. In particular:

- Fireworks' retained rows show \`$3.00 / $0.30 / $15.00\`, but the
  source excerpt lacks an independently verified mapping from each
  number to a dimension. **Never assign input/cache/output by position.**
- Together AI excerpts show concatenated base and cached amounts.
  **Never infer** that adjacent numbers are distinct independently
  priceable services without a publisher-backed legend.
- Gemini's \`through November 30\` and \`starting December 1\`
  cells are *dated schedules*, not a single current rate. Never pick
  the lower/latest number solely based on the crawl date.
- AWS Bedrock's per-region, commitment and infrastructure rates are
  **not** interchangeable with generic token inference.

P17B1 therefore starts with a **strict reusable model-token matrix
candidate** instead of guessing price semantics across providers.

### Source-verified format: Fireworks official docs

The first-party official document at
https://docs.fireworks.ai/serverless/pricing explicitly states, under
**Text and vision models**, that each Standard or Priority cell lists
**input / cached input / output**, in that order, with **USD per 1M
tokens**. This is *publisher-owned format evidence*, not independently
verified current model prices. The Nov 2 parsed Fireworks export contains
39 multi-amount observations; those Items do not preserve the original
paragraph/HTML, so the new parser must confirm the exact legend on the
current captured page before decomposing anything.

The separate Together and Gemini layouts do **not** inherit that
Fireworks legend. The historical Nov 2 export contains zero cells
matching the stricter semicolon-delimited `Input: ...; Output: ...`
pattern; P17B1's meaningful real-layout hypothesis is the
**legend-backed Fireworks triplet**, not the generic semicolon syntax.

## Implementation

- \`pricing_adapters.py\`: pinned, versioned source-to-family *review*
  mapping of 19 exact existing pricing source IDs across four future
  families: model-token matrices (6), cloud/regional matrices (2),
  seat/plan cards (6), and request/credit metering (5). No host/URL
  discovery, provider ownership verification or new crawl permission.
- The only executable family behavior is **exact inline-labeled
  decomposition** for the six candidate token-matrix source IDs, plus
  a narrowly pinned Fireworks triplet parser that requires a nearby
  identical, publisher-owned order legend in the same section.
- A cell must contain 2–4 semicolon-delimited segments, each with an
  independent **explicit** label \`Input:\`, \`Cached input:\`,
  \`Output:\`, \`Batch input:\`, \`Batch output:\` or
  \`Cache write:\` and exactly one visible amount.
- Unlabeled slash triples remain unresolved **unless** they are from
  the exact Fireworks pricing URL, in the **Text and vision models**
  section, in a **Standard** or **Priority** column, with the original
  publisher paragraph explicitly defining both the 3-price order and
  USD/1M-token unit. The publisher's exact paragraph and hash are
  preserved per component for reviewer verification.
- Multiple/duplicate/unknown labels, unlegend-ed triples, dates,
  discounts, threshold rates, promotional terms, footnotes and
  unrecognized conditions are **not decomposed**. The original
  unsplit evidence remains in the Item for human review.
- Every emitted sub-observation carries its own source evidence SHA,
  a unique component ID, the **original parent cell**, the literal
  price-dimension label and a component count. It is explicitly
  **review-only** and not comparable, even when all dimensions appear
  complete. A P15B independent publisher review would be needed
  before any production price could be emitted.
- Existing P17A DOM model attribution and long-context guards apply
  after decomposition; missing currency, region, plan and unit remain
  absent rather than being defaulted.
- \`pricing_observation_total_detected\` now accounts for extra
  decomposed components **without** falsely increasing the count
  of physical table cells. Over-300 cases remain
  \`partial_capture\`/not inventory complete.
- Parser and P11B bounded window assembler revisions move in
  lockstep to \`evidence_quote_v5_inline_labeled_components\`.
  Previously captured v4 archives are not treated as identical
  pricing keys or proven real vendor price movements.

## Synthetic regression checks

- Three properly labeled, separately recorded input/cache/output
  numbers are individually observable but **0 approved/comparable**.
- Fireworks three-price rows require an **explicit matching
  original-page order legend**; without it, they stay unsplit.
  Together adjacent cached amounts stay unresolved without their
  own independently supported label/column semantics.
- Gemini time-window pricing remains composite and unresolved.
- Unknown USD/Global/Standard never materializes from the provider ID.
- Other pricing families and unprofiled sources stay on the current
  generic parser, not a newly authorized custom adapter.
- Cap and window accounting remain explicit and safe at 300/375.
- Unchanged single amount evidence source hash remains stable.

## What this **does not** establish

This is a parsing-fidelity hypothesis, not the outcome of a
real before/after replay. Do not label a historical Fireworks row as
correct merely because the site's current text explains a three-rate
order: a version change or a different table section could invalidate
the mapping. Only original captured markup + P15B dual human review
can establish operational accuracy.

A passing test proves only deterministic extraction against **synthetic
HTML**. It does not prove original publisher claims, real cross-region
currency, independent P15B human gold, or correct interpretation of
Fireworks, Gemini or Together multi-rate cells. P16B's paired
rendered/static experiments remain offline review-only.

**The next P17B2 milestone** should collect permitted original-page
snapshots for all four families and independently review rate legends,
model/region/plan identity and effective periods before expanding or
authorizing additional component parsing.

Do not launch a full 460-source crawl just to verify this small adapter.
The source manifest, approved source permissions, Zyte schedules, data
retention and AgentFuse/Supabase production database must remain
untouched. Because \`main\` auto-deploys to Zyte, merge only after CI,
manual review and accepting the changed pricing parser revision.
