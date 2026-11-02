# P15A — Frozen Nov 2 evidence and reproducible failure matrix

**Phase:** accuracy-first P15A from the 2026-11-02 comprehensive blueprint.
**Status:** implementation + synthetic CI, with exact input hashes pinned.
No change to the 460-source manifest, three spiders, publisher permissions,
Zyte schedule, database, or advisor publication.

## Why this is necessary

Earlier P10–P14B work established source accounting, provenance, bounded
parsing and multi-axis diagnostics, but each generic-parser revision could
change a metric without a locked baseline. The Nov 2 three Zyte dashboard
exports give **460 source summaries** and a useful frozen regression
dataset. They are **NOT original publisher HTML** and not official P07
checksum-authenticated job archives; never claim original HTML re-extraction
or independent price/capability/date accuracy from these files.

### Exact frozen export identity

- \`official_pricing\` job \`883514/3/10\`, 177 Items
- \`official_documentation\` job \`883514/2/12\`, 194 Items
- \`official_changelogs\` job \`883514/1/13\`, 89 Items
- Deployed crawler package fingerprint:
  \`359051038fea0c0d165760980ff1f0d74ce527a3ebb1601a68106402d7248cce\`.
- 9 input SHA-256 values, byte sizes and record counts are locked in
  \`baselines/2026-11-02_dashboard_export_lock.json\`.
- No confidential Items, original raw publisher text, access tokens,
  Requests URLs or Logs bodies are committed to GitHub.

Run this command on a private operator workstation with the nine *original*
JSON exports (update the filenames/paths if you stored them elsewhere):

\`\`\`bash
python -m scripts.freeze_baseline \
  --pricing-items items_official_pricing_10.json \
  --pricing-requests requests_official_pricing_10.json \
  --pricing-log log_official_pricing_10.json \
  --documentation-items items_official_documentation_12.json \
  --documentation-requests requests_official_documentation_12.json \
  --documentation-log log_official_documentation_12.json \
  --changelog-items items_official_changelogs_13.json \
  --changelog-requests requests_official_changelogs_13.json \
  --changelog-log log_official_changelogs_13.json \
  --baseline-lock baselines/2026-11-02_dashboard_export_lock.json \
  --out-dir output/private/p15a
\`\`\`

The command verifies:
- Exactly 194+177+89 source IDs from the currently pinned manifest, each
  once, including no-fetch Items for three quarantined v0 sources.
- Official source URL/provider/spider and unchanged source/manifest/
  selection/registry/package fingerprints and validation-mode cohort.
- Matching job IDs in the three log exports, explicit successful scrape
  close and 100% Items source-summary accounting.
- Request records include every original source URL that yielded an HTTP
  status; robots/redirect/other Requests are not mistaken for source fact
  approval. File sizes and exact bytes match the lock.
- Previously known key totals: 422 HTTP 200, 3 quarantine skips,
  3,448 price observations detected, 3,050 retained, zero comparable,
  66 documentation topic hints, 5,086 docs links detected, 3,584
  omitted, 4,356 changelog events detected, 2,426 retained, 1,762
  dated, 118 surplus duplicate IDs.
- All outputs deterministic: no crawl timestamp fabricated and no
  requests or factual approval performed.

## Artifacts and replay scope

The private output directory contains:
- \`freeze_manifest.json\` — exact SHA-256 of each supplied file, declared
  Zyte job ID, crawler/manifest/registry identity, aggregate request
  statuses and an integrity digest of the computed quality matrix.
- \`quality_baseline.json\` — typed source counts, concurrent issue flags,
  category outcomes, price/date/docs aggregate failure metrics.
- \`source_failure_matrix.csv\` and \`.jsonl\` — one row per pinned source:
  failures across independent axes (HTTP/access, redirect, canonical,
  static JS shell, product scope, source freshness, clipping, price
  dimensions, region/currency/plan/unit, release identity and dates),
  plus proposed review priority and family hint.

These artifacts permit **deterministic post-extraction replay**: give the
same nine byte-identical exports to the command, and obtain the same
quality matrix, counters and file-hash identities. This is not publisher
HTML replay. P16–P19 parser improvements will require **separately
approved and privately retained original HTML/feed fixtures** or live
manual verification before asserting real extraction gains.

## Privacy, retention and evidence-integrity rules

By default, the script emits only derived matrix/metadata. It **does not**
copy the original Items/Requests/Logs into GitHub or into the output
directory. Keep those original exports in restricted, access-controlled,
encrypted storage under your organization's publisher/retention policy.

To *explicitly* create private plaintext copies on a **pre-existing
encrypted local volume**, both dangerous flags are required:

\`\`\`bash
python -m scripts.freeze_baseline [all nine export arguments] \
  --copy-private-exports --acknowledge-plaintext-private-storage \
  --out-dir /encrypted/private/agentfuse/p15a
\`\`\`

No encryption is implemented by this CLI. The operator must supply a
trusted encrypted filesystem and retention policy. By default output
permissions are 0700 directory / 0600 files on POSIX, and the utility
refuses symlink output files. Define a written time-to-live for original
publisher HTML/Requests and reviewed snapshots; do not store secrets
in logs, source URLs or Git commits.

If the official job metadata remains available and access policy
permits, additionally run the existing P07 read-only archive for each
job \`883514/3/10\`, \`883514/2/12\`, \`883514/1/13\`.
Only official archive metadata can establish job completeness and Item
integrity against Zyte's storage API. A historical P07 re-fetch can
also fail if Zyte no longer retains the original Items. Do not silently
replace old exports with a fresh crawl and claim they are the same bytes.

## P15A exit, P15B input

- The 460 Item/Request/Log export lock passes exactly, with no missing
  or duplicate source, correct 3 quarantines, correct source/package
  identity and a stable 460-row failure vector.
- A reviewed source-owner work queue exists, with P0 pilot sources
  explicitly labeled **candidates**, not permission-approved vendors.
- No \`approved_for_advisor=true\`, source-policy promotion, direct DB
  writes, or fake "verified" price/date/capability claims.
- Actual raw HTML retention availability must be reported honestly.
  If original page bodies were not retained, collect *small publisher-
  policy-approved fixtures* in a subsequent P15B/P16 pilot; do not
  conflate dashboard excerpt hashes with entire response snapshots.

Next PR: **P15B — Human Gold Labeling Protocol** (source-stratified,
blind holdout, price/date/capability examples, reviewer ownership, and
actual publisher evidence), followed by P16 source-owned adapters.
Run another 460-source crawl only after pilot gold and adapter improvements.
