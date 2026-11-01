# P12 — Release-owned identity and publication-date extraction v3

## Audit basis
The November 1 all-source Zyte run had repeated generic changelog
headings/ID collisions, Kiro date misses, Devin pages with zero structured
events, and mixed-order Gemini dates. P12 is a **conservative structural
improvement**; only real canaries can establish which live sources improved.

## Improvements
- Preserve \`<article><header><time>\` release metadata while stripping
  sitewide headers and navigation.
- Recognize whole, explicit \`<time>\` publication dates and standalone
  \`Published on: Oct 28, 2026\` datelines. No year imputation, edited-at
  timestamps, prose/deprecation dates or page-cache dates as publication.
- Recognize a bounded unique single-heading release-card's announcement link
  **only when nested under the configured first-party changelog URL**.
  Shared docs, cross-host URLs and query secrets are excluded.
- Distinct explicitly dated recurring unanchored headings ("Added", "Bug fixes",
  "What's Changed", "Highlights") use date-scoped review-only event IDs.
  Repeated headings on the **same day** or without an explicit year remain
  collisions. Source-visible dates are not publisher verification.
- Source-typed offline comparison and immutable-run evaluation **do not emit
  first-seen/new-release candidates** for date-scoped generic identities:
  a date correction could otherwise masquerade as a new event.
- A page with mixed date order may expose bounded individually dated
  source events for human review; \`latest_release_date_candidate\` remains
  unavailable. Latest publication is never auto-verified.
- HTML release identity revision changes from
  \`release_owned_anchor_v2\` to \`release_owner_date_scope_v3\`;
  official version-only Claude Code Markdown gets
  \`official_markdown_version_v1\`. This forces a fresh baseline, not a
  mass-new-release alert.
- Preserve 80-event window, full relevant event hashes, explicit truncation,
  conservative source lifecycle and \`approved_for_advisor=false\`.

## Merge order and CI
PR #25 restores P11B onto \`main\` after PR #24 was merged into the old
P11A feature branch. **Merge PR #25 first.** P12 targets its branch; after
#25 lands, retarget P12 to \`main\` and verify the full PR CI again.

Run 3.12/3.14 tests, package digest checks, synthetic replay and blocked
production quality gates. Green synthetic tests are not independently
reviewed publisher gold results.

## Manual validation
Only after the operator verifies policy, robots rules and deployed package
fingerprint, manually canary these exact IDs in validation mode:
\`openai_api_changelog\`, \`gemini_api_changelog\`, \`kiro_changelog\`,
\`devin_changelog\`, \`claude_code_changelog\`.

Each test job should use \`cohort=all\`, a single explicit \`source_ids\`
value and \`collection_mode=validation\` in Zyte Spider Arguments. Inspect
Items, Requests and Logs. Compare new source records against verified
original HTML dates/anchors and manually label real examples. Devin may
still require a source-specific profile: do not invent success.

No new spider, URL, crawl schedule, permissions, production DB write,
source promotion, or automatic advisor publication in P12.
