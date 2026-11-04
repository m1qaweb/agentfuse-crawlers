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

## Step 2 — Expand to Wave 2 and independent gold

After diagnosing Wave 1, run Wave 2's preregistered sources only when
each publisher's policy allows the exact requests. This increases the
diversity of evidence; it is still not a full source audit.

Minimum evidence expectations already specified in the project:

- Pricing: >=200 distinct, real archived and independently reviewed
  amount+model+currency+unit+plan+region+scope observations, >=99% exact
  comparison agreement, zero fabricated comparable rates when scope
  or rate units are missing.
- Changelogs: >=100 real publisher event date examples, >=99% exact
  publication-day agreement, zero invented latest days and false
  new-release alerts from baselines/reorders. P19A6 also requires a
  15-25-provider original-HTML independent two-reviewer full-page
  census, including parser misses and inaccessible source attrition.
- Documentation: independent human inspection of original publisher
  pages, intended product identity, substantive child-page coverage,
  and JS-only or wrong-product scope. A docs landing page is not a
  verified complete documentation inventory.
- Collection: two archived real canary rounds, >=95% usable among
  source-policy-reviewed and Git-approved collection-eligible rounds,
  exact source accounting, no duplicate job, policy violation or
  unauthorized advisor facts.

The P08/P15B strict quality gate must recompute real gold with
hash-checked original publisher evidence and Zyte archives; a
precomputed accuracy-report JSON does not establish these conditions.

## Step 3 — Conditions for ONE supervised full diagnostic crawl

Run ONE 460-ID accounting diagnostic **only after all of these**:

1. Python 3.12 and 3.14 CI pass for the exact intended deployed
   revision, which is verified as the Zyte egg in use, preserving
   the three spiders and original source manifest.
2. Both manually approved canary waves have been captured twice,
   archived and independently reviewed. Previously observed pricing,
   docs and changelog failure cases have been fixed or held as
   explicit unknowns; real gold thresholds have been met.
3. Every URL that will be fetched has an individual current
   publisher ownership, robots, terms, product-scope and private
   retention review. Existing quarantined IDs stay held unless
   independently cleared. A denied URL is NEVER retried via evasion.
4. The user deliberately authorizes a finite, supervised full
   inventory diagnostic with clear Zyte budget, job monitoring and
   complete archived Items/Requests/Logs. Automatic schedules,
   production data writes and advisor-fact approval remain disabled.
5. The operator preserves original 194/177/89 expected Item counts
   and fails the quality review on missing IDs, unexpected redirects,
   forbidden 429/403 behavior, wrong products, invented dates,
   missing pricing dimensions or unreviewed accuracy.

With current local registry restrictions, a supervised validation
run could produce 460 **accounted-for** source Items, but the
three quarantined URLs would be held and NOT fetched. It would
have at most 457 technically permitted validation fetch candidates,
and those 457 still need external publisher-specific permission.
Do not equate source accounting with 460 lawful and correct fetches.

**Do not schedule the full crawl automatically or turn its first
results into AgentFuse recommendations.** Inspect and compare real
evidence and source-level quality before proposing a repeat.

## Step 4 — Conditions for unattended monitoring

Later than the one-time diagnostic: each monitored source must have
its own Git-reviewed lifecycle collection approval, established
publisher permission and repeated verified extraction. Currently
zero qualify. No schedule activation, autonomous news feed or
advisor fact may be inferred from green CI or a successful manual
full-inventory accounting run.

## Final recommendation

**NO-GO now.** The next meaningful milestone is Wave 1 manual
policy review and real Zyte canaries, followed by the source-bound
human gold that exposes actual extraction failures. P20A only
makes the next actions visible and pinned. Once you provide the
authentic Items, Requests and Logs from those jobs, prioritize
measured failures over additional speculative infrastructure.
