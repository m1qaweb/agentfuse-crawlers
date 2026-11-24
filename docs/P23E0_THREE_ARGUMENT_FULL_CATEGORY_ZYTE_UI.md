# P23E0 — Three-argument Zyte full-category launch (no new fetch permissions)

**November 7, 2026.** This simplifies the operator's full-category Zyte
Run screen without relaxing publisher-access requirements. This PR does not
create any publisher GET, change source/plan registries, or approve one source.

## Simple operator UI (AFTER actual approvals)

Run these as three **separate** manual Zyte jobs:

| Zyte spider | Full configured IDs |
|---|---:|
| `official_changelogs` | 89 |
| `official_pricing` | 177 |
| `official_documentation` | 194 |

For each spider, enter exactly three key/value arguments:

```text
cohort = all
confirm_full_inventory = yes
collection_mode = validation
```

Job Units: 1. Priority: Normal. Leave tags blank. **No**
`source_ids`, `limit`, `offset`, `bulk_run_plan_id`,
`expected_bulk_plan_sha256` or `expected_deployment_package_sha256`
is necessary for this narrowly scoped manual full-category mode.

Optional manifest/selection/source-lifecycle SHA pins are still accepted.
Any explicitly supplied incorrect pin fails closed as before.

## What the installed code does

Only if `cohort=all`, `confirm_full_inventory=yes`, **no**
`source_ids`, limit or offset, and all three optional bulk-plan arguments
are absent:

1. Revalidate the **installed** packaged `bulk_run_authorizations.json`
   registry. Match a plan by exact category, mode, cohort and complete
   selected source-ID order, not by a user-supplied URL or untrusted page.
2. If **zero** plans match, a recognized Scrapy Cloud bulk job (valid
   `SHUB_JOBKEY`) fails startup with an actionable NO-GO message and issues
   **zero** publisher GETs. Local offline held-only accounting preserves
   `bulk_run_plan_not_present` Items. If **two or more** plans match, fail
   startup with an ambiguity error. This cannot prevent the Cloud job
   from already having been scheduled; use P25 preflight before clicking Run.
3. For **exactly one** match, derive its plan ID, SHA-256 fingerprint
   and the *running* package's content fingerprint. Supply them to the
   **unchanged** `authorize_bulk_run()` logic, which still checks:
   - source URL review scope `bulk_validation` and its expiry;
   - full source URL, manifest, selected IDs, lifecycle and access registry;
   - approved plan category/cohort, human review, expiry (up to 7 days),
     maximum primary requests and redirects.
4. Fetch **only** IDs in the allowed subset, keep quarantine, robots,
   exact-URL redirect and max-request limits, emit held Items for the rest.
   A plan review attestation is not an independent legal permit.

**Strict boundaries:** No plan is inferred or invented. Exact **subsets**
and all monitoring jobs keep the previous explicit-plan/permission behavior.
Old manually supplied bulk IDs and SHAs remain accepted and strictly
validated. No change to full-inventory `confirm_full_inventory=yes` safety.
No universal auto-authorization, authorization to bypass robots, or automatic
scheduling.

## Why this does not immediately unlock the November 7 crawl

The actual checked-in `data/validation_access_reviews.json` still has
`reviews={}` and `data/bulk_run_authorizations.json` has `plans={}`.
The November 7 Zyte jobs generated 460 **held** Items, zero publisher GETs,
and `bulk_run_plan_not_present`. They confirmed full source accounting,
not retrieval accuracy. No CLI argument or optional omitted field can supply
missing human-reviewed source-specific permissions and plan decisions.

After genuine publisher terms/robots/ownership/retention review and real
small canaries, a human-reviewed short-lived bulk plan can be added in a
separately reviewed PR. The operator must verify the **actual installed
remote Zyte package** before launching it. Computing the package hash
inside the deployed process is **not an independent external assertion**
that it was the release the operator intended.

A reviewed plan can be reused within its expiry window if an operator
relaunches it: static JSON cannot enforce exactly-once consumption.
Avoid relying on plan expiry as a substitute for an external job budget.

## Test contract

```bash
python -m pytest -q tests/test_p21b_run_authorization.py
python -m pytest -q tests/test_p20b_zyte_ui_args.py
python -m pytest -q
```

In-memory fake access/plan fixtures cover all 3 full categories, exact
accepted subset, held source accounting, old UI arguments, missing plan,
wrong category, duplicate matching plans, expired/tampered reviews,
wrong pinned hashes, non-full subsets and monitoring isolation.
**Synthetic tests never approve real websites or make live requests.**
