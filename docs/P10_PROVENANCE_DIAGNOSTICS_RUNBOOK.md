# P10 — Package provenance and independent diagnostic axes

## What this milestone actually changes

This PR is an offline/parser instrumentation upgrade. The three spiders, 460 fixed
source identities, 3 v0 quarantines, robot middleware, strict same-host HTTPS
redirects, and publisher fact approval gates are unchanged.

The November 1 all-source audit found empty deployment revisions on all 460 Items
and quality overlap masked by a single legacy error string (e.g., 33 documentation
source summaries simultaneously had canonical-path and scope issues).

### Runtime fingerprint

The running Python package computes SHA-256 over sorted relative paths, byte
counts, and exact bytes of all installed agentfuse_crawlers .py and .json
files (including data/sources.json and data/source_lifecycle.json).

- deployment_revision: 64-character package digest; this is NOT a Git commit.
- deployment_revision_kind: package_py_json_sha256_v1.
- deployment_source_revision_claim: optional environment-supplied hex string,
  recorded as a claim, never used to override the measured package digest.
- GitHub CI builds the Zyte legacy .egg and compares its embedded code/data
  digest with the source package. Mismatch fails CI.
- The hash is reproducible from an archived egg and can identify exactly which
  installed package revision ran. It is not a digital signature; an attacker
  controlling package bytes can forge both bytes and any accompanying claim.
- A Git checkout/SHA is only independently attributable after comparing the
  archived egg digest to a trusted build artifact/commit and reviewing deployment.
- Do not use deployment_revision as a Git commit SHA in external systems.

### Diagnostic schema 1.0

All emitted source-summary Items include quality_axes containing:

1. fetch_status
2. access_policy_status
3. source_identity_status
4. freshness_status
5. content_capture_status
6. semantic_evidence_status
7. completeness_status
8. alert_eligibility

They also include an ordered diagnostic_reason_codes array, a bounded count,
and diagnostic_review_required=true. These fields are machine-review hints,
not publisher capability, price, or release claims.

The old status and error fields stay untouched. Multiple independent issues
survive primary error precedence: same-host canonical mismatch + documentation
scope uncertainty; price inventory clipping + missing dimensions; release
identity collision + unresolved dates; CDN cache age + semantic extraction.

All alert_eligibility states remain blocked_unverified. The spider never
automatically changes lifecycle states or approves facts.

### Operator audit and compatibility

Use the offline command (no Zyte credential or network request):

    python -m scripts.report_diagnostics \
      --items items_official_documentation_10.json \
              items_official_pricing_8.json \
              items_official_changelogs_11.json \
      --out-dir output/p10-diagnostics

The command writes summary.json and source_diagnostics.csv. Old exports without
P10 fields are labeled recomputed_from_legacy_export; this is not evidence that
their historical jobs actually executed P10. Embedded diagnostics are not
independent human-vetted evidence.

### Validation and rollout

1. Review the diff, CI tests for Python 3.12/3.14, strict 460-source manifest
   verification, the Zyte egg digest verification and no new spiders.
2. Do not merge/deploy on green synthetic tests alone. Inspect existing job
   schedule arguments before changing the deployed revision.
3. Operator verifies publisher policy, then manually runs a small, exact-ID
   validation canary across all categories, preserving lifecycle quarantine.
4. Check exactly one Item per source, 64-character deployment_revision and
   the expected deployment_revision_kind. Recalculate the same digest from the
   archived deployed egg and compare it with each Item. Distinguish a package
   digest from a Git SHA.
5. Check concurrent diagnostic reasons on a genuine review-needed page,
   and verify that an HTTP-200 homepage remains unverified.
6. For a larger rollout, compare new source statuses to the November 1 exports.
   Keep P11/P12/P13 parser fixes independent of P10 diagnostics.

Do not change Zyte schedules, Supabase/AgentFuse data, source manifests,
publisher restrictions, or fact approval states in this PR.
