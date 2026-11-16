# P25 — Operational 200–300 publisher-URL Zyte crawl (3 full-category jobs)

**Implementation date:** 16 November 2026  
**Target:** 200, 205, …, 300 individually reviewed URLs, balanced 40% documentation, 40% pricing, 20% changelog.  
**Current operational decision:** **NO-GO**. Actual packaged per-source access registry still has `reviews={}`, and the run-plan registry still has `plans={}`. This code does **not** make the full crawl runnable today.

## The full-size approach — do not confuse 460 Items with 460 GETs

The three **existing production spiders** support entire categories and preserve every configured source as an Item (including held/unreviewed sources) while sending network Requests **only** for sources explicitly allowed by the exact, Git-reviewed P21B plan.

| Single full-category job | Manifest Items | Authorized requests at 200 target | At 250 | At 300 |
|---|---:|---:|---:|---:|
| `official_pricing` | 177 | 80 | 100 | 120 |
| `official_documentation` | 194 | 80 | 100 | 120 |
| `official_changelogs` | 89 | 40 | 50 | 60 |
| **Campaign total** | **460** | **200** | **250** | **300** |

At the maximum 300 target, **160 sources are accounted for but held**. A held Item is not a fetched URL. Scrapy may additionally issue robots.txt requests; source counts are **not** a limit on total HTTP transactions. G3's historical `captured` diagnostic is not independently verified accuracy, and zero pricing sources achieved that status in the November 4 real baseline.

The `P21B` production bulk gate already requires a **reviewed exact source URL access record for each URL to be fetched**, and a **short-lived Git-reviewed run plan for the complete category selection**. The new P25 code directly reuses the existing `authorize_bulk_run()` implementation and is not permitted to create or alter these decisions. This means no bulk source can be unlocked by a command-line flag, selection ranking, or checksum alone.

## Implemented (not aspirational)

1. `scripts/p25_large_campaign.py` — read the G3 redacted 300-source review CSV and deterministically select 200–300 source IDs; inspect **all three exact full-category installed run plans**, access reviews, expiry, quotas, lifecycle holds, manifest/SHA bindings and current package fingerprint. Write a private immutable NO-GO inspection report. Plan-only operation makes **zero Zyte requests**.
2. `scripts/p25_launch_full_campaign.py` — **real opt-in job dispatch** to Zyte's documented `POST https://app.zyte.com/api/run.json` endpoint, with one unit, normal priority, the **exactly three existing full-category spider arguments**, and `CLOSESPIDER_TIMEOUT` bounded to 600–3300 seconds. No proxy bypass, new spider, periodic job, or vendor-unapproved URL is introduced.
3. **Full-campaign gate before any POST:** all 200–300 selected publisher URLs must have current, independently reviewed access entries with `bulk_validation`, and all **three** full-category run plans must match **exactly** the selected authorized sets; partial or larger plans are rejected. The caller must verify the deployed Zyte package separately and explicitly attest current account billing and source rights. The script compares the operator-supplied deployed package SHA with current compiled package bytes but **cannot independently retrieve remote egg bytes**.
4. **Account gate:** fetch the existing read-only G2 pending/running/schedules pages (exactly three Zyte GETs), require both job pages and the schedule page to be complete, no pending/running Jobs, no enabled periodic schedules. These reads are **non-atomic** and do not guarantee the account stays idle forever.
5. **Duplicate guard:** before POST, write a private exclusive (create-only) `ATTEMPTED_NO_BLIND_RETRY` record. If Zyte times out, returns malformed JSON, or the client disconnects, the marker remains and **no automatic retry occurs**. A valid Zyte Job ID writes a separate `SCHEDULED_NOT_FINISHED_NOT_AUDITED` receipt, never a fictional completed/accurate-crawl claim.
6. **One full category per explicit operator dispatch.** The three categories are ordered pricing, documentation, changelog. **There is no automated chain**: an error or 429 in the first job cannot silently schedule the other two.

**Important limitations:** local file-exclusivity is not a distributed lock across different machines/operators; Scrapy's timer is not a guaranteed monetary cap. Publisher robots GETs, any separately billed Zyte API features, cloud storage, Scrapy Cloud subscription unit limits, free-tier maximum runtime, and data retention must be independently verified. Do not use this feature from simultaneous CI runners or several laptops.

## Step 1 — prepare the complete 300-source campaign

Use the G3 output **generated from the three private, SHA-pinned November 4 originals** (do not commit those raw files):

