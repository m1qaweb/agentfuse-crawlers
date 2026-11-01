# P11B — Bounded multi-job pricing-table windows (manual validation only)

## Rationale

November 1 complete Zyte inventory:
- Gemini API: 89 relevant HTML tables, 600 potential observations, 300 retained.
- AWS Bedrock: 100 relevant tables, 398 potential observations, 300 retained.

Increasing per-Zyte-Item limits would risk silent loss, unreliable archival and
false pricing completeness. P11B allows separate table windows, each source
summary remaining a single Item *per job*, and a strict **offline-only** union.

## Design and guarantees

- The spider args below select the same pinned source URL and extract a
  0-based offset and count over **relevant pricing tables**, not raw HTML tables.
- Unbounded/default runs still select the first 64 relevant tables and keep
  the original explicit 300-observation and 720KB source-Item ceilings.
- A selected window contains explicit
  \`pricing_table_window_start\`, \`pricing_table_window_limit\`, \`end\`,
  selected original HTML \`table_index\` values, and card ownership.
- Only offset=0 captures tableless pricing cards. Later windows do not
  repeat cards. This prevents duplicated price observations in replay.
- Every window with omitted relevant tables remains \`partial_capture\`.
  It cannot be compared or advertised as complete.
- \`pricing_parser_revision=evidence_quote_v3_windows\` resets old baseline.
- \`scripts.assemble_pricing_windows\` combines source-linked Items **offline**
  and only when source URL, manifest, registry, deployed package fingerprint,
  full-page extracted text SHA-256, parser revision, table counts, table
  identities, ranges and observation cardinality all agree.
- Any gap, overlap, wrong job ID, truncated budget, content change, duplicated
  rate ID or irrelevant source/URL fails explicitly.
- Its result is **not** a normal source Item: it lacks \`status\` and
  \`pricing_inventory_complete\`, and reports
  \`rate_comparison_eligible=false\` and \`approved_for_advisor=false\`.
- This proves only the union of recognized relevant static HTML tables on
  that one page, not global publisher completeness, dynamic tabs, geography,
  plan variants, terms, or price accuracy.

## Example manual run (Zyte spider arguments, not Scrapy Settings)

Start with a publisher-access-reviewed source. One job per range and source:

    official_pricing
    cohort=all
    source_ids=gemini_api_pricing
    collection_mode=validation
    pricing_table_offset=0
    pricing_table_limit=16

Then repeat only \`pricing_table_offset\` with 16, 32, 48, 64, 80.
For AWS Bedrock 100 relevant tables, continue with 96 as the last offset.
Make no extra full-inventory jobs. Keep each job's separate job ID and full
Items, Requests, Logs JSON export. If a selected window has >=300 detected
observations, the Item remains explicitly partial and MUST be rerun with a
smaller table limit (as low as 1), not marked complete.

If publisher pages change between jobs (hash or package revision mismatch),
do NOT merge; restart the bounded capture from a stable source revision.

After successful jobs, offline:

    python -m scripts.assemble_pricing_windows \
      --items windows_0.json windows_16.json windows_32.json \
              windows_48.json windows_64.json windows_80.json \
      --out-dir output/review-gemini

Inspect \`assembly_manifest.json\` and
\`gemini_api_pricing_review_inventory.json\`. Only human reviewers can
evaluate price meanings. No automatic publishing/approval.

## Tests

- Default 64-table budget and strict 300-observation budget preserved.
- 89-table synthetic union over six separate windows with full source ID
  provenance and unique observation keys.
- Mid-window omissions, overlap, duplicated Zyte jobs, changed content,
  wrong table indices, oversized windows, conflicting parser revisions
  and budget caps fail closed.
- Exactly one emitted source summary per job; three spiders preserved.
- Existing P08 gold replay and production approval gates continue to block
  publication absent independent real evidence.

No Zyte schedule, publisher policy, v0 quarantine, 460-source manifest,
Supabase/AgentFuse production DB, or advisor approval is changed.
