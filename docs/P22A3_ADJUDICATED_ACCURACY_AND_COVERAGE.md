# P22A3 — Real-evidence adjudicated extraction diagnostics

**Status:** Offline scoring implementation, not completed publisher accuracy.
Follows the merged P22A2 #66 dual-human source-wide original-page census.
No Zyte, external requests, auto-approval, source policy or production DB
writes. This PR changes scripts, tests and documentation only; the deployed
crawler fingerprint is unchanged.

## Why this sub-step exists

P22A1 preserved 18 fixed P20A source IDs across 36 expected source-rounds,
with source-specific access/retention holds and validated original HTML byte
hashes. P22A2 provided two blank, *independent human* full-visible-page
reference review workflows. A matching A/B pair of human labels is not by
itself a measurement of the actual extractor.

**P22A3 joins human references and current deployed parser candidates only
AFTER the A/B source review.** A third independent adjudicator must account
for every eligible source's predicted and manually observed identity.
All files and raw HTML stay in private operator storage; public GitHub
Actions uses synthetic fixtures only. No labels, credentials, access grants,
raw vendor HTML or private reviewer names belong in Git.

## Scoring units — do not conflate them

| Source | Unit and limits | Permissible diagnostic |
|---|---|---|
| Pricing | Fully comparable rate prediction with exact original-page evidence and a completely scoped gold price | Strict rate TP/FP/FN; model/unit/currency/amount/region/tier field equality |
| Changelog | Publisher-owned **unique release permalink**, not guessed title/date | Release-owner TP/FP/FN; separately count matched owner exact publication day |
| Documentation | One distinct **topic on a single captured page** (multiple sections or claims under a topic count once) | Topic-discovery TP/FP/FN. **Not** feature support or documentation corpus coverage |
| Inaccessible, JS-only, disputed, unreviewed, incomplete, wrong-product or truncated sources | None | Explicit held denominator; **NULL** accuracy |

The original P20A source-round denominator stays 36. Each category
accounts for 6 original source IDs × 2 rounds = 12 source-rounds.

A fully comparable price reference needs an exact monetary Decimal
**numerically present in the uniquely quoted ORIGINAL visible HTML**, and
verified-by-human explicit currency, unit, model/service and price direction.
A "free" label, absent numeric rate, different amount, or ambiguous locale
formatted number cannot be silently used as a rate. Re-review such evidence
rather than entering a guessed price; these checks still cannot prove
publisher origin or the legal access decision.
Unknown **region or plan applicability blocks strict price scoring**, rather
than assuming the vendor is global or has a default plan. Human reviewers
can instead mark reviewed_not_applicable after genuine publisher review.
The current parser's own region/tier fields are compared; its output
cannot automatically establish that applicability was independently checked.

Billing units are evaluated through a short, explicit same-denominator
vocabulary contract: the human legacy alias per_million_tokens is
identical to the deployed parser code per_1m_tokens. Per_1k_tokens is
NOT the same denominator and cannot be converted or accepted
automatically. Unknown human unit codes are held/refused, never
reported as correct just because strings matched.

A comparable parser rate's wrong amount, currency, model, unit, tier
or region is **not** a TP even if adjudicated as the same physical cell.
That pair produces one strict FP + one strict FN, while individual field
comparison counts remain available for diagnosis.

A price match requires the parser's material source-cell text to overlap
the original human quote, plus a third reviewer's independent note.
Release-owner matches require exact first-party permalink equality,
never a similar title. Docs topics must be the same topic from the
deployed taxonomy. A duplicate prediction or human reference may
never be reused for two matches.

The human source-wide census can never be substituted with parser
predictions, even when the parser detects no comparable prices.
A valid full page with true human-reviewed prices and zero qualified
parser rates can produce genuine false negatives. Source capture
incompleteness, truncated parser inventories and missing human reviews
instead produce **held** source-rounds, not false negatives.

## The strictly offline two-stage operator procedure

First complete earlier steps with **genuine** humans and permitted
original bytes:

1. P22A1: frozen exact 18-source selection, private operator-filled
   publisher access/robots/HTML retention ledger, exact original-page
   SHA-256s, two capture rounds where permitted.
2. P22A2: two actual distinct humans independently read the entire
   visible static HTML page, quote exact official evidence, verify
   source/product identity, and complete A/B files. Disputes are held.
3. P22A3: run the adjudicator-only preparation, after the A/B files
   are already fully recorded.

### Prepare a third-person adjudication packet

    python -m scripts.adjudicate_cross_category_accuracy \
      --prepare-adjudicator \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/publisher_original_html \
      --reviewer-a /secure/independent_reviewer_A_FILLED.json \
      --reviewer-b /secure/independent_reviewer_B_FILLED.json \
      --out-dir /secure/p22a3-third-human-prep-1

