# P24D — Recheck validation access at the downloader boundary

**2026-11-13 — Draft code change. NO publisher access or bulk-run approval.**

## Why this matters

P23B and P21B validate the source review and bounded bulk plan when the
spider schedules a Request. If a Scrapy Request waits in the queue and its
30-day source review or 7-day bulk plan expires in the meantime, that
earlier check is stale. A successful GitHub package build is not a
time-of-download source authorization.

The existing P24B change disables automatic validation source retries, and
P24C requests a supervised shard shutdown after critical publisher access
failures. Neither of those changes rechecks access for a queued Request
*immediately before* the downloader handles it.

## Code change

New `agentfuse_crawlers.validation_downloader.ValidationDownloadGate` is
registered as downloader middleware order **110**, after Scrapy's default
`RobotsTxtMiddleware` (order 100). This is deliberate: an in-progress
robots lookup can delay the page, so the final access recheck must follow
that lookup. Robots network traffic is separately governed by the actual
human publisher/robots review, not counted as an approved source page GET.

For `collection_mode=validation` source page Requests, it:

1. Requires a source in the frozen 460-ID manifest, the exact category,
   source ID and URL in the spider's selected subset.
2. Requires an exact `GET`, `dont_redirect=True`,
   `dont_retry=True` and exactly one of the spider's existing
   `single_validation` or `bulk_validation` scopes.
3. Re-runs the existing **P23B** source-access function with the **current
   UTC clock**. Deferred, prohibited, missing, expired or wrong-scope
   reviews are denied.
4. For bulk selection, additionally checks the original **P21B**
   authorized-source set, presence of the approved plan ID and the plan's
   unexpired UTC deadline at downloader entry. The full plan and source
   registry hashes were validated earlier by the spider; this is an
   additional time-of-use control, not a substitute for those checks.
5. Allows at most **one publisher source-page GET per source ID per job**.
   A duplicate yield/redirect is denied even if its URL has not changed.
6. Sends a specific held reason to the existing `record_failure`
   errback, yielding an unverified Item without a claimed HTTP response
   or publisher HTML. Holds never become advisor-approved facts.

The exception for Scrapy's internal `/robots.txt` request is restricted
to an explicit `dont_obey_robotstxt=True` GET with **no source cb_kwargs**
and the HTTPS root robots path of a selected source host. This is required
for Scrapy's own `ROBOTSTXT_OBEY=True` machinery, not a publisher-data
access bypass. Changed-host/path robots redirects are not implicitly
permitted; operators must investigate blocked robots resolution. A
download failure to obtain robots rules is **not**, by itself, permission
to collect a page.

## Scope and limitations

- **No new permission.** Production access and run-plan registries are
  unchanged and empty. This PR creates no canary, Zyte job, deploy,
  schedule, source URL migration or production AgentFuse facts.
- **No cost guarantee.** The gate counts only primary publisher
  page requests. Scrapy's internal robots traffic, middleware-level
  behavior, job resource consumption, storage, Zyte account pricing,
  invoices and already-started downloads still require independent
  verification and P23E/P23F resource controls.
- **No live authorization.** A Git-reviewed metadata record is not
  independent proof of actual publisher rights or a remote package
  attestation. The registered policy is static for the duration of a
  running process; immediate external revocation is not proven.
- **No retroactive cancel.** The gate checks at the beginning of
  downloader processing. In-flight downloads may finish after the review
  deadline. Keep shards small and human-supervised.
- Monitoring behavior is unchanged and remains governed by the separate
  lifecycle approval.
- Any failure to collect or verify a publisher URL leaves its source
  explicitly held, including in the frozen P20A 18-source/36-round study.

## Verification

Offline regression tests:
```bash
python -m pytest -q tests/test_p24d_validation_downloader.py
python -m pytest -q tests/test_p23b_single_source_access_gate.py
python -m pytest -q tests/test_p21b_run_authorization.py
python -m pytest -q
```

All affirmative review records in the tests are deliberately **fictional,
in-memory** fixtures; they do not authenticate the publisher, traffic,
stored HTML or human approval.

CI also checks Python 3.12/3.14 and legacy Zyte egg fingerprint consistency.
This production Python edit **changes** the package fingerprint. After any
approved merge, the real Zyte deployment must be separately checked.

## Remaining critical path

[Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85):
actual human ownership, applicable website terms, robots, intended commercial
use and retention review for each exact candidate. Only after genuine
per-source `single_validation` reviews are merged, independently verify
the remote deployment and operator budget; then run one supervised
one-source canary, archive Items/Requests/Logs and original publisher HTML
where independently permitted; repeat round two only if safe. Complete
real independent cross-category reviews, empirical P23D corrections and
retests, short-lived approved P23E plans and successful P23F small shards
before any staged P23G permitted-subset campaign.

**Full 460-ID inventory is still NO-GO. Never launch an unbounded
460-URL publisher crawl.**
