# PR03 — Bounded recent changelog capture and source Item integrity

**Status:** implementation branch, not deployed. Build on PR02 (per-event extraction) and merged PR01 (safe scopes). Continue to use **only three spiders**: `official_documentation`, `official_pricing`, `official_changelogs`.

## What changes, precisely

- Changelogs are analyzed for **all recognizable event candidates**, but only a bounded **80-event recent window** is retained in the source Item.
- A recognized timeline may be **newest-first** (retain the first 80) or **oldest-first** (retain the last 80 and reverse into newest-first for review). If dates/versions are mixed, the order is **unknown**: never infer the latest.
- **Explicit dates** determine day-based ordering only when every recognized event is explicitly dated. If dates are absent but all releases contain comparable numeric versions, the system can compare *version identities*, without making any claim about published dates. Mixed dated and undated events must not be ranked by numeric version alone.
- `release_window_complete` is strictly a **fetched-page recognized-entry** completeness indicator. It never proves all vendor posts were published today, that upstream pages are up to date, or that an entire documentation tree was covered.
- `release_events_truncated` / `release_historical_event_count_omitted` count omitted **older historical entries**. They must not, on their own, suppress comparisons when the recent window is demonstrably complete.
- `release_recent_body_loss_count` records incomplete evidence among the **selected recent window**; `release_historical_body_loss_count` separately records omissions in the archived backlog. Recent body loss remains non-comparable.
- Changelog source records retain a full extracted-page content SHA-256 and bounded text/section samples; `historical_text_truncated` is explicit.
- Source Items target **650 KB serialized**, well under Zyte's documented ~1 MB per-item rejection threshold. If even progressive compaction cannot satisfy the byte budget, fail closed with `partial_capture` / `scrapy_item_budget_exceeded` and no unqualified recent evidence.
- The existing one-Item-per-source invariant and approved_for_advisor=false gate remain intact; no production catalog or DB writes.

### New source-level fields

| Field | Meaning |
| --- | --- |
| `release_events_schema=1.1` | Backward-compatible event schema with new ordering/window semantics |
| `release_order_direction` | newest_first / oldest_first / single / equal_values / mixed / unknown |
| `release_order_basis` | explicit_publication_dates / numeric_versions_no_date_inference / mixed_or_undated_entries |
| `release_recent_event_count` | Number of retained recent event candidates |
| `release_event_count` | Total recognized candidates scanned on this page |
| `release_historical_event_count_omitted` | Older records omitted from the Item |
| `release_window_complete` | Structural completeness of recognized recent entries, **not authoritative vendor freshness** |
| `release_window_coverage_status` | Why the window was considered structurally usable or uncertain |
| `release_recent_body_loss_count` | Number of selected entries with incomplete body capture |
| `release_historical_body_loss_count` | Body clipping anywhere in history |
| `text_total_characters` / `text_retained_characters` | Historical page size vs included excerpt size |
| `historical_text_truncated` | Historical content omitted from bounded Item |
| `serialized_item_bytes` | Approximate JSON-serialized source Item size |
| `markdown_alternate_attempted/result` | Whether the allowlisted alternate was checked, and outcome |

## Claude Code Markdown strategy

**Exactly one pinned source:** `claude_code_changelog`.
- Manifest source URL remains `https://code.claude.com/docs/en/changelog`.
- When its HTML cannot demonstrate a usable recent window and is long/undecodable as release cards, the same **official publisher host** may be requested at `https://code.claude.com/docs/en/changelog.md`.
- This fallback uses a normal Scrapy request under robots.txt, no cross-site redirect, no JS rendering or authentication bypass. If it fails or returns non-Markdown content, keep the original diagnostic source Item and record the failure.
- Markdown parser recognizes version-heading patterns such as `## 2.1.316`. It retains latest **numeric versions on the fetched page** but does not invent a date from the version or crawler timestamp.
- Such version-only sources remain `needs_review:release_events_missing_publication_dates`. After two comparable official Markdown observations, the offline review queue can flag a `version_first_seen_date_unknown` or `version_notes_edited_date_unknown`. These are **review observations**, not claims that a new release was published today.
- Generic Markdown discovery, GitHub Releases API, and arbitrary provider alternates are **not** part of PR03.

