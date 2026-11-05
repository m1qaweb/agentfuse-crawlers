# P22A2 — Dual-blind, original-HTML-bound cross-category evidence review

**Status:** Offline implementation only; NO new publisher requests, source grants,
Zyte jobs, changing deployed spiders, real human reviews or verified accuracy.
This is the next step after merged P22A1 #64 in the November 4 evidence-first
master plan.

## Why this is not a conventional parser benchmark

The P22A1 workbench freezes 18 source IDs / 36 source-rounds from the old
P20A waves and accepts operator-retained original static HTML, without
silently replacing policy-blocked sources. But no two human experts have
independently reviewed those specific original publisher pages. Our old
November 4 Zyte 460-Item exports do not contain these raw pages. We
cannot infer reference rates, publication dates or documentation
capabilities from a crawler's own normalized output.

P22A2 adds *validatable human evidence* without manufacturing labels
or reporting false precision. It inherits the original P20A denominator,
the P22A1 original byte/policy/source tests and **existing mature P19A2
release-owned date validation**.

## New script

scripts/reconcile_cross_category_reviews.py

Two offline modes:

1. **--prepare-reviewers**: recomputes the P22A1 accession and produces
   one frozen task bundle plus BLANK independent reviewer A/B forms.
   Reviewer forms include source ID, exact source URL, category, wave,
   capture round, original byte SHA-256, timestamp and private file
   reference. NO parser prediction, guessed label or auto-approved fact.
2. **--reconcile**: accepts both independently filled files, verifies
   snapshot/task hashes and distinct named reviewers, checks their
   full-visible-page source census and individual exact quotes against
   the private original HTML. A price is a typed exact-Decimal amount
   with explicitly reviewed or unknown currency/billing/region/plan.
   A release is a unique publisher DOM owner with an explicit,
   unknown or undated publication day. A documentation technical
   claim is source-quoted with exact support state and conditions.

A checked original HTML byte hash is NOT publisher authentication.
Two different reviewer IDs plus operator attestation do NOT prove
the two humans were independent, nor do matching answers
necessarily establish actual publisher correctness.

## Human reviewer instructions — keep private

First, satisfy P22A1's genuinely permitted source-by-source access
research and capture two separate original static HTML rounds when
authorized. Never bypass publisher rules, privacy restrictions,
authentication requirements or JS access barriers.

Run:

    python -m scripts.reconcile_cross_category_reviews \
      --prepare-reviewers \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/actual_original_html \
      --out-dir /secure/p22a2-blind-forms-1

This creates:

    cross_category_blind_task_bundle.json
    independent_reviewer_A_BLANK.json
    independent_reviewer_B_BLANK.json

Make two separate copies of each appropriate reviewer file; assign
two DIFFERENT actual human reviewers. They must inspect the complete
available, static HTML independently and **before** viewing parser
candidate lists or the other reviewer's judgments.

Top-level:
- Set reviewer_id to an actual human-identifying reviewer tag.
- Set independent_blind_review_attested=true only if it really occurred.
- Do not change reviewer_letter, task_bundle_sha256, selected source
  identifiers, page URL, snapshot hash or privileges.

For each captured source-round:
- page_scope is sufficient_visible_static_page ONLY if the reviewer
  can inspect the entire relevant visible static page, not a JS shell,
  empty app mount, CAPTCHA, partial render or arbitrary excerpt.
- Set whole_visible_page_review_complete=true and
  exact_product_scope_reviewed=true only with a genuine complete
  exact-product/page review. Otherwise retain a held page_scope such
  as insufficient_js_or_challenge or ambiguous_product_scope with
  no claimed negative evidence.
- Provide reviewed_at_utc, a substantive review_note and all
  independently found qualifying observations in evidence_inventory.
- If the entire visible source page truly contains no relevant
  evidence, evidence_inventory=[] and no_relevant_evidence_observed=true.
  This is a *visible static page* negative only, NOT proof that the
  publisher has no prices, releases or capabilities elsewhere.
- Every evidence row includes evidence_type, exact original
  publisher_evidence_quote (24–450 characters, appearing exactly ONCE
  in visible HTML), publisher_evidence_url matching this source,
  reviewed_value (category-typed), a concrete review_note and
  approved_for_advisor=false. A quote only inside JavaScript or hidden
  navigation does not establish visible source content.

