# AgentFuse AI Provider Intelligence — Collection Layer

A conservative, **read-only** Scrapy Cloud project that tracks *official documentation, pricing and changelogs*. It collects evidence for a future AgentFuse Intelligence directory and AI-stack advisor; it **does not publish provider claims, price comparisons or recommendations automatically**.

## What's implemented

- **460 configured official-source URL candidates / 194 provider names** (October 30, 2026): 194 documentation, 177 pricing, 89 changelogs. **82** original entries preserved, **378** appended from the owner's expanded JSON file. Only the original **nine** source URLs have previous observed Zyte crawl success; **451 remain candidates** awaiting source-by-source live validation. The uploaded filename saying "verified" is not live extraction evidence.
- Exactly three Scrapy 2.18 spiders: `official_documentation`, `official_pricing`, `official_changelogs`. Each job requests the current HTML of every selected official URL; the source inventory can be expanded without adding spider types.
- Fixed offline URL manifest; no arbitrary-URL spider arguments. `cohort=proven|candidate|all`, explicit source-ID selection, and bounded `offset` and `limit` make safe rollout easier.
- **PR01 operational guard:** omit `cohort` to crawl only 3 historical smoke-test URLs per spider. Any job with `cohort=all` and no `source_ids` now **requires** `confirm_full_inventory=yes`, even when using `limit`. Existing recurring jobs explicitly set to `cohort=all` must be deliberately updated before deploying this change. This is a scope safety control, not an access-permission check.
- Evidence schema v2: fetch metadata, status, full-text SHA-256, semantic heading sections and dated *candidates*, HTML table cells with row/colspan, canonical link when same-host, length/quality warnings and original source URLs.
- Offline JSON/JSONL import, snapshots, source health report, page diffs, section diffs, and **unverified review queue**. A first crawl is a baseline, not a new announcement.
- Optional manual Zyte job exporter to archive data beyond Zyte's retention window. Uses an environment variable; never commits API keys.
- GitHub Actions validation of packaged egg and Scrapy spider registration, plus unit tests.

## Fresh-fetch and extraction integrity (v2.1)

Each triggered run schedules **new network requests**, with Scrapy's HTTP cache disabled and `Cache-Control: no-cache` / `Pragma: no-cache` revalidation hints. The crawler records the fetch timestamp, server Date, Last-Modified, ETag, Cache-Control and CDN Age when available. These are *response observations*, not proof that the publisher has posted a newer version.

The spider only follows bounded (max 3) **same-source-host HTTPS redirects** and flags moved URLs or unexpected canonical paths for review. Global automatic redirects remain enabled to let Scrapy process **robots.txt redirects**; all *source page requests* explicitly opt out and use the stricter per-source policy. A login page, JavaScript-only shell, missing dated release sections, link-only documentation index, or pricing page with no observable billing evidence is `needs_review`, not `captured`. Truncated text/tables/changelog sections are `partial_capture`. The cross-source coverage extension writes job stats `agentfuse/coverage/*` and closes a run with a descriptive reason when expected item records are missing or nothing usable was collected.

**Important boundary:** these spiders fetch the current version of each **configured page**, not every subpage in a provider's entire documentation tree. A changelog includes historical entries; a daily run should identify *changes relative to prior snapshots*, not pretend those old entries were published today. A CDN may serve cached content even when the crawler asks for revalidation. Thus `latest_publication_verified=false` until independently confirmed. A `captured` status means structurally useful source evidence, **never fact verification**. Do not mistake a `finished` job for successful source coverage—inspect the coverage stats.

### Reproducible PR01 job provenance

Each fetched or errored source Item now carries **both** `source_cohort` (historical source membership) and `requested_cohort` (actual Zyte job argument), plus an ordering-sensitive selection-ID SHA-256 and a manifest SHA-256, job start time, spider ID, and optional Zyte job ID / deployment revision. `SHUB_JOBKEY` may provide a real Zyte job ID; `AGENTFUSE_DEPLOY_REVISION` must be set by the deployment environment or it remains empty. Do not invent a revision when unavailable. The exporter refuses to compare modern Items from incompatible job scopes, manifest revisions or mixed job sessions; old Items remain readable but are explicitly labeled `legacy_unverified`.

The separate `agentfuse/run/quality_outcome` and `agentfuse/coverage/*` job metrics show counted source Items, comparable evidence and clipped excerpts. **`finished` + complete source accounting is not proof that the facts or dates are accurate.**

For stable validation jobs, generate `validation_batches.csv` and use `pinned_cohort=all`, `source_ids=<source_ids_csv>`, `expected_manifest_sha256=<hash>` and `expected_selection_ids_sha256=<hash>` from one CSV row. This pins a fixed ID set even if the candidate/proven registry changes. Explicit source-ID scoped jobs do not require `confirm_full_inventory=yes`; that confirmation is for broad unbounded `cohort=all` jobs only. Compare using the *same* `--cohort all --source-ids ...` arguments.

