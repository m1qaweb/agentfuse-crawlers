# P14B — Full 460-source Zyte validation: operator procedure

**Goal:** inspect **ALL** pinned provider pages (194 documentation, 177
pricing, 89 changelogs) without silently omitting sources or treating
HTTP 200 as a correct AI recommendation. Unlike the earlier P08 small
canary, this is a **full-inventory diagnostic campaign**.

## When you should run full spiders

Run the first full-inventory campaign **after**:
1. PR #30 P14B has passed Python 3.12 + 3.14 CI and you have reviewed/
   merged it, or you independently adopt the equivalent exact Spider
   Arguments on the existing deployed version.
2. Zyte Code & Deploys shows a SUCCESS deployment for the GitHub \`main\`
   commit and the normal three spiders. The Git SHA is different from the
   in-Item \`deployment_revision\` package SHA-256.
3. Check publisher ownership, crawl/robots/terms and budget for each
   planned source. Respect the pinned source lifecycle; never bypass a
   denied publisher, 429 robots response, or login challenge.
4. Verify \`collection_mode=validation\`, **not** \`monitor\`, and schedule
   no recurring unattended all-source crawl. Make sure only the expected
   sources can be selected; do not enter arbitrary URLs in Spider Arguments.
5. Confirm the plan report counts exactly 460, with \`v0_docs\`,
   \`v0_pricing\` and \`v0_changelog\` explicitly **not fetched** due to
   unresolved publisher access. The dashboard may report one skipped
   source-summary Item per quarantined ID; that is correct.

**Do not wait until 200 real vendor prices / 100 dates are human-labeled**
before the first full diagnostic crawl. The full diagnostic crawl is how
the dataset needed for those manual accuracy evaluations gets collected.
However, do not use a finished full crawl for user-facing advisor facts
until independent gold, policy and release gates pass.

## Step 1 — Generate a plan for ALL 460 sources

Recommended: 25-source shards. This produces **20 manual jobs** across
the existing three spiders (8 documentation, 8 pricing, 4 changelogs).
Shards preserve exactly the same 460-source coverage, but permit retry
of a failed partition without wasting a giant run or mixing jobs.
Run jobs sequentially to respect publisher load, Zyte budget and
Scrapy's single-domain throttle; don't start 20 at once.

    python -m scripts.full_inventory_plan \
      --strategy sharded --shard-size 25 \
      --expected-package-sha256 YOUR_DEPLOYED_PACKAGE_SHA256 \
      --out-dir output/private/p14b

\`YOUR_DEPLOYED_PACKAGE_SHA256\` must be the actual 64-character package
fingerprint from the deployed crawler's \`deployment_revision\` or
matching verified CI package, **not** GitHub commit \`10d87e5e\`.
If unavailable, omit that flag for an *unverified* initial triage plan;
the final archived dataset cannot claim a pinned package until it is set.

**Alternative, if you specifically want 3 FULL spider jobs:**

    python -m scripts.full_inventory_plan \
      --strategy full \
      --expected-package-sha256 YOUR_DEPLOYED_PACKAGE_SHA256 \
      --out-dir output/private/p14b-three-jobs

This creates three jobs: \`official_documentation\` (194),
\`official_pricing\` (177), \`official_changelogs\` (89). Every full job
uses these Spider Arguments, with no \`source_ids\` field:

    cohort=all
    collection_mode=validation
    confirm_full_inventory=yes
    expected_manifest_sha256=<value in plan>
    expected_selection_ids_sha256=<unique per-spider value in plan>
    expected_source_registry_sha256=<value in plan>

**Why full jobs crashed earlier:** The spider explicitly refuses
\`cohort=all\` without \`source_ids\` unless
\`confirm_full_inventory=yes\`. It is a deliberate safety guard.
The tool prepares this argument; don't disable the guard. A different
exception in an actual Zyte job must be diagnosed from its logs, not
assumed to be this guard.

Both modes generate:
- \`full_inventory_plan.json\` with exact source selection and plan digest;
- \`manual_zyte_jobs.csv\` with a **spider_args_json** column for each job;
- \`publisher_review_flags.csv\` for year-pinned changelogs, documentation
  landing/index pages and generic blogs.

In the Zyte UI, enter values from \`spider_args_json\` as **Spider
Arguments**, not Scrapy project Settings. If a job fails its manifest or
registry fingerprint, do not override it: regenerate the plan for the
actual deployed code, then review the source policy change.

## Step 2 — Run all jobs and archive each real Job ID

Use the P07 read-only archiver once a job is finished:

    python -m scripts.archive_jobs --job-id 883514/1/EXAMPLE \
      --out-dir output/private/p14b-archives

The example ID is illustrative; paste the real finished Zyte job ID.
The archiver verifies 950 KB per-Item budget, page-order, Item checksums,
the official run metadata and one source-summary per source. All
local archives live under \`output/private/p14b-archives/jobs/\`.
Do not publish publisher page text, credential-bearing outputs or
human reviewer JSON into GitHub.

## Step 3 — Audit ALL 460, not just a few handpicked providers

For fully archived jobs (recommended), pass exactly the archive directories
corresponding to the planned 20 shards (or 3 full jobs):

    python -m scripts.audit_full_inventory \
      --plan output/private/p14b/full_inventory_plan.json \
      --archives output/private/p14b-archives/jobs/JOB_1 \
                 output/private/p14b-archives/jobs/JOB_2 \
      --out-dir output/private/p14b-audit

For Dashboard Items only, which **cannot verify original job metadata**:

    python -m scripts.audit_full_inventory \
      --plan output/private/p14b-three-jobs/full_inventory_plan.json \
      --items items_official_documentation.json \
              items_official_pricing.json \
              items_official_changelogs.json \
      --out-dir output/private/p14b-items-audit

The tool checks all 460 expected IDs once; duplicates, unexpected IDs,
forged source URL/product IDs, unsafe quarantine requests and off-plan
jobs fail closed. It separately exposes missing archive/jobs,
source-summary missing IDs, source identity drift, unexpected package
revisions, per-category HTTP/status/reason counts, pricing table gaps,
documentation scope quality and release identity/date gaps.

Outputs:
- \`summary.json\` with category metrics, source-accounting proof status,
  package verification and publisher fact/policy disclaimers.
- \`source_quality_triage.csv\`, one row per observed source ID,
  including concurrent issue reasons and concrete review action.
- \`job_accounting.csv\`, one row per planned job, including exact
  missing/incomplete partitions.

**A green \`whole_inventory_accounted\` means all source-summary Items
were received, not that they are true/complete vendor facts.**
\`publisher_evidence_accuracy_independently_verified\` always remains
\`false\` until real publisher evidence is independently reviewed.

## Step 4 — Focus improvements across ALL providers, then rerun ALL

After a 460-source baseline:

- Documentation: prioritize static app shells, canonical/product mismatch,
  overview indexes and missing technical sections. P13 child links are
  **review-only**, not automatically allowed additional URLs.
- Pricing: inspect explicit currency, unit, model, region, tier, caching,
  service mode and table completeness. P11B's bounded **relevant table
  windows** are needed for publishers with more than 16 relevant tables,
  especially historical examples Gemini/AWS Bedrock. One bounded source
  page with 300 capped observations cannot be called complete.
- Changelogs: identify repeat headings, unique permalinks, explicit
  publication dates, duplicate IDs, missing release events and mixed
  ordering; never infer date from crawl or an edited-at timestamp.
- Publisher policy: keep \`v0\` quarantine and any new access failures
  blocked. Do not turn a successful HTTP request into monitor approval.
- Independent real-world gold: review 200+ distinct genuine price
  observations and 100+ genuine dated events from different vendors,
  including incorrect/negative examples; score PR14A archives against
  actual official pages. Future P14C must add robust documentation gold.
- Repeatability: run a second full-inventory campaign AFTER improvements
  and compare the same package/version/source cohort and source quality
  across two jobs or rounds, not only nominal HTTP success.

If the validation platform reaches budget/slot limits or an archived job
fails, use smaller shards; do not bypass publisher restrictions or silently
drop missing URLs.

## Limits and security contract

This PR does not start any crawler, create Zyte credentials, change 460
configured URLs, install a new spider, modify publisher policy, run a
browser-render add-on, approve AgentFuse facts, write Supabase, or schedule
unattended monitoring. GitHub main is auto-deployed to Zyte, so merging
does change its installed code package; review CI and plan before merge.
The accuracy of individual prices, capabilities, and release dates is still
unproven until explicit human review.


## P14B integration with P14A gold: reuse the full campaign's batches

**Important correction:** P14A originally required one exact source per
job. P14B now allows the **same 20 pinned multi-source archives** to
produce unreviewed pricing/date/doc review packets and to bind human
gold, without re-fetching each source individually. A batch is eligible
only when its original P14B plan and entire P07 archive scope, source
accounting, registry, publisher skips and deployed package fingerprint
are verified. The original one-source-only path still blocks multi-source
archives if the plan is omitted.

    python -m scripts.real_gold_binding \
      --full-inventory-plan output/private/p14b/full_inventory_plan.json \
      --archives output/private/p14b-archives/jobs/JOB_1 \
                 output/private/p14b-archives/jobs/JOB_2 \
      --prepare-review output/private/p14b/unreviewed_evidence.json

The same \`--full-inventory-plan\` flag can be used with
\`--reviewed-gold\`, or pass \`--gold-inventory-plan\` to
\`scripts.quality_gates\` when scoring real human labels. A partial
set of fully verified **planned** batch archives is allowed for gold
sampling, but the separately audited **full 460-source coverage** must
still be complete before declaring the inventory campaign successful.
Pages with HTTP failures, insufficient hashes and v0 quarantine remain
in inventory diagnostics but are excluded from gold observations.

This saves re-crawling hundreds of sites while preserving a high-trust,
source-indexed audit trail and case-level human truth verification.