### Pricing value object

    {
      "amount_decimal": "1.25",
      "currency": "USD",
      "billing_unit": "per_million_tokens",
      "price_dimension": "input",
      "model_or_service": "EXACT_PUBLISHER_MODEL",
      "region": null,
      "region_applicability": "unknown",
      "tier_or_plan": null,
      "tier_applicability": "unknown",
      "conditions": null
    }

Use null for unknown currency, billing unit, tier, region or condition;
never infer USD from a dollar sign, global region from silence, or
a default plan from a table heading. Region and tier
applicability can be explicit, reviewed_not_applicable, conditional
or unknown, with values/conditions consistent with the state.

### Release value object

    {
      "event_owner_url": "EXACT_SAME_HOST_SOURCE_URL#unique-release-id",
      "publisher_title": "Exact publisher visible title",
      "version": null,
      "date_status": "explicit_publication_day",
      "published_at": "2026-11-01",
      "date_evidence_text": "November 1, 2026"
    }

An owner URL must resolve to one actual in-page ID or exactly linked
nested release, with title, exact original quote and (if explicit)
a full-year publication day grounded in the same release card.
Unknown/undated must use null date, not an inferred publication day.
This reuses scripts/score_release_gold.py's original P19A2 DOM-owner
checks; ambiguous owner identities are held.

### Documentation value object

    {
      "topic": "authentication",
      "support_state": "conditional",
      "capability_statement": "Exact narrowly scoped human claim ...",
      "conditions": "Original publisher precondition ...",
      "product_id": "Human-reviewed exact product label"
    }

Topic must use the existing documentation taxonomy. Supported,
unsupported, conditional and unknown are different labels. A claim
from an overview page is NOT evidence that the entire docs corpus was
reviewed.

## Score agreement / attrition (NO parser precision yet)

After both human reviews are done, run:

    python -m scripts.reconcile_cross_category_reviews \
      --reconcile \
      --frozen-plan /secure/frozen_p20a_18_source_plan.json \
      --private-ledger /secure/source_policy_and_capture_ledger_FILLED.json \
      --capture-root /secure/actual_original_html \
      --reviewer-a /secure/independent_reviewer_A_FILLED.json \
      --reviewer-b /secure/independent_reviewer_B_FILLED.json \
      --out-dir /secure/p22a2-private-consensus-1

Private, new-only outputs:

    cross_category_review_readiness_NOT_ACCURACY.json
    all_36_source_round_review_status.json
    agreed_quote_grounded_evidence_PRIVATE.json

The original **36** source-rounds are always present; uncollected,
policy-denied or expired sources are *held*, NOT false parser
negatives. A/B disagreements, incomplete page review, unknown
product identity, missing whole-visible-page evidence and
publisher quote mismatch remain held. Agreement on an empty page
counts only as an independently labeled page-local absence, never
an assertion of publisher-level product/pricing completeness.

The report contains per-category and aggregate counts of source-rounds
that were actually captured, reviewed, disputed, held and independently
quote-grounded. Parser precision/recall, false positives/negatives
and real-world accuracy all remain null/not established until an
independent human adjudicator matches stable original evidence
identities to the separately replayed parser candidates (next P22A3).
Do not use the source label counts to choose a new parser or claim it
is more accurate.

## Operational constraints and next phase

The only committed artifacts are the script, synthetic adversarial
tests and this runbook. The production crawler Python/JSON package
fingerprint is intentionally unchanged. The existing GitHub Actions
no-local preflight makes P22A1's BLANK initial 18-source policy/capture
study available. It cannot generate filled P22A2 reviews, since that
would require private publisher HTML and two genuine independent
reviewers; never upload those private inputs to public CI.

P22A3 should generate a separate adjudicator-only source-wide
candidate mapping packet, require every predicted and reference
observation to be accounted for, validate exact rate units,
publication owner/date and documentation product scope, and report
precision/recall ONLY where original-page coverage is complete.
Use real original publisher bytes and authentic reviewed references
before embarking on P22B pricing normalization or another all-460 crawl.

**The full 460-source Zyte run remains on hold.**