Creates a **new private directory**, with:

    adjudicator_only_parser_vs_human_packet_PRIVATE.json
    adjudicator_THIRD_HUMAN_BLANK.json

The adjudicator packet is fingerprint-bound to the exact P22A1
18-source manifest, both P22A2 reviewer outcomes, all original HTML
SHA-256s and the current crawler package code. A changed capture byte,
an edited policy record, a new parser revision, a swapped source, or an
altered reviewer label invalidates the packet and requires explicit
restaging.

An eligible source-round contains both arrays:
- predictions: **ALL** current strict parser predictions for the
  relevant metric, or zero if it correctly returned no such predictions.
  The number of unqualified pricing observations is separately shown.
- references: **ALL** dual-reviewed original-page human references
  in the scoring unit (docs collapsed to one reference per topic).

Held sources have explicit reasons and are not adjudicated or silently
excluded from 36-source-round coverage counts.

### Human adjudicator responsibilities

The third reviewer MUST be genuinely different from both original
reviewers. Set adjudicator_id and
independent_of_a_and_b_attested=true only after a real independent
review. Make one decision for every eligible source-round:

- review_completed=true, and a timezone-aware
  adjudicated_at_utc **after both A/B reviews and HTML capture**.
- Provide a substantive adjudication_note on complete source-wide
  disposition and any identity uncertainty.
- matches: explicit one-to-one pairs of prediction_id and reference_id,
  with a detailed same_visible_evidence_note.
- unmatched_prediction_ids: every other predicted item exactly once.
- missed_reference_ids: every other reference label exactly once.
- approved_for_advisor must remain false.

An ambiguous physical-price-cell match must stay unmatched, **never**
be forced into a TP. A parser match with the wrong typed rate
still counts FP+FN. A novel source variation cannot become a fact
approval through this review process.

### Score the frozen evidence without publisher requests

    python -m scripts.adjudicate_cross_category_accuracy \
      --score \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/publisher_original_html \
      --reviewer-a /secure/independent_reviewer_A_FILLED.json \
      --reviewer-b /secure/independent_reviewer_B_FILLED.json \
      --packet /secure/p22a3-third-human-prep-1/adjudicator_only_parser_vs_human_packet_PRIVATE.json \
      --adjudicator /secure/adjudicator_THIRD_HUMAN_FILLED.json \
      --out-dir /secure/p22a3-scored-1

Private outputs:

    p22a3_accuracy_READINESS_and_diagnostics.json
    source_round_diagnostic_scores_PRIVATE.json
    all_36_original_round_coverage.json

The report provides **source-qualified diagnostic** per-category TP,
FP, FN, precision, recall, exact date counts and rate-field equality
only when a valid original page and an independent complete
adjudication exist. If there are no eligible cases, every metric
remains null. It includes held/capture-disputed denominators, not
zero-padded predictions from blocked sites.

A "precision=1" result on one source is **not** proof of 100% accuracy
across 460 sources. Treat results as a biased, small, preselected pilot
and do not feed them into AgentFuse production recommendations without
a separate validated release gate.

## Important scientific and provenance limitations

- SHA-256 proves file byte consistency, NOT that a page originated
  from the publisher or that capture/retention was permitted.
- Different reviewer IDs and true attestations are not cryptographic
  proof of independent human labor.
- The 18 P20A sources were deliberately chosen from known difficult
  categories. The resulting sample is **not** representative and does
  not estimate full-population precision without additional sampling
  and verification.
- The existing P22A2 quote requirement may be insufficient for
  cells carrying multiple independent price dimensions. Those cases
  require improved human review evidence and should be held if
  identities are ambiguous, not invented.
- A page's complete visible HTML is not the entire vendor docs,
  pricing product range or changelog archive. Overall provider
  completeness and live freshness remain unverified.
- The stable private P21A holdout and the separate P19A6 15–25-source
  release study must NOT be treated as part of this original P20A
  reference sample.
- This PR has zero real publisher byte captures and zero real human
  reference labels. Its CI results demonstrate only deterministic
  implementation integrity on **synthetic** examples.

## Exit gate and what to build next

Complete the permitted actual 18-source human pilot and adjudication.
Prioritize measured failures in **P22B pricing scope**, then release
owner/date and documentation child-page retrieval, using original
publisher bytes before/after parser changes and keeping the sampled
sources unchanged.

Do not run another 460-source Zyte crawl yet. P21B's bulk access gate
requires separate real publisher URL decisions and exact reviewed,
short-lived bulk run plans. Even an authorized bulk run is not
evidence of accurate pricing or release detection.
