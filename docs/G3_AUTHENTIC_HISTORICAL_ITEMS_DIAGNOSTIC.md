# G3 — Empirical review priorities from authentic November 4 Zyte Items (NO-GO)

**Date:** 15 November 2026 · **Historical evidence date:** 4 November 2026.

**Scope:** offline forensic ranking of the three **authentic**, SHA-pinned November 4 Zyte Items exports; no publisher HTML or raw Items published to GitHub; no live requests or Job launches.

## Why this is a meaningful improvement over G0

G0's preliminary 300-source queue ranked publisher labels and category quotas. It did **not** use original real crawl evidence. G3 adds the missing empirical signal: what the previously deployed November 4 parser actually observed on each exact manifest source URL. It is a **review/diagnostic priority**, not a source-quality score, source permission, verified current publisher fact, or claim that 300 URLs can be crawled.

### Verified real historical baseline

The original files were retrieved from the user's private file Library **without adding the raw exports to this repo**. Their SHA-256 digests match the already-checked-in P21A baselines in \`scripts/audit_nov04_inventory.py\`.

| Category | Sources | \`captured\` | \`needs_review\` | \`partial_capture\` | \`rejected_redirect\` | \`http_error\` | \`source_quarantined\` |
|---|---:|---:|---:|---:|---:|---:|---:|
| Documentation | 194 | 51 | 124 | 0 | 14 | 4 | 1 |
| Pricing | 177 | **0** | 158 | 1 | 11 | 6 | 1 |
| Changelog | 89 | 14 | 69 | 1 | 3 | 1 | 1 |
| **Total** | **460** | **65** | **351** | **2** | **28** | **11** | **3** |

**Important diagnostic:** Of 177 pricing source Items, **159 returned HTTP 200 but none had \`status=captured\`**. This is serious historical evidence that a 200–300-source production-quality pricing crawl is not ready. Historical parser \`captured\` is **not** proof of accuracy or completeness either. The November 7 re-run generated only 460 held Items and **zero publisher GETs**, so it does not supersede the November 4 extraction diagnostic.

## New reproducible offline procedure

The script only runs when all three private original Items files exist, match their exact existing P21A SHA-256 pins, match the same pinned 460-ID manifest, and have the original Zyte job IDs and source ID/URL/category/provider bindings.

Expected private files:

\`\`\`text
/private/zyte-nov04-items/
  items_official_documentation_15.json
  items_official_pricing_11.json
  items_official_changelogs_16.json
\`\`\`

From the reviewed repository checkout:

\`\`\`bash
python -m scripts.g3_historical_items_triage \
  --input-dir /private/zyte-nov04-items \
  --out-dir output/private/g3-historical-nov04-NEW
\`\`\`

The output contains only:

| Output | Meaning |
|---|---|
| \`g3_historical_empirical_summary_NO_GO.json\` | Original input SHA pins, all 460 denominators, historical statuses, zero approvals/jobs |
| \`g3_historical_triage_all460_REVIEW_ONLY.csv\` | All exact source IDs ranked by **past parser observations** |
| \`g3_historical_top300_NOT_RUN_LIST.csv\` | Tentative top 300 historical review candidates; same 120 docs / 120 pricing / 60 changelog G0 **planning quotas** |
| \`g3_historical_shortlist24_NOT_AUTHORIZED.csv\` | Eight per category for independent **human access and parser-review**; **not** the preregistered 18-source study and **not** executable Zyte job specifications |

No scraped text, prices, model facts, title excerpts, original HTML, original full Items, API keys, raw job arguments or user private reviewer details are copied to the output. **Do not commit the original exports to GitHub, or send them to a CI workflow/artifact.** The generated sanitized CSVs are still review material, not public permission decisions.

The sorting is transparent: historically captured → partial capture → pricing with structurally recognized but *unverified* observations → other HTTP 200 parser holds → redirects → errors → quarantined. Within groups it favors explicit scoped documentation/release windows, AI-stack relevance and price-table observations; none of those imply accuracy. Known G1 website-terms cautions covering the affected Cursor, Vercel and Kiro same-site URL candidates are pushed back for additional human review, not erased or categorically declared prohibited.

### Example supplemental 24-source review set

This is **separate from** the original frozen 18-source, 36-round P20A research. It may be reranked after later evidence; it never substitutes a frozen source that failed or lacks permission.

| Category | Source IDs |
|---|---|
| Docs (8) | \`bria_ai_docs\`, \`cloudinary_ai_docs\`, \`confident_ai_deepeval_docs\`, \`databricks_mosaic_ai_docs\`, \`docker_ai_docs\`, \`elasticsearch_ai_search_docs\`, \`photoroom_api_docs\`, \`redis_vector_search_docs\` |
| Pricing (8) | \`anthropic_api_pricing\`, \`cloudflare_workers_ai_pricing\`, \`huggingface_pricing\`, \`openai_api_pricing\`, \`supabase_pricing\`, \`voyage_ai_pricing\`, \`xai_pricing\`, \`fireworks_ai_pricing\` |
| Changelog (8) | \`anthropic_api_changelog\`, \`cloudflare_workers_ai_changelog\`, \`assemblyai_changelog\`, \`databricks_mosaic_ai_changelog\`, \`google_cloud_ai_changelog\`, \`zilliz_cloud_changelog\`, \`railway_changelog\`, \`trigger_dev_changelog\` |

All eight pricing candidates are **\`needs_review\`**, not captured or comparable rates. The eight documentation sources were historically captured but many are single-page snapshots, not entire product documentation. Changelog candidates were captured but still need independent date/event identity and source-owned verification.

## Next real evidence gate

1. Operator runs [G2 manual Scrapy Cloud read-only workflow](G2_SCRAPY_CLOUD_READONLY_OPERATOR_PREFLIGHT.md) to establish project queue/schedule exposure; independently verifies current deployed package and account-specific budget.
2. Accountable human reviews current website terms/robots/usage/retention for **one exact source ID** (Issue [#85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85)); no inferred \`allowed_reviewed\` entry based on past HTTP 200 or G3 rank.
3. If and only if the publisher method is genuinely permitted, create the separately reviewed exact \`single_validation\` source policy record, deploy the reviewed package, and manually run **one bounded source/round**. Archive authentic Requests/Logs/Items and original HTML only as permitted.
4. Compare independently labeled original publisher truth against parser output. Fix only reproduced defects and rerun a distinct second round. A small supervised shard precedes any 200–300-URL diagnostic.

**Hard status:** \`NO_GO_HISTORICAL_EVIDENCE_ONLY\`. G3 authorizes **zero** Zyte jobs, source requests, source-access decisions, bulk plans or AgentFuse advisor facts. The November 7 held-only re-run and passing CI are not real extraction validation.

## Tests

\`\`\`bash
python -m pytest -q tests/test_g3_historical_items_triage.py
python -m pytest -q
\`\`\`

Tests use synthetic manifests/Items only; real raw historical Items are **never required by CI**. The actual run requires the owner's original private files.
