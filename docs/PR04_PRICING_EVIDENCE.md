# P04 — Pricing evidence integrity, rollout, and explicit unknowns

**Implementation branch:** `implementation/p04-pricing-evidence-completeness`, based on `main` independently of the ongoing changelog PRs. **Draft PR #10, not deployed.** The existing `official_pricing` spider is the *only* modified pricing spider. No new spiders, paid Zyte services, source URLs, credentials, schedules, or production writes.

## Problem statement

October 31 audit showed **three partially captured enormous pricing sources** (`gemini_api_pricing`, `aws_bedrock_pricing`, `oracle_oci_generative_ai_pricing`) because raw HTML extraction stopped at **40 tables**, along with **19 pricing URLs with no recognizable billing details**. A raw dollar value is not sufficient to recommend a model price: it may have a different currency, paid tier, date, region, token denomination, input/output mode or product scope.

This implementation **does not claim it has verified those providers in live Zyte yet**. It establishes deterministic extraction, completeness reporting and a human-review boundary.

## What's implemented

- Inventory **all recognized top-level HTML pricing tables** up to an explicit, bounded scan. Record `pricing_table_total`, `pricing_table_scanned`, `pricing_table_relevant`, `pricing_table_selected`, `pricing_table_omitted_relevant` and row/observation limits. A source with more relevant tables than can be represented is `partial_capture`, **not “captured”**.
- For the Oracle **general cloud price list**, conservatively inspect only tables whose nearby headings/caption explicitly indicate **Generative AI**. A Data Science Jobs table is not evidence for OCI Generative AI.
- Preserve table caption, nearby h2/h3/h4 headings, raw cell text, row/column indexes, expanded rowspan/colspan context, footnotes, the first-party source URL and each observation's SHA-256.
- Price states are explicit: `numeric_candidate`, `free`, `contact_sales`, `custom`, `not_available`, `usage_based`, `multiple_or_time_dependent`, `unparsed`, `not_displayed`. “Missing” does not mean “free.”
- Use `Decimal` (serialized as a string) and **never floating-point** for numeric rate candidates.
- A numeric rate becomes a `comparable_candidate` **only** with an explicit currency, billing unit, price dimension, model/service, region, tier/plan, a single amount, and no time-dependent, promotional, conditional or unresolved footnote context. It is **not approved for the advisor**, even if comparable.
- Distinguish inputs, outputs, cached inputs, cache writes, batch inputs/outputs, fast/ultrafast and long-context modes. Distinguish per-1M-tokens vs per-1M-characters, per-user-month, per-hour, per-GPU-hour, per-vCPU-hour, per-OCPU-hour and others.
- `$` alone does **not** imply USD; a page's query parameter, HTTP Date, crawl timestamp, country or provider ownership does **not** imply a billing currency, release date or effective date.
- `pricing_inventory_complete` means **the crawler scanned every recognized relevant HTML table on this fetched page within its configured bounds**. It does **not** mean all regions, prices, dynamic tabs, linked subpages, or today's vendor terms are covered.
- Bound the final Zyte JSON Item to **720 KB** target, well below Zyte's ~1 MB rejection limit. Raw-table evidence is a short excerpt, independent from whether the extracted rate observations are complete. If the Item cannot be safely represented, fail closed (`pricing_item_budget_exceeded`).
- The offline exporter writes `pricing_observations.jsonl` and `pricing_rate_changes.jsonl` alongside existing outputs. Rate-level change candidates compare stable identity across two healthy, scope-matched snapshots; a first sighting is **not** a published/effective-today price change.
- `approved_for_advisor=false` and `review_status=unverified` on all observations. No production recommendation, billing decision, or automated catalog publication is authorized.

## Schema (version 1.0, appended to existing source-summary Item)

### Source fields

`pricing_evidence_schema`, `pricing_table_total`, `pricing_table_scanned`, `pricing_table_relevant`, `pricing_table_selected`, `pricing_table_omitted_relevant`, `pricing_table_scan_truncated`, `pricing_table_rows_incomplete`, `pricing_observation_limit_reached`, `pricing_inventory_complete`, `pricing_coverage_status`, `pricing_product_scope_unresolved`, `pricing_price_cells_examined`, `pricing_rows_examined`, `pricing_observation_count`, `pricing_comparable_candidate_count`, `pricing_non_numeric_states`, `pricing_unparsed_candidate_count`, `pricing_observations`, `pricing_table_evidence`, `pricing_publisher_completeness_verified=false`.

