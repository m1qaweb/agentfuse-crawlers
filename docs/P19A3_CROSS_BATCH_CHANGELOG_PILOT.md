# P19A3 — Multi-Batch, Provider-Stratified Release Accuracy Pilot

## Problem this closes

P19A1 captures exact original publisher HTML and creates an offline,
source-pinned release replay. P19A2 scores a blind, two-reviewer *full-page*
changelog census against that identical HTML, including release events
completely missed by the parser. But a P19A2 batch is restricted to a
maximum of **five sources**, so an isolated batch cannot demonstrate
multi-provider reliability.

P19A3 adds a **read-only, cross-batch pilot aggregator** without weakening
any P19A2 review constraints. The intended initial study is 15–25
independently chosen, publisher-policy-permitted first-party changelog
sources. Every selected source must retain its own original HTML and
P19A2 human-review materials.

**As of this PR, no real publisher HTML snapshots or independently
completed human review labels have been supplied or scored by P19A3.**
Synthetic CI passing will not change that.

## Strict safety boundary

- No external requests and no modification to any existing crawler.
- No new source IDs, source URL rewrites, publisher permissions, spiders,
  Zyte jobs/schedules, Supabase writes or AgentFuse production facts.
- No new-release alerts or claims that the latest publisher update
  is verified.
- No input score reports accepted. P19A3 calls P19A2's scoring function
  again with each original HTML capture, exact P19A1 replay, publisher
  source manifest, blind packet and both completed reviewer files.
- SHA-256 verifies **byte integrity**, not publisher origin or humans.
  Reviewer identity/independence remain operator-attested, not proven.
- A recognized event window can still omit undetected publisher cards.
  This is why the complete human page census remains mandatory.

## 1. Freeze cohort selection before collecting or scoring

Choose 15–25 distinct changelog source IDs across as many independent
provider groups as possible, using the existing 89 changelog IDs only.
Include difficult/previously failing layouts, not merely the easiest
test fixtures. Avoid using holdout results to pick sources or tune
provider adapters. Never treat a configured URL as permission to fetch:
review individual publisher access/retention policy and robots rules
before using P19A1's optional manual HTML capture.

Use P19A1 to create an original HTML capture for each 1–5-source
batch. Use P19A1 offline replay and P19A2 prepare + independent
full-page reviewer A/B workflow for those exact bytes.
Keep all original HTML and reviewer labels privately under one
operator-controlled input root, such as:

    output/private/release-pilot/
        cohort.json
        wave_a/
            capture/
                original_source_id-abcdef.html
                frozen_release_snapshots.json
            replay/
                changelog_html_replay.json
            census/
                blind_source_census_packet.json
                reviewer_a_filled.json
                reviewer_b_filled.json
        wave_b/
            ... (further independent sources)

No P19A3 action fetches a website or approves a source.

## 2. Create a cohort manifest under that private root

Example for one batch (add at least two additional batches and
15 distinct sources for the engineering sample coverage threshold):

    {
      "schema_version": "1.0",
      "kind": "p19a3_reviewed_release_source_batch_cohort",
      "approved_for_advisor": false,
      "holdout_percent": 25,
      "batches": [
        {
          "batch_id": "wave_a",
          "replay": "wave_a/replay/changelog_html_replay.json",
          "capture_manifest": "wave_a/capture/frozen_release_snapshots.json",
          "snapshot_root": "wave_a/capture",
          "blind_packet": "wave_a/census/blind_source_census_packet.json",
          "reviewer_a": "wave_a/census/reviewer_a_filled.json",
          "reviewer_b": "wave_a/census/reviewer_b_filled.json"
        }
      ]
    }

All paths are RELATIVE to the chosen private input root. Absolute paths,
parent traversal, repeated path separators, symlink hops, oversized
JSON and missing files are refused. Batch IDs must be unique; a source
may not occur twice across different batches. The pipeline accepts
1–12 batches of 1–5 sources each, up to 60 sources. The intended
initial pilot needs only 15–25, not a full 460-source crawl.

Use the SAME private 32+ character split key and the SAME
holdout_percent for every P19A2 batch. Never change the secret or
the partition to optimize results. Source groups use the provisional
provider ID from the current profile registry when present, otherwise
the manifest provider label; this grouping is NOT publisher ownership
verification. A provider's split must stay the same across batches.

## 3. Run the offline pilot

    export AGENTFUSE_RELEASE_GOLD_SPLIT_KEY='use-your-own-long-random-operator-secret'
    python -m scripts.aggregate_release_pilot \
      --input-root output/private/release-pilot \
      --cohort-manifest cohort.json \
      --out-dir output/private/release-pilot-analysis-1

This creates a NEW private 0700 directory with a
release_pilot_diagnostics.json file (0600 on POSIX). The script never
overwrites a previous report. It also never prints the secret or raw
publisher HTML.

It rejects:
- Wrong replay package or source-registry fingerprint; mixed parser builds
- Forged replay or cached scorecards inconsistent with original raw bytes
- Original HTML SHA mismatch, path traversal, symlinked metadata
- Missing/forged dual-review evidence, invented DOM anchors or dates
- Duplicate selected source IDs or repeated identical original HTML
  across supposedly different sources
- Provider-group holdout changes, tampered packet or wrong HMAC split
- A human label declaring a release published more than one calendar day
  after its original HTML capture; +1 day tolerance accommodates UTC+14
  publishers and still requires human scrutiny

## 4. Read both denominators and the hold reasons

Per source: parser owner TP/FP/FN, exact date matches, disputed
or unattributed owner IDs, clipped windows and direct hold reasons.
**A held source remains in the selected-source denominator but cannot
supply a numerical accuracy score.**

For development and holdout independently, the report includes:

- Micro owner precision and recall over **only scored sources**
- Provisional provider-weighted macro precision/recall, with each
  entirely scored provider group weighted once rather than letting a
  large changelog dominate
- Publication date exact-match rate and its denominator
- Distinct provider groups, selected/held/scored source counts,
  independent full-page release cases, coverage blockers
- Null for unmeasurable ratios, never artificial zero or 100%

Any provider group with even one held source is excluded from
**macro diagnostics**, explicitly listed as partially unreviewable.
Micro diagnostics are labeled scored-only and can suffer selection
bias. No partial metric is usable to assert broad release accuracy.

Engineering pilot sample coverage is marked reviewable only if:

1. At least 3 genuine batches, 15 unique source IDs and
   15 provisional provider groups.
2. No held source, 60 dual-agreed human release owner records,
   and 30 comparable publication/explicitly-undated decisions.
3. At least 3 completely reviewed holdout provider groups and
   15 held-out human owner records.
4. Nonempty scored development/holdout, and at least one
   attributable parsed release identity.

Those thresholds identify a *potentially useful engineering sample*,
not statistically proven global accuracy, publisher-fact approval or
permission to expand crawling. Even with all thresholds satisfied,
all of the following remain false: publisher truth verification,
cryptographic source authentication, representative sampling proof,
permission to deploy a provider-specific adapter, advisor-fact
approval and automatic new-release alerts.

## 5. Next evidence-dependent decision

Compare consistent development vs untouched provider-group holdout
performance, error rates and the actual *missed* release cards.
Do not build a provider-specific source adapter merely because it
increases the number of extracted headings.

P19B should only change an extractor or add a publisher-owned feed
adapter when authentic publisher HTML/feeds, explicit human evidence,
a stable release owner and an honest same-snapshot before/after test
justify it. Merge into main only after synthetic tests, actual
policy-reviewed canaries, and relevant human evidence pass their
separate gates. The full 460-source Zyte crawl remains on hold.
