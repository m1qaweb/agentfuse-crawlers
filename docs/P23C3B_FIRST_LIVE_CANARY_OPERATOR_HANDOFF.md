# P23C3B — First permitted Zyte canary: human review and manual execution handoff

**As of November 7, 2026:** First source-specific pilot still **NO-GO**.
**This is an execution handoff, NOT an automated publisher-access approval.**

**Progress:** P23A → P23B → P23C1 → P23C2 → P23C3A are merged.
P23B already enforces exact-source Git-reviewed publisher access even for
`source_ids=ONE_ID`. P23C1/P23C2/P23C3A can audit **real** finished jobs.
The missing dependency is **genuine human-reviewed publisher access** and
the first genuinely permitted live Zyte jobs, not additional synthetic tests.

### November 8 verified P24A checkpoint

The third November 7 three-spider Zyte run accounted for all 460 configured source IDs,
but recorded **zero publisher GETs**. Its deployed package matched the latest
successful GitHub main CI package. The unreviewed source/plan registries, not
package deployment, remain the blocker.

The November 4 genuine pricing job additionally recorded an **HTTP 301 cross-host**
redirect for the frozen Gemini pricing source to
`https://aistudio.google.com/docs/pricing`. That destination has **not** been
reviewed; do not silently follow it or claim pricing data was captured.
Preserve the frozen source slot and review any canonical source migration.

