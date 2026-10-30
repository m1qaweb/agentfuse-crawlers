# AgentFuse Official AI Source Monitors

Read-only Scrapy Cloud project for monitoring **official AI API documentation, pricing, and changelogs**. Scope: 82 manually curated official source URLs across 29 AI platforms (documentation, pricing, and changelogs). The original OpenAI, Anthropic, and Gemini sources have been preserved.

## Goals

- Gather attributable page evidence: original URL, fetch time, title, normalized text, SHA-256 hash, and crawl status.
- Produce JSONL/CSV snapshots and detect textual changes for human review.
- Provide a safe future feed for the AgentFuse AI Provider Intelligence directory and advisor.

## Scope and safeguards

- No X/Twitter, login scraping, CAPTCHAs, bypass tools, anti-blocking add-ons, or paid Zyte API.
- Fixed official-source allowlist only; robots.txt respected and conservative rate limits.
- No secrets, no Supabase credentials, and **no writes to the production AgentFuse database**.
- Source snapshots are unverified material. A changed page is **not proof** of a pricing or model change. Verify facts before publishing or using in recommendations.

## Local setup

```bash
python -m venv .venv
# Activate your venv
pip install -r requirements-dev.txt
scrapy list
pytest -q
mkdir -p output
scrapy crawl official_documentation -O output/documentation.jsonl
scrapy crawl official_pricing -O output/pricing.jsonl
scrapy crawl official_changelogs -O output/changelogs.jsonl
python scripts/compare_exports.py --current output/*.jsonl --out-dir output/review
```

To compare later snapshots, pass `--previous path/to/previous/*.jsonl` as well as `--current`.

## Zyte deployment

1. In Zyte Scrapy Cloud, open project `aidata` > **Code & Deploys**. Ensure the connected repository is `m1qaweb/agentfuse-crawlers` and the selected branch is **main** (not master).
2. Trigger **Deploy Branch** manually. `scrapy.cfg` is in the repository root, as required by Zyte.
3. Check the build log, then verify the three spider names in **Spiders**.
4. Run each spider once. Examine Jobs > Items, export the JSONL items, and confirm source coverage and block statuses before setting a schedule. **Expect some sites to block crawlers, render in JavaScript, redirect, or return incomplete text: treat these as coverage gaps rather than silently calling them verified.**
5. If periodic jobs are available on your plan, run changelogs daily and docs/pricing weekly, without overlapping jobs on a single cloud unit.

Official deployment guide: https://support.zyte.com/support/solutions/articles/22000201935-deploying-a-project-from-a-github-repository

## Scaled coverage (82 sources)

Current source counts: 29 documentation, 27 pricing, 26 changelog pages across 29 platforms. See `agentfuse_crawlers/data/sources.json` for the full list.

Sources were selected from official provider sites, but the new URLs have not all been successfully fetched on Zyte yet. A GitHub passing build is **not** a live crawling guarantee. Keep the original nine validated pages as your baseline. On the single-unit plan, launch one spider job at a time; verify `captured`, `text_truncated`, `blocked`, and missing records in exported items. If a new provider disallows crawling, honor its robots.txt and use its public feed or API instead.

**Crawl cadence (only if your plan supports scheduling):** changelogs once daily, pricing and docs once weekly. Do not treat the page count as a quota guarantee, and watch Zyte RAM/runtime, rate-limits, and retention.

**Pricing safety:** the `text` field is evidence only. It flattens complex tables and sometimes misaligns columns; never publish or compare model prices from this field automatically. Prices require a table-aware, currency/tier/effective-date-aware verifier.

**Changelog safety:** whole-page hashes detect changed HTML text, not distinct releases. Before integrating with the advisor, extract dated release entries and manually approve any proposed recommendation impact.

## Review outputs

`compare_exports.py` creates `status.csv`, `changes.csv`, `snapshots.jsonl`, and `summary.json`. It flags missing/blocked pages, new baselines, and page-level text changes. It does not extract verified structured model prices or semantic announcements yet.

For the future public intelligence hub, publish official links and independently verified summaries rather than verbatim full documentation. The advisor should only consume reviewed, source-linked facts; this repository has no automatic promotion path to recommendations.
