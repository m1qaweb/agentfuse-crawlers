# P20A — When a Full 460-Source Zyte Crawl Is Justified

**Date:** November 4, 2026  
**Status:** Offline planning only; no real publisher requests, permits or accuracy evidence obtained by this PR.

## Decision: NOT YET

Do **not** run the complete 460-source inventory today. The deployed
collector has stronger deterministic parsing, typed evidence and status
accounting, but green synthetic CI and old Zyte Items cannot prove
vendor-specific price accuracy, release ownership or complete docs coverage.

The exact source counts are:

| Category | Source IDs |
|---|---:|
| Documentation | 194 |
| Pricing | 177 |
| Changelogs | 89 |
| **Total** | **460** |

Current lifecycle: 454 need validation, 3 degraded, 3 quarantined
(v0 docs, pricing, changelog), and **zero validated for unattended
monitoring**. The 457 technically validation-eligible sources are
NOT individually granted publisher access. Robots/terms, private
retention, product identity and review remain external human tasks.

An October 31 full crawl accounted for all 460 IDs, yet only 246/460
were marked captured (53.5%). This was not a measured correctness rate;
several real extraction errors were found and subsequent parser tests
remain predominantly synthetic.

## What P20A adds (zero network)

Run from the current reviewed repository checkout:

    python -m scripts.full_inventory_readiness \
      --out-dir output/private/p20a-preflight-1

This produces a NEW owner-private directory with:

    full_inventory_readiness.json
    all_460_source_review_queue.csv
    wave_01/manual_canary_plan.json
    wave_01/manual_canary_job_args.csv
    wave_02/manual_canary_plan.json
    wave_02/manual_canary_job_args.csv

The 460-row CSV preserves every source ID, configured URL, category,
publisher-policy state, lifecycle, risk and next manual action. It
never creates publisher approval or an execution ticket.

Two fixed, diagnostic waves each contain three documentation, three
pricing and three changelog sources. There are 18 distinct
manifest provider/product labels and six sources of each category:

| Wave 1 | Wave 2 |
|---|---|
| Docs: Kiro, Google Cloud AI, Anthropic API | Docs: Cursor, Supabase, Cloudflare Workers AI |
| Pricing: Gemini API, AWS Bedrock, Oracle OCI | Pricing: DeepSeek, Mistral, Together AI |
| Changelogs: OpenAI API, Render, xAI | Changelogs: Claude Code, Gemini CLI, GitHub Copilot |

These are risk-informed hypotheses based on old failure patterns,
not independently verified current defects. Some labels can share a
parent company. This is not a statistically representative selection.
The source IDs were frozen before looking at new test outcomes; never
silently substitute convenient sources after an access denial.

Each source uses the existing P08 manual canary plan with the EXACT
single source_id, validation collection mode and manifest/lifecycle
checksums. The spider argument cohort=all only describes the requested
selection *when source_ids names one source*; this is not a broad run.
There are 18 optional **manual** single-source Zyte jobs per wave:
two rounds x nine sources, 36 across both. **P20A schedules none.**

## Step 1 — First real 9-source canary

For every Wave 1 source, independently inspect publisher terms,
robots.txt, page ownership, product scope and private research
retention. A configured source ID or technical validation allowance
is not permission. Skip blocked and unresolved publishers, preserving
them in the selected-source denominator.

When explicitly permitted, manually run each pinned single-source
Zyte validation job, then independently archive the complete
Items, Requests, Logs and actual job metadata. Repeat a second
time with distinct job IDs so baseline changes cannot be mistaken
for new announcements. Never modify periodic schedules here.

Existing offline tools:

    python -m scripts.archive_jobs \
      --job-id YOUR_ZYTE_JOB_ID \
      --out-dir output/private/archived-wave-01

    python -m scripts.score_canaries \
      --plan output/private/p20a-preflight-1/wave_01/manual_canary_plan.json \
      --archives output/private/wave_01_archive_map.csv \
      --out-dir output/private/wave_01_quality_review

Use the P08 runbook for the archive mapping CSV and scoring protocol.
Review source IDs, URL and product scope, exact deployment/package
fingerprint, time ordering, two distinct jobs per source and any
403/429/robots, redirects, truncated source evidence or missing Item.

