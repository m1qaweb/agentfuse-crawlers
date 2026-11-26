# Phase 2B: bounded retained documentation recovery

This is a private historical evidence adapter. It reuses Phase 1 SHA-bound consolidation and create-only private output. It is not a live parser change, source authorization, product identity verification, or full capability inventory.

    python -m scripts.recover_retained_documentation --input-dir /private/exports --out-dir /private/new-docs-recovery

The CLI requires the twelve canonical original exports. As with Phase 2A, the existing output writer emits report.json, inventory.json (source coverage) and primary_observations.json (review candidates). Keep outputs private, outside the public repository.

Actual offline replay: all 69 HTTP 200 documentation observations were cross-checked against their original Items and Requests row indices and SHA-256 digests. The adapter recovered 88 page-scoped statements from 52 sources, including 23 with previously unresolved documentation scope. All 88 locators were checked against exact retained text or section excerpts; 33 have a matching section ID, two of those through section fallback. No navigation link was promoted into a capability fact. Twenty local synthetic regressions passed.

Seventeen sources remain unresolved: 6 insufficient/index-only, 4 without a scoped statement selected by this adapter, 3 requiring freshness review, 2 canonical review, 1 product-scope review, and 1 containing an embedded setup prompt rather than fact evidence. The 88 candidates remain unverified and are not normalized Boolean capability flags. A page statement does not prove the complete corpus, current availability, or applicability to a particular plan or model. Lifecycle statements require effective date review. Source-specific selectors are bounded to actual historical failure clusters, not intended as universal or future-proof live extraction.

No source data, private recovery results, live crawler behavior, paid requests or publisher reuse permission are added by this change. Independent fact and rights review and canonical product mapping remain required. The next steps are changelog event recovery and extraction quality/coverage evaluation before live-crawler readiness.