`text_total_characters`, `text_retained_characters`, `pricing_raw_table_excerpt_truncated`, and `serialized_item_bytes` document bounded export size. A short raw table excerpt is never substituted for full relevant-table row accounting.

### Rate observation fields

- `observation_id`; `source_id` / `source_url`; `table_id` / `row_index` / `column_index`
- `model_or_service`, `price_dimension`, `currency`, `billing_unit`, `region`, `tier_or_plan`
- `price_state`, `raw_displayed_price`, `raw_amount_text`, `normalized_amount_decimal` (nullable)
- `normalization_blockers[]`, `comparable_candidate` (bool)
- `row_label`, `column_label`, `table_caption`, `heading_context`, `footnotes`
- `source_evidence_sha256`, `review_status=unverified`, `approved_for_advisor=false`

## Accuracy limitations and known scope gaps

1. **Gemini:** Current pricing tables can contain *multiple successive prices in a single paid-tier cell* (e.g., through a specified date and starting at a later date). P04 preserves this as ambiguous, **not** a current normalized rate. Future work can implement source-verified effective-date intervals.
2. **Bedrock:** Providers, throughput modes, AWS regions and batch/on-demand pricing may be mixed. Without explicit disambiguation, candidates remain unnormalized.
3. **OCI:** The manifest URL is a generic all-cloud price list. Scoped table selection reduces false attribution, but it does not prove that all Generative AI SKUs are on the page or that tables loaded dynamically were present in downloaded HTML.
4. **OpenAI / Anthropic / other vendors:** Not all APIs publish explicit region or tier in every table. These rates may remain `needs_review:pricing_rate_dimensions_unresolved` until the publisher's official scope has been separately verified.
5. **JavaScript-only tables, linked rate cards and dynamic tabs** are not rendered or followed in this PR. Mark unavailability; never invent missing prices.
6. The fixture suite uses short **synthetic, annotated** HTML patterns. Passing 200 synthetic price observations is **not proof of >=99% correctness across real vendors**. The plan's >=200 *human-annotated real rows* and >=99% accuracy threshold remain to be validated.
7. Missing, clipped, incompatible, changed-metadata or migrated pages must establish a new comparable baseline. Never claim model discontinuation or a price reduction merely because a row disappeared.

## Deployment-safe canary runbook

**Before deployment:** verify PR #10 passes `python -m pytest -q`, `scrapy list` (exactly three spiders), and the Zyte-compatible egg package build. Do not merge automatically; first review any changes from PR #9/#8 that also touch `extract.py`, `quality.py` or `official.py`.

**After code deploy matches a reviewed commit SHA**, use individually selected pricing sources (each job selects one URL, never an unbounded cohort):

```text
spider=official_pricing
cohort=proven
source_ids=gemini_api_pricing

spider=official_pricing
cohort=candidate
source_ids=aws_bedrock_pricing

spider=official_pricing
cohort=candidate
source_ids=oracle_oci_generative_ai_pricing

spider=official_pricing
cohort=proven
source_ids=openai_api_pricing
```

The provider may be blocked, redirected, JS-only, or may serve different content at deployment time. **Review HTTP requests, robots policy, canonical URL, content-type and actual price sections** before accepting a capture. Inspect `pricing_table_total/relevant/selected` and sampled table evidence manually.

Repeat successful canaries to establish comparable snapshots. To compare only **the same selected source** and job scope:

```bash
python -m scripts.compare_exports \
  --current output/pricing-current.jsonl \
  --previous output/pricing-previous.jsonl \
  --category pricing \
  --cohort proven \
  --source-ids gemini_api_pricing \
  --out-dir output/pricing-review
```

For candidate sources, use `--cohort candidate` with the matching ID. Review `status.csv`, `summary.json`, `pricing_observations.jsonl`, `pricing_rate_changes.jsonl` and `review_queue.jsonl`. Do not use a newly deployed parser's initial archive as evidence of a price update; it is a new baseline.

**GO for unattended *collection subset* only after repeated reviewed successes with a stable source scope and no hidden table loss. NO-GO for advisor publication** until an independent human-reviewed price ledger with validity/effective dates and supersession exists.

## References

- [Overall roadmap](AGENTFUSE_CRAWLERS_TRUST_AND_ACCURACY_IMPLEMENTATION_PLAN_2026-10-31.md)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [Oracle Cloud price list](https://www.oracle.com/cloud/price-list/)
- [Zyte Items API](https://docs.zyte.com/scrapy-cloud/usage/reference/http/items.html)

**Status of live infrastructure:** unchanged by this PR. This is a code/fixture implementation and deployment guide, not a production verification report.
