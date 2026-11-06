# P22C2B — Independent paginated human pricing review and source-cell adjudication

**Scope: ONE preselected pricing source and ONE of its two original HTML
capture rounds. All publisher access, capture and original HTML retention
must be independently reviewed and permitted BEFORE the private workflow.**

P22C2A (#76) proved that P22C1 can identify more physical table-rate cells
on the same original page, but the old P22A2 form has a 200-label/source
ceiling. P22C2B adds an **independent, private, paginated** review path
capable of recording up to **1,600 human price labels** across at most
160 bounded original-row pages. It does NOT simply relax the legacy
P22A2 global limit or prefill gold from the parser.

## Preserved scientific and permission controls

- The P20A study denominator remains **18 preselected sources × 2
  original rounds = 36**, including exactly six pricing sources and
  twelve pricing rounds. **Never swap an inaccessible source** for an
  accessible one.
- Each source snapshot comes from a P22A1 **operator-attested,
  source-specific** permitted original capture ledger. The script
  independently checks the file SHA, exact configured source URL, capture
  timestamp and reviewed terms/robots/retention window under the
  existing P22A1 validator. Such a ledger is NOT cryptographic
  publisher-origin authentication or a legal rights determination.
- This path measures only **selected recognized, visible, static HTML
  table rows**. It deliberately rejects a page with unrecognized
  tables, rowspans, colspans or nested table grids. Cards, JS state,
  hidden plans, alternate product URLs and publisher catalog coverage
  are not scored. Even a completed review is **NOT** whole-vendor accuracy.
- Neither the scripts nor GitHub Actions fetch any publisher webpage,
  initiate Zyte jobs, authorize bulk runs, grant permissions, store
  credentials, send alerts or write trusted AgentFuse facts.
- All reviewer identities, raw HTML, ledger and completed forms must stay
  **PRIVATE**. Only synthetic examples may appear in GitHub CI.

## Step 1 — prepare original row-page blind tasks

Using exact, genuinely permitted original HTML and the private P22A1 ledger:

    python -m scripts.p22c2b_paginated_pricing_review \
      --prepare-blind \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/publisher_original_html \
      --source-id deepseek_pricing \
      --round 1 \
      --rows-per-window 64 \
      --out-dir /secure/p22c2b-blank-review

The example source ID is part of the frozen six-source cohort, but **does
not authorize any request**. If this exact source or round is held,
record that fact instead of fabricating bytes or substituting another URL.

Creates a new directory (private permissions):
- source_original_table_blind_task_bundle_PRIVATE.json
- source_independent_human_A_BLANK.json
- source_independent_human_B_BLANK.json

The bundle contains original source ID/URL, exact snapshot SHA-256,
parser/version and source registry fingerprints, window IDs, row indexes
and ORIGINAL row SHA-256s. It exposes **no extracted rate values, model
predictions or parser results to blind human reviewers**.

For a 400-data-row table, 64 rows per page yields **seven pages**.
Every original data row and each of its direct physical table cells
appears once, never just the rows or cells the parser recognized as rates.

## Step 2 — genuine independent human A and B original-source reviews

Two *different* humans independently inspect the entire relevant
static source table content (with original publisher HTML available
privately). Neither may view parser predictions or the other's form
before completing their own. In each BLANK form:

1. Provide a real reviewer_id, set
   independent_blind_review_attested=true only after independent work,
   and keep parser_predictions_seen_before_review=false.
2. Complete **every** page: review_completed=true, genuine
   reviewed_at_utc after original capture, substantive review_note.
3. For **every ORIGINAL CELL** in each row, fill cell_reviews with
   rates_labeled, explicit_no_relevant_rate or ambiguous. A visible
   model-name cell with no monetary price should be explicitly no-rate;
   both input and output rate cells require their own decisions. The
   row-level disposition must agree with all its cell decisions:
   ambiguous if any cell is ambiguous; otherwise rates_labeled if any
   cell has rate evidence; otherwise explicit_no_relevant_rate.
4. For each rates_labeled CELL, record at least one real monetary rate
   (maximum 8 distinct labels per physical data row) using
   original_column_index, ORIGINAL cell SHA-256,
   a directly copied original visible CELL quote (not a guessed label),
   reviewed_value (amount/currency/unit/direction/model/region/tier/
   applicability/conditions) and a substantive review_note.
5. Keep approved_for_advisor=false on every label and form. Do not
   invent missing USD from "$", default plan, region or denominator.
   Use the P22B2 canonical billing-unit vocabulary or its short
   same-denominator synonym list. A rate missing required dimensions
   cannot support strict typed scoring.
6. If a row's evidence or scope is ambiguous, use disposition=ambiguous.
   Such a row **HOLDS the entire source-round accuracy evaluation**;
   it is never automatically counted as a false negative.

The system confirms that the original row and cell bytes are unchanged;
each selected quote must occur within the exact original cell and contain
the human-labeled numeric price. Identical price strings can legitimately
occur in many rows: original table/row/column SHA-bound locator is the
identity, **not global quote uniqueness**.

The two complete human forms must independently agree on **all** row
dispositions, all physical cell dispositions, and typed labels. A
single disagreement, ambiguity,
missing page or partial review stops scoring rather than silently
discarding that row.

This protocol extends the **P22A2 table-label capacity** without
weakening P22A2's existing 200-label limitation in other tasks.

## Step 3 — prepare the independent THIRD adjudicator

Only AFTER both independent A/B reviews are finished, prepare:

    python -m scripts.p22c2b_adjudicate_pricing_rows \
      --prepare-third \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/publisher_original_html \
      --bundle /secure/p22c2b-blank-review/source_original_table_blind_task_bundle_PRIVATE.json \
      --reviewer-a /secure/reviewer_A_COMPLETED.json \
      --reviewer-b /secure/reviewer_B_COMPLETED.json \
      --out-dir /secure/p22c2b-third-private

This recomputes the original HTML, source IDs, A/B consensus, P22C1
same-byte row-window extractor receipts and complete parser candidate
inventory. It creates:
- p22c2b_parser_vs_human_ADJUDICATION_PACKET_PRIVATE.json
- p22c2b_third_human_ADJUDICATOR_BLANK.json

The third human must be genuinely different from A and B. They must
inspect original cell evidence and account for **every** strict
comparable parser prediction and **every** agreed human reference
exactly once: one-to-one matches, unmatched_prediction_ids, or
missed_reference_ids. For each match include a substantive
same_original_cell_note.

**A match requires the identical original table, row, column and cell
SHA-256**. Identical numeric strings, similar model names, or
nearby rows are insufficient. An incorrect amount, billing unit,
currency, price dimension, model or scope that the third reviewer
associates with the *correct physical cell* counts as **one FP and
one FN**, not a true positive.

Unqualified parser observations remain separately counted for triage;
they do not count as qualified predictions. A human reference that
the parser never qualifies contributes a genuine source-table FN
only after the human source census is complete.

## Step 4 — score the frozen original source, offline

After actual third-person review:

    python -m scripts.p22c2b_adjudicate_pricing_rows \
      --score \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/publisher_original_html \
      --bundle /secure/p22c2b-blank-review/source_original_table_blind_task_bundle_PRIVATE.json \
      --reviewer-a /secure/reviewer_A_COMPLETED.json \
      --reviewer-b /secure/reviewer_B_COMPLETED.json \
      --packet /secure/p22c2b-third-private/p22c2b_parser_vs_human_ADJUDICATION_PACKET_PRIVATE.json \
      --third-human /secure/THIRD_HUMAN_COMPLETED.json \
      --out-dir /secure/p22c2b-scored-private

The scorer **reconstructs the entire frozen original HTML/parser/review
packet**; it rejects modified pages, stale packages, changed A/B forms,
fabricated parser predictions, duplicate matches, unaccounted-for
identities, future timestamps or cross-cell mappings.

Output (new private directory):
- p22c2b_original_table_row_accuracy_NOT_VENDOR_TRUTH.json

The report contains conditional, **source-local selected static-table**
strict TP, FP, FN, precision, recall and exact typed field diagnostics.
It also identifies the original 18/36 and pricing 6/12 cohort,
the fraction of unqualified parser observations, and how many
data rows/pages were fully accounted.

A 400-row synthetic test may score 100% under its **invented test gold**;
that is not genuine price accuracy, proof of reviewer independence, proof
of legal permission, or an estimate for all 177 pricing sources.

## Remaining exit criteria before any live P22C2 spider opt-in

- Obtain original legally retainable publisher HTML for actual frozen
  source-rounds, never fabricated or derived from historical request logs.
- Complete real independent A/B reviews and independent third matching.
- Independently verify the publisher's original-page source/product
  provenance and permissible uses, beyond the operator's checkboxes.
- Diagnose any actual false positives, false negatives and rate
  dimensions from source-local adjudicated evidence. Decide whether
  the extra row-window coverage justifies deployable crawler complexity.
- Make a new, separately reviewed **P22C3 live canary** design with
  strict single-URL source authorization, bounded budgets and
  exact deployed package fingerprints. DO NOT just enable bulk crawling.

The original full 460-source diagnostic and all automatic monitoring
remain **ON HOLD** under P21B.
