# P19A6 — Attrition-aware, frozen 20-source changelog pilot

## Why this change is necessary

P19A4 freezes 15–25 distinct provisional changelog providers before
collection. P19A5 requires source-specific human-reviewed access/retention
decisions. **One legally denied publisher in a wave should not prevent
research on a different, permitted publisher.** Conversely, excluding the
denied publisher from the sample would make the pilot artificially easy.

P19A6 separates **capture coverage** from **parser owner/date accuracy**.
An unreviewed or inaccessible source is NEVER an observed correct parse,
a zero-error reference case, or a parser false negative. Parser false
negatives require two real full-page human inventories on the SAME
permitted and hash-bound original publisher HTML.

P19A6 does NOT validate publisher truth, independently certify legal
permission, run publisher requests, invent human labels, install a
publisher adapter, or approve AgentFuse recommendations.

## 1. Freeze your P19A4 selection and P19A5 policy research

If the pilot plan and policy ledger already exist, use the original
ones and the original keys. **Do not rotate keys to change the sample.**
Relevant documentation:

- docs/P19A4_OPERATIONAL_CHANGELOG_PILOT.md
- docs/P19A5_PUBLISHER_POLICY_PREFLIGHT.md

20-source example: 4 frozen waves, 5 sources per wave. Every publisher
has one policy decision, including pending/deferred/blocked.

## 2. Manually capture ONE individually eligible source at a time

The P19A1 CLI still requires explicit --capture, --policy-reviewed,
publisher-specific retained private evidence and robots verification.
It now accepts an exact **ordered nonempty subset from one frozen
wave**, not just a full five-source wave. Subsets cannot span waves,
reorder source IDs or contain a publisher denied by P19A5.

For an eligible source SID in the frozen wave_01:

    export AGENTFUSE_RELEASE_PILOT_SELECTION_KEY='YOUR_PRIVATE_EXISTING_SELECTION_KEY'
    export AGENTFUSE_RELEASE_GOLD_SPLIT_KEY='YOUR_DIFFERENT_PRIVATE_GOLD_KEY'

    python -m scripts.capture_release_html \
      --source-ids SID_FROM_WAVE_01 \
      --capture --policy-reviewed \
      --policy-review-note "I independently checked this source's actual ownership, terms, robots, product scope and retention rights." \
      --pilot-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --out-dir output/private/changelog-pilot-captures-1/wave_01/SID_FROM_WAVE_01

Each subdirectory MUST contain the original P19A1-generated:
frozen_release_snapshots.json, capture_audit.json, and raw .html.
Never fabricate these receipts for real sources. P19A1 itself
checks robots and strict exact original HTTPS URLs and fails closed
on redirects, denial, or unexpected content.

For another source use wave_01/OTHER_SID; for a different batch use
wave_02/SID. The P19A6 staged format supports this 1-source
per directory layout to avoid mixing robots receipt provenance.

A legacy P19A5 full-wave original capture at
capture-root/wave_01/ is also supported **only if all five publishers
in that wave were independently eligible**. Mixed full-wave and
per-source captures for the same wave are rejected.

**If the publisher disallows access or HTML capture fails:** do not
retry stealthily, forge approval, or swap source IDs. Leave the
original capture directory absent and record the publisher's policy
decision. A policy-eligible source with no capture is separately
reported as "eligible_but_original_html_not_supplied", which does
not establish the reason for the failed fetch.

## 3. Offline stage, including all denied/missing source IDs

    python -m scripts.stage_release_pilot_attrition \
      --stage-partial \
      --input-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --capture-root output/private/changelog-pilot-captures-1 \
      --out-dir output/private/changelog-pilot-staged-1

This command does **not** fetch publisher pages. It independently
recomputes P19A4 selection, the P19A5 policy receipt and each
provided P19A1 capture's exact original HTML hash, source URL,
robots audit and timestamp. Blocked-source captures, duplicate
sources, unknown waves, source symlinks, unplanned files and mixed
policy receipt hashes are rejected before writing.

