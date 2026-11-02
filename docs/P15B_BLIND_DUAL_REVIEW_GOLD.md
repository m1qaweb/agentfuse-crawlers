# P15B — Blind, two-reviewer publisher gold and holdout protocol

## What this PR adds

The prior P14A workflow proves a crawler Item matches archived Zyte bytes
but **does not** establish that manually typed expected values reflect
publisher truth. P15B creates an operator-run **blind** labeling workflow:
reviewers inspect an independently captured official publisher snapshot,
without seeing predicted rate amounts, dates, normalized scope dimensions,
confidence scores or capability support statements. Two different reviewers
submit independent expected labels. Their quote must appear uniquely inside
the exact hash-pinned publisher snapshot; disagreements remain unresolved.

Source groups are split by **provider**, not individual table rows or
changelog events. A private operator HMAC key controls a deterministic 25%
provider-group holdout. Without enough provider diversity and separately
agreed gold examples, a perfect-looking accuracy score stays blocked.

P15B does not scrape sites, approve publishers, collect snapshots
automatically, promote individual claims, change Supabase, or make
AgentFuse advisor recommendations.

## Step 1 — Obtain genuine immutable P07 job archives, NOT dashboard JSON

Use the already implemented P07 archiver and P14B plan audit, if current
Zyte retention and source permissions permit. P15A's nine November 2
Dashboard exports are valid for a reproducible **failure matrix**, but they
lack the original publisher response bytes and cannot themselves become
human-reviewed source truth.

