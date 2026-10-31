# PR07 — Reproducible Zyte archives and typed unverified change detection

**Status:** Draft until offline tests, controlled Zyte canaries and human release review.
**Dependencies:** PR14 correctly integrates the P06 lifecycle guard into main. This P07
PR must be based on that same mainline integration, not the obsolete PR13 branch.
No automatic job scheduling, publisher crawling, approved facts, DB writes or
additional paid storage are added.

## Architecture

Three unchanged spiders -> Zyte Scrapy Cloud Jobs metadata + paginated Items API
-> immutable local compressed archive + per-item integrity index -> verified
replay -> separate latest-observed and latest-healthy ledger -> typed unverified
review exports.

Use only the documented Zyte Scrapy Cloud endpoints:
- Job metadata: https://docs.zyte.com/scrapy-cloud/usage/reference/http/jobmeta.html
- Paginated Items: https://docs.zyte.com/scrapy-cloud/usage/reference/http/items.html

The downloader uses GET on storage.zyte.com with HTTP Basic Authorization,
with the key from ZYTE_SCRAPY_CLOUD_API_KEY only in the request header. It
refuses API redirects instead of forwarding credentials; it does not place the
key in an HTTP URL, log it, or commit it. Jobs must be in state finished. Each
Items request uses explicit count, start and meta=_key. Records are checked
against official job item_scraped_count, ordinal _key, source ID/category and
size bounds. Missing, duplicate, reordered or excessive items cause an error.

## Operator commands

Keep keys outside shell history where possible. Set the key securely using
existing secret management, then run:

    python -m scripts.download_zyte --job-id 883514/1/9 --out-dir output/archive

or directly:

    python -m scripts.archive_jobs --job-id 883514/1/9 --out-dir output/archive

The local result is output/archive/jobs/883514_1_9/ with:
- envelope.json: selected safe metadata, source scope, official job stats,
  observed quality counters and archive integrity checksums
- index.json: fixed position, _key, source ID, per-item SHA256, size/status
- items.jsonl.gz: deterministic gzip of original canonical JSONL Items

An existing job archive is verified and returned without network requests.
Never overwrite or silently repair corrupt immutable archives. Store backups
on private durable media with access controls; local staging is not a durable
offsite backup or a digital signature.

Verify without credentials or network access:

    python -m scripts.download_zyte --job-id 883514/1/9 --out-dir output/archive --verify-only

Evaluate against explicit earlier finished jobs:

    python -m scripts.evaluate_run --current output/archive/jobs/883514_1_9 --history output/archive/jobs/883514_1_7 output/archive/jobs/883514_1_8 --out-dir output/review-job-9

Exports are:
- status.csv: latest observed versus last healthy status and job
- changes.csv: typed review classifications only
- release_events.jsonl: event candidates and edited/backfilled/restored evidence
- pricing_observations.jsonl: extracted pricing observations including source ID
- review_queue.jsonl: all reviewable changes; never advisor-approved
- run_quality.json: job count, scope consistency, health and issue counters
- latest_state.jsonl: source-level last observation and last healthy pointer

The older compare_exports command remains usable for exported JSON/JSONL
files; it now rejects parser/schema/manifest/product-scope crossover as a
semantic comparison and also generates release_events.jsonl and run_quality.json.

## What qualifies for semantic comparison?

- Every archive is checksum verified on reading. The official job must have
  finished with close_reason=finished.
- Every observed Item must match manifest category and provider/URL, and
  all Items share request scope hashes, selection count and spider name.
- Full manifest SHA256 and selected-ID SHA256 must be present in the Items.
  A missing or mismatched scope marks the run as **non-comparable**.
- Captured, substantive, untruncated source evidence is required for typed
  changes. A failure or incomplete job is recorded immediately but cannot
  replace a prior healthy baseline.
- A changed source URL, manifest revision, lifecycle registry, typed extraction
  schema or documentation product scope resets baseline.
- First complete capture is historical_baseline, never a fresh announcement.
- Changelogs compare stable event_id and body_sha256. Unknown/future dates
  remain needs_review; old-dated first-seen cards are backfilled_event.
- Pricing compares model/service, region, tier, mode, price dimension, unit,
  currency and eligibility dates; Decimal values are never mixed across
  different rate dimensions. Missing rows are **not** price removals.
- Docs compare stable section IDs and content hashes on scoped pages. A
  missing section is not evidence a product feature was removed.
- CDN Age, Last-Modified and crawl timestamps are not release dates.
  Changed publisher evidence may be a candidate, not a verified vendor fact.

## Offline regression coverage

Tests use **synthetic Items and job metadata** and mocked page readers. They
exercise exact pagination, tamper detection, idempotent replay, malformed
response rejection, secret-safe Authorization headers, first-baseline
suppression, event ordering/edit/backfill, price identity/units, schema
migration, CDN/HTTP failures, restoring previous healthy baselines and
documentation section deltas.

CI must pass pytest, three Scrapy spider registration and Zyte egg packaging.
Before any main merge, coordinate with the real scheduled Zyte jobs and
validate controlled source-ID canaries. Existing deployment automation may
run when main changes; no deployment is initiated from this draft branch.

## Known limits / non-goals

This is an auditable local archive, not a production retention service or
backup service. The source registry still needs real first-party
policy/product verification. Some source URLs remain quarantined/degraded.
The extractor is not an authoritative vendor pricing/legal/fact resolver.
No ML-generated inference, automated advisor publishing, arbitrary URLs,
robots bypass, third-party paid proxies, cloud object storage, or Supabase
writes are enabled.

To get actual historical archives for a job, an operator must run the
explicit download command with their own authorized Zyte API key. CI tests
cannot validate real Zyte responses or verify the owner's production jobs.
