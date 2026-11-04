# P20B — GitHub-Only Zyte Operator Setup (No Local Repository)

**As of November 4, 2026.** The source commit shown in the operator's
Zyte Run screen was 4ced6f6-main, matching the merged P20A GitHub main
at that time. If the source package auto-deploys after another PR,
verify the newer actual Zyte deployment/version before any job.

## No laptop checkout or Python setup is needed

GitHub Actions can prepare the readiness plans remotely:

1. Merge the P20B PR only after CI is green.
2. Open the agentfuse-crawlers repository in GitHub.
3. Select **Actions** in the repository header.
4. Select **Prepare Zyte UI preflight (no crawl)** in the left sidebar.
5. Select **Run workflow**, choose **main**, and confirm.
6. Open the new successful workflow run and download its
   p20b-zyte-no-local-preflight-... **Artifacts** ZIP.
7. Unzip on any machine; there is no need to clone the repo, install
   Python, connect a GitHub key to Zyte, or run terminal commands.

The GitHub workflow NEVER schedules or requests anything on Zyte,
does not access publisher sites, does not use Zyte credentials,
does not change source permissions/schedules, and never writes to
AgentFuse or Supabase.

The ZIP includes:

    p20b-preflight/
      full_inventory_readiness.json
      all_460_source_review_queue.csv
      wave_01/manual_canary_plan.json
      wave_01/manual_canary_job_args.csv
      wave_02/manual_canary_plan.json
      wave_02/manual_canary_job_args.csv
    p20b-zyte-args/
      READ_ME_ZYTE_UI_SETTINGS_NOT_AUTHORIZED.txt
      zyte_full_3_spiders_NOT_AUTHORIZED.json
      zyte_full_3_spiders_NOT_AUTHORIZED.csv

The CSV files are exact *configured-source* plans, not grants of
publisher access or completed accuracy metrics. All full-spider
arguments are explicitly marked NOT_AUTHORIZED until the human
preflight is complete.

The run also triggers when P20B itself is first opened as a PR,
so its pre-merge Actions artifact can be reviewed before merging.
This runs the same no-publisher-fetch planning code.

## Your exact Zyte Run screen

- **Current version**: verify the seven-character prefix against
  reviewed GitHub main and the deployed package; 4ced6f6-main in
  the supplied screenshot matched the then-current reviewed main.
- **Spider**: select ONE of official_documentation, official_pricing
  or official_changelogs.
- **Job Units**: 1.
- **Priority**: Normal.
- **Tags**: optional; leaving them blank is fine.
- **Arguments**: press the plus (+) icon and enter EACH key and value
  in its own row. Do not combine all key=value settings into one row.

## Recommended NOW: one individually permitted validation source

For example, after independently reviewing that official OpenAI API
changelog page's access terms, robots, exact owner and research
retention for THIS request:

    Spider: official_changelogs
    Job Units: 1
    Priority: Normal

    Arguments key                 Value
    ----------------------------- -----------------------
    cohort                        all
    source_ids                    openai_api_changelog
    collection_mode               validation

Use the planned three additional expected_* SHA pins from
wave_01/manual_canary_job_args.csv for a strict, repeatable job.
You may omit them for initial manual UI entry, but preserving them
guards against an unnoticed source registry/selection change.

IMPORTANT: cohort=all with source_ids set to ONE configured source
does **not** crawl all changelogs. It tests ONLY that source.
Do not add confirm_full_inventory to a one-source validation job.
The P20A Wave 1 plan lists nine exact sources: three docs,
three pricing and three changelogs, two separate real job rounds,
all first-party access-policy-reviewed before collection. Source
policy denial must remain a recorded hold; do not substitute.

When done, export the complete job **Items, Requests, Logs and job
metadata** and share those JSON files in ChatGPT. You do not need
local scripts for review. Preserve distinct job IDs and timestamps.

## P21B security update — older full-run arguments are INSUFFICIENT

After P21B is merged and deployed, the three full-category UI
configurations below do **not** authorize publisher GETs on their own.
With no matching Git-reviewed source-access and exact-scope run
approval, each spider emits held source Items (no publisher page
request), including the old default three-source smoke cohort.
Do not interpret all-held Items as successful evidence acquisition.

The no-local GitHub Actions ZIP now includes
p21b-bulk-policy/bulk_validation_readiness.json and the full
460-source access-review queue. It reports **zero** current bulk
access reviews and zero authorized run plans.

Only after independently reviewing each publisher's exact URL,
robots/terms and private retention, and adding a separate short-lived
Git-reviewed run plan, can a bulk validation job supply
bulk_run_plan_id, expected_bulk_plan_sha256 and
expected_deployment_package_sha256. There is NO valid plan ID today.
See docs/P21B_ENFORCED_BULK_ACCESS_RUNBOOK.md.

## FUTURE ONLY: one full-inventory diagnostic (not now)

**Do not use these arguments until the real cross-category manual
canaries, source-specific publisher permissions, actual deployed
revision, budget and operator approval have been verified.**

When the above prerequisites are satisfied, run these as **THREE
separate Zyte jobs** (not a single 460-source spider):

| Spider | Expected source Items |
|---|---:|
| official_changelogs | 89 |
| official_pricing | 177 |
| official_documentation | 194 |
| TOTAL | 460 |

For each spider enter:

    Arguments key                Value
    ---------------------------- -----------------------
    cohort                       all
    confirm_full_inventory       yes
    collection_mode              validation

Add the exact, category-specific three SHA pins in the ZIP's
zyte_full_3_spiders_NOT_AUTHORIZED.csv as extra Argument rows:

    expected_manifest_sha256
    expected_selection_ids_sha256
    expected_source_registry_sha256

The first and third hashes match across all three jobs. The
selection_ids hash differs by spider. Never copy the changelog
selection hash into the pricing or docs job.

**Remove or omit source_ids, limit and offset** from any previous
test's Arguments before full inventory; otherwise you may
accidentally request a subset. If left with no Arguments,
the spiders default to cohort=proven, NOT all. If cohort=all
is set without source_ids, confirm_full_inventory=yes is mandatory.
Do not set collection_mode=monitor (zero source IDs currently
have reviewed ongoing-monitor approval).

The current policy gate has three quarantined v0 sources that are
emitted as held status Items; they must NOT be requested under
unresolved access rules. Other 457 technically validation-eligible
entries are NOT automatically legally approved: perform publisher
rights/robots/scope checks for any intended fetch. Job completion
and an HTTP 200 do not establish correct pricing, event dates or
full documentation.

Keep schedule changes, automatic release alerts, advisor fact
approval and database writes OFF. Archive the full Items/Requests/
Logs for each run. No automatic trusted facts can be created from
a diagnostic baseline. The original 194/177/89 configured
source-ID accounting is the primary completeness check, not a
claim that all publisher data is usable.

## What comes AFTER one safe diagnostic

Compare source-specific pricing units/models/regions, release
owner/date evidence, documentation scope and missing/truncated
extractions. Run the independent human P19A6 release review and
archive-bound P08/P15B quality gates before any recurring full
monitoring or trusted recommendations. A new live 460-source
diagnostic is allowed earlier than the complete 200-price/
100-date human accuracy benchmark, but only when its access-
policy and representative live-canary prerequisites have passed.

See docs/P20A_FULL_INVENTORY_GO_NO_GO.md for the full rationale.
