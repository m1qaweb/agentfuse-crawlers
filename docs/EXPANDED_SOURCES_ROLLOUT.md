# October 30, 2026 — expanded AI source rollout

## Decision and source provenance

The owner supplied `agentfuse_verified_100plus_ai_sources_2026-10-30(2).json` with **378 distinct HTTPS URLs and 165 provider names**. It was appended (without replacing the original 82 IDs/URLs) into the existing three-spider manifest.

| Cohort | Documentation | Pricing | Changelog | Total |
| --- | ---: | ---: | ---: | ---: |
| Original 82 | 29 | 27 | 26 | 82 |
| Added 378 | 165 | 150 | 63 | 378 |
| **Total configured** | **194** | **177** | **89** | **460** |
| Previously observed on Zyte (`proven`) | 3 | 3 | 3 | **9** |
| **Candidate for live validation** | **191** | **174** | **86** | **451** |

A user-supplied filename containing **"verified" means only the user labeled the list that way**. We verified JSON shape, exact ID/URL uniqueness, HTTPS and manifest compatibility. We have **not** established that the 378 endpoints are operational or permitted by robots policy, nor that they contain complete and current documentation. All new entries are `candidate`. Existing `proven_sources.json` is unchanged. No production database/catalog/advisor changes.

## What stays the same

Exactly **three** Scrapy Cloud spider names remain: `official_documentation`, `official_pricing`, `official_changelogs`. Every spider handles only its matching category. The configured owner's jobs—daily documentation, daily changelogs, Monday pricing—can continue using `cohort=proven` without expanding their loads.

A spider fetches only its **configured URL list**, not all linked documentation subpages. `captured` is complete-looking extraction evidence, *not fact verification*. Failed/blocked/JS pages must remain visible as errors; never bypass robots, logins or site restrictions.

## Validation in controlled batches (one cloud unit)

Generate an offline operational plan:

```bash
python -m scripts.plan_validation --cohort candidate --batch-size 15 \
  --out-dir output/validation-plan
```

Outputs `validation_batches.json` (exact source IDs per batch), `validation_batches.csv` (copyable Zyte args), and `static_review_flags.csv` (non-network hints). For 451 candidates, batch size 15 creates **31 jobs** spread over the three existing spiders. Jobs should run **sequentially**, never on top of each other with a single cloud unit.

In Zyte **Run Spider** manually, select the spider listed in the CSV. Set:

```text
cohort=candidate
offset=0
limit=15
```

After its items have been reviewed, run the next batch for the **same spider** with `offset=15`, then `offset=30`, until that category is complete. Repeat for the other two spiders. Offset is applied *after* category and proven/candidate filtering, so the batches are stable as long as the manifest and proven-source registry do not change. Do not promote candidates mid-validation; that would change candidate offsets. To rerun a completed batch, keep the exact same manifest commit and args.

For review output, match the **same** job arguments:

```bash
python -m scripts.compare_exports \
  --current output/batch-015/items.json \
  --category documentation --cohort candidate --offset 15 --limit 15 \
  --out-dir output/batch-015/review
```

Inspect `agentfuse/coverage/expected_sources`, `reported_sources`, `captured_sources`, `missing_sources`, `uncaptured_sources`, `agentfuse/status/*`, `redirect_chain`, `http_status`, `final_url`, `error`, `word_count`, `visible_latest_date_candidate`, and `sections_truncated` / `tables_truncated` flags.

Source approval requires confirming: publisher owns the page; access policy allows collection; URL points at the correct product/topic; expected information is actually present; date/tier/units are explicit; and a later crawl is stable. A successful HTTP response alone is insufficient.

## Known static review flags

- `pinecone_changelog` (`/release-notes/2026`) and `warp_changelog` (`/changelog/2026/`) are **year-pinned**. They may need URL maintenance when a later year starts; the crawler does not invent a future URL.
- `inception_labs_changelog`, `typesafe_ai_changelog`, and `prime_intellect_changelog` use broad blog pages rather than dedicated release-note feeds. Review their content relevance.
- GitHub `/releases` URLs are HTML list pages. Our existing changelog HTML parser may require live confirmation of dated sections; it does not automatically query the GitHub REST API.
- General documentation landing pages are *not comprehensive docs crawls*. Do not infer complete feature coverage from a landing page alone.

These flags are **static suspicions, not observed failures**. Every source is independently assessed by its Zyte Items output.

## Publication and operational safety

Keep all new sources in `candidate` until reviewed and explicitly promoted via a separate provenance-backed source-registry change. Do not silently set the daily/weekly jobs to `cohort=all` and do not mark new data approved for AgentFuse. Review outputs remain `approved_for_advisor=false`.

A future switch to `cohort=all` means **194 docs + 89 changelogs every day, and 177 pricing sources every Monday**. Watch Zyte unit runtime, robots denials, site timeouts and crawl health before increasing coverage. One cloud unit can queue jobs sequentially, but "unlimited" requests do not mean unlimited concurrent execution.

The repo does not interact with AgentFuse's production Supabase database and does not use paid Zyte API/browser-rendering features.