Read [P24A's nine-file evidence freeze and human-review handoff](P24A_NOV7_ZYTE_EVIDENCE_FREEZE_AND_FIRST_LIVE_REVIEW.md).
No extra crawler code or plan-hash UI arguments are needed for the first
genuinely permitted exact-source canary; a real publisher-access decision is.
## 1. Exact three initial sources — FROZEN preselected Wave 1

| Purpose | Source ID | First-party target URL | Source state |
|---|---|---|---|
| Documentation | `kiro_docs` | https://kiro.dev/docs/ | Human review pending |
| Pricing | `gemini_api_pricing` | https://ai.google.dev/gemini-api/docs/pricing | Human review pending |
| Changelog | `openai_api_changelog` | https://developers.openai.com/api/docs/changelog | Human review pending |

The P20A study has **18 original distinct sources and 36 round slots**.
These three form an *initial execution subset*, not a replacement for the
remaining original 15. If a site is denied or unresolved, **hold** its slots;
do not replace it to artificially improve measured success rates.

### P23C3C source-rights finding (November 7, 2026)

The [first-party policy research memo](P23C3C_PUBLIC_PUBLISHER_POLICY_RESEARCH_2026-11-07.md)
documents a significant additional risk: **Kiro's own documentation
footer links to AWS Site Terms**, and those terms restrict robots/data
mining and commercial use without appropriate permission. Do **not**
choose Kiro as an automatically safe first canary; a reviewer must
establish whether those terms apply and whether the intended work is
separately licensed or expressly authorized.

Google's public ai.google.dev robots file was readable and specifically
disallows authuser-query URLs, but that does not grant automated crawling,
reuse or retention rights. OpenAI's developer-subdomain robots file
remained unverified through the research browser. **All three remain
human-review pending** and the P23B access registry remains the sole
local permission-status input.

The downloadable human review CSV now contains **dated policy research
flags and original evidence URLs**, separate from actual P23B review
decisions. The paper/source findings never authorize Zyte publisher GETs.

## 2. Get a real, source-specific human review

A human reviewer must examine each publisher's **actual**, current first-party:

- Official source ownership and the specific documentation/pricing/release
  product, exact hostname and target path.
- Applicable robots.txt user-agent rules and path restrictions, verifying
  the actual robots file rather than assuming `/robots.txt` is readable.
- Governing website/crawler terms and whether the contemplated automated
  collection is allowed under the applicable agreement or other legal basis.
  The API's use terms are not necessarily the crawler's website terms.
- Limits on reuse, attribution and retention of **original publisher HTML**,
  Requests/Logs and derived model-pricing/release facts.
- Reasonable source-specific call cadence; no bypassing rate limits,
  authentication restrictions, CAPTCHA, robots disallows, changed URLs or 403/429.

Relevant *research starting points*, **not positive authorizations**:
- Kiro: [Kiro documentation](https://kiro.dev/docs/),
  [AWS Service Terms](https://aws.amazon.com/service-terms/);
  the latter does not automatically authorize public-page scraping.
- Gemini: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing),
  [Google AI developer terms](https://ai.google.dev/gemini-api/terms),
  [ai.google.dev/robots.txt](https://ai.google.dev/robots.txt).
  A readable robots file alone is not a positive publisher permission.
- OpenAI: [API changelog](https://developers.openai.com/api/docs/changelog),
  [OpenAI policies](https://openai.com/policies/),
  [developers.openai.com/robots.txt](https://developers.openai.com/robots.txt).
  The different OpenAI consumer/business/developer terms have different
  scopes; the reviewer must identify what actually applies.

If evidence is missing or unfavorable, record **deferred** or **prohibited**
after a genuine review, or leave the source **not_reviewed**. **Never set**
`allowed_reviewed` or positive booleans based on an AI summary or guessed
terms. Written permission or a competent human review may be necessary for
some sources; this document cannot provide it.

### P23D0: Real historical failure evidence (November 4, 2026)

The previously supplied genuine November 4 Zyte export bundle (nine files
matching P21A's pinned SHA-256 hashes) showed three specific **archived,
unverified** weaknesses in these exact first-pilot sources:

- **Kiro docs:** HTTP 200 but likely JavaScript shell with insufficient
  content; separate Kiro/AWS site-term restrictions remain unresolved.
- **Gemini pricing:** HTTP **301 rejected redirect**. Human review must
  separately verify the current exact URL and canonical ownership, not
  assume that non-disallowing robots rules mean a useful source GET.
- **OpenAI API changelog:** HTTP 200 but release-event identity collisions
  and truncated text. A successful fetch is not an accurate release feed.

The full [historical 460-Item / 992-Request triage](P23D0_HISTORICAL_REAL_ZYTE_CANARY_DEFECT_TRIAGE.md)
explains original source attrition and request counts. **These are dated,
pre-P23B observations, not current publisher facts or permissions.**

The GitHub review CSV now adds labeled historical status, HTTP status,
diagnostic reasons and review action **without changing access decisions
or permitting any job**. Do not retry a historic 301 blindly or
auto-fetch alternate URLs.

## 3. Obtain the operator packet from GitHub without a local clone

After this PR merges:

1. Open GitHub → **Actions** → **Prepare Zyte UI preflight (no crawl)**.
2. Select **Run workflow** on **main**. Download the new artifact.
3. Open `p23c3b-first-canary/`:
   - `first_3_source_canary_handoff_NO_GO.json` — exact source/round/
     policy status plus local revision fingerprints;
   - `human_first_source_review_queue_NOT_APPROVED.csv` — three distinct
     publisher review tasks and robots *candidate* URLs;
   - `six_manual_zyte_job_specs_NOT_AUTHORIZED.csv` — two rounds per source,
     one exact source ID per job, exact source/manifest/lifecycle SHA pins;
   - `READ_ME_NO_CRAWL.txt` — explains why no permission is conferred.
4. **Do not** run the jobs just because the CSV contains precise arguments:
   even a positive local P23B record is only an attestation and does not
   independently verify publisher rights, deployed Zyte package or budget.

The packet is generated by:
```bash
python -m scripts.p23c3b_first_canary_operator_handoff \
  --out-dir output/private/first-real-canary-01
```

The command is offline and does **not** schedule Zyte or query publisher
websites. It refuses source substitutions, changed source identities, invalid
P23B registry entries, overwriting earlier reports, and any claim that an
operator or publisher has already approved the run.

## 4. Record actual reviewed decisions — separate Git PR, not this phase

The checked-in source-review registry is:

`agentfuse_crawlers/data/validation_access_reviews.json`

A real human-reviewed `allowed_reviewed` record requires exact source
URL/category, `scopes=["single_validation"]`, a named human reviewer,
timezone-aware timestamps expiring within 30 days, exact first-party
ownership/robots links, applicable policy URL, actual robots/terms/retention
checks, and a substantive publisher-specific evidence note. The existing
`validation_access.validate_access_registry` checks structural integrity
and source scope, **not** legal permission or truthfulness of attestations.

**Never** add positive reviews in a synthetic test fixture to the production
registry. Only genuine findings and independent Git review belong there.
A review may be denied/deferred; that result is valid attrition evidence.

After merging genuine determinations, verify Zyte's **installed** deployed
package fingerprint against the new reviewed main package. Git commit or
local egg equality alone is not remote deployment proof.

## 5. Manual first Zyte job — only after human and operational signoff

For a **single genuinely approved** original source, in Zyte Scrapy Cloud UI:

- Select only that source's matching spider.
- Job Units **1** and Priority **Normal**, under an explicit operator budget.
- Enter each key/value separately (use the exact six job arguments from the
  packet, including the three expected SHA pins). No full-inventory flag.
- Start **one** round. Export Items/Requests/Logs and review anomalies before
  starting another independent round.
- If the source returns 403/429 or a redirect to an unreviewed URL, **hold**
  and do not bypass the restriction.
- Perform the second round only if still permitted and operationally safe.
  Preserve the distinct real Zyte Job IDs and all 36 original study slots.

Existing tooling:
- `scripts.archive_jobs` — immutable metadata/Items from finished jobs.
- `scripts.p23c3a_download_completed_zyte_evidence` — READ-ONLY downloads
  existing completed-job Requests/Logs from Zyte storage.
- `scripts.p23c2_zyte_requests_logs_html_gate` — offline exact source/round
  evidence reconciliation.
- `scripts.accession_cross_category_html` — independently supplied original
  publisher HTML bytes, provided collection and retention are permitted.

These tools do not establish that a separate original-HTML capture was
the identical body returned by the Zyte job. Real human review of the source
facts is still required before claiming accuracy.

## 6. Stop/GO decisions

| Condition | Decision |
|---|---|
| No current genuine publisher review | **No publisher GET** |
| Human review denies/restricts scraping | **Hold source; preserve slot** |
| P23B review present but Zyte deploy/budget not verified | **Do not start job** |
| Human policy/deployment/budget checks pass | **Operator may consider one bounded manual source job** |
| Genuine archived two-round evidence + independent human grading | **Evaluate expanding diagnostic, not automatically GO** |

**Current outcome:** 0 confirmed human source-review records in the repository,
0 source-specific authorized canaries, and **NO_GO** for all 460 original URLs.
The next necessary input is a real human reviewer/operator decision for one
of the three original sites; code alone cannot provide that evidence.
