# P14A — Real-World Gold: immutable evidence binding before accuracy claims

**Status:** Implemented as a review-only PR. No live publisher jobs or human
gold have been collected by this PR. DO NOT label the P08 synthetic corpus or
unreviewed old Zyte Items as independently reviewed accuracy.

## Current deployment and automatic deployment risk

At 2026-11-01, the operator's Zyte Code & Deploys screenshot shows:
- Automatic deployment from GitHub **main** enabled.
- Current deployment **#28**, SUCCESS, **3 spiders**.
- Deployment label **cc5ba1a-main**, matching GitHub main SHA
  \`cc5ba1ae20b3a4f2559acf98e50d23547740470d\`.

**Crucial:** This proves the displayed GitHub revision was deployed according
to Zyte, not that real publisher facts are accurate. A GitHub PR is safe to
test; **MERGING PRs into main WILL TRIGGER another automatic Zyte deployment**.
Only merge after operator checks policy/schedules/rollback plan, or deliberately
disable automatic deploy first. No settings are changed by this PR.

The package content fingerprint is distinct from a Git commit SHA.
The last P13 CI showed SHA-256:
\`359051038fea0c0d165760980ff1f0d74ce527a3ebb1601a68106402d7248cce\`
for its Python/JSON payload. A new PR merge will change that fingerprint;
always obtain the value from the actual Item's \`deployment_revision\` and
verify \`deployment_revision_kind=package_py_json_sha256_v1\`.

## 1 — Pin permitted canary sources and run only manual validation

Only explicit approved first-party source IDs, e.g. initial small diagnostic
cohort: \`openai_api_pricing\`, \`gemini_api_pricing\`,
\`openai_api_changelog\`, \`gemini_api_changelog\`,
\`kiro_docs\`, \`aws_bedrock_docs\`. These are *examples* requiring the normal
reviewed publisher-policy and source lifecycle checks. Never use quarantined
v0 sources or run a full-inventory unattended spider.

    python -m scripts.canary_rollout \
      --source-ids openai_api_pricing,openai_api_changelog,kiro_docs \
      --out-dir output/private/p14a-plan

Manually run the preflight jobs in Zyte with explicit \`cohort=all\`,
\`collection_mode=validation\`, exact \`source_ids\` and pinned manifest
and registry hashes. P14A requires these exact six job arguments in
archived Zyte metadata for every case: `cohort=all`,
`source_ids=<one exact ID>`, `collection_mode=validation`,
`expected_manifest_sha256`, `expected_selection_ids_sha256` and
`expected_source_registry_sha256`. An old broad batch or an unpinned
default job is NOT an accuracy canary. Use **distinct job IDs**, two
repetitions if evaluating stable capture. Inspect Items, Requests, Logs and robots/policy decisions.
Never confuse successful deployment with a successful crawl.

## 2 — Archive the finished jobs (read-only)

Use P07's bounded, paginated, checksum-verified archiver. This stage is the
ONLY stage requiring a Zyte credential; it is passed by environment, never
written to a JSON report or code repository.

    python -m scripts.archive_jobs --job-id 883514/3/123 --out-dir output/private/zyte
    python -m scripts.archive_jobs --job-id 883514/1/124 --out-dir output/private/zyte
    python -m scripts.archive_jobs --job-id 883514/2/125 --out-dir output/private/zyte

The job IDs are examples. Archives live at
\`output/private/zyte/jobs/<project>_<spider>_<job>\`.

## 3 — Generate unreviewed evidence packets

    python -m scripts.real_gold_binding \
      --archives output/private/zyte/jobs/883514_3_123 \
                 output/private/zyte/jobs/883514_1_124 \
                 output/private/zyte/jobs/883514_2_125 \
      --prepare-review output/private/p14a/review_candidates.json

This file is an **unreviewed** queue, not a \`reviewed-gold\` input.
All records carry typed event/observation IDs, bounded source evidence and
their archive's exact full \`deployment_revision\` fingerprint. Identical
source observations repeated in different jobs are not double-counted.

## 4 — Human annotator creates PRIVATE reviewed gold

Each case must be checked against the original official publisher page and
the exact archived Item. Use the existing PR08 golden JSON format
(\`schema_version=1.0\`, \`origin=human_annotated_official_source_evidence\`,
\`approved_for_advisor=false\`, \`synthetic_only=false\`) plus these P14A
binding requirements:

- Root \`expected_package_sha256\`: exactly the immutable crawler package
  fingerprint stored in every reviewed archive Item, **not** a Git commit SHA.
- Root \`reviewed_by\` and timezone-aware \`reviewed_at_utc\`.
- Every case contains unique \`case_id\`, exact \`source_id\`, \`source_url\`,
  official first-party \`evidence_url\`, \`job_id\`, and
  \`evidence_review_note\` (24–1,200 characters), and
  \`approved_for_advisor=false\`.
- Pricing: \`observation_id\`, independent \`expected\` with exact amount,
  currency, unit, region, plan, model, dimension and other scope,
  and \`observed\` **copied unmodified** from the packet's typed observation.
- Date: \`event_id\`, \`event_body_sha256\`, human \`expected_day\` (ISO
  date or null), and archived \`observed_day\` copied unchanged.
- Negative rate: \`observation_id\`, \`expected_comparable=false\`,
  \`observed_comparable\` equal to the archived candidate boolean.
  The same observation must not be used in pricing and negative samples.
- Change safety: \`scenario=first_baseline\` or
  \`scenario=reordered_same_events\`. Reordering requires
  \`previous_job_id\` pointing to a *different, earlier* immutable job
  with the same full event identity/content set.
- Never copy old or synthetic price/date truth into the human expected
  field without actually reviewing official publisher evidence.

Human labels remain self-attested: archive binding verifies the crawler's
output, **not** that human expected values accurately reflect publisher truth.

## 5 — Verify every observation and run quality gates

    python -m scripts.real_gold_binding \
      --archives output/private/zyte/jobs/883514_3_123 \
                 output/private/zyte/jobs/883514_1_124 \
      --reviewed-gold output/private/p14a/human_gold.json \
      --out output/private/p14a/gold_binding.json

After independently labeling **>=200 distinct actual pricing observations**,
**>=100 actual release events**, negative-scope cases and first-baseline /
reorder safety cases, run the existing PR08 scorecard with mandatory binding:

    python -m scripts.quality_gates \
      --synthetic-report output/ci-synthetic/synthetic_report.json \
      --canary-score output/private/canary-review/canary_score.json \
      --reviewed-gold output/private/p14a/human_gold.json \
      --gold-archives output/private/zyte/jobs/883514_3_123 \
                      output/private/zyte/jobs/883514_1_124 \
      --out-dir output/private/p14a/release-review \
      --strict

Requirements remain: >=99% price/date accuracy, zero invented latest dates,
zero false comparable negative prices, zero new-release false alerts,
>=95% usable across **two** rounds for explicitly reviewed/monitor-eligible
sources, no access or policy violations and no advisor approvals.

The new *sixth* gate \`archive_bound_human_gold\` blocks any label set
whose \`observed\` values, event body hash, IDs, job identity, source URL or
package fingerprint differ from actual immutable archives. All repeated
same-source observation IDs across jobs are rejected.

There are currently **no supplied independently labeled real gold records**,
and the existing source lifecycle registry has zero monitor-approved sources.
The strict gate MUST remain blocked. A future passing scorecard only allows
**human release review**, never automatically publishes price facts, upgrades
the source policy or authorizes deployment.

## 6 — Limitations and next step

P14A is an evidence-binding foundation, not automatic source truth validation.
The archive verifies source-summary Item integrity, not the original DOM or
the human reviewer's independence. Store human gold and private archives
outside Git; the \`output/\` path is gitignored. For P14B, include the
publisher-original HTML/Requests evidence and a true documentation/product-
scope gold set, then perform independently reviewed real canaries and
conservative staged rollout decisions.

No extra spider, automatic Zyte job, new manifest URL, source-policy
promotion, database write or automatic advisor publication is part of P14A.
