# P23E1/P23E2 — Read-only Scrapy Cloud queue, schedules and operator cost preflight

**2026-11-13 — P23E2 improvement under code review. Full inventory remains NO-GO.**

## Motivation

The P23C human gate and two-round real canaries cannot be bypassed.
The project also needs to verify its **actual current Zyte environment**,
unscheduled/unexpected jobs and its **real account-specific cost** before an
operator considers a bounded run. A local package SHA or GitHub CI result
is not independent remote deployment proof. Likewise, `Job Units=1` is
a compute allocation, **not a guarantee of $0 billings, unlimited runtime,
retention, no other jobs, or a hard maximum dollar charge**.

Zyte's public documentation provides a read-only Scrapy Cloud Jobs API:
`GET https://app.zyte.com/api/jobs/list.json` with `project`, `state`
and a requested `count`. Its own Job Units documentation describes
1–6 units per job, with shared limits based on the account's available
units. Those public pages cannot verify **your** current subscription,
existing commitments, data retention, or optional add-on charges.

References:
- https://docs.zyte.com/scrapy-cloud/usage/reference/http/jobs.html
- https://docs.zyte.com/scrapy-cloud/usage/units.html
- https://docs.zyte.com/scrapy-cloud/usage/reference/http/jobmeta.html
- https://docs.zyte.com/scrapy-cloud/usage/reference/http/periodicjobs.html

## Implemented

`python -m scripts.p23e1_zyte_queue_preflight` reads exactly three
allowlisted **GET** URLs: one each for `state=pending` and
`state=running`, and one for the documented
`/api/projects/{project_id}/periodicjobs` list. All three URLs are
restricted to the operator's **exact** Scrapy Cloud project ID.
It uses the private `ZYTE_SCRAPY_CLOUD_API_KEY` in a Basic Authorization
header, refuses redirects, limits each JSON response to 1 MB,
validates project ownership, state, exact row counts, unambiguous job IDs
and duplicate JSON keys, then writes a **new-only, private** report.

- No `run.json`, `stop.json`, `update.json`, `delete.json`, periodic-job
  POST/PATCH/DELETE, or deployment endpoint is callable from this code path.
- Periodic schedules are enumerated **read-only** with schedule IDs,
  enabled/disabled state, job/task names and cadence. Secret-bearing
  `spider_args`, `script_args`, descriptions, custom fields and metadata
  are discarded before the private report is generated.
- If the API reports a next schedule page, or `count` differs from returned
  rows, the tool does **not** follow the untrusted next URL and flags the
  schedule audit as incomplete; absence of enabled schedules is **not**
  asserted. Operators must review remaining pages independently.
- A reported total greater than its returned page is marked
  `queue_list_single_pages_complete=false`, not a clean queue.
- Pending/running job IDs and spider names remain visible for review.
  Arbitrary unknown remote metadata is discarded; API keys are never
  serialized.
- A zero-job result means only **no jobs seen in the two sequential
  queue GETs**. A complete, empty schedule page means only **no enabled
  periodic jobs observed in the third read-only GET**. These three
  snapshots are non-atomic, may become stale instantly, and cannot prove
  that another operator will not schedule or run a job later. They do not
  establish remote code identity, independent permission or cost controls.
- The report ALWAYS says `NO_GO`, `readiness_to_run=false` and
  `incremental_spend_ceiling_approved_by_operator=false`. This is
  deliberate even if both lists are empty. Code does not mint approvals.


## P23E2 schedule audit interpretation

The third read-only request follows Zyte's documented
[Periodic Jobs API](https://docs.zyte.com/scrapy-cloud/usage/reference/http/periodicjobs.html).
The returned **list** is project-scoped. For example, an enabled schedule
with `cron_UNVERIFIED="0 9 * * 1"` could create a job even when both
pending and running queues happen to be empty. The report contains:

- `periodic_schedule_list_complete` and
  `periodic_schedules_reported_total`
- `enabled_periodic_schedules_visible` and
  `disabled_periodic_schedules_visible`
- `no_enabled_periodic_schedules_observed`, which can only be true if the
  current schedule page is complete and contains zero enabled schedules
- Sanitized schedule IDs, task names and cron fields; **never** raw
  scheduled task arguments or unknown remote API metadata

A remote API read is direct observational evidence for this project at
that moment, **not** an independent audit of all account projects,
deployment source bytes, account billing, or future scheduling. Even if
the three API reads all show zero active jobs and zero enabled schedules,
the program deliberately continues reporting `NO_GO`. The user must not
take this tool's queue/schedule snapshot as a job authorization.

## Operator usage (explicit read-only action)

Requires a trusted local checkout and operator's existing Scrapy Cloud
API key (not a Zyte API key). Do not put a key on the CLI, in Git, in
GitHub Actions secrets for public build jobs, in screenshots or in reports.

```bash
# Set ZYTE_SCRAPY_CLOUD_API_KEY privately in your shell/environment.
python -m scripts.p23e1_zyte_queue_preflight \
  --project-id 883514 \
  --out-dir output/private/p23e1-queue-check-001
```

The example project number `883514` comes from previously recorded
historical Zyte job keys; **confirm this is the actual current target
project** before using it. The output path must not already exist.
Avoid committing the report to Git; retain it privately with other
operator evidence.

This action does not contact any publisher, schedule a job, deploy an
egg or change a Zyte project.

## Required independent human checks before ANY actual publisher canary

1. The actual **installed** remote project deploy/egg identity versus the
   reviewed local package SHA and three-spider source manifest. Neither the
   queue API's job `version` nor a GitHub hash alone proves current deploy.
2. Independently re-check the dashboard's periodic schedules (including
   pagination), **all relevant projects**, and pending/running queues
   *immediately before* a separately approved manual canary. Three sequential
   API GETs are not atomic and cannot rule out future jobs.
3. Current billing/plan: included unit allocation, subscription price,
   runtime limits, data retention, extra services, and any account-specific
   usage fees. Set a **documented finite per-job and cumulative incremental
   cost ceiling** with real unit prices and a stop procedure. A zero
   incremental-charge claim must be supported by account evidence.
4. A human's genuine **per-URL** publisher ownership, terms, robots,
   commercial use, original HTML retention and request-cadence decision;
   all other sources stay held. `robots.txt` availability is not consent.
5. Independently archived, two-round **real** Jobs/Items/Requests/Logs/
   original HTML where permitted, plus blind human reviews and empirical
   parser retests. Then P23E short-lived reviewed source-specific plans
   and supervised P23F small-shard pilots, *not* an unbounded 460-URL crawl.

## Offline tests / safeguards

```bash
python -m pytest -q tests/test_p23e1_zyte_queue_preflight.py
python -m pytest -q
```

All test Jobs and API responses are synthetic. No tests use a real
Zyte key or contact either Zyte or any publisher. Build/package CI on
Python 3.12/3.14 remains necessary. A successful test is not an
operational cost approval or independent publisher permission.

**Outcome:** The software can produce a bounded, read-only queue-evidence
snapshot. It cannot proclaim the P23C or P23E gates passed. Issue
[#85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85) remains
the critical human and real-evidence dependency.
