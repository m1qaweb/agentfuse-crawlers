# Perplexity non-tariff price evidence (2026-11-28)

Historical Zyte job 883514/3/18, original private Items export SHA-256
`6a5a2cdd006d2539aa77ccc4db903f4b79d007d4b348a393fb3bcef4271ebc97`.
The retained Perplexity record contains 51 price observations and ten
unclipped raw table excerpts. Cell-by-cell replay against those retained
rows identified 19 observations that are not independent tariffs: six
explanatory description cells, four worked request-cost cells, and nine
worked component/total cost cells. The remaining 32 observations are
still unverified; this count is not a price-accuracy or live-coverage
result.

The live parser now uses exact source ID/URL, observed section and header
layout, explicit row labels for examples, and unmerged complete rows to
exclude these non-tariff cells from the independent rate inventory. Raw
table excerpts remain subject to the existing bounded retention policy;
per-table reason counts and the source-level exclusion count are explicit.
Unknown layouts fall back to the generic parser. No currency, unit,
region, tariff normalization, or advisor approval is inferred. The
classification is row-local for the original-byte row-window replay;
only Perplexity receives a new parser baseline. Both existing pricing
window consumers use the exact source-specific revision.

The standalone classification was replayed on all 51 retained
observations; original HTML is unavailable, so live DOM qualification
and actual post-fix extraction remain unverified. Integrated synthetic
regressions must pass normal CI. No publisher requests, Zyte jobs, access
reviews, authorizations, manifests, deployment or publication changes.
