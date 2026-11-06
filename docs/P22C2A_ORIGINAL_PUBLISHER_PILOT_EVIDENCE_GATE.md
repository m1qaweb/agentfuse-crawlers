# P22C2A — Evidence-gated pricing row-window pilot

**Status: offline operator gate, NOT authorization to crawl or verification of
publisher accuracy.** This is the next increment after P22C1 #74.

## Why now

P22C1 replays one publisher-supplied HTML snapshot through the actual
pricing extractor in original-row windows, recovering parser-addressable
positions beyond the old 250-row and 300-observation caps. It does not
establish the legal right to retrieve or retain that HTML, prove the bytes
came from the publisher, or measure precision and recall.

P22C2A connects the existing P22A1–A3 framework to the same-snapshot
row-window pipeline **without starting new publisher requests**.

It does four useful things:

1. Freezes EXACTLY the original P20A pricing selection: 6 sources and
   12 expected rounds, inside the original 18-source/36-round study.
   It never substitutes an easier URL when a selected publisher denies
   collection.
2. Revalidates the **operator-attested, source-specific** P22A1 access,
   terms, robots, retention window, original exact URL and raw HTML
   byte hash. This is an attestation check, not independent proof of
   access rights or publisher authentication.
3. Recomputes legacy pricing extraction and P22C1 row-window
   extraction from those SAME original bytes, reporting exact
   parser-observed physical table-cell positions, extra positions
   outside the old cap, lost positions, package fingerprint, structural
   holds and full 36-round attrition. These are **candidate coverage
   diagnostics, NOT actual true-positive/false-negative metrics**.
4. Optionally validates two separate genuinely completed P22A2 blind
   human page-wide reviews. It holds source rounds with disputed,
   missing or dimension-incomplete labels, or with the current
   **200-label/source reference capacity** exceeded.

Even successful dual review does **not** determine whether the
row-window parser captured a price correctly. A distinct third human
adjudicator must still perform original-evidence identity matching
(P22C2B), and real publisher origin and legal reuse remain separate
obligations.

## No-local-repository first step

After merging this PR, run GitHub Actions →
**Prepare Zyte UI preflight (no crawl)** on main.

The downloadable artifact gains
p22c2a-blank/p22c2a_six_pricing_sources_BLANK.json.
It lists the **six fixed pricing source URLs, two rounds each, ALL
pending**, without storing a publisher document, reviewer identity,
access permission or trusted price.

Do NOT upload a populated ledger, publisher HTML or human reviewer
records to public GitHub Actions runs. The no-crawl workflow is for
BLANK templates only.

## Private operator workflow — actual evidence only

A real operator must first determine whether the exact configured
publisher URL can be acquired and privately retained in compliance
with publisher policies. Respect access controls, robots instructions,
terms, and retention deadlines. If denied, record the denied/held
source in P22A1. **Never replace it or bypass a refusal.**

Create and populate the private P22A1 source-policy/capture ledger
using genuine source-specific reviews, verified file SHA-256 and
real original publisher HTML (NOT old Zyte Items/Requests/Logs).
Complete two capture rounds, when allowed, using distinct real
responses and genuine UTC timestamps.

For eligible original source-rounds:

    python -m scripts.p22c2_pilot_readiness \
      --evaluate \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/original_html \
      --source-id deepseek_pricing \
      --round 1 \
      --rows-per-window 64 \
      --out-dir /secure/p22c2a-readiness-1

The deepseek_pricing ID is an example from the fixed cohort; **it
does not grant publisher access**. You may omit reviewer-a and
reviewer-b to inspect offline candidate-coverage and held
review requirements first.

When actual distinct human reviewers A/B have completed the
blind full-visible-page P22A2 forms (before seeing parser
candidates), add:

    --reviewer-a /secure/independent_reviewer_A_FILLED.json \
    --reviewer-b /secure/independent_reviewer_B_FILLED.json

A report is generated in a NEW private directory:

    p22c2a_single_source_pilot_READINESS_NOT_ACCURACY.json

Never edit or overwrite old evidence or invent a human identity.
All source attestations and original pages stay PRIVATE.

## Reading the report correctly

The legacy and P22C1 results share:
- the same exact publisher source ID/URL;
- the same original UTF-8 HTML source bytes and SHA-256;
- the same deployed package fingerprint; and
- the same pricing category and source ownership.

The report distinguishes:

- **Legacy parser-addressable physical rate cells:** distinct
  (table ID, original row index, column index) positions detected
  by the existing bounded parser.
- **Row-window parser-addressable physical rate cells:** the same
  original positions after P22C1 derived-view replay.
- **Additional cell positions:** positions observed by the
  row-window parser but not the old capped parser. They are NOT
  independently verified rates and not proof of recovered FNs.
- **Lost cell positions:** original positions seen by the old parser
  but missing in row-window output; held for debugging, not ignored.
- **Source-wide reviewer status:** true agreement, dispute or not
  supplied. Agreement is operator-attested, not cryptographically
  independently verified.
- **Capacity hold:** the current P22A2 200-label/source cap cannot
  support a human source-wide census of a 400-rate price table
  without a separately reviewed capacity extension or a carefully
  scoped alternative evaluation design.

All pricing facts remain approved_for_advisor=false.
Precision, recall, false positives and false negatives are
NULL, including when 400 numeric candidate cells were detected.

A positive readiness_for_third_identity_adjudicator means the
specific static original page passed these operator and review
gates and may proceed to **independent human identity matching**.
It never authorizes a Zyte job or production price publication.

This is not representative accuracy across 177 pricing sources or
all 460 official documentation/pricing/changelog sources. Missing
dynamic tabs, pricing cards and vendor URL families remain outside
the row-window table-only census.

## Current 400-rate human review capacity blocker

P22A2 currently enforces MAX_SOURCE_LABELS=200, and P22A3
holds incomplete original pricing inventories. A 400-row synthetic
parser replay can validly recover 400 candidate positions yet have
ZERO supported source-wide accuracy metrics. This is intentional:
**do not reduce 400 original prices to 200 review labels and call
the resulting ratio recall**.

The subsequent P22C2B task should implement a separately reviewed
multi-window / paginated human census and third-person exact
matching contract, with all original source-round denominators and
unique publisher quotes preserved. It must be tested on 400-row
synthetic pages and genuine independently reviewed source bytes
before exposing any live P22C2 spider opt-in.

## Safety and deploy status

P22C2A changes only scripts, tests, documentation and a BLANK
GitHub preflight artifact. It does NOT modify the deployable
agentfuse_crawlers package or change the package fingerprint.
No publisher requests, Zyte jobs, schedules, runtime permissions,
Supabase DB writes, advisor recommendation feeds or alerts.

Keep the full 460-source Zyte crawl **ON HOLD** until P21B
per-publisher authorization, independent validation and deployment
provenance are separately complete.
