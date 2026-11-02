# P17B2 — Frozen Original-Pricing-HTML Replay and Independent Gold

**Status:** Offline-only implementation, stacked on P17B1 draft PR #36.
No live Zyte jobs, website requests, provider approval, production DB edits,
source changes, automatic parser activation or published AgentFuse rates.

## Why this matters

P17B1 adds a source-specific Fireworks parser for an official, nearby
input/cached-input/output price legend. The first-party official page
at https://docs.fireworks.ai/serverless/pricing gives the ordered
components in the **Text and vision models** section. However, the
November 2 Zyte Dashboard export contains **parsed Items, not the original
HTML bytes**; its 39 Fireworks multi-price observations cannot prove that
the parser now extracts them accurately.

The hard question is: **on exactly the same original publisher HTML
bytes, does P17B1 extract more *correctly scoped* rate components than
P17A, without losing cells or inventing data?**

## What P17B2 implements

- \`scripts/replay_pricing_snapshots.py\`: deterministic current-pricing-
  extractor replay against operator-supplied raw official HTML, identified
  by exact source URL, status 200, immutable SHA-256 and capture timestamp.
- Validates the current 460-source manifest and pricing source lifecycle,
  source IDs, exact request and final URLs, UTF-8 raw bytes, local non-
  symlink storage, 8 MB per capture, and zero approval privileges.
- Produces source/model/dimension-specific **unverified** observations,
  associated with stable *physical table cell* IDs, so a 3-part P17B1
  rate is not incorrectly compared against three unrelated v4 rows.
- Preserves parser/package SHA-256, source registry, manifest digest,
  input HTML digest, inventory completeness, observation cap, model
  identity risks, and whether a source still needs scope review.
- \`--compare\` enforces exactly the same original HTML snapshots and
  source manifest against **different package/parser revisions**, and
  explicitly reports cells lost, cells gained, extracted amount changes,
  completeness regressions, and *unverified* new candidates.
- \`--blind-review-tasks\` makes a finite source-round-robin reviewer
  packet with up to 20 physical cells per source and 1,000 total,
  without pre-filling a price, dimension, currency, region or plan.
- \`scripts/score_pricing_replay_gold.py\`: compares **two independently
  entered reviewer labels** against the original SHA-pinned HTML quote.
  Both reviewers must agree, otherwise cases become a disagreement.
  Reports exact typed amount/currency/unit/model/region/tier/dimension
  matching, missing components, false or misattributed components, and
  precision/recall on *only the reviewed subset*. It cannot assert
  population-wide provider accuracy or authenticate reviewers.
- No statement with \`approved_for_advisor=true\` or a verified production
  rate is emitted, even if a small test scores 100% on a frozen page.

## 1. Obtain permitted original raw HTML

From a publisher-permitted collection procedure, save the raw response
HTML (not screenshots, DOM text, pre-scraped Items, or synthesized markup)
into a private encrypted folder. Capture a small, deliberately diverse
source set: Fireworks, Together, Gemini, Anthropic, OpenAI, and at least
one non-token pricing family. Do not bypass authentication, CAPTCHA,
paywalls, rate limits, robots controls or provider terms.

The original historical Nov 2 raw HTML was not retained, so a later
capture must be treated as a **new source snapshot with a new version**.
Never claim to have replayed the Nov 2 original bytes when using today's
page. Rendered browser content should not be silently substituted for
original static HTML; P16B uses a separate method comparison.

Make \`frozen_snapshots.json\`:

\`\`\`json
{
  "schema_version": "1.0",
  "kind": "frozen_original_pricing_html_manifest",
  "expected_manifest_sha256": "ACTUAL_MANIFEST_SHA256",
  "expected_source_registry_sha256": "ACTUAL_REGISTRY_SHA256",
  "approved_for_advisor": false,
  "snapshots": [
    {
      "source_id": "fireworks_ai_pricing",
      "snapshot": {
        "file": "fireworks_static.html",
        "sha256": "SHA256_OF_ORIGINAL_HTML_BYTES",
        "request_url": "https://docs.fireworks.ai/serverless/pricing",
        "final_url": "https://docs.fireworks.ai/serverless/pricing",
        "http_status": 200,
        "media_type": "text/html",
        "capture_method": "static_html",
        "captured_at_utc": "2026-11-02T10:00:00Z",
        "capture_origin_review_status": "operator_supplied_unverified"
      }
    }
  ]
}
\`\`\`

The manifest and registry SHA-256 values must come from the exact
checked-out repository and must not be invented. The example timestamps
and digest placeholders above are NOT real publisher evidence.

## 2. Replay exact HTML with OLD and NEW parser versions

To prevent sampling drift, use independent worktrees/installations that
differ only in extractor revision. P17B1 remains a draft branch, while
P17A is now in \`main\`.

\`\`\`bash
git worktree add /tmp/p17a-replay main
git worktree add /tmp/p17b1-replay implementation/p17b1-explicit-inline-token-rates
\`\`\`

In each worktree, install the same lockfile dependencies and copy the
**identical two P17B2 runner files** from this PR into each worktree's
\`scripts/\` directory as *untracked offline scripts only*. The code
imports the installed package from the active worktree. Verify the
\`local_package_sha256\` in each output; the source and registry
fingerprints should be identical, while package/parser SHA should differ.

In **each** worktree separately:

\`\`\`bash
python -m scripts.replay_pricing_snapshots \
  --replay \
  --manifest /private/frozen_snapshots.json \
  --snapshot-root /private/raw_html \
  --out-dir /private/replay_v4_or_v5
\`\`\`

Copy the two resulting \`pricing_html_replay.json\` reports to a
separate private comparison directory and run (using P17B2 checkout):

\`\`\`bash
python -m scripts.replay_pricing_snapshots \
  --compare \
  --before /private/replay_v4/pricing_html_replay.json \
  --after /private/replay_v5/pricing_html_replay.json \
  --out-dir /private/p17b2-comparison
\`\`\`

The comparison **fails closed** if the HTML digest, source URLs,
manifest/registry pin or parser fingerprint changed unexpectedly.
A positive \`new_structured_observations_unverified\` is a reviewer
candidate, not a validated pricing accuracy improvement.

## 3. Generate BLIND tasks and obtain independent human gold

\`\`\`bash
python -m scripts.replay_pricing_snapshots \
  --blind-review-tasks \
  --after /private/replay_v5/pricing_html_replay.json \
  --out-dir /private/p17b2-human-review
\`\`\`

The result is \`blind_pricing_cell_tasks.json\` plus two EMPTY
reviewer JSON templates. Reviewers must independently view the
original official page snapshot, not the crawler's proposed amounts,
and fill the reviewer template's \`labels\` array.

Each label has this schema (example values are SYNTHETIC only):
\`\`\`json
{
  "case_id": "24_HEX_TASK_ID",
  "resolution": "established",
  "expected_components": [
    {
      "amount": "3.00",
      "currency": "USD",
      "billing_unit": "per_1m_tokens",
      "price_dimension": "input",
      "model_or_service": "Example-1",
      "region": null,
      "tier_or_plan": "Standard"
    }
  ],
  "publisher_evidence_quote": "Example-1 $3.00 / $0.30 / $15.00",
  "review_note": "I checked the original publisher source and exact row.",
  "reviewed_at_utc": "2026-11-02T11:00:00Z",
  "approved_for_advisor": false
}
\`\`\`

Use \`resolution=not_price\` or \`resolution=unresolved\` with
\`expected_components=null\` when necessary. Different reviewer IDs
are required, and a substantive exact quote must occur uniquely in the
frozen original page. A valid established quote must name the
reviewed model and at least one component amount.

## 4. Evaluate the frozen benchmark, never approve directly

\`\`\`bash
python -m scripts.score_pricing_replay_gold \
  --before /private/replay_v4/pricing_html_replay.json \
  --after /private/replay_v5/pricing_html_replay.json \
  --snapshot-manifest /private/frozen_snapshots.json \
  --snapshot-root /private/raw_html \
  --reviewer-a /private/p17b2-human-review/reviewer_a_filled.json \
  --reviewer-b /private/p17b2-human-review/reviewer_b_filled.json \
  --out /private/p17b2/independent_pricing_gold.json
\`\`\`

Inspect both precision AND recall, rejected or disputed cells, source
diversity and full inventory accounting. A 100% match on two synthetic
cells does not establish 99% accuracy on a population of 177 websites.

**Only after enough real, independently reviewed publisher evidence**
should P17B2 inform the P17B3 decision to expand a provider adapter.
P15B release-quality and source-policy approvals still apply and are
not bypassed by these offline replay outputs.

No full 460-source Zyte crawl is needed to validate this work.


## Scope-aware interpretation of dual-review accuracy

P17B2 reports two deliberately separate measurements:

- \`correct_exact_typed_components\`: the extracted amount and every
  **entered reference field** match, including matching an unknown/null
  region. This tests parser fidelity to *observable* source evidence.
- \`fully_scoped_exact_review_matches\`: the reference and extraction
  agree **AND** currency, unit, dimension, model, region and plan/tier
  are all explicitly present. A null region is counted under
  \`partial_scope_review_matches\`, **never** as a fully scoped price.

For example, a Fireworks Standard input amount may be correctly parsed
with \`region=null\`. The exact observed-component benchmark can score
100%, but the fully scoped score is **0%** until official applicable
region evidence is reviewed. Neither number establishes publisher
authenticity or authorizes a rate for AgentFuse's advisor.

A source blocked by an access challenge is also never categorized
as a positive extraction gain, even if DOM parsing emits rate-like text.
