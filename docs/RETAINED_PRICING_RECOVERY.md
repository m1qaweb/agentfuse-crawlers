# Phase 2A: bounded retained pricing recovery

This is a private historical evidence adapter, not a live parser release or verified rate card. It reuses Phase 1's SHA-bound consolidation and private create-only output. No original HTML, network access, new paid jobs, source authorization, or publisher rights are inferred.

    python -m scripts.recover_retained_pricing --input-dir /private/exports --out-dir /private/new-price-recovery

The CLI requires all twelve canonical original exports. Its output directory uses the existing writer: report.json (coverage and summary), inventory.json (per-pricing-source outcomes), primary_observations.json (review-only recovered pricing observations, not raw primary Items). Keep all outputs private.

The actual offline replay of the Phase 1 consolidated primary observations recovered 114 typed candidates across 8 of 97 HTTP 200 pricing sources:
- xAI 42: explicit USD, two context bands, model label and input/cache/output.
- Together 35: first retained table matched to its flattened header and row sequence; batch selector state and currency unresolved.
- DeepSeek 12: transposed model/rate matrix and peak/off-peak tiers; retain schedule evidence, currency unresolved.
- Perplexity 10: tool invocation and search request units, separate services.
- Apify 7: subscription vs compute units; never substitute included credits.
- Hyper3D 5: monthly charge, annual total, and direct credit price separated.
- Replit 2: explicit annually billed monthly equivalent only.
- Weaviate 1: contact-sales contract state, not zero price.

Only 42 have explicit currency. All 114 remain unverified and non-comparable. The remaining 89 successful pricing sources are unresolved by this adapter, not failed crawls. This is a bounded recovery step, not a new universal price engine or evidence of 95% precision. There is no automatic promotion to the existing catalog and no change to runtime extraction or access controls. Source patterns and retained excerpts can change; independently validate each consequential fact and any future live parser changes. Synthetic regression tests contain no raw publisher export contents.
