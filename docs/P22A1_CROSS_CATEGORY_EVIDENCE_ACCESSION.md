# P22A1 — Cross-category original HTML evidence accession

**Status:** Offline evidence preparation, NOT publisher access permission, verified benchmark, trusted facts or a Zyte job. First sub-step of P22A in the 2026-11-04 evidence-first master plan.

## Why

P21A froze November 4 Items/Requests/Logs. P21B closed the bulk publisher-access loophole. Neither supplies independently reviewable original publisher HTML across pricing, documentation and changelogs. A 24,000-character text excerpt or a source-summary Item cannot establish exact publisher price/release-date recall.

P22A1 reuses the exact P20A source selection: two precommitted waves of nine sources (three documentation, three pricing and three changelog sources in each), totaling **18 source IDs / 36 required source-rounds**. No source may be replaced after a policy denial or disappointing parser result. P19A6's separate 15–25-changelog pilot and P21A's private holdout are different populations and must remain separate.

## Deliverables

New script: scripts/accession_cross_category_html.py

In --prepare mode it writes only three private files:
- frozen_p20a_18_source_plan.json
- source_policy_and_capture_ledger_BLANK.json
- README_PRIVATE.txt

The ledger begins with pending human access research and both rounds not_attempted. Nothing in this template grants permission to collect data.

In --stage mode it consumes an actual operator-filled source-specific policy/capture ledger plus private, already-collected HTML files. It verifies exact configured publisher source URL, source ID, category, wave, timestamp, 200 response status, no redirect, static HTML method, UTF-8 bytes, SHA-256, 8 MB cap and safe non-symlink paths through the existing P16B byte-verification helper. Source-specific reviewer names, official ownership/terms/robots evidence URLs, bounded policy review dates, retention review and substantive reviewer notes are mandatory for retained original HTML.

It uses the unchanged production evidence extractor to generate explicitly UNVERIFIED candidate diagnostics. Nothing is promoted to a verified pricing rate, release date, capability, gold label or advisor fact.

Outputs:
- all_36_source_round_attribution.json
- attrition_and_parser_diagnostics_NOT_GOLD.json
- reviewer_A_BLANK.json
- reviewer_B_BLANK.json

The reviewer packets contain original URL, capture hash and private file reference but deliberately NO parser predictions. Reviews remain blank until two genuinely independent humans complete full-page review of each permitted original HTML source. A blank form is not human gold.

Every denied, deferred, unobserved, or failed source stays in the original 18-source denominator. A policy-inaccessible source is NOT a parser true negative or false negative.

## No-local GitHub workflow

After the PR is manually reviewed and merged, open GitHub → Actions → Prepare Zyte UI preflight (no crawl) → Run workflow on main. The workflow artifact will include a new p22a1-blank directory with the same original selection and blank private ledger. It never contacts publishers or Zyte.

**Do not upload real HTML, publisher terms correspondence, reviewer names/notes, or the populated private ledger to the Git repository or a public GitHub Actions run.** The Github artifact intentionally includes only a blank template.

## Operator commands

To create the initial plan, when an operator Python environment is available:

    python -m scripts.accession_cross_category_html \
      --prepare --out-dir output/private/p22a1-cross-category-plan-1

For each actually permitted original source, capture through existing bounded manual publisher tools (P17B3 pricing, P19A1/P19A5 changelogs, or existing reviewed docs capture where applicable), using real human URL/policy and private retention reviews. Do not bypass robots, CAPTCHA, 403/429 or follow a canonical migration without new review. Original documentation parent HTML may be provided only with its exact source URL and an honestly operator-unverified origin; P18A2 child-page HTML is NOT automatically equivalent to its configured parent source URL.

Fill the private ledger only with authentic per-source review notes, original HTML metadata, an exact SHA-256, and distinct receipt IDs. The two capture rounds must be temporally ordered. HTML and the filled ledger must stay in private operator storage; do not commit publisher HTML to CI.

Then run the offline accession:

    python -m scripts.accession_cross_category_html \
      --stage \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/permitted_original_html \
      --out-dir /secure/p22a1-staged-output-1

If an input is missing, edited, out-of-scope, expired, forged, symlinked, oversized, incorrectly attributed, or unexpectedly privileged, the stage refuses it without creating a misleading benchmark.

## Assessment limitations

This is **original-byte integrity and attrition**, not independent authentication of a publisher response, proof of legal permission, or an accuracy evaluation. Each actual source review remains an operator attestation requiring human verification. A successful HTTP 200 does not establish semantic completeness. A hash detects a byte change but not the provenance of those bytes.

Use existing P17B2 independent physical-cell pricing labels, P19A2 independent whole-page release owner/date censuses and P18A2 reviewed docs child-page checks as separate tools. P22A2 will assemble actual independently completed source-wide labels, adjudication and calibrated per-category metrics. It must avoid cherry-picked examples and measure price/no-price, event/no-event, and docs claims with actual human source evidence, while accounting for source/capture attrition separately.

No new crawler network requests, Zyte jobs, source permissions, schedules, DB writes, or advisor facts in this PR. The next full 460-source run stays **on hold**.
