# Release-event evidence, iteration 1 (stacked PR 02)

This upgrade lives **inside the existing official_changelogs spider**. It creates
per-release *candidates*, not authoritative product announcements.

## Source Item fields

The spider still emits exactly **one** source-summary Item per selected source
and keeps all previous v2.1 fields for offline compatibility. Changelog source
Items additionally include:

- release_events_schema: currently "1.0"
- release_events[]: event_id, source_id, title, version, published_at (nullable),
  date provenance, explicit date text, first-party permalink, evidence locator,
  body_sha256, bounded excerpt and excerpt truncation, review_status=unverified,
  approved_for_advisor=false.
- release_event_count, release_dated_event_count, release_events_truncated,
  release_event_identity_collision.
- latest_release_date_candidate: may be null; it is **not** a confirmed latest
  vendor release date.
- latest_release_date_status and release_window_coverage_status.
- release_window_complete=false (until a later explicit recent-window audit).

**Do not use the legacy visible_latest_date_candidate as a release-freshness
signal.** Its old heading-based heuristic remains in v2.1 for compatibility
with historical exports, but release-event candidates have their own dates.

## Date handling

Recognize, with uncertainty:

- Explicit official date headings: 2026-10-30, October 30, 2026;
- A standalone dateline before a title, such as Oct 28, 2026;
- A date within a first-party time element's datetime attribute, unless it
  explicitly describes a modification timestamp;
- Month/year grouping followed by matching month/day entries, e.g. October,
  2026 followed by Oct 30. It may group multiple releases on the same date.

Never infer a missing year from fetch time or the current calendar. A future
deadline embedded in a description is never a publication date. A version-only
entry can remain an undated candidate. Any ambiguity in the event inventory
disables the supposed latest-date claim.

Every date is **still unverified** until reviewed against original publisher
evidence. Dates and headings are candidates, not a fact ledger.

## Comparisons and failure policy

- First versioned crawl is a **historical baseline**.
- Subsequent healthy comparable snapshots produce release_event_first_seen or
  release_event_edited when stable event IDs, content hashes or explicit date
  metadata change.
- First seen != published today; an older announcement can be discovered later.
- Reordered cards and disappearing archive entries do not create announcements,
  deprecations or removals.
- Changed sections from the old heading parser are suppressed for modern typed
  changelog sources to prevent duplicate, contradictory alerts.
- A page with missing or ambiguous dates, body capture limits, event ID
  collisions, or absent recognizable event markers remains needs_review or
  partial_capture, and must not feed an automatic advisor fact.
- Every review candidate is source-linked, excerpt-limited and always has
  approved_for_advisor=false.

## Test and rollout (after PR 01 compatibility is resolved)

1. Confirm PR 01's schedule-safe guard has been reviewed. The current
   owner-configured cohort=all scheduled jobs, if still present, must be
   explicitly amended to avoid a planned fail-closed run.
2. Build, test, and verify exactly three spiders with GitHub CI.
3. Confirm the latest commit deployed successfully to the Zyte Scrapy Cloud
   project. GitHub green CI is not a Zyte deployment certificate.
4. Run the proven changelog source IDs, then targeted IDs including
   cursor_changelog, kiro_changelog, xai_changelog and render_changelog.
5. Examine actual release_events[], published_at provenance, Item size,
   text_truncated, release_event_count, change queue and robots outcomes.
6. Replay the owner's previously archived October 31 Items and inspect
   before/after structural findings with appropriately paired job scope.
7. Do not turn on autonomous all-source monitoring or publish candidate
   announcements as product facts until sources are individually approved.

## Unimplemented work / known limits

- Huge Claude Code/Codex/Antigravity changelogs still require a bounded
  recent-window and/or official Markdown strategy (planned PR 03).
- GitHub Releases HTML may lack dates in conventional markup. A pinned,
  official GitHub Releases API adapter is a separate follow-up.
- Specific live provider DOMs may differ from our synthetic golden fixtures.
  Passing CI alone does **not** establish real-world recall or date precision.
- Source policies, canonical migrations, product-scope corrections, and pricing
  intelligence are separate planned milestones.
- The current parser caps per-source event candidates and individual event body
  size; it never claims full historical or newest-window coverage.
