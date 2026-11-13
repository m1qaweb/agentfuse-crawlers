# P24C — Stop a supervised validation shard after an access barrier

**November 13, 2026. Status: review-only implementation; publisher collection remains NO-GO.**

## Observed implementation gap

Before P24C, `OfficialBaseSpider.parse_page()` recorded 403/429 as
source-level failures and flagged unreviewed redirects or HTML challenges.
`record_failure()` likewise recorded robots/IgnoreRequest denials.
`SourceCoverageAudit` tracked these statuses, but did not request that
Scrapy stop the remaining **validation** shard after this policy signal.
A supervised batch might therefore continue to other approved sources after
its first access-denial signal, contrary to the first-canary stop policy.

## Scoped change

`SourceCoverageAudit.item_scraped()`, which runs after an Item passes through
the Item Pipeline, now requests a single Scrapy spider closure with an
explicit reason when a **selected** source in `collection_mode=validation`
emits:

| Captured Item | Requested close reason |
|---|---|
| `robots_or_policy_denied` | `agentfuse_validation_robots_or_policy_denied` |
| HTTP 401, 403 or 407 | `agentfuse_validation_http_access_denied` |
| HTTP 429 | `agentfuse_validation_http_429` |
| `blocked/access_or_login_challenge` | `agentfuse_validation_access_or_login_challenge` |
| `rejected_redirect` or `redirect_needs_review` | `agentfuse_validation_unreviewed_redirect` |

The signal records `agentfuse/run/validation_abort_reason` and
`agentfuse/run/validation_abort_source_id`. Repeated responses do not
request a second close. The source Item is processed before shutdown is
requested. Lifecycle/policy-held Items from **unattempted** sources do not
invoke the new stop. HTTP 5xx remains an error Item, not necessarily a
publisher restriction; validation request retries are separately addressed
by [P24B PR #95](https://github.com/m1qaweb/agentfuse-crawlers/pull/95).

**Unattended monitoring is intentionally unaffected.** Existing configured
source manifest, three spiders, explicit access review and run-plan
registries, parser outputs and data approval flags remain unchanged.

## Operational caveats (critical)

A Scrapy `close_spider` request is **cooperative**, not a pre-download
atomic abort. Requests already in the downloader queue (up to configured
concurrency) may complete; some queued Items may be absent. The post-run
coverage gate must therefore mark missing Items and abbreviated jobs as
incomplete, **not** assume a successful complete shard. A successful close
request does not establish fixed HTTP, time, Zyte units or monetary budget.
Keep shards small and supervised. P23E still requires exact current Zyte
account pricing, independent remote package verification, explicit maximum
spend/runtime and actual account-level stopping controls, and per-source
publisher rights before any run is authorized.

Synthetic offline tests verify critical status triggers, duplicate-close
suppression, nonfatal review holds, monitor isolation, and one genuine
Scrapy parser 429 **object** (not a live publisher fetch). All access
registries remain empty. No Zyte jobs or schedules are created.

## Review and follow-up

- `python -m pytest -q tests/test_coverage.py`
- `python -m pytest -q tests/test_p23b_single_source_access_gate.py`
- `python -m pytest -q`
- Independently review all CI conclusions and code changes before merge.
- Re-verify the **new** deployed Zyte package fingerprint after any reviewed
  merge; GitHub green checks are not remote deployment proof.
- Continue [Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85):
  genuine human URL-by-URL ownership, robots, governing site terms,
  commercial use and retention review; then one manually approved,
  cost-bounded single-source Zyte canary, followed by a second round only
  if policy and evidence remain sound.

**Full inventory = NO-GO.** A 460-ID accounting run is not approval to
fetch 460 publisher URLs.
