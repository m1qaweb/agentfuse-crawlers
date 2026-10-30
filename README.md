# AgentFuse AI Provider Intelligence — Collection Layer

A conservative, **read-only** Scrapy Cloud project that tracks *official documentation, pricing and changelogs*. It collects evidence for a future AgentFuse Intelligence directory and AI-stack advisor; it **does not publish provider claims, price comparisons or recommendations automatically**.

## What's implemented

- **82 configured source URLs / 29 providers** (as of 2026-10-30). The **original nine URLs** for OpenAI, Anthropic and Google Gemini completed real Zyte crawls; the remaining 73 are **candidates** requiring live source-by-source checks. A URL in the manifest does not mean it works.
- Three Scrapy 2.18 spiders: `official_documentation`, `official_pricing`, `official_changelogs`.
- Fixed offline URL manifest; no arbitrary-URL spider arguments. `cohort=proven|candidate|all`, explicit source-ID selection, and bounded `limit` make safe rollout easier.
- Evidence schema v2: fetch metadata, status, full-text SHA-256, semantic heading sections and dated *candidates*, HTML table cells with row/colspan, canonical link when same-host, length/quality warnings and original source URLs.
- Offline JSON/JSONL import, snapshots, source health report, page diffs, section diffs, and **unverified review queue**. A first crawl is a baseline, not a new announcement.
- Optional manual Zyte job exporter to archive data beyond Zyte's retention window. Uses an environment variable; never commits API keys.
- GitHub Actions validation of packaged egg and Scrapy spider registration, plus unit tests.

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

Recommended validation order:

1. Run `official_changelogs` with spider argument **`cohort=proven`**: expect three requests and three items (plus robots.txt requests).
2. Run `official_changelogs` with **`cohort=candidate`**: review each item. Flag broken URLs, redirects, blocked policy responses, JS shells and irrelevant content. Preserve these errors; do not bypass site restrictions.
3. Repeat for pricing and documentation. Run `cohort=all` only when coverage is satisfactory.

To test individual sites safely, use `source_ids=cursor_changelog` (ID must be present in `sources.json`) or `limit=5`; **neither supports arbitrary URLs**. Use `cohort=all` with an explicit source ID that is outside the proven cohort.

Proposed schedule *after validating access and plan scheduling*: changelogs daily, pricing and docs weekly. On one unit, offset their start times; observe runtimes, response quality, and data retention. Do not enable automatic paid features.

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

## Next phase (not implemented yet)

1. Validate each candidate URL and publisher access policy. Replace unsupported pages with official feeds/APIs where possible.
2. Add provider-specific structured pricing extractors with row/header alignment, effective date, currency, units, tier and region validation. Do **not** derive prices from the flattened `text` field.
3. Add dated release entry extraction and cross-source corroboration; deduplicate repeated announcements.
4. Introduce a reviewed-fact schema and evidence ledger (source, first seen, source published date, effective date, last verified, expiry and reviewer). Only reviewed facts should inform advisor recommendations.
5. Build a separate AgentFuse `/intelligence` interface using attributed summaries, searchable provider pages, and source-health indicators. It should read from a reviewed public dataset, **not raw Zyte output**.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the quality gates and technical tradeoffs.
