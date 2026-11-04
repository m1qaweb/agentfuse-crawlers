# P21A -- Reproducible November 4, 2026 Zyte baseline

**Scope:** First offline milestone of
AGENTFUSE_CRAWLERS_EVIDENCE_FIRST_IMPLEMENTATION_PLAN_2026-11-04.md.
**Safety:** NO publisher GETs, NO Zyte jobs, NO writes to the deployed
package, lifecycle/manifest, Supabase or advisor.

## What is frozen

The nine exact Zyte Dashboard JSON arrays from 2026-11-04.
The script has nine explicit SHA-256 pins, including original byte
lengths in its private output:

| Category | Spider | Job ID | Source Items |
|---|---|---|---:|
| Documentation | official_documentation | 883514/2/15 | 194 |
| Pricing | official_pricing | 883514/3/11 | 177 |
| Changelog | official_changelogs | 883514/1/16 | 89 |

All nine exports have the *reported* deployable Python-package
fingerprint 1f02ac83f9388b8636ce46c861f92bdddc80b0463fd3a8c4ce12690d698d8a17,
source manifest SHA 231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933
and lifecycle SHA 776384e860fe3207c734719a19b782adb20b30468f856549bfe35378709e6cc2.

That fingerprint is **not** proof of which Git commit was deployed;
the exported source-revision claim is empty. The Dashboard exports
also lack independently archived Zyte job envelopes, response HTML
bytes and independent publisher-origin authentication. Never describe
them as verified pricing, date or documentation facts.

## Running locally, without requesting anything

Retain the original files without modification in an existing PRIVATE
directory, with these exact filenames:

    items_official_documentation_15.json
    requests_official_documentation_15.json
    log_official_documentation_15.json
    items_official_pricing_11.json
    requests_official_pricing_11.json
    log_official_pricing_11.json
    items_official_changelogs_16.json
    requests_official_changelogs_16.json
    log_official_changelogs_16.json

Use a unique, private HMAC key to preregister six holdout sources
from each category independent of how the current parser performed.
This does not create reference labels or validate representativeness.

    export AGENTFUSE_P21A_HOLDOUT_KEY='REPLACE_WITH_32PLUS_PRIVATE_RANDOM_CHARACTERS'

    python -m scripts.audit_nov04_inventory \
      --input-dir /secure/nov04-zyte-originals \
      --out-dir /secure/p21a-frozen-audit-1

The parser refuses any changed raw input SHA-256, missing arrays,
unknown/duplicate source, forged source/manifest/registry/selection/
package/job provenance, source status/HTTP inconsistency, missing
initial or final request, fake non-GET request, missing finished-job
log, or an advisor-approved fact. No files are overwritten.

**Importantly:** initial configured URL status and FINAL response
status need not be the same. A permitted same-host HTTP 308 may be
followed by a separate HTTP 200 Request for the final URL. Both
requests are accounted for, and robots.txt GETs are separated. The
request stream is **not** one row per original source summary.

## Expected private outputs (not checked into GitHub)

    baseline_metrics.json
    source_triage.csv
    request_outcomes.csv
    risk_clusters.json
    holdout_source_ids_PRIVATE.json
    README.md

The first JSON has two conceptually independent report sections:

1. \`operational_run_integrity\`: exact selected source accounting,
   source/Request/Log reconciliation, statuses, SHA fingerprints,
   redirect request chains, source policy and job proof limitations.
2. \`evidence_and_semantic_quality\`: diagnostic price observations,
   normalized vs unqualified numeric amounts, changelog owner and
   publication-window risks, documentation scope and URL omissions.
   **None** is independent publisher-fact correctness.

The CSV queue ranks NON-holdout source-review risks using a simple,
transparent heuristic. It does not claim that unknown providers are
unimportant or that a detected pricing rate is correct. Keep the
private holdout and HMAC key out of developer calibration loops; do
not expose its observed performance while tuning a new adapter.

The exact input bytes stay where the operator stored them and are
NEVER committed, copied into regression fixtures, served publicly
or shipped to the AgentFuse backend. Any original HTML must be
acquired separately under publisher-specific access/retention review
(P22A) and securely retained with permitted TTL.

## Expected baseline metrics from the real Nov 4 exports

| Metric | Known current baseline |
|---|---:|
| Source summaries | 460 |
| HTTP 200 source summaries | 418 |
| Sources marked captured | 65 |
| Sources marked needs_review | 351 |
| Redirect rejected | 28 |
| Source HTTP errors | 11 |
| Quarantined sources with no source GET | 3 |
| Partial captures | 2 |
| Pricing observations retained | 2742 |
| Fully comparable pricing candidates | 0 |
| Changelog events detected / retained | 4240 / 2344 |
| Changelog dated entries retained | 1685 |
| Changelog repeated ID excess occurrences | 115 |
| Docs navigation candidates / omitted | 4977 / 3498 |

These values are crawler-generated evidence counts, NOT prices or
dates that were independently verified to be correct. The tool
must recompute them from original files rather than accepting a
user-supplied aggregate. Do not silently correct any mismatch; record
the mismatch and fix the code or locate the actual input export.

## Definition of done and next PR

P21A is complete when a fresh offline run against the private
original nine files:

- Recomputes and reconciles ALL 460 configured source IDs,
  true raw SHA-256s, category and job IDs, initial and final request
  statuses, source count in logs, and no advisor approvals.
- Produces an owner-private, immutable-by-convention baseline
  report and the 460-row source triage with 18 source-disjoint
  precommitted holdout IDs.
- Never confuses captured with verified or accounts robot/redirect
  probes as additional configured source Items.
- Runs Python 3.12 and 3.14 CI on synthetic negatives, without
  committing real publisher HTML, secret key or Zyte exports.

Then implement **P21B** (fail-closed, publisher-specific, bulk
validation authorization) before ANY next broad source crawl.
P22A private original-page capture and dual blind human review
remain necessary to measure genuine extraction accuracy.