### Match review exports to periodic-job scope

For your schedules using `cohort=proven`, the post-run comparison automatically detects that cohort from v2.1 Items. For a bounded candidate batch, pass the **exact same** `--cohort candidate --offset 15 --limit 15` or `--source-ids cursor_docs` arguments used in Zyte; otherwise unrequested sources may appear missing. Use `python -m scripts.plan_validation --batch-size 15` to generate batch instructions and static warning flags for all 451 candidates. See [EXPANDED_SOURCES_ROLLOUT.md](docs/EXPANDED_SOURCES_ROLLOUT.md). Example:

```bash
python -m scripts.compare_exports --current output/today-changelogs.json \
    --previous output/yesterday-changelogs.json --cohort proven \
    --out-dir output/changelog-review
```

Only the original **nine** source URLs have prior real Zyte crawl evidence. A URL in `sources.json` is not automatically current, accurate, or reachable.

## Security & accuracy contract

- `ROBOTSTXT_OBEY=True`. No login, CAPTCHA bypass, headless browser add-ons, third-party scraping proxies, or paid Zyte API.
- Sources are manually curated public HTTPS URLs. Spider arguments only **filter existing source IDs**, never add new URLs.
- A `200` response and nonempty text **do not imply the information is correct, current or complete**. Failed, redirected, blocked, short and truncated results are surfaced for review.
- **Pricing tables are evidence, not normalized prices.** Complex headers, billing modes, regions, currencies, effective dates, and token tiers require provider-specific extraction and human validation before comparison.
- Changelog sections, timestamps and importance hints are **candidate metadata**, not verified release notes. HTML section removal can indicate a site restructure, not a product change.
- External page text may contain malicious instructions: treat all collected content as **untrusted data**. It must never be executed or used as a high-priority system prompt.
- No AgentFuse production Supabase/database writes and no automated ingestion to the advisor. All `review_queue.jsonl` entries set `approved_for_advisor=false`.
- For any public provider directory, publish *independently authored brief summaries and attribution*, not a mirror of provider docs.

## Install and smoke test

```bash
python -m venv .venv
# Activate .venv in your environment
pip install -r requirements-dev.txt
pip install -e .
python -m pytest -q
scrapy list
```

Scrapy 2.18 requires `async def start()`; it will NOT call the legacy `start_requests()` hook. The project uses Zyte's `scrapy:2.18-20260824` base image and ships `setuptools` for its egg build.

## Scrapy Cloud rollout (one unit)

The GitHub `main` branch deploys to your existing Zyte project `aidata`. First confirm the **latest commit** shows `SUCCESS` in **Code & Deploys**. Test one spider job at a time; the account has only one concurrent crawl unit. Spiders read the catalog at job start and crawl only their category.

**Existing scheduled-job compatibility warning:** If any live scheduled job currently supplies `cohort=all` without an explicit source ID list, it will fail fast after PR01 is merged. Update its arguments to `cohort=proven` first, or consciously authorize the full job with `confirm_full_inventory=yes`. This protects against the accidental 460-source run observed on October 31.

Recommended validation order:

1. Run `official_changelogs` with spider argument **`cohort=proven`**: expect three requests and three items (plus robots.txt requests).
2. Run `official_changelogs` with **`cohort=candidate`, `offset=0`, `limit=15`**; review all 15 records, and advance by offset 15 after validation. Never test all 451 candidate URLs at once on a single unit. Flag broken URLs, redirects, blocked policy responses, JS shells and irrelevant content without bypassing site restrictions.
3. Repeat for pricing and documentation. Do not switch a periodic job to `cohort=all` until its source inventory is validated and run times are measured.

To test individual sites safely, use `source_ids=cursor_changelog` (ID must be present in `sources.json`) or `cohort=candidate`, `offset=30`, `limit=15`; **none supports arbitrary URLs**. Use `cohort=all` with an explicit source ID that is outside the proven cohort.

Current owner-configured schedule: changelogs **daily**, documentation **daily**, pricing **Mondays**. On one unit, offset their start times; observe runtimes, response quality, and data retention. Do not enable automatic paid features.

## Review local Zyte exports

Download Zyte **Items → JSON or JSON Lines**; both formats are supported. Use separate time-stamped directories so current and previous never overwrite each other.

```bash
python -m scripts.compare_exports \
  --current output/2026-10-30/*.json \
  --previous output/2026-10-29/*.json \
  --out-dir output/review/2026-10-30
```

If you only downloaded changelogs, the tool automatically scopes expected URLs to `changelog`, rather than falsely flagging every pricing and docs URL as missing. To audit every source, pass `--category all`.

Outputs:

