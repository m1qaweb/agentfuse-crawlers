# PR08 — Offline replay, independent quality gates and manual Zyte canaries

**Status:** Draft. This is an engineering verification framework, **not**
authorization to deploy, crawl unreviewed URLs, treat synthetic test scores as
real-world accuracy, or publish facts to the AgentFuse advisor.

**Branch order:** PR16 fixes P07 onto actual mainline; PR08 follows PR16.
Never merge a stacked PR into a completed or obsolete integration branch.

## 1. What the implementation verifies

CI runs a fixed, copyright-respectful synthetic regression suite covering:

- Nine representative product changelog layouts: Cursor, Render, xAI,
  OpenAI API, Kiro, Supabase, Claude Code, Codex and Antigravity.
- **15 distinct synthetic GitHub Releases layouts**, tied to manifest IDs.
- 24 release/date expectation cases, including unknown-year and version-only
  cases; date precision is day or explicitly unknown. Additional date tests
  exercise invalid days, mixed date formats and edit vs publication timestamps.
- **240 synthetic numerical price examples** with exact Decimal preservation,
  explicit currency, model/service, region, plan, unit and rate dimension.
- Negative prices: ambiguous dollars, absent units/tiers/regions, promotional
  pricing, footnotes, free and contact-sales states must not normalize as a
  comparable numeric rate.
- Historical first baselines, reordered cards, archived backfills, edited
  entries, stale CDN/HTTP failures, source/product/schema migrations, missing
  sections and incomplete releases via existing P02-P07 regression suites.
- Access safety, quarantined v0 URLs, same-host redirect constraints,
  no arbitrary source IDs, no prompt-driven fact approval, immutable Item
  checksums, full source count and package entry-point checks.

These short examples are deliberately invented, not copied from proprietary
source pages. The synthetic suite can detect *regressions*. Its **240 rows are
NOT the roadmap's >=200 independently reviewed real vendor pricing cases.**

## 2. Repeatable offline CI

The GitHub Actions workflow validates both Python **3.12 and 3.14**, Scrapy
2.18's original three spiders, legacy Zyte egg packaging, 460 source
IDs (194 documentation / 177 pricing / 89 changelogs), publisher-safety
settings, synthetic golden results and unit tests. It freezes TZ=UTC and
PYTHONHASHSEED=0.

Reproduce locally, without any Zyte credential:

    python -m pip install -r requirements-dev.txt
    python -m pip install .
    python -m scripts.replay_gold --out output/ci-synthetic/synthetic_report.json
    python -m scripts.quality_gates --synthetic-report output/ci-synthetic/synthetic_report.json --out-dir output/ci-synthetic/gates
    python -m pytest -q
    scrapy list
    python setup.py bdist_egg

Expected synthetic replay: 24/24 release cases, 240/240 pricing examples,
zero false latest date, zero negative price normalized as comparable.

**Crucial:** quality_gates deliberately reports
"blocked_pending_evidence_or_quality" when fed *only* synthetic data. CI checks
that blocking logic. A green CI badge is **not a release approval**.

## 3. Prepare manual, pinned two-round canaries

Select only exact, first-party manifest source IDs. Avoid the v0 app
quarantine. Example only, requiring an operator's publisher-policy review:

    python -m scripts.canary_rollout --source-ids openai_api_changelog,anthropic_api_changelog,gemini_api_changelog --out-dir output/canary-plan

This produces *manual_job_args.csv* and *canary_plan.json*, with exactly two
iterations for each selected ID and pinned:
- cohort=all (with ONE explicit source ID, not the complete inventory)
- collection_mode=validation (never a monitoring approval)
- expected_manifest_sha256
- expected_selection_ids_sha256
- expected_source_registry_sha256

**No Zyte job is scheduled or executed by this command.** Publisher robots
and access policy must be independently verified before an operator
authorizes each job. A source's historical "proven" cohort does not supply
that permission. First-party source identity, product scope and change
evidence still require separate review. Do not crawl a quarantined URL.

Run the exact one-source jobs manually only after permission checks, twice
on distinct completed Zyte job IDs, preferably separated enough to compare
repeatability. Do not edit existing production schedules or use extra paid
rendering/proxy services.

## 4. Archive and score real canaries

Use P07's read-only, paginated, checksum-verified Zyte job archiver to
capture each manually completed job (not a screenshot or a partial export):

    python -m scripts.archive_jobs --job-id 883514/1/9 --out-dir output/archive

