# P23B — Enforce Exact-Source Publisher Review Before Any Single-Source Validation GET

**Scope:** follows merged P23A / PR #79. **Safety:** no permissions granted, no source manifest edit, no Zyte job, no publisher GET, no automation/alerts/DB writes.

## Why

P21B correctly prevented unreviewed bulk jobs, but intentionally left
`collection_mode=validation` + `source_ids=ONE_ID` as an operator-managed
exception. That exception could still yield a live publisher request with no
record in `data/validation_access_reviews.json`. It also allowed a changelog
Markdown fallback at a **different** publisher URL. P23B closes these gaps
before launching any actual P23C canaries.

## Production contract

1. **Every single initial publisher GET is source-policy gated.**
   `OfficialBaseSpider.start()` first enforces the existing source lifecycle
   decision, then invokes `validation_access_decision(source,
   scope="single_validation")`. The review must already be in the reviewed
   DEPLOYED `agentfuse_crawlers/data/validation_access_reviews.json`, match
   the exact manifest source ID, URL and category, remain unexpired, contain
   first-party ownership/terms/robots/private-retention evidence, and explicitly
   include `single_validation` scope.
2. A missing, denied, deferred, stale, bulk-only or wrong-scope review produces
   exactly one **unverified held Item**, no publisher request:

       status: source_single_validation_not_approved
       error: single_source_policy_not_reviewed
       http_status: null
       policy_observation: not_fetched_by_single_source_access_gate
       approved_for_advisor: false

   The `error` changes to the actual scope/decision/expiry hold code when
   applicable. Invalid/malformed packaged registries fail startup closed.
3. Single-source redirects to a **different URL** (even a different path or
   query on the same first-party host) stop with
   `redirect_needs_review` / `single_source_redirect_target_requires_review`
   and preserve the original HTTP redirect response status. The response
   target is evidence for independent review, not a permitted next GET.
   A same-URL redirect also cannot bypass a review that expired during the
   job; it is held before further requests. Migrate the canonical manifest
   URL through a separately reviewed change when required; do not force a
   redirect by passing a raw URL CLI argument.
4. Single-source changelog validation **does not fetch the separately
   allowlisted Markdown alternate** without its own reviewed URL mechanism.
   Primary HTML evidence remains available for offline diagnostics. Existing
   monitor-mode behavior is not expanded or granted new permissions in P23B.
5. Bulk validation still needs P21B's separately reviewed exact run plan and
   per-source `bulk_validation` scope. Single-source approval does **not**
   grant a bulk plan or monitoring privileges.
6. `agentfuse/coverage/single_access_held_sources` and diagnostics
   `not_attempted_by_single_source_access_policy` /
   `single_validation_unapproved` distinguish these held sources from
   bulk-plan holds and technical lifecycle quarantines.
7. `cohort=all`, a valid configured source ID, historical "proven" status,
   `confirm_full_inventory=yes`, a SHA-256 or a completed CI run **never**
   supply a human publisher access decision.

## Private operator procedure (not executable permission)

1. Check actual publisher ownership, access terms, robots restrictions, exact
   product URL, source purpose and private retention constraints. Do not
   bypass 403/429, CAPTCHA, robots rules, or move to another publisher URL.
2. Record a genuine human decision in a Git-reviewed minimal metadata entry
   under `agentfuse_crawlers/data/validation_access_reviews.json`. The
   `reviews` map is currently **empty**. A positive review requires:
   - `source_url`: exact value already in `sources.json`;
   - `category`, `decision="allowed_reviewed"`,
     `scopes=["single_validation"]` (add `bulk_validation` only after
     distinct actual approval for that scope);
   - named human `reviewed_by`, timezone-aware `reviewed_at_utc`,
     `expires_at_utc` within **30 days** of the review;
   - `ownership_evidence_url` on the exact official host,
     `publisher_access_policy_url`, exact-host `robots_url` ending
     `/robots.txt`;
   - genuine `publisher_terms_reviewed=true`, `robots_reviewed=true`,
     `private_retention_reviewed=true`, and a substantive publisher-specific
     `evidence_note` (80–1500 characters).
   Never fabricate evidence or commit confidential correspondence/HTML.
   For denied/deferred reviews, all affirmative booleans must be false and
   `scopes=[]`; preserve every inaccessible frozen source in the denominator.
3. Review the PR and verify deployed package fingerprint in Zyte after merge
   (this is a production-package change). A GitHub SHA or screenshot alone
   does not prove the deployed byte fingerprint.
4. Only when a legitimate, reviewed source record is present and deployed,
   manually request a **single** bounded validation spider:

       cohort = all
       source_ids = EXACT_REVIEWED_SOURCE_ID
       collection_mode = validation

   Add manifest/selection/lifecycle fingerprint pins from the P20A manual
   canary plan. Do not use bulk-run flags, `limit`, `offset`, monitoring
   mode or `confirm_full_inventory` as permission bypasses.
5. Archive the full Zyte Items/Requests/Logs and job metadata. A `finished`
   status with one held Item and zero original-source GETs is not successful
   evidence collection. Review any redirect hold separately.

## Verification and non-goals

```bash
python -m pytest -q tests/test_p23b_single_source_access_gate.py
python -m pytest -q
```

Synthetic tests exercise all three spider categories; true positive, missing,
expired, denied, deferred, bulk-only, mismatched source URL/host, quarantined,
redirect, mid-job expiry, Markdown alternate, unchanged bulk and monitor rules.
They do **not** establish publisher permission or real-world pricing accuracy.

No publisher HTML, real human reviews or 460-source diagnostic runs were
created. No permission registry was populated. **Current P23C readiness
remains NO-GO** until genuine publisher-specific reviews and permitted,
independently archived two-round source canaries are completed.

**Next phase P23C:** private, evidence-backed source policy review and
bounded exact-ID two-round live canaries, with complete 18/36 frozen-source
attrition accounting. Do not use synthetic fixture reviews in production.