## Completeness and comparison rules

Two v1.1 release snapshots can be compared when the same source is healthy, its recent event window is structurally complete, no recent event bodies are clipped, the source identity is stable, and the event schema matches. Historical sections/text missing because of the bounded retention do not automatically disqualify this scoped comparison. No missing historical event is treated as a deprecation or release deletion.

A migration from v1.0 to v1.1 creates a new baseline; it cannot become an automatic "new release" alert.

For the Claude Code Markdown special case, undated version changes may enter a **human review queue** only if the exact approved alternate URL, source ID, complete numeric version order, parser schema, error code and access conditions agree on both snapshots. The date stays null and approval stays false. Cached, blocked and malformed responses are ineligible.

## Scope and deployment: explicit checklist

1. **Do not merge/deploy automatically.** PR03 is stacked on PR02; PR01 has merged to main. Ensure PR02 changes are reviewed and integrated first, then rebase PR03 on the integrated code.
2. Verify CI: `pytest`, three registered spiders only, Scrapy 2.18 startup and Zyte-compatible egg packaging.
3. Check Zyte **Code & Deploys** matches the merged commit. Green GitHub CI alone does not mean the running spider contains this code.
4. Run explicitly scoped canaries in the existing changelog spider, starting with:
   - `source_ids=claude_code_changelog,cohort=candidate`
   - `source_ids=chatgpt_codex_changelog,cohort=candidate`
   - `source_ids=google_antigravity_changelog,cohort=candidate`
   - `source_ids=supabase_changelog,cohort=candidate`
5. For each Item compare `status`, `error`, `release_event_count`, `release_recent_event_count`, `release_window_complete`, `release_order_basis`, `latest_release_date_candidate`, `text_total_characters`, `historical_text_truncated`, `serialized_item_bytes`, plus full coverage stats and robots requests.
6. Preserve source IDs and run/manifest fingerprints; compare only two matching deployments and scopes. Initial run is a baseline, not a release announcement.
7. Do not promote a source to unattended monitoring, turn on unrestricted `cohort=all`, or automatically publish fact candidates until real Zyte evidence passes review.

## Important remaining limitations

- This patch cannot prove every current official update is present on a page. Real provider DOMs vary, so **live source-specific canary verification is mandatory**.
- A large single release body that exceeds its parsing budget is explicitly marked partial, not silently accepted.
- Historical page flattening still processes the returned HTML. The memory footprint must be measured on the same one-unit Zyte environment after deployment.
- Claude Code's Markdown versions normally have no explicit publication dates; it is not valid to manufacture them.
- Other changelogs whose HTML uses custom DOM structures may need narrow, tested adapters or their own pinned official-text format under the **same three spiders**.
- This milestone does not fix pricing-table completeness (next PR04), canonical URL migrations, robots policy review, or source-level product scope errors.

## Official technical constraints

- Zyte Items HTTP API and 1 MB rejection behavior: https://docs.zyte.com/scrapy-cloud/usage/reference/http/items.html
- Original source HTML: https://code.claude.com/docs/en/changelog
- Official same-host Markdown alternative: https://code.claude.com/docs/en/changelog.md
- Previous release evidence design: [RELEASE_EVENTS_V1.md](RELEASE_EVENTS_V1.md)
- Overall roadmap: [AGENTFUSE_CRAWLERS_TRUST_AND_ACCURACY_IMPLEMENTATION_PLAN_2026-10-31.md](AGENTFUSE_CRAWLERS_TRUST_AND_ACCURACY_IMPLEMENTATION_PLAN_2026-10-31.md)