| File | Purpose |
|---|---|
| `status.csv` | Successful, partial, missing, blocked or failed sources, with source links |
| `changes.csv` | Page-level baseline/changed/unchanged/failed; no semantic claims |
| `section_changes.csv` | Changed heading sections with human review priority hints |
| `review_queue.jsonl` | Candidate changes, original URL, excerpts, `approved_for_advisor=false` |
| `snapshots.jsonl` | Raw source records for dated archival and future comparisons |
| `summary.json` | Expected/captured/comparable sources, categories, error counts |

**Critical:** The initial run is always a historical baseline, not a list of breaking announcements. Any claim must be checked against its official URL and a publication/effective date before promotion to the advisor.

## Archive an official Zyte job

Set **`ZYTE_SCRAPY_CLOUD_API_KEY`** to your **Scrapy Cloud** API key (different from a paid Zyte API key). Never paste the key into a GitHub issue or commit. For job ID `883514/1/9`:

```bash
python -m scripts.download_zyte --job-id 883514/1/9 --out-dir output/archive
```

This uses Zyte's official Items download endpoint (JSON Lines). It downloads only the specified job, validates records and saves an immutable-style dated archive file locally. Back up `output/archive` outside this repository; `output/` is ignored by Git. The script does not create scheduled jobs, set up storage or change AgentFuse.

Zyte docs: [Scrapy Cloud deployment](https://docs.zyte.com/web-scraping/tutorials/main/cloud.html) · [Downloading Items](https://docs.zyte.com/scrapy-cloud/usage/items/download.html) · [Periodic jobs](https://docs.zyte.com/scrapy-cloud/usage/reference/http/periodicjobs.html).

## Dated changelog evidence (stacked PR 02)

The existing `official_changelogs` spider now emits independent `release_events[]`
with official date candidates, stable event identities, bounded excerpts and
source permalinks. Unlike the old single date-from-heading heuristic, it
refuses to guess a missing publication year or to assert that a changed
template represents a new release. The new event-level review queue is
unverified and baseline-safe. See [RELEASE_EVENTS_V1.md](docs/RELEASE_EVENTS_V1.md)
for limitations and a source-by-source canary checklist.

## Bounded recent changelog capture (stacked PR 03)

The existing changelog spider retains a bounded, explicit recent-event
window instead of exporting large historical text snapshots. Versioned
events are compared only within compatible, healthy windows, and historical
truncation is separately reported. Claude Code has a single vetted same-host
Markdown fallback for version-only release evidence; dates are never guessed.
Source Items are limited to a conservative byte budget for Zyte.
See [RECENT_CHANGELOG_CAPTURE_PR03.md](docs/RECENT_CHANGELOG_CAPTURE_PR03.md).

## Typed pricing evidence (PR 04 — draft)

The existing `official_pricing` spider now scans relevant pricing tables
beyond the old first-40 cutoff and emits explicitly unverified typed rate
observations. Missing currency, model, unit, region, plan, or effective-date
certainty prevents comparable numeric candidates. Large rate cards produce
partial/review statuses rather than plausible but incorrect pricing. The
offline review tool can compare fully specified rates without claiming that
a newly seen amount is effective today. See
[PR04_PRICING_EVIDENCE.md](docs/PR04_PRICING_EVIDENCE.md) for limitations,
output fields, and source-by-source Zyte canary instructions.

## Scoped documentation evidence (PR 05 — draft)

The existing `official_documentation` spider now distinguishes a captured
landing/index page from a substantive, product-scoped technical page. A
companion registry pins 22 priority source IDs to the original official URLs
and records intended product/page scope with **pending live validation**.
Sections about models, authentication, limits, tools or SDKs are **unverified
topic evidence**, not confirmed vendor capabilities. Canonical equivalences
remain same-host/safe-path only; genuine migrations stay review tasks.
`kiro_docs` requires a new Zyte capture to diagnose the previously empty
HTML, and Google Cloud's narrower product scope remains unapproved. See
[PR05_DOCUMENTATION_SCOPE_RUNBOOK.md](docs/PR05_DOCUMENTATION_SCOPE_RUNBOOK.md).

## Next phase (not implemented yet)

1. Validate each candidate URL and publisher access policy. Replace unsupported pages with official feeds/APIs where possible.
2. Validate PR04's structured pricing rate evidence on live source HTML. Add explicit source-verified effective-date intervals and model/region/tier scope mappings before any advisor publication. Do **not** derive prices from flattened `text`.
3. Extend already implemented dated release extraction with verified official GitHub release adapters and additional per-provider canaries; deduplicate repeated announcements.
4. Introduce a reviewed-fact schema and evidence ledger (source, first seen, source published date, effective date, last verified, expiry and reviewer). Only reviewed facts should inform advisor recommendations.
5. Build a separate AgentFuse `/intelligence` interface using attributed summaries, searchable provider pages, and source-health indicators. It should read from a reviewed public dataset, **not raw Zyte output**.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the quality gates and technical tradeoffs.
