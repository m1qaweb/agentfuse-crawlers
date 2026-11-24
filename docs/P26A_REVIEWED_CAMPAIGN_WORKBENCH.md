# P26A — Finish actual source review and three exact P25 run plans

**Goal:** remove clerical effort from 200–300 exact-URL decisions without
turning research, historical captures or blank sheets into permissions.
This tool does not verify the reviewer's identity or legal conclusion and
cannot dispatch Zyte. It never edits the production registries.

## 1. Prepare the review worksheet

From the latest installed checkout and the authentic G3 all-460 CSV:

    python -m scripts.p26a_reviewed_campaign \
      --g3-all460 /secure/g3-nov04-NEW/g3_historical_triage_all460_REVIEW_ONLY.csv \
      --target 300 --out-dir /secure/p26a-review-NEW

Use the P26A worksheet (not the older informal review-queue CSV). All 460
source identities, rank and exact URLs are immutable. Sort rows by hostname
if helpful, but do not change any immutable cells or omit held sources.
No decision cells are prefilled. The installed record hash detects a
stale attempt to replace an existing source decision.

## 2. Fill actual review decisions

A human accountable for the source review checks first-party ownership,
applicable website/API access terms, actual crawler UA/path in robots.txt,
commercial derived-fact use, redirects, throttling, and permitted storage
of Items, Requests, Logs and any separately retained response evidence.
Reuse shared publisher evidence when it applies to each exact URL; do not
assume identical terms across all hosts or products. Research evidence
may be prepared by an agent, but it is not a human approval.

* Leave decision blank or not_reviewed until review is complete. Such
  rows preserve existing installed records, including denied ones.
* allowed_reviewed requires a real named reviewer, actual timezone-aware
  review and expiry times, evidence URLs, explicit yes for ALL three
  attestation columns, substantive evidence notes and retention scope/TTL.
  New positive records use bulk_validation scope only. They cannot be
  generated from a ranking, public accessibility or HTTP status.
* prohibited_reviewed or deferred require the real reviewer, dates and
  substantive notes. Leave evidence URLs blank if unavailable, and
  attestation cells blank or no. These decisions explicitly revoke access
  scopes when replacing a previous decision.
* Expiry must meet the existing 30-day source-review limit. A newly
  imported allowed review must be current. Do not approve a lifecycle-held
  source merely to meet a quota; it remains held by P25.
* Retention details are stored in the existing evidence_note field (1500
  characters total). Keep private account data and secrets out of the
  worksheet, registry and Git history. If an earlier single_validation
  decision must be preserved, do not blindly replace it with this
  bulk-only workflow; review the desired complete record separately.

Use the same full worksheet for successive review batches before merging.
Blank cells or research notes alone do not become positive decisions.

## 3. Compile and measure the actually reviewed pool

    python -m scripts.p26a_reviewed_campaign \
      --g3-all460 /secure/g3-nov04-NEW/g3_historical_triage_all460_REVIEW_ONLY.csv \
      --reviewed-csv /secure/p26a-review-NEW/p26a_exact_url_review_worksheet.csv \
      --target 300 --out-dir /secure/p26a-compiled-NEW

The output candidate access registry is a mechanical conversion of explicit
decisions plus unchanged installed records. It uses the existing production
validator. Review and merge it through the normal accountable-human PR;
do not upload the raw worksheet or private evidence.

The NO-GO report counts exact current bulk reviews by category, missing
quotas, feasible 200–300 targets and selected reviewed/pending source IDs.
No smaller target is silently chosen. If 300 is infeasible, inspect the
reported maximum and explicitly choose a feasible 250/200 or other P25
five-URL increment. If none reaches 200, do not manufacture approvals.

Only when every selected ID has a current bulk review does the tool
generate the three exact, unsigned category plan drafts. These include
all category manifest IDs, exactly the P25-selected authorized IDs in
manifest order, access/manifest/selection/URL hashes and exact primary GET
caps. The plans use zero publisher redirects. The drafts are intentionally
invalid for P21B dispatch: blank reviewer and review/expiry times, and
publisher_policy_review_attested=false. No campaign launch SHA is issued.

## 4. Independently review and merge the exact plans

Once the candidate access registry is reviewed and installed, rerun the
workbench without --reviewed-csv against that registry, with the same G3
ranking and chosen target. Confirm the current installed access hash
matches the plans. The accountable operator must review each category
scope and supply its real approver, actual timestamps, expiry no later than
7 days after review and preferably no later than the earliest selected
source-review expiry (the report gives this time). Set the attestation true
only after the required human review. Never infer approval from this tool.

If installed plans already exist, review their replacement/removal
explicitly; these drafts contain ONLY the three proposed campaign plans,
not a merge of unrelated plans. Any changed access registry invalidates
the former digest-bound plans. Use a separate reviewed PR. After the
final merge, rebuild the egg and run the original P25 offline planner.
Only its final exact package/plan digest applies to the actual run.

Then independently verify live deployed egg content, account budget and
G2 pending/running/schedule snapshot; use the existing P25 launcher.
Preserve P24 stop-on-access-barrier behavior and P26B evidence export.
The original frozen 18/36 canary study and production-quality gates remain
separate; the owner must explicitly approve the larger diagnostic
sequencing. A valid access registry or plan is not a finding of extraction
accuracy or readiness for AgentFuse advisor ingestion.

No new spider, policy bypass, source changes, network call or automatic
authorization. At initial empty registries, all 300 target reviews remain
missing and no draft plans are produced.
