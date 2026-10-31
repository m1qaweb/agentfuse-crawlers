# PR09B — Release-owned identities, not shared guide links

**Source:** October 31, 2026 full Zyte changelog job 883514/1/8 (89/89 Items). All extracted announcements are still unverified. The user owns the private original exports.

## Confirmed live failure and implications

The old parser used the first same-host heading link as a release permalink/event identity. The user-supplied Items exposed identical event IDs for **distinct** publisher announcements that shared a guide link:

- OpenAI: separate Decisions API beta and general availability announcements pointed to the same Decisions guide.
- Anthropic: separate fast-mode deprecations across different versions pointed to one fast-mode documentation page.
- Google Gemini: several Computer Use announcements pointed to one feature guide.
- Google Antigravity: distinct v2.28.x version headlines pointed to one generic /releases index.

17/89 source summaries set release_event_identity_collision=true. Such collisions correctly prevented new-event alerts but also suppressed useful separate announcements.

## Fix

Only a verified structural release-owned location becomes the event permalink:
1. Heading ID with bounded safe characters, or a unique single-heading article/section ID.
2. Same-page anchored entry or first-party release path *nested below the current selected changelog path*, such as /changelog/release-123 and /releases/tag/vX.
3. Otherwise use the selected official changelog source URL; related links to docs, pricing, model guides, migration guides, or a generic listing cannot identify an announcement.

First-party related URLs remain in a **separate bounded list** of up to three supporting documentation references. Sensitive URL queries are stripped, cross-host/HTTP/credential links are rejected, and no fetched links are followed.

Where no release-owned link exists, the stable bounded full heading (up to 250 characters) + version defines identity. The publication date is *not* part of the fallback key, so corrections to a vendor's publication date are detected as edits rather than fabricated newly published events.

If a site reuses the same real release-owned ID or repeats an indistinguishable generic heading, the extractor still flags an identity collision and disallows a reliable latest-date claim. We do not invent dates or positional IDs.

## Critical backwards compatibility safeguard

The new source record includes release_identity_revision=release_owned_anchor_v2. Historic Zyte archives do not contain that field. Both the JSON/JSONL legacy comparator and the immutable archive evaluator treat **cross-revision snapshots as NEW BASELINES, not new vendor updates**. Do not turn on automatic new-release alerts during an identity-parser migration.

The release_events_schema remains 1.1 because the event wire-field schema is compatible; the semantic identity *revision* is tracked separately. Existing collectors still recognize the record.

## Acceptance and validation

- New synthetic fixtures reproduce the exact live failure **mechanism** for OpenAI, Anthropic, Gemini, and Antigravity; do not ship proprietary HTML or the provider's entire changelog.
- Existing tests continue to verify source-host safety, date precision, record bounds, duplicated genuine release anchors, edited old entries, and reordered events.
- Two CI Python versions and Zyte-compatible egg must pass.
- After PR review and manual publisher-policy confirmation, rerun one exact source ID per permitted target and evaluate release_event_identity_collision, release_recent_body_loss_count, release_dated_event_count, release_window_complete and latest_publication_verified.
- Compare first new-version snapshot to old exports only as a baseline. A **second new-version run** (distinct finished job ID) is required to validate actual event diffs under the same revision.
- Current separate tasks: vendor-native xAI/Render/Kiro/Codex publication dates; Claude Code's 4.5 MiB input/3 incomplete bodies and Markdown alternate; 13 capped histories; other publisher-specific regressions.

No work here authorizes monitoring or automated advisor facts, publishes release news, modifies Zyte jobs, changes publisher-policy overrides or touches production database tables.
