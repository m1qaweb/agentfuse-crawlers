# G0 — Ranked publisher review queue and supplemental canary shortlist (NO-GO)

**Scope:** An offline prioritization/handoff, **not** a Zyte run, source policy decision, deployed package verification, pricing accuracy test, or production-data approval.

This phase makes the existing P23A 460-source accounting actionable for the first **human source reviews**. It does not create any new access registry entries or bulk plans, and it does not add a crawler, permission system, adapter or network dependency.

## What changed

Run from a reviewed checkout:

```bash
python -m scripts.g0_priority_review_queue \
  --out-dir output/private/g0-priority-new
```

Or use **GitHub Actions → Prepare Zyte UI preflight (no crawl)**. Its artifact now includes `g0-priority/` with:

| File | Use |
|---|---|
| `g0_source_priority_summary_NO_GO.json` | Frozen manifest/preceding P23A digest, 460/300/12 counts, explicit zero jobs/permissions |
| `source_priorities_all460_NOT_APPROVED.csv` | Every original source, held/disposition information and provisional rank |
| `priority_top300_NOT_APPROVED.csv` | **Provisional 300** high-priority candidates for staged human review, **not** fetch targets |
| `supplemental_canary12_REVIEW_ONLY.csv` | 12 diverse human review candidates, no Zyte job specifications |
| `host_review_groups_top300_NOT_PERMISSIONS.csv` | Group first-party terms/robots research by hostname for efficiency; **decide each URL separately** |

### Ranking contract

1. **Do not alter the preregistered P20A 18-source / 36-round two-wave research selection.** It remains preserved, including unavailable sources. The G0 shortlist is labeled **supplemental operational** and never replaces a frozen subject.
2. Among the frozen 194 docs / 177 pricing / 89 changelog manifest, allocate provisional top-300 representation: **120 docs / 120 pricing / 60 changelogs**. Those are *planning quotas*, not rights or confidence thresholds.
3. Within each category, sort technical lifecycle eligibility, the explicitly curated supplemental shortlist, configured high-value AI-stack provider labels, then source ID. The top-300 output is a **transparent judgment-based review queue**. Real extractability, freshness, source terms, user value, actual parser precision and maintenance costs have not been measured for most URLs. Reprioritize after empirical diagnostics.
4. Report all existing P23A policy states and holds as-is. Do not infer permission from a priority, a robots URL suggestion, an HTTP-200, an open-source license, historical Zyte Items, or a human review form that has not been completed.
5. **No changes to deployed `agentfuse_crawlers/` code, manifest, robots protections, access registry or bulk-run registry.** No publisher GET, no Scrapy Cloud deployment/run/schedule, no production data export.

### Supplemental cross-category canary review candidates

These 12 exact configured source IDs cover 12 different hostname origins. This is a **human review workload**; none is approved to fetch merely by inclusion.

| Category | Source IDs |
|---|---|
| Documentation (4) | `github_copilot_docs`, `openai_api_docs`, `vercel_ai_gateway_docs`, `deepseek_docs` |
| Pricing (4) | `anthropic_api_pricing`, `xai_pricing`, `cloudflare_workers_ai_pricing`, `fireworks_ai_pricing` |
| Changelog (4) | `cursor_changelog`, `supabase_changelog`, `mistral_changelog`, `groqcloud_changelog` |

The manifest currently contains **305 distinct hostnames** among 460 URLs, including 204 hosts with only one configured URL. Host grouping reduces duplicate research but does not create blanket host-wide permissions.

## Next operational gate — requires real evidence, not more generic code

1. Independently review the first several exact URLs, including owner/product, current robots path/user-agent rules, applicable terms, commercial automated access, HTML retention, redirect rights, rate/cadence restrictions and legal obligations. Mark denied/deferred honestly. **Do not upload filled review notes, correspondence, account credentials or original publisher HTML into public/Actions artifacts.**
2. Only after a genuinely substantiated, Git-reviewed exact-source `single_validation` access decision, verify the **actual** deployed Scrapy Cloud package, schedules/queue and a finite account-specific cost ceiling. Existing P23E1/E2 is read-only and does **not** verify deployed bytes or billing by itself.
3. The accountable human operator, not this G0 packet, may separately authorize a bounded **one-source/one-round** Zyte validation job. Archive Items, Requests, Logs and permitted original HTML; independently verify extraction against the publisher content. Repeat a second distinct round when appropriate.
4. Obtain evidence across documentation, pricing and changelogs; fix reproduced critical parser defects only. Then prepare **3–5-source** and **10–25-source** supervised pilot shards under independently reviewed exact bulk plans. Do not run 200–300 sources until the rights, cost, coverage and parser evidence warrant it.

**Stop condition:** If permissions or reliable extraction cannot be substantiated for a useful pilot subset, stop/shrink the HTML-crawl campaign. Evaluate official APIs/feeds and licensed sources rather than inventing approvals or building more generic infrastructure.

## Verification

```bash
python -m pytest -q tests/test_g0_priority_review_queue.py
python -m pytest -q
```

The new tests validate exact 460/300/12 counts, original frozen 18/36 preservation, distinct canary hosts, non-authorizing state, replay stability and new-only private output behavior. **Passing tests does not imply permission or real extraction accuracy.**
