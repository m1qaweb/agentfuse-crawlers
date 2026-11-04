# P19A5 — Source-Specific Publisher Policy Preflight

**Goal:** A 20-publisher changelog pilot must never treat one generic
batch note as permission to request 5 different publisher websites.

P19A4 preregisters a diverse 15–25-source pilot. P19A5 adds a
separate **source-by-source human policy research sheet** and a strict
preflight gate before a manual P19A1 original-HTML request. It does not
retrieve robots.txt, evaluate legality, perform publisher capture,
review release cards or create AgentFuse facts.

## 1. Freeze the 20-source pilot first

Complete the P19A4 --plan workflow, retaining a secure private
AGENTFUSE_RELEASE_PILOT_SELECTION_KEY. Use a *different* private
AGENTFUSE_RELEASE_GOLD_SPLIT_KEY for holdout review. Do not commit
either secret or an operator's publisher research.

If you already have a frozen P19A4 plan, **reuse it**. Do not rotate
the seed to replace inconvenient, prohibited or blocked publishers.

## 2. Create one blank policy record per selected source (offline)

    export AGENTFUSE_RELEASE_PILOT_SELECTION_KEY='your-existing-private-selection-key'
    python -m scripts.review_release_pilot_policy \
      --prepare \
      --pilot-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --out-dir output/private/changelog-pilot-policy-blank-1

This creates a new private file:

    source_policy_review_template.json

Every original source ID, exact source URL and robots.txt URL is
already pinned to the chosen plan. Each row starts with
decision=pending_review, no reviewer, no evidence, and all three
operator-attestation booleans set to false. No network requests run.

## 3. Independently research EACH publisher before declaring eligible

Review the page ownership and exact product scope, current publisher
terms and access rules, robots restrictions, and whether the terms
allow your **particular** request and private research retention.
Consult legal advice when publisher policy is unclear. Do not use
login/CAPTCHA bypass, stealth rotation, prohibited paths or redirects
to evade the publisher's rules.

For each source, independently fill these fields:

- decision: operator_attested_one_manual_capture_eligible only if
  that publisher's specific terms, scope, retention and robots were
  reviewed and considered eligible for one bounded validation attempt.
- reviewer_id and reviewed_at_utc: genuine human reviewer and
  timezone-aware review time.
- ownership_evidence_url: exact first-party HTTPS page on the SAME
  host as the selected changelog. This is an anchor to review, not
  proof of ownership.
- access_policy_evidence_url: real relevant official terms/policy
  HTTPS page. Some publishers place terms on another host; the
  operator must assess its authenticity.
- scope_and_retention_note: 60–1200 characters documenting specific
  product/page access, ownership, why the terms and private retention
  are applicable and any explicit access or reuse restrictions.
- robots_review_attested, lawful_private_retention_attested,
  publisher_scope_attested: all must be true **only** when the source
  has cleared those three independently reviewed operator checks.
- approved_for_advisor: false, always.

Other permitted decisions:

    pending_review
    blocked_by_publisher_terms
    blocked_by_robots
    blocked_by_access_controls
    deferred_product_ownership
    deferred_policy_unclear
    deferred_retention_rights
    deferred_source_unavailable

A held/deferred source needs a real reviewer/time and substantive
note, but does not need fabricated legal evidence URLs. Its three
affirmative booleans must all remain false. An unreviewed source
has all reviewer/evidence/note fields null.

No ledger field constitutes a legal grant, a publisher-specific
collection permission in the deployed registry, or an advisor fact.
The raw publisher web site and robots.txt are checked AGAIN during
a separately initiated P19A1 manual capture, which may still fail.

## 4. Validate the ledger OFFLINE

Save the filled sheet privately, then run:

    python -m scripts.review_release_pilot_policy \
      --validate \
      --pilot-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --out-dir output/private/changelog-pilot-policy-check-1

The result is a **private** source_policy_preflight_receipt.json.
It recomputes the P19A4 source selection and source registry pins
using the original private selection key. It rejects duplicate,
missing, foreign, cross-owned or credential-bearing records,
malformed/future review timestamps, weak policy notes, partially
affirmative blocked records, invented permissions or an unknown
decision. It emits a bound SHA-256 of all filled review records.

The receipt reports all 20 source IDs and any blocked/pending
sources, plus separate readiness for each 5-source wave. A held
source is never silently replaced, dropped from the original sample
or scored as healthy.

## 5. Manual capture: per-source policy is now REQUIRED

Even with an operator-attested eligible wave, live HTML GET is never
automatic. The capture CLI now requires the frozen pilot plan AND
the filled source-by-source policy ledger, in addition to the old
explicit capture and operator policy flags:

    python -m scripts.capture_release_html \
      --source-ids EXACT_SOURCE_IDS_FROM_ONE_FROZEN_WAVE \
      --capture --policy-reviewed \
      --policy-review-note "Each named publisher was independently reviewed for exact ownership, terms, robots, scope and private retention." \
      --pilot-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --out-dir output/private/changelog-pilot-captures-1/wave_01

**P19A6 update:** Manual captures may select an original-order,
nonempty subset of one frozen wave, but ONLY its individually eligible
P19A5-reviewed sources. Every publisher remains in the original sample
denominator, including blocked, deferred and not-yet-captured sources.
See P19A6_ATTRITION_AWARE_CHANGELOG_PILOT.md. Real capture also performs fresh robots.txt checks
and refuses redirects/access challenges.

The resulting P19A1 original-HTML capture audit binds the policy
receipt's SHA-256, but the review itself remains human-attested
rather than cryptographically authenticated.

Legacy synthetic tests may call the capture function with an
injected fake HTTP opener; that unit-test seam does not authorize
real CLI capture.

## 6. Stage captured waves only after complete reviewed evidence

After all frozen wave captures actually exist, staging is still
offline and writes only *blank* P19A2 reviewer templates:

    export AGENTFUSE_RELEASE_GOLD_SPLIT_KEY='your-existing-private-heldout-key'
    python -m scripts.prepare_release_pilot \
      --stage \
      --input-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --capture-root output/private/changelog-pilot-captures-1 \
      --out-dir output/private/changelog-pilot-staged-1

The original P19A4 full-cohort staging CLI remains all-or-none;
P19A6 provides a separate attrition-aware staging and scoring path for
individually permitted captures. Both bind P19A1 audits to the
current source-specific P19A5 review receipt.
It refuses inconsistent or missing waves and never fakes a human
full-page census. Reviewers A and B must still supply independent
real original-HTML evidence before P19A3 owner/date metrics.

**If a source is blocked:** record the blocker, do NOT capture it,
do NOT silently replace it, and do NOT declare pilot accuracy.
The P19A4 whole-cohort staging gate stays held. P19A6 now supports
individual manual captures and offline attrition-aware diagnosis while
retaining all 20 originally selected source IDs.

## Safety boundary

No real publisher requests were performed as part of P19A5 code
implementation. This PR does not alter any of the 460 source IDs,
three deployed spiders, source lifecycle/collection permission
registry, Zyte jobs, schedules, AgentFuse data or Supabase.
Synthetic tests prove code guards, not legal permissions or
real-world release accuracy. Never start the full 460-source crawl
merely because CI is green.