**Zero current collection-approved sources** means the P08 reviewed
eligible >=95% success gate cannot pass merely because unapproved
manual diagnostic runs returned HTTP 200. Human-reviewed terms,
two stable job IDs, correct product identity and Git-reviewed source
lifecycle approvals remain separate requirements.

## Step 2 — Expand to Wave 2 after checking Wave 1

Run Wave 2's nine preregistered sources in two distinct manually
approved, archived rounds, only where each specific publisher allows
the exact request. Across both waves, this is at most 36 manual
one-source jobs, not a full inventory. Investigate parser gaps,
wrong-product docs, empty HTML shells, large pricing tables, release
date/owner ambiguity, duplicate IDs, unexpected redirects, access
denials and inconsistent parser revisions.

The initial live canaries are a **safety and technical validation**
checkpoint, not proof of 99% source-wide accuracy or collection
rights for unrelated vendors. Preserve failed sources as explicit
holds and identify every changed adapter/fingerprint.

## Step 3 — When to do ONE supervised full-inventory diagnostic

For a single, nonpublishing 460-ID inventory **diagnostic** run,
these checks should pass:

1. The actual deployed Zyte egg/revision equals a reviewed,
   green-CI commit with exactly three spiders and the pinned
   460-ID source manifest.
2. Real two-round Wave 1 and Wave 2 manual canaries have been
   independently archived and inspected. No uninvestigated
   source-selection, robots/access-policy or job-accounting
   failure; known extraction defects are scoped and explicitly
   held when unresolved.
3. Every publisher URL intended for the broad run has an
   individually reviewed ownership, robots, terms, scope and
   retention decision. No implicit permission from manifest
   presence or historical success. Denied/quarantined URLs
   MUST be skipped and counted as held source Items.
4. The operator explicitly approves **one finite** Zyte
   diagnostic, checks its cost and schedules, and leaves
   Supabase writes, automatic release alerts and advisor
   approval completely disabled.
5. Capture and retain all original job metadata, Items, Requests
   and Logs; verify the 194/177/89 source-summary accounting
   independently of semantic accuracy.

**The 200 real pricing / 100 date human-gold thresholds are NOT
prerequisites merely to collect this bounded diagnostic dataset.**
The full run is a new observation for diagnosis, not a source
of trusted recommendation facts. Its data can help prepare
independently reviewed gold and discover difficult providers.

With the current registry, the three v0 quarantined URLs would
produce **held, not fetched** status Items. At most 457 URLs
are technically validation-eligible, but none is thereby
publisher-authorized. Do not run the broad job before the
individual publisher policy checks above.

## Step 4 — When to trust the results or enable recurring full monitoring

This is a **strictly later** milestone than one supervised
diagnostic run. The program's existing real-evidence checks
must be satisfied:

- >=200 distinct archived real vendor rate comparisons,
  >=99% agreement on decimal amount AND exact currency,
  billing unit, model, service mode, region, plan and dimensions.
  Unknown scope must not become a fully comparable rate.
- >=100 genuinely human-reviewed release owner/date examples
  with >=99% publication-day agreement, zero invented latest
  days and no first-baseline/reorder false announcements.
- P19A6 original-HTML independent full-page blind human
  census across a preregistered 15–25-provider changelog
  pilot, including missed events and access attrition.
- Actual first-party documentation page scope and child-page
  evidence reviewed; an HTTP-200 landing page alone is not
  documentation coverage.
- P08/P15B strict gates pass using **immutable real publisher
  bytes and Zyte job archives**, dual blind human reviews and
  >=95% usable collection over two rounds among source-policy
  reviewed, collection-eligible sources. A self-written
  accuracy JSON does not prove any of these.
- Every publisher for ongoing monitoring obtains an individual,
  Git-reviewed source lifecycle approval after policy and
  repeatable collection assessment. Currently **zero** have it.

These checks must precede trusted recurring full collection
or AgentFuse fact export. Do not turn archived HTTP-200 results
into automatically approved price or release claims.

## Final recommendation

**NO-GO today.** First complete policy-reviewed, archived, two-round
Wave 1 and Wave 2 live canaries and the broad-scope publisher policy
preflight. After those pass, one supervised **diagnostic** inventory
is sensible; it does not wait for every 200+ real rate and 100+
real date reference label. Use the diagnostic originals plus
independent human reviews to prove accuracy BEFORE recurring
monitoring or recommendation export. P20A only prepares pinned
dry-run plans, never jobs or permissions.