Outputs are new-only private files (owner-only permissions on POSIX):

    changelog-pilot-staged-1/
      full_frozen_selection_accounting.json
      captured_subset_review_cohort.json
      wave_01/                   (only when >=1 source was captured)
        capture/
          frozen_release_snapshots.json
          SID-source-hash.html
        capture_audits/
          SID.json              (unaltered original P19A1 audit)
        replay/
          changelog_html_replay.json
        census/
          blind_source_census_packet.json
          reviewer_a_template.json
          reviewer_b_template.json
      wave_02/
      ...

IMPORTANT: full_frozen_selection_accounting.json includes **EVERY**
original selected source, its provisional provider group, original
batch, exact configured URL, P19A5 policy decision, missing/captured
state and optional capture hashes. No approved/verified release
facts, news alerts or completed reviewer labels are present.

The P19A3-shaped "captured_subset_review_cohort.json" intentionally
contains only sources for which original HTML was lawfully supplied.
This file is an intermediate INPUT; its raw accuracy metrics MUST NOT
be read alone as 20-source results. Use P19A6 --score-partial, which
reconciles the full original denominator.

## 4. Obtain REAL independent full-page human release inventories

Reviewer A and Reviewer B each receive the exact same staged original
HTML, but not the parser predictions or each other's labels. Follow
docs/P19A2_BLIND_RELEASE_CENSUS_GOLD.md exactly.

Only after independent completion create the private filenames:

    wave_01/census/reviewer_a_filled.json
    wave_01/census/reviewer_b_filled.json

Reviewers must identify all visible release owners, including ones
the parser missed; exact publisher evidence quotes and dates or
explicit unknowns must be corroborated with the original page.
Empty templates are not signed human reviews.

## 5. Offline score with the ORIGINAL source denominator

    python -m scripts.stage_release_pilot_attrition \
      --score-partial \
      --input-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --staged-root output/private/changelog-pilot-staged-1 \
      --out-dir output/private/changelog-pilot-scored-1

P19A6 recomputes the P19A3 frozen-HTML and independent human
label comparisons for each captured source, then **reconciles those
observations to the original P19A4 20-source selection**.

Report fields distinguish:
- original_selected_sources: e.g. 20
- captured_original_html_source_count: e.g. 15
- missing_policy_capture_or_review_source_count: e.g. >=5
- selection_capture_coverage: 15/20
- selection_reviewed_and_scored_coverage: <=15/20
- underlying P19A3 development/holdout metrics: ONLY on scored
  and manually reviewed original HTML (never general accuracy).
- frozen_selected_sources: one row PER originally selected publisher,
  with explicit policy/capture hold reason or evidenced owner/date
  metrics when available.

If no source was legally capturable, the report contains 20 held
entries and **no invented accuracy fraction**. A failed full-page
review remains held even if the HTML itself was captured. If there
is any selection attrition or held scored source, the top-level
pilot_sample_coverage_diagnostic_ready remains false.

No parser precision, recall, publisher origin or latest release date
is implied for an inaccessible source. Sample coverage cannot be
inflated by removing difficult pages.

## 6. Mandatory limitations

A successfully hash-checked local HTML copy does not independently
authenticate publisher origin, prove that a cached HTML page shows all
release history, or demonstrate factual accuracy. Operator policy
attestations do not establish independently verified legal permission.

This PR changes only offline operator tooling and synthetic tests:
no new source IDs, lifecycle overrides, production data writes, Zyte
jobs/schedules, fourth spider or parser/extractor package change.
Real human-reviewed publisher evidence remains **not collected**
as part of this implementation.

The full 460-source crawl stays on hold. The next meaningful
accuracy work is a real, policy-permitted and source-diverse
original-HTML pilot, with independent human publisher-event reviews.
