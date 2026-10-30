# AgentFuse Official AI Source Monitors

Read-only Scrapy Cloud project for monitoring **official AI API documentation, pricing, and changelogs**. Initial scope: OpenAI, Anthropic, and Google Gemini (9 manually approved URLs).

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
4. Run each spider once. Examine Jobs > Items, export the JSONL items, and confirm source coverage and block statuses before setting a schedule.
5. If periodic jobs are available on your plan, run changelogs daily and docs/pricing weekly, without overlapping jobs on a single cloud unit.

Official deployment guide: https://support.zyte.com/support/solutions/articles/22000201935-deploying-a-project-from-a-github-repository

## Review outputs

`compare_exports.py` creates `status.csv`, `changes.csv`, `snapshots.jsonl`, and `summary.json`. It flags missing/blocked pages, new baselines, and page-level text changes. It does not extract verified structured model prices or semantic announcements yet.

For the future public intelligence hub, publish official links and independently verified summaries rather than verbatim full documentation. The advisor should only consume reviewed, source-linked facts; this repository has no automatic promotion path to recommendations.
