# Evidence-first architecture / quality gates

## Pipeline

`Official source list -> Scrapy (robots, slow, fixed HTTPS) -> HTML evidence v2 -> dated JSON(L) archive -> change detection -> human review queue -> verified facts -> AgentFuse advisor / public Intelligence UI`

**Only the first five phases exist in this repository.** The reviewed-fact ledger, automated semantic fact validation, public UI and advisor integration remain unimplemented.

## Why the previous implementation needed changes

1. A successful HTTP response could contain a JS shell or access restriction, wrongly counted as content. It is now labeled and reviewed.
2. Price tables lost row/column structure when flattened to text. Cells and spans are now captured as evidence; verified normalization still needs per-provider parsers.
3. An entire 14,000-word changelog was one blob. Individual heading sections and date *candidates* now provide narrower diff granularity, but aren't release records yet.
4. A hash change from site-wide template edits could look like an announcement. The comparator now captures section changes and distinguishes `new_baseline` from subsequent changes.
5. Zyte's default JSON-array Items export previously did not work with the JSONL-only comparator. It now supports both formats.
6. All 82 URLs were treated as equally reliable although only nine had actually been tested live. Source cohorts now separate these states.
7. The review system lacked guardrails. Review entries are always pending and `approved_for_advisor=false`.

## Evidence schema v2

`source_id`, `provider`, `category`, `source_url`, `final_url`, `fetched_at_utc`, `http_status`, `content_type`, `last_modified`, `etag`, `status`, `review_status`, `source_cohort`, `title`, `text`, `word_count`, `content_sha256`, `text_truncated`, `sections[]`, `sections_truncated`, `tables[]`, `tables_truncated`, `canonical_url`, `description`, `language`.

Each `sections[]` entry has a stable-ish heading-based ID, title, date *candidate*, same-site evidence link, excerpt, excerpt truncation flag and content hash. `tables[]` captures visible cell text, header flags and row/column spans; it does not assert numeric meanings.

**Schema compatibility:** Existing v1 Zyte exports still load in `compare_exports`; absent `sections` means page-level review only. Truncated old v1 captures are not trusted as comparable baselines.

## Review gates for recommendation facts

1. Is the original first-party publisher authoritative for this claim?
2. Is the evidence complete, actually about the target product, and within the relevant date window?
3. Can we uniquely identify the model/tool version, access tier, location and features?
4. For price changes, are currency, input/output units, caching mode, effective dates and special rates unambiguous? If not, reject or escalate to manual review.
5. Is the change material to a specific user's stack? Do not treat all news as upgrades.
6. Only after review should the main AgentFuse app ingest a structured fact linked to source and reviewer. Prevent obsolete and superseded facts from being shown as current.

No automation in this repository may bypass these gates. A model cannot elevate a scraped instruction to system authority.

## Operational controls

- Only approved HTTPS manifest URLs. A spider argument can limit scope but cannot supply a URL.
- One concurrent crawl unit and conservative per-domain pacing. No JS rendering and no paid Zyte features are enabled.
- `cohort=proven` for smoke tests; run candidates deliberately and inspect per-source status.
- Do not publish raw docs. Raw data is for private research and manual evidence review; respect source terms and robots exclusions.
- Historic snapshots must be archived before Zyte retention removes them. The manual downloader supports secure storage to a local folder; continuous archiving still needs implementation.
- A missing item can mean skipped policy/redirect, not a successful parse. The compare tool reports missing records for each selected category.
- Truncated pages and truncated section lists are excluded from semantic section comparison to avoid false removals.

## Technical debt to avoid before scaling to 300–500 pages

- Source-specific parsers and conformance tests with **real, rights-compliant sample HTML**.
- Distinguish source page health (fetch/extraction) from truth confidence (human review).
- Backfill historical snapshots and version immutable evidence; provider announcements must not be inferred from crawl timestamps.
- Pagination/navigation only when publisher terms permit and crawl load is bounded.
- If automated export is added, use repository secrets with least privilege and avoid logging keys; GitHub Actions is not a general-purpose archive.
