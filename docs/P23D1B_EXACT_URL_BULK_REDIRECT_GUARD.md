# P23D1B — Exact-URL redirect enforcement for reviewed bulk validation

**State:** Code change to three official spiders via their shared base class.
**No publisher access decisions, crawling, deployment, new authorizations,
jobs or schedules are made by this PR.**

## Verified gap

P21B correctly requires **per-source exact-URL reviews** and a separately
approved finite bulk run plan. P23B extended that review requirement to
single-source jobs, including redirects.

However, the existing bulk validation redirect branch could follow any
HTTPS redirect **on the same publisher hostname**, up to the plan's
`max_redirects_per_source`. That would issue requests to a **different
path/query** not present in the original URL review or manifest. A budget
cap is not permission for those second URLs.

The authentic November 4 historical Zyte baseline contained **28
rejected redirects** across 460 source Items, including a Gemini
pricing HTTP 301. These historical facts show that redirect handling is
relevant to rollout; they do **not** prove current site behavior or
publisher authorization.

## Change: fail closed on changed URLs, including same-host

For `collection_mode=validation`, whether exact **single** source or
reviewed **bulk** scope:

1. A 301, 302, 303, 307 or 308 response is never allowed to initiate a
   GET to a destination other than the source's **exact reviewed
   manifest `source_url`**, even on the same host.
2. Changed path, query, fragment, default-port spelling or URL scheme
   all produce an unverified Item:
   - `status=redirect_needs_review`
   - `error=bulk_source_redirect_target_requires_review` for bulk, or
     the existing single-source error;
   - `policy_observation=redirect_not_fetched_without_exact_url_review`
   - `approved_for_advisor=false`;
   - `redirect_review_target` sanitized to HTTPS host/path, **without
     sensitive query parameters**.
3. Defense in depth: if any callback unexpectedly receives HTTP 200
   at a URL different from the exact source URL, the spider **does
   not extract HTML or prices/releases from that page**. It records
   `redirect_needs_review/unreviewed_validation_response_url`.
4. Same-URL redirect loops remain blocked by existing loop/depth
   checks. The plan's 0–3 redirect limit remains a resource ceiling,
   **not a second URL authorization**. To fetch a migrated canonical
   URL legitimately, first independently review the new URL and
   update the manifest, publisher access registry, and bounded plan
   through normal approvals.
5. Separately approved `collection_mode=monitor` preserves existing
   legacy handling; this PR neither grants nor expands monitor rights.
6. The existing robots obedience, bandwidth limits, and no
   403/429/CAPTCHA bypass remain unchanged.

## Synthetic regression checks (zero network)

Tests simulate an *in-memory*, explicitly fictional, structurally
valid bulk policy and plan for each of the three source categories.
They demonstrate all off-URL redirects are held **even with a
three-redirect budget**, including changed path/query/default-port/
fragment, and that a forged final HTTP 200 on a new path cannot be
parsed or trusted. The original cap test still verifies loop rejection
with a cap of zero, and single-validation and monitor legacy tests
remain in the full suite.

Tests never request actual publisher URLs or create genuine positive
permission registry records.

## Operator deployment and full inventory readiness

This phase **changes the deployable crawler package fingerprint**.
Therefore after merging, the operator must independently verify that
Zyte Scrapy Cloud runs this exact updated package before initiating
any approved one-source job. Old cached source/plan hashes or old
manual job arguments are not evidence of the new deployment.

**Next permitted operation is still the small canary, NOT full crawl**:

- A genuine human completes the original-source ownership, website
  terms, robots and retention review for at least one frozen source,
  and that specific decision is reviewed in P23B's registry.
- The operator verifies installed Zyte package and exact allowed
  spend/priority, then **manually** starts one actual allowed source
  job. Save real Jobs/Items/Requests/Logs and original HTML if licensed.
- Review the result, then run one distinct second-round job only if
  still allowed. Examine extraction quality with independent human
  reviewers across documentation, pricing and changelog. Fix any
  real parser failures based on original page evidence.
- Next, reviewed time-bounded P23E batch authorization, supervised
  P23F small-shard expansions and P23G 460-ID accounting are required.

**Full 460-source Zyte crawl: NO-GO** while the P23B source access
registry is empty, the bulk plans registry is empty, and real
category canaries have not been independently reviewed. In a later
full-inventory *audit*, all 460 original IDs must be accounted for
while only **approved source URLs are actually fetched**.

Actual human access review and permitted first canary:
[Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85).

## Validation

```bash
python -m pytest -q tests/test_p21b_run_authorization.py
python -m pytest -q tests/test_p23b_single_source_access_gate.py
python -m pytest -q tests/test_fresh_spiders.py
python -m pytest -q
```

CI must pass Python 3.12/3.14, the no-crawl preflight, exactly three
official spiders, and match locally built egg bytes to the new
source-package fingerprint. Equality of local egg bytes alone is
**not proof of remote deployment**, publisher permission, or
data correctness.