\`\`\`bash
python -m scripts.real_gold_binding \
  --archives output/private/zyte/jobs/JOB_1 output/private/zyte/jobs/JOB_2 \
  --full-inventory-plan output/private/p14b/full_inventory_plan.json \
  --prepare-review output/private/p15b/unreviewed_packet.json
\`\`\`

The plan flag is needed only for multi-source, pinned P14B batch archives.
Single-source P07 canaries still use the default one-source bound checks.
The packet is **unreviewed**, not the release-quality gold set.

## Step 2 — Generate blind tasks and two empty reviewer sheets

Keep the secret split key in a **private environment variable**, not Git,
logs, screenshots, or shared review files:

\`\`\`bash
export AGENTFUSE_GOLD_SPLIT_KEY='generate-a-long-private-random-secret'
python -m scripts.gold_review_protocol \
  --prepare \
  --candidate-packet output/private/p15b/unreviewed_packet.json \
  --out-dir output/private/p15b
\`\`\`

Outputs:
- \`blind_tasks.json\`: official URL, provider, exact source and observation
  identity, \`train\` or \`holdout\`, and unverified navigation hints.
  **No observed amount, currency, date, blockers, or capability claims.**
- \`reviewer_a_template.json\` and \`reviewer_b_template.json\`:
  empty \`labels\` arrays. Reviewers fill these **independently** after
  consulting a publisher-owned page or verified official feed.
- The HMAC split key is NOT embedded in tasks. A SHA-256 commitment is
  recorded so the partition is reproducible, without disclosing the key.

Holdout provider groups must not be selected for prompt tuning, provider
adapter development, manual threshold adjustments, or iterative bug fixing.
Re-running the same cases after code was changed is development evaluation,
not an independent holdout.

## Step 3 — Capture original official publisher evidence independently

For each reviewed \`case_id\`, acquire an original publisher source
HTML/Markdown/JSON/text snapshot **separately** from Zyte's parsed Item,
under publisher terms, access rules and a private retention policy.
Save the bytes under an encrypted operator-controlled
\`output/private/p15b/publisher_snapshots/\` directory. Do NOT commit them.

Prepare a JSON manifest:

\`\`\`json
{
  "approved_for_advisor": false,
  "snapshots": [
    {
      "case_id": "THE_24_HEX_TASK_ID",
      "source_id": "openai_api_pricing",
      "publisher_url": "https://developers.openai.com/api/docs/pricing",
      "file": "THE_24_HEX_TASK_ID.html",
      "sha256": "THE_64_HEX_SHA256_OF_EXACT_SNAPSHOT_BYTES",
      "captured_at_utc": "2026-11-02T10:05:00Z",
      "media_type": "text/html",
      "approved_for_advisor": false
    }
  ]
}
\`\`\`

Use actual source URLs and timestamps, never those placeholders.
The snapshot must be captured within 24 hours of the original Zyte
source Item's fetch timestamp to reduce time-of-check/time-of-use risk;
different markup versions still require review. Hash correctness does NOT
cryptographically authenticate the publisher or prove human labels correct.

Each reviewer entry must contain:
- \`case_id\`, \`resolution\`, \`expected\`,
  \`publisher_evidence_url\`, \`publisher_evidence_quote\`,
  \`review_note\` (24–1200 chars), \`reviewed_at_utc\`,
  \`approved_for_advisor=false\`.
- Exact unique publisher quote between 24 and 450 characters, matching
  the frozen snapshot's visible text. No quotes copied from the crawler
  excerpt; reviewers read the independent original.
- **Pricing:** \`resolution=established\` with \`expected\` including
  amount, currency, billing unit, model/service, region, tier/plan,
  dimension and optional mode/effective bounds. \`resolution=incomplete\`
  or \`unresolved\` must carry \`expected=null\`. An unknown region must
  not be imputed as Global.
- **Date:** \`resolution=published_date\`, \`expected=YYYY-MM-DD\`, or
  \`resolution=explicitly_undated\` / \`unresolved\` and \`expected=null\`.
  Modified-at timestamps are never publication dates.
- **Docs:** \`resolution=topic_relevant\`, \`topic_irrelevant\`, or
  \`unresolved\`, with \`expected\` a full object:
  \`{"support_state":"unknown|supported|unsupported|conditional",
     "capability_statement":"...", "conditions":"..."}\`.
  Do not infer unsupported from a missing section. Capture product,
  plan, region, feature availability and conditions in specific quotes.
  This is **topic retrieval gold**, not verified capability precision;
  the crawler currently does not make explicit support predictions.

Reviewer IDs must be different. Agreement on labels and the exact
snapshot hash is mandatory. A disagreement is not silently resolved by
majority vote or an LLM. Independently adjudicate it in a later
explicitly reviewed process without altering the untouched holdout.

## Step 4 — Score and verify against archived crawler observations

\`\`\`bash
python -m scripts.gold_review_protocol \
  --score \
  --candidate-packet output/private/p15b/unreviewed_packet.json \
  --reviewer-a output/private/p15b/reviewer_a_filled.json \
  --reviewer-b output/private/p15b/reviewer_b_filled.json \
  --snapshots output/private/p15b/snapshots_manifest.json \
  --snapshot-root output/private/p15b/publisher_snapshots \
  --archives output/private/zyte/jobs/JOB_1 output/private/zyte/jobs/JOB_2 \
  --full-inventory-plan output/private/p14b/full_inventory_plan.json \
  --out-dir output/private/p15b/scored
\`\`\`

Scoring REGENERATES the original candidate packet from checksum-verified
Zyte archives, then recomputes private grouped holdout partitions.
It rejects missing/corrupt/stale/off-host snapshots, unmatched quotes,
unknown reviewer cases, non-unique evidence, and mutated crawler
observations. Reviewers cannot supply their own predicted values.

Minimum **proposed holdout gates** before separate human accuracy signoff:
- Pricing: 200 agreed evaluable distinct observations overall;
  ≥50 on ≥3 holdout providers; ≥99% holdout *exact normalized rate*.
- Release dates: 100 agreed evaluable events overall;
  ≥25 on ≥2 holdout providers; ≥99% holdout date accuracy.
- Documentation: 50 agreed evaluable topic candidates overall;
  ≥15 on ≥2 holdout providers; ≥98% holdout *topic retrieval precision*.
- Zero accepted false comparable prices, zero invented dates, and zero
  unresolved dual-review disagreements or unlabeled tasks.

Precision on a selectively extracted set is NOT recall or complete
coverage of any provider's documentation, and positive topic retrieval
is NOT evidence that the model/feature is supported in production.

**All outputs remain review-only.** Even a passing offline scorecard
requires independent publisher-authenticity audit, source policy approval
and separate release signoff; nothing is published to the advisor.

## Known limitations and P15C/P16 follow-up

- SHA-256 and exact HTML quote matching establish byte consistency,
  **not publisher authorship**. Snapshot acquisition provenance needs a
  separately reviewed response URL/headers and policy-approved capture.
- Temporally close but separately fetched page may differ from Zyte's
  original response. Mark ambiguous examples unresolved; do not equate
  the crawler's \`content_sha256\` with a raw HTTP body digest.
- Provider-group holdout protects against reusing closely related pages,
  but is not a statistically representative random estimate of all AI
  providers. Report evaluated source/provider counts and missing evidence.
- No meaningful support precision can be asserted until P18 explicitly
  extracts typed capability *claims*, with provenance and conditions.
- P15B establishes the scoring framework, not real labels. Do not
  manufacture 200/100/50 examples from the old Nov 2 dashboard exports.

After real gold is collected, P16 can target adapters to the actual
highest-cost issues and measure gain on untouched provider holdouts.