To score, create a **private local** CSV mapping with columns
source_id,round,archive_path, for example:

    source_id,round,archive_path
    openai_api_changelog,1,output/archive/jobs/883514_1_9
    openai_api_changelog,2,output/archive/jobs/883514_1_11

Then:

    python -m scripts.score_canaries --plan output/canary-plan/canary_plan.json --archives output/private_canary_archives.csv --out-dir output/canary-review

Scoring replays verified P07 archive hashes, official metadata, one
source Item per selected job, full selection/job/registry fingerprints,
source identity, HTTPS same-host final URLs, exact args, finished state,
chronologically ordered two distinct jobs, advisory approval anomalies
and usable typed evidence. It reports missing, mis-scoped or unavailable
source rounds explicitly. No source is promoted by a green result.

The critical denominator is **reviewed collection-eligible sources**.
At present the source lifecycle registry contains **zero** reviewed
collection approvals. Therefore the release target of >=95% usable
capture across two rounds is **NOT EVALUATED and cannot pass**, even if
manual diagnostic test jobs fetch every page successfully.

Do not relax this gate by counting unreviewed 460 URLs as approved.

## 5. Separately reviewed real-world gold (still required)

To evaluate production-grade precision, a human must prepare a **private**
\`--reviewed-gold\` JSON using at least 200 distinct, independently
annotated actual vendor price observations, at least 100 independently
annotated release-date cases (an additional conservative minimum chosen
for Step 8), negative rate cases, and baseline/reordering no-false-new
release examples.

Each record must identify its real source_id and **exact official URL**,
first-party evidence URL, distinct job ID, a unique typed observation/event
ID, expected and actual normalized fields, and manual reviewer provenance.
Real pricing comparisons require exact Decimal amount **plus** currency,
billing unit, model/service, region, plan, rate dimension and any known
service mode/effective-date eligibility. Unknown units, tiers, regions,
promotions or footnotes must not normalize as fully comparable.

Required human score:
- >=200 *distinct* real reviewed price records, >=99% exact amount+scope
  accuracy; no fake 200-row inflation by reusing the same observation ID.
- >=100 independent dated examples, >=99% day accuracy, **zero invented
  "latest" dates** for unknown-year records.
- Zero normalized comparable prices from negative missing-scope cases.
- Zero false newly-published release from a first baseline or reordered
  cards.
- Zero unapproved advisor facts or claim promotions.

These metrics cannot be inferred from the synthetic regression corpus,
and self-attested reviewer metadata is not cryptographically verified.
A human operator must inspect real evidence against archived Zyte Items.

Once BOTH actual two-round canary archives and reviewed gold are available:

    python -m scripts.quality_gates --synthetic-report output/ci-synthetic/synthetic_report.json --canary-score output/canary-review/canary_score.json --reviewed-gold output/private_human_gold.json --out-dir output/release-review --strict

The script exits nonzero on unmet safety or accuracy criteria. Even when
all checks pass, it only says "eligible_for_human_release_review", **never**
"deployed" or "approved_for_advisor".

## 6. Release and rollback checklist

Before merge: review the exact PR diff and CI across both Python versions,
validate original 460 manifest and three spiders, check Scrapy Cloud egg
build, and confirm the scheduled-job settings still use pinned cohort
semantics. No full-inventory unattended sweeps.

For an authorized canary, inspect real Zyte Items, Requests and Logs for
robots 429/403, HTTP 403/404, unexpected cross-host redirects, scraped
content size, duplicate/missing source summaries, malformed candidate
dates, stale CDN responses, and source attribution. Zero unresolved
robots 429 in reviewed unattended scope; never bypass terms.

Engineering targets (not already achieved):
- 100% expected source-summary IDs, zero duplicates, zero unreviewed
  advisor facts.
- >=99% human-reviewed real price accuracy (>=200 cases) and >=99% full
  publication dates (>=100 cases).
- >=95% usable high-priority capture in **two repeat** live canaries of
  only permitted, collection-eligible sources.
- Prefer Scrapy Cloud peak memory below 400 MiB; higher is a warning for
  investigation, not proof of bad data.
- Distinguish observed fetch age from official publication date.

A mainline merge may deploy to Zyte. Coordinate with the operator;
validate the deployed revision and existing schedules, then perform small
source-ID canaries before widening. Roll back if item accounting, publisher
policy protection, evidence precision or package compatibility regresses.

## 7. Strict non-goals

No autonomous Zyte schedules or live crawling; no DB/Supabase writes;
no automatic source lifecycle promotion; no automated vendor fact
verification or advice publication; no use of large private crawls as
public repo fixtures; no new spiders; no CAPTCHA/robots bypass.
