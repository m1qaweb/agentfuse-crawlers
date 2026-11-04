# P19A4 — Operational Changelog Pilot Workbench (Offline-First)

**Purpose:** move from synthetic infrastructure to actual evidence generation
without accidentally launching the 460-source crawl or contaminating
independent review.

P19A1 captures one to five **exact configured** official changelog HTML
pages after explicit operator review of publisher rules. P19A2 generates
**two blank, blind, whole-page human census templates** and scores them
against the exact original HTML. P19A3 aggregates verified local
replays across at least three small source batches.

Previously the operator had to build the 15–25-source sample, manually
copy original HTML and P19A1 metadata, create P19A2 packets, keep a
private holdout split consistent and construct P19A3's cohort JSON.
P19A4 performs the selection and **OFFLINE** staging, but never
starts requests, claims legal access, supplies gold labels or approves
new releases.

## 1. Preregister a diverse sample (offline; no network)

Choose TWO independent private secrets of at least 32 printable ASCII
characters. Store them securely and outside git or shell history.
One freezes source selection; the other freezes the provider-level
development/holdout split. These must not change during the study.
Use real random values; the example below is a placeholder, NOT a
secret to reuse.

    export AGENTFUSE_RELEASE_PILOT_SELECTION_KEY='replace-with-your-own-private-random-selection-secret'
    export AGENTFUSE_RELEASE_GOLD_SPLIT_KEY='replace-with-a-different-private-random-gold-split-secret'

Create a 20-source pilot, 5 per wave:

    python -m scripts.prepare_release_pilot \
      --plan --size 20 --batch-size 5 --holdout-percent 25 \
      --out-dir output/private/changelog-pilot-plan-1

The new private directory contains:

    pilot_selection_plan.json

The selector validates the unchanged 460-source/89-changelog manifest
and its lifecycle policy registry. It excludes validation-blocked
sources, chooses **one source per provisional provider group** using a
fixed private HMAC seed, and produces four ordered 5-source waves.
Every planned source has its exact configured URL and publisher
robots.txt location. A readable, **zero-network** command is included
for P19A1 source inspection, not for direct live capture.

The selection is reproducible with the same key and pinned repo version,
and **must be frozen before collecting publisher evidence**.
It is an exploratory sample of manifest entries, not proof of
representativeness across all AI publishers. Failed or access-denied
sources stay documented as holds; never rotate the secret to quietly
substitute easy sites. Provider grouping is based on unverified
static profiles/manifest labels, not authenticated publisher ownership.

## 2. Review every chosen publisher's access/retention policy

**P19A5 requirement:** Fill and validate a private source-specific policy
ledger before any live original publisher HTML capture. One generic
batch note is NOT sufficient for capture or staged review. See
P19A5_PUBLISHER_POLICY_PREFLIGHT.md for the full workflow.

Read the plan and visit the official publisher site directly. The
operator must decide whether the specific page can lawfully and
technically be fetched and privately retained. Check terms, robots,
ownership, product scope and required delays separately for every
source. A manifest entry, successful historic Zyte job or read-only
plan is **not** permission.

The existing P19A1 manual capture tool is explicitly opt-in. For each
wave, run its read-only command first, then **only when every source
in that wave has been separately reviewed and allowed**, use:

    python -m scripts.capture_release_html \
      --source-ids EXACT_COMMA_SEPARATED_IDS_FROM_WAVE_01 \
      --capture --policy-reviewed \
      --policy-review-note "Each publisher was separately researched for ownership, terms, robots access, product scope and lawful private retention." \
      --pilot-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --out-dir output/private/changelog-pilot-captures-1/wave_01

Repeat for wave_02, wave_03 and wave_04, using that exact wave's
source IDs and output directory. P19A1 checks robots.txt, refuses
redirects/403/429/login/captcha/bypass, obeys bounded requests and
writes an audit plus hash-pinned UTF-8 original HTML. Keep per-source
publisher-policy research privately; the P19A1 note is only an
operator attestation. This command is an EXAMPLE; the workbench
never builds or executes live --capture commands.

**P19A6 update:** If a source is blocked, do not capture or replace it.
Other individually permitted sources in that original wave may be
captured under wave_ID/SOURCE_ID using P19A5 source-specific policy
review. P19A6 offline partial staging and scoring preserve every
original selected source in the denominator, even when access fails.
The older P19A4 full-wave staging command remains all-or-none.
See P19A6_ATTRITION_AWARE_CHANGELOG_PILOT.md.

