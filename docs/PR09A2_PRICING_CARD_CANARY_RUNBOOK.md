# PR09A2 — Structured pricing cards, attribution and honest coverage

**Status:** Draft. No scheduled Zyte jobs, live publisher requests, database changes, secret handling or advisor approvals.

## The live failure baseline

On October 31, 2026 the owner ran three full source-inventory Zyte jobs, accounting for all 460 source IDs. Pricing produced 3,011 structured observations from 51 sources but no fully comparable rate captures, with 83 pricing sources lacking structured pricing evidence. Many modern publisher pages show cards/lists instead of traditional tables.

The uploaded Items/Logs/Requests exports DO NOT contain all complete origin HTML. The new tests use ORIGINAL synthetic markup shaped around observed failure mechanisms, not copied publisher content and not independent real-vendor pricing labels.

## Changes

- agentfuse_crawlers/pricing_cards.py: bounded recognition of explicitly structured pricing/plan/rate cards, label/value paragraphs, list rows, definition lists and exact rate amount elements. Does not scrape unrelated marketing dollar amounts, navigation, forms or footer content.
- Uses explicit model/service headings or returns unknown, with strict card-local region, tier/plan, unit and pricing currency citations. A page-wide currency only applies if explicitly ALL-prices before the cards and not contradicted anywhere. Missing scopes are never guessed.
- Keeps raw Free/Contact sales/promotion and unresolved currencies/regions as unapproved evidence, never numeric comparable prices. Supports explicitly printed seat/month subscription billing, not inferred subscriptions.
- Combines table and card candidates under a single MAX_OBSERVATIONS=300 budget. Exposes detected/retained/omitted row counts, number of recognized cards, oversized candidates, truncated card scans and same-identity contradictions. Incomplete source inventories remain partial_capture.
- Deduplicates identical fully scoped table/card observations and invalidates conflicting price amounts with the same identity.
- Tightens generic model attribution: a heading like "Model pricing" or a row label "Input rate" never becomes a specific model name.
- Adds pricing_parser_revision=structured_cards_v2. Both JSON export and immutable Zyte archive comparators reset the first changed-parser snapshot to a fresh baseline, not a first-seen vendor price increase or newly launched model.
- scripts/audit_pricing_items.py now reports card coverage and parser revision for private before/after source exports.

## Reproduce offline

Install normal project dependencies and run:

    python -m pytest -q tests/test_p09a2_pricing_cards.py tests/test_pricing_evidence.py tests/test_p09a_pricing_scope.py
    python -m pytest -q
    python -m scripts.replay_gold --out output/p09a2/synthetic_report.json
    python -m scripts.quality_gates --synthetic-report output/p09a2/synthetic_report.json --out-dir output/p09a2/gates

The final quality-gates report MUST say BLOCKED without 200+ independently labeled real rate observations, verified publisher permissions and two official repeat canary rounds. Synthetic regression results are not genuine vendor accuracy.

With the prior owner private Items, generate the original evidence baseline (no external calls):

    python -m scripts.audit_pricing_items --items /private/items_official_pricing_6.json --out-dir output/p09a2/before --expect-all

## Manual targeted Zyte validations only after review

1. Merge PR09A2 only to real main after CI and code review. Confirm latest egg revision in Zyte.
2. Check each intended publisher robots policy and terms. Use one approved exact source ID per spider job in validation mode; never a new daily periodic schedule.
3. Select a real pricing page with verified card markup, preferably among the original 83 non-table sources. An OpenAI pricing table source is useful as a control. Do NOT assume this fix recovered all 83 pages.
4. Build the exact two-round manual plan via scripts/canary_rollout.py; pass cohort=all, source_ids=<one exact ID>, collection_mode=validation and pinned expected manifest/selection/registry hashes.
5. Archive completed Zyte jobs and inspect their Items/Requests/Logs. Run the offline auditor on the one-source pricing Items without --expect-all; compare card counts, evidence completeness, and missing currency/region/tier before/after.
6. Manually review the actual first-party page against EVERY proposed comparable amount, model, rate dimension, currency, region, tier, billing unit, footnote and promotion. Never publish or normalize missing dimensions by assumption.
7. A second distinct finished same-parser, source-policy-permitted job is necessary to validate actual rate diffs. Treat cross-parser comparisons as a baseline, not news.

## Known gaps

Static HTML only: this does NOT execute publisher JavaScript, click tabs, bypass access controls, scrape hidden content, verify provider truth, prove regional completeness, recover all old 300+ rate candidates or solve cross-product price-list attribution. Generic card markup without explicit pricing markers remains unrecognized.

Upcoming work: publisher-specific reviewed HTML variants and independent golden labels, Claude Code/release-date fixes (P09B2), documentation scope and canonical/redirect hygiene (P09C), then two-repeat safety/accuracy canaries and Zyte version provenance.

**Never enable automatic advisor facts or unattended monitoring from a green synthetic test.**
