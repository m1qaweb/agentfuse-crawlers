# R2 — Bounded publisher-level validation containment

Owner decision: on 2026-11-25 the project owner explicitly approved the
proposed bounded publisher-level failure isolation, with all publisher
restrictions, authorization checks and systemic global-stop safeguards
preserved. This is approval of internal stop behavior only. It does not
approve a single publisher URL, production ingestion, a Zyte job or a budget.

## Activation and grouping

Only explicitly confirmed full-category validation jobs with a positive,
exact, currently reviewed bulk plan and zero redirects activate R2.
Single-source validation, bounded shards, older redirect-capable plans and
monitoring retain their existing behavior.

Build deterministic operational groups from the entire pinned 460-source
manifest, not just the current category. Join the same provider, known
cross-domain product families, and shared last-two-label DNS suffixes
transitively. This is a conservative operational grouping, not verified
corporate ownership or permission. Shared platforms and public suffixes can
overhold unrelated publishers; never split a held group to improve yield
during a run. Review grouping against the actual publisher relationships
before approving the campaign.

## Stop behavior

- Before robots and again at the publisher admission boundary, check exact
  source, method, review, plan scope and expiry. One GET per authorized
  primary ID, at most one robots GET per exact origin, no redirect following
  or retries. A held publisher cannot trigger a new robots lookup.
- A publisher HTTP 401/403/429/451, 3xx, 5xx, unresolved/denied robots or a
  detected access/login challenge holds its entire group immediately.
  Genuine robots 404/410 keep the existing strict parser behavior; they
  are not permission to collect HTML. The hold is latched before asynchronous
  Item pipelines. Only other currently reviewed groups may continue.
- Three distinct held groups over the **entire job** trigger the systemic
  global stop (deliberately stricter than a rolling time window).
  A 407 proxy authentication failure, unknown primary transport failure,
  unknown scope/target/method, expiry, budget/clock anomaly or audit
  integrity failure stops globally. Known per-origin robots transport
  failures hold their group; unknown transport failures stop globally.
- An admission deadline is no later than 3300 seconds after spider
  construction, narrowed by any configured shorter Scrapy job timeout.
  This is not a monetary limit. Operator/account controls remain mandatory.
- Already-admitted requests might be slot-queued or in flight and may
  finish; they cannot be claimed cancellable. Record admitted-pending
  tokens separately from actual Requests records. No new admission once
  the relevant hold is latched. No automatic retries or alternate routes.

## Sequential campaign and evidence

Use P25 launch order pricing, documentation, changelog with a persistent
owner-private ledger. Before documentation, provide the pricing Items
archive and P26B raw evidence export. Before changelog, provide both prior
pairs in the same order using repeated:

```text
--prior-category-evidence ITEMS_ARCHIVE_DIR P26B_EVIDENCE_DIR
```

The existing P26B loader and offline replay reconstruct the exact prior
dispatch, package, Items and raw Requests/Logs evidence. Missing/mismatched
evidence, any blocked group, intentional hold, unknown missing primary,
abnormal closure or audit issue prevents the next API GET/POST. This first
implementation deliberately halts the campaign after **any** prior barrier
rather than attempt automatic scope repair. Review the affected groups,
retain all prior attempted IDs/receipts, and obtain fresh operator approval
for a different scope; never blindly relaunch a completed or unknown job.

Direct Zyte dashboard launches cannot share private launcher state. They
must not be used to bypass the sequential evidence gate. If using the
dashboard manually, enforce the same stop/review rule before each later
category; the runtime cannot guarantee cross-job shared state without a
trusted external ledger. Prefer the P25 launcher.

P25/P26B report intentionally held Items separately from unexpected missing
Items or primary GETs; the 460-source denominator stays unchanged. An
intentional hold never counts as a fetch, capture, quality pass or advisor
approval. A local archive receipt is not a remote signature.

## Release gate

All R2 tests are synthetic/offline: no real publisher or Zyte jobs. Final
Python 3.12/3.14 Scrapy validation, egg fingerprint verification, source
reviews, valid plans, remote deployment and account/budget checks remain
required. Keep authorization registries empty until actual owner-reviewed
access decisions exist. No production deployment merely because this code
has passed tests.
