# P23A — Unified Full-Crawl Readiness Audit (NO NETWORK)

**Scope:** First phase of the November 6 full Zyte diagnostic readiness plan.  
**Current expected decision:** `NO_GO` for the frozen 460-source inventory.  
**Production package/spiders:** Unchanged. No Zyte jobs, URL fetches, permission changes, schedules, data writes, alerts, or advisor approvals.

## Why this phase exists

The Zyte code deployment succeeding does not mean a 460-ID full diagnostic can
fetch publisher pages. After P21B, the deployed
`validation_access_reviews.json` and `bulk_run_authorizations.json` both
start EMPTY. A full-category spider with missing run-plan authorization emits
held source Items without requesting publisher pages. The P14B planning tool's
legacy `expected_primary_source_fetches=457` is the **lifecycle-only
technical possibility**, not the number of legally/operationally authorized
primary requests. Never reuse that figure as an approved fetch budget.

P23A gives one **fail-closed**, source-complete, operator-readable offline
snapshot. It reuses P21B's actual source access-decision and run-authorization
functions; it does not invent a second permit mechanism.

## Contract

- Frozen manifest: 460 exact IDs and URLs, SHA-256
  `231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933`.
  Required mix: 194 documentation, 177 pricing, 89 changelogs.
  Manifest changes (even one URL with the same source count) **fail** and need
  a new reviewed baseline.
- Frozen scientific canary selection: 18 original P20A sources (36 two-round
  source slots), never quietly replace an inaccessible source.
- Show **technical validation**, current source review attestations, and
  locally P21B-authorized plan coverage as *three separate quantities*.
  None is a legal permit, verified publisher origin, remote Zyte confirmation,
  genuine independent canary or human crawl sign-off.
- For each locally packaged run plan, rerun
  `agentfuse_crawlers.validation_access.authorize_bulk_run` against the exact
  selected sources, URL/policy/manifest fingerprints, current installed
  package and supplied plan digest. An expired, stale, re-ordered or mismatched
  plan contributes **zero eligible primary GETs**, with a reported hold.
  Overlapping authorized source IDs across plans are also held.
- A current valid source-review attestation WITHOUT a valid plan does **not**
  produce an executable Zyte argument packet.
- `status=NO_GO` is intentional until later phases can independently verify
  real canary archives, remote deployment, operator budget/sign-off and
  P23B single-source access enforcement. No CLI flag can manufacture any of
  those facts or transition to `CANARY_READY`/`SUPERVISED_DIAGNOSTIC_GO`.
- All source rows are accounted once, including denied, deferred, expired,
  not-reviewed and quarantined. No HTTP 200 or synthetic test can promote a
  source to trusted product facts.

## Run from a reviewed checkout (zero external requests)

```bash
python -m scripts.full_crawl_readiness \
  --out-dir output/private/p23a-first-readiness
```

Two **new-only** output files:

- `full_crawl_readiness_NO_GO.json`: status, blocker codes, exact manifest and
  installed-package fingerprints, run-plan holds, review/plan counts, frozen
  source inventory, local unverified plan eligibility, and *zero* approved
  publisher requests from this report.
- `source_dispositions_460.csv`: one row for every original configured ID,
  with lifecycle, review/expiry, reviewed scopes, locally matching plan and
  explicit held/eligible classification. This CSV contains only configured
  publisher metadata and policy decisions, never raw HTML, human reviewer
  identity/notes or publisher correspondence.

Reusing an existing output path fails; no previous report is overwritten.

## GitHub-only no-local workflow

After code review, in **Actions → Prepare Zyte UI preflight (no crawl) →
Run workflow**, select the reviewed branch or `main` after merge.

The workflow creates an additional `p23a-readiness/` directory in the existing
preflight artifact. CI asserts `status=NO_GO`, 460 exact sources, zero
network requests and zero actual crawl approval. It cannot contact publishers,
schedule Scrapy Cloud jobs, grant permissions or produce an executable job plan.
The other historical P20A/P21B/P22A1/C2A blank artifacts are unchanged.

**Do not upload publisher HTML, real reviewer identities/correspondence,
filled private ledgers, account credentials or actual retention receipts into
GitHub Actions or into this repository.**

## Expected current readout

| Value | Expected current result | Interpretation |
|---|---:|---|
| Configured source IDs | 460 | Original inventory only |
| Technically validation-selectable | 457 | **Not** granted publisher access |
| Lifecycle-held/quarantined | 3 | No source fetch |
| Packaged current per-source bulk reviews | 0 | No affirmative bulk access attestations |
| Packaged bulk run plans | 0 | No authorized source GETs |
| Locally plan-eligible requests | 0 | **Not** remote deployment or run authorization |
| Real canary archives verified by this command | 0 | Later private operator input |
| Approved for Zyte full run | **NO** | Fail closed |

## Next phases and exit criteria

**P23B:** Require current exact-source publisher access review in
`OfficialBaseSpider.start()` **even for one-source validation**. Add only real,
human-reviewed source policies. Keep denied/expired/quarantined URL attempts at
zero requests.

**P23C:** Complete genuine, individually permitted, two-round, immutable
Zyte canaries. Keep raw HTML and reviewer notes in private operator storage;
preserve the complete 18/36 frozen denominator with explicit holds.

**P23E:** After real evidence, generate reviewed, package-pinned, finite
10–25-source diagnostic run plans and executable Zyte UI packets. A new
separate gate must independently verify the actual Zyte deploy, plan expiry,
job budget, source-specific publisher access, actual canary archives and
operator approval before reporting `SUPERVISED_DIAGNOSTIC_GO`.

Never run a 460-URL network fetch merely to make the source accounting 460:
a denied or deferred URL must remain explicitly **held**. Full inventory
accounting and full network fetch are different milestones.

## Verification

```bash
python -m pytest -q tests/test_p23a_full_crawl_readiness.py
python -m pytest -q
```

GitHub Actions must pass Python 3.12/3.14, existing package-identity checks
and exactly three spiders. P23A changes only scripts, tests, docs and a
read-only workflow: **no change to deployed `agentfuse_crawlers` bytes**.