```bash
python -m scripts.g3_historical_items_triage \
  --input-dir /secure/zyte-nov04-original-items \
  --out-dir /secure/g3-nov04-NEW

python -m scripts.p25_large_campaign \
  --g3-top300 /secure/g3-nov04-NEW/g3_historical_top300_NOT_RUN_LIST.csv \
  --target 300 \
  --out-dir /secure/p25-300-NEW
```

Inspect `p25_full_campaign_plan_NO_GO.json`. At current main it must say `missing_current_source_access_reviews=300`, `local_policy_and_three_plan_scope_complete=false`, `readiness_to_launch_from_this_report=false`. This is **not a source-rights approval**. It is the exact scope for the eventual full crawl.

To choose 200 instead of 300, pass `--target 200`; a target of 250 uses `--target 250`. All three use **three category-wide jobs**, not 20 tiny shards.

## Step 2 — review and deploy real publisher-authorized scope

This is the **material blocking work**; it cannot be completed by a synthetic GitHub CI test:

- Review each proposed exact publisher URL, source ownership, applicable website access terms, robots behavior for the proposed crawler user agent, allowed commercial fact use, redirect behavior, request throttling, raw HTML/Items/Requests/Logs retention, and downstream usage. **Some G1 candidates have substantive scraping restrictions**. Exclude or replace those only through independent review and a separate documented selection/research change; do not silently treat a different host as the same source.
- Create appropriately evidenced, independently **human-reviewed** `allowed_reviewed` entries with `scopes=["bulk_validation"]` for **all target source IDs** in the production `agentfuse_crawlers/data/validation_access_reviews.json` registry, via separately reviewed PR. Never write true attestations that a human did not make. A source not genuinely authorized must remain held and reduces the obtainable 200–300-source target.
- Create **three** separately Git-reviewed full-category run plans in `agentfuse_crawlers/data/bulk_run_authorizations.json`, each `source_ids` listing its entire category's manifest IDs and `authorized_source_ids` listing **only** that category's selected and reviewed source IDs **in manifest order**. Each plan must include the existing P21B 7-day expiry, correct SHA scope, named real reviewer, and primary-request budget equal to authorized IDs. All three plans must agree with the **same** access-registry fingerprint. Plan target caps: **120, 120, 60** at 300 URL campaign, not 194/177/89.
- Rebuild and **deploy** the compiled Scrapy Cloud egg that actually contains those reviews and plans. Compare the hash of deployed **package bytes** with `local_package_sha256_NOT_REMOTE_PROOF` and independently verify the installed remote deployment/version in Zyte. A GitHub commit SHA and local fingerprint alone do **not** prove the active remote version.
- Inspect the Scrapy Cloud account's actual number of units, billable features, current invoices/usage, subscription, planned spend, storage/retention, API/proxy costs, and concurrent/pending/scheduled jobs. Independently approve the true financial ceiling and stopping conditions; the runner's timer and `units=1` setting alone do not impose a USD cap.

## Step 3 — dispatch the FULL campaign (only after all external gates)

Rerun Step 1 **against the deployed reviewed package**. It must show:

```text
target_primary_urls: 300
reviewed_bulk_source_count_in_campaign: 300
missing_current_source_access_reviews: 0
local_policy_and_three_plan_scope_complete: true
planned_full_category_jobs: 3
```

Even then, `readiness_to_launch_from_this_report=false` intentionally remains true: the offline report cannot verify vendor billing, external publisher rights, or the independently observed remote package.

After **actual verified account/project/version/budget and true publisher-rights decisions**, the responsible operator may dispatch the first **full category** using the code below. The SHA values are **not** secret but must be copied from the reviewed current campaign report and separately observed remote package, not invented:

```bash
python -m scripts.p25_launch_full_campaign \
  --g3-top300 /secure/g3-nov04-NEW/g3_historical_top300_NOT_RUN_LIST.csv \
  --target 300 \
  --project-id VERIFIED_SCRAPY_CLOUD_PROJECT_ID \
  --dispatch-category pricing \
  --campaign-sha256 VERIFIED_CURRENT_CAMPAIGN_SHA256 \
  --remote-package-sha256 INDEPENDENTLY_VERIFIED_REMOTE_PACKAGE_SHA256 \
  --ack-account-billing ACCOUNT_BILLING_AND_JOB_RUNTIME_REVIEWED \
  --ack-source-rights ALL_CAMPAIGN_SOURCE_URL_RIGHTS_INDEPENDENTLY_REVIEWED \
  --timeout-seconds 3300 \
  --ledger-dir /secure/p25-shared-persistent-ledger
```

