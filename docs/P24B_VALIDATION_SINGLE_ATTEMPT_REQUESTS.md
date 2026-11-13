# P24B — Single-attempt publisher GETs for bounded validation

**November 13, 2026. Status: code change proposed for review; full inventory remains NO-GO.**

## Concrete issue

`agentfuse_crawlers/settings.py` enables Scrapy's `RetryMiddleware` with
`RETRY_TIMES = 1` for HTTP 500/502/503/504 and retryable network exceptions.
A nominal **one-source, one-round validation** could therefore issue an
additional publisher GET without another explicit operator approval. A
reviewed bulk run plan's `max_primary_requests` currently counts the initial
requests yielded by `OfficialBaseSpider.start()`, not RetryMiddleware's
follow-up requests. It would be wrong to describe that counter as a complete
network or billing cap while automatic source retries remain enabled.

This issue is visible from the production configuration; **no new publisher
request, claim of actual double-GET behavior, or billed cost measurement was
required** to identify it.

## Narrow fix

- Put `dont_retry=True` on **validation-mode publisher source requests**
  (`collection_mode=validation`), including defensive same-source redirect
  requests. Scrapy RetryMiddleware honors this flag for retryable responses
  and downloader exceptions.
- Leave the current monitor-mode retry policy unchanged. Existing exact-URL
  access reviews, separate bulk plan reviews, URL redirect holds, lifecycle
  quarantine, robots obedience, Item statuses and three spider types remain.
- Offline synthetic regression tests check single-source validation across
  all three categories, a reviewed subset inside bulk validation, and a 503
  response passing through real Scrapy RetryMiddleware without generating a
  new request. A synthetic monitor request verifies isolation.

## What this does NOT guarantee

- **Not a fixed total HTTP request cap.** Robots.txt requests, robots
  redirects/retries, download-layer behavior and any other infrastructure
  requests may consume time or units. A source-specific approval is not
  a dollar budget. P23E still needs independent current Zyte account pricing,
  remote deployment verification, per-source limits, whole-job cost ceilings,
  explicit human/operator sign-off, and stop thresholds.
- Not a guarantee of successful fetch or a workaround for 403/429, CAPTCHA,
  robots disallow, login walls, changed URLs, or an inaccessible publisher.
  A 5xx/timeout remains an unverified failure for human review; if another
  attempt is justified, it must be a separately authorized round/job.
- No source access review has been provided. Both checked-in source/plan
  registries remain empty. **No P23C canary, Zyte job, deployment, schedule,
  permission or approved AgentFuse fact is created here.**

## Review and next real step

Review on GitHub; run:
```bash
python -m pytest -q tests/test_p23b_single_source_access_gate.py
python -m pytest -q tests/test_p21b_run_authorization.py
python -m pytest -q
```

The production Python package fingerprint changes after merge; any future
permitted pilot must independently verify the installed Zyte package again.

Then execute [Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85):
an actual human conducts **exact URL ownership, governing site terms, robots,
commercial data reuse and retention review**. Denied/deferred sources remain
held. Only genuine per-source `single_validation` determinations, deployed
and combined with an independently checked budget, can precede one manually
approved Zyte canary. Preserve the original 18 sources / 36 rounds; do not
run all 460 URLs.
