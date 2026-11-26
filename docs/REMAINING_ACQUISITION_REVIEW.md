# Phase 3A — Remaining acquisition review, not a launch scope

November 26, 2026. Reuse the SHA-pinned historical consolidation.

    python -m scripts.prepare_remaining_acquisition_review --input-dir /private/exports --out-dir /private/new-review

This generates private report.json, inventory_review.json (all 460 identities),
held_groups.json (all 84 historical group holds), and gap_review_only.csv (260
missing HTTP 200 observations). Review columns are blank. This is a companion
worksheet, NOT an importable P26A authorization worksheet or a run plan.
Keep private, outside the public repository.

## Observed review tiers

| Category | Retain HTTP 200 | Original URL review | Ordinary redirect review | Other redirect hold | Unfetched group hold |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pricing | 97 | 10 | 0 | 14 | 56 |
| Documentation | 69 | 15 | 31 | 4 | 75 |
| Changelog | 34 | 4 | 0 | 2 | 49 |
| Total | 200 | 29 | 31 | 20 | 180 |

The 60 initial review candidates span 54 containment groups. All require current
publisher/source review; 31 additionally require a reviewed canonical migration
and group-hold disposition. The 29 unchanged URLs are historical exclusions,
not previously approved URLs. No automatic release of any hold.

Theoretical cumulative ceiling of that pool is 260 HTTP 200 sources assuming all
are reviewed, admitted and successful. Reaching 250 requires 50 additional
successes; reaching 300 requires 100, including at least 40 outside this pool.
No guaranteed acquisition yield or production data accuracy is inferred.

Of 51 observed redirect targets, 50 are same-origin: 10 trailing-slash only,
38 other path changes, and two source identities sharing one target (Inception
pricing and changelog redirecting to the homepage). One is cross-origin
(Portkey pricing). No redirect is automatically followed or written to the
manifest. Replit's redirect to one dated release page is not automatically a
replacement for a complete changelog index. Review product and category scope,
not just the destination hostname. Three v0 sources are quarantined.

## Next action, not another broad paid crawl

1. Independently review the exact 29 original URLs and 31 ordinary redirect
   targets, with applicable terms, robots, first-party product scope and
   permitted retention. Resolve the documented holds explicitly before any
   admission. Research evidence is not a human attestation.
2. Review the remaining 20 redirects and 180 held unfetched IDs only where
   material to the acquisition objective. Do not bypass denials, quarantine,
   challenges or rate limits; do not substitute unofficial sources.
3. Review any canonical URL/manifest updates and source-specific access records.
   Preserve the historical checkout for replay. The old public diagnostic
   and documentation-only resume descriptors are manifest-bound; do not reuse
   or silently extend them after edits.
4. Once actual source reviews exist, use the existing P21B validation policy
   to construct the exact three category plans with approved subsets and
   max_redirects_per_source=0. The P25 planner's 200–300 fresh-target minimum
   is not a cumulative continuation goal. Do not pad a continuation by
   refetching 200 successful sources. The existing P21B manual full-category
   plan matcher supports a nonempty reviewed subset. Exactly one full category
   plan per spider can use the existing three-argument convenience, but only
   after installed plans, package pins, expiry, account and deployment checks.
   A new continuation-specific plan review is required; do not claim the P25
   campaign launcher supports a smaller target.
5. Validate the merged live parser in the intended deployment before paid
   execution and preserve Items, Requests and Logs for every job.

At this snapshot the strict access and run-plan registries are empty. Authorized
next primary requests: 0. No runnable new scope or launch instruction issued.
No changes to crawler runtime, manifest, rights, lifecycle or access controls.

Local evidence check: all twelve original export hashes, 251 primary Item/Request
pairs, 542 accounting row references, and all 51 redirect targets matched the
private consolidated evidence. The review builder and writer were exercised
against that evidence; 17 synthetic targeted tests passed. The CLI's existing
consolidate integration is not claimed locally executed; normal CI remains
required. The public PR contains code, synthetic tests and aggregate documentation
only, not the private review packet.