Uses `ZYTE_SCRAPY_CLOUD_API_KEY` in the environment, **never** as a CLI argument or source file. Do not paste the key into chat, PRs, or GitHub logs.

Repeat manually for `--dispatch-category documentation` and `--dispatch-category changelog` **only after the previous full job finished and its original Items/Requests/Logs were inspected**. The SAME persistent ledger must be used. If a POST fails or times out, inspect the Zyte account and reconcile the outcome first; **do not delete the attempted marker to rerun blindly**.

Each full category will contain held Items for unreviewed/non-target sources. **After all three jobs have finished**, archive each real job's Items and completed-job metadata using the existing **read-only** archive utility (substitute each *actual* Zyte Job ID, not a guessed one):

```bash
python -m scripts.archive_jobs --job-id REAL_PRICING_JOB_ID --out-dir /secure/p25-archive
python -m scripts.archive_jobs --job-id REAL_DOCUMENTATION_JOB_ID --out-dir /secure/p25-archive
python -m scripts.archive_jobs --job-id REAL_CHANGELOG_JOB_ID --out-dir /secure/p25-archive

python -m scripts.p25_audit_campaign_items \
  --g3-top300 /secure/g3-nov04-NEW/g3_historical_top300_NOT_RUN_LIST.csv \
  --target 300 \
  --archive /secure/p25-archive/jobs/PROJECT_SPIDER_JOB_FOR_PRICING \
  --archive /secure/p25-archive/jobs/PROJECT_SPIDER_JOB_FOR_DOCUMENTATION \
  --archive /secure/p25-archive/jobs/PROJECT_SPIDER_JOB_FOR_CHANGELOG \
  --out-dir /secure/p25-full-campaign-items-audit-NEW
```

The archive subdirectories are the Zyte Job IDs with slashes replaced by underscores, as printed by `scripts.archive_jobs`. Use those **exact** printed paths. The new P25 archive audit supports the three-argument P23E0 full-category mode (the legacy P14B audit expects extra pins). It rejects duplicate/missing-job cross-category scope, wrong package/manifest/selection, unauthorized extra fetched sources, wrong job arguments, and package or source ID provenance drift. It reports incomplete/blocked campaigns as **NO-GO**, even when the source metadata appears healthy.

**Still required for independent completion:** download/inspect genuine Requests/Logs (using an appropriately scoped read-only operator export) and retained original publisher HTML where legally allowed; reconcile true source URLs/methods/statuses and robots/canonical behavior, then independently compare extracted pricing dimensions, documentation scope, and release identities with human-reviewed publisher evidence. **The Items audit alone cannot prove that there were no extra HTTP requests**, that a price is correct, or that a publication date is current. Unknown/aborted jobs are incomplete, not successful.

## What “ready” actually means

| Gate | Today's status | Owner |
|---|---|---|
| Three production category spiders | Implemented | Code |
| Full 200/250/300 selection, 3-job binding | Implemented in P25 | Code |
| Opt-in real Zyte POST, fail-closed duplicate and queue gates | Implemented in P25; unexecuted | Code / Operator |
| 200–300 genuine publisher access decisions | **0 current reviewed** | Human reviewer / publisher |
| Three matching reviewed category run plans | **0 current plans** | Human operator |
| Verified actual deployed Scrapy package | Unverified | Zyte account operator |
| Account-specific spend and runtime ceiling | Unverified | Zyte account operator |
| Real Items/Requests/Logs and publisher-owned truth | Not yet collected for this campaign | Operator / independent reviewer |

**A calendar ETA is not justifiable while the above external actions have zero verified progress.** A future successful launch is not equivalent to 200–300 accurate, current, or legally reusable records.

Relevant vendor documentation: [Scrapy Cloud Jobs API](https://docs.zyte.com/scrapy-cloud/usage/reference/http/jobs.html), [Scrapy Cloud units](https://docs.zyte.com/scrapy-cloud/usage/units.html), [Scrapy Cloud pricing](https://docs.zyte.com/scrapy-cloud/pricing.html). All three are first-party reference docs; account-specific billing is not supplied by these general pages.

## Tests

```bash
python -m pytest -q tests/test_p25_large_campaign.py
python -m pytest -q
```

The tests **mock** all vendor HTTP calls and positive permissions using explicitly synthetic, unprivileged in-memory objects. No Zyte key, real publisher access approval, real POST or actual source GET is used in CI.