## 3. Stage existing captures into review-ready files — OFFLINE

After all four P19A1 waves were captured lawfully and completely,
run the workbench's offline staging mode:

    python -m scripts.prepare_release_pilot \
      --stage \
      --input-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --capture-root output/private/changelog-pilot-captures-1 \
      --out-dir output/private/changelog-pilot-staged-1

This command **never contacts websites**, creates Zyte jobs or
re-fetches a source. It refuses any partial or altered sample before
creating a new output folder.

It validates, for every wave:

- Matching P19A5 source-specific operator-policy ledger digest in the
  original P19A1 capture audit, with no missing/blocked wave sources

- Exact frozen source IDs/order and current source/lifecycle pins
- Genuine P19A1-shaped audit (operator-attested, not externally verified)
- Actual original HTML bytes, SHA-256, configured source URLs, valid
  bounded filenames, original UTC capture timestamp
- Source-specific receipt size/checksum and allowed-robots attestation
- Receipt URL, robots.txt URL and robots hash, zero fact approval
- No symlink/path traversal, missing source or changed original HTML

The all-or-none staged folder contains:

    changelog-pilot-staged-1/
      cohort.json
      pilot_staging_audit.json
      wave_01/
        capture/
          frozen_release_snapshots.json
          capture_audit.json
          original-source-fingerprint.html
        replay/
          changelog_html_replay.json
        census/
          blind_source_census_packet.json
          reviewer_a_template.json
          reviewer_b_template.json
      wave_02/
      wave_03/
      wave_04/

**Human review files are deliberately NOT generated as completed.**
The staged cohort points to reviewer_a_filled.json and
reviewer_b_filled.json, which do not exist until two people
independently complete the source-wide census. Do not rename an empty
template to "filled" or invent an evidence quote to pass validation.
Do not share the replay's predicted release list with blind reviewers.
Original HTML is retained privately at its exact hash-pinned path.

## 4. Independently fill owner/date census for each wave

Give Reviewer A and Reviewer B their own blank template and the
correct original publisher HTML. Neither reviewer should see the
parser predictions or the other's results. Follow:

    docs/P19A2_BLIND_RELEASE_CENSUS_GOLD.md

Reviewers must inventory **all** release cards visible in the original
HTML, even ones the parser missed, with source-specific unique owner
URLs, human titles, dates or explicitly unknown dates, unique original
quotes, counts of unowned cards and substantive review notes. Human
records must remain in private, noncommitted files:

    wave_01/census/reviewer_a_filled.json
    wave_01/census/reviewer_b_filled.json

Repeat separately for each wave. A matching hash does not prove the
publisher's identity or human independence. Disagreements, incomplete
inventories, and ambiguous owners block scores.

## 5. Run P19A3 cross-batch evaluation (OFFLINE)

Only after both reviewer files are complete for every wave:

    python -m scripts.aggregate_release_pilot \
      --input-root output/private/changelog-pilot-staged-1 \
      --cohort-manifest cohort.json \
      --out-dir output/private/changelog-pilot-scored-1

P19A3 RECOMPUTES the P19A1 replay and P19A2 independent review for
every source from its unchanged original HTML. It measures source and
provider-stratified owner TP/FP/FN, date correctness, held sources,
unattributed releases, and development vs held-out groups.

A source census can truthfully be held as incomplete. A high score
from a small, easiest-case subset cannot justify adapters, publisher
claims, AgentFuse recommendations or a full 460-source crawl.

## Non-goals and mandatory safeguards

- This PR does not perform any live publisher captures. No real
  provider gold corpus is claimed.
- Both HMAC secrets remain operator controlled. Frozen selection
  and split commitments do not reveal those secrets.
- Staging duplicates only privately retained exact P19A1 HTML
  snapshots; it never silently treats old Zyte Items as original HTML.
- Every score is diagnostic, never an automatic new-release alert,
  publisher truth verification or factual approval.
- The three spiders, original 460 source IDs, policy registry,
  Zyte jobs/schedules, packaged extractor and Supabase data
  are unchanged.
- Do not start the 460-source crawl based on green CI; first obtain
  permitted real captures and honest independent human owner/date gold.
