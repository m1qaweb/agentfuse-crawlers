# Phase 2C: bounded retained changelog recovery

This is a historical, private, review-only evidence adapter. It does not change the live crawler, grant source access, establish publisher rights, verify product mapping, or enable alerts. Reuses Phase 1 SHA-bound consolidation and its create-only output writer.

    python -m scripts.recover_retained_changelogs --input-dir /private/exports --out-dir /private/new-changelog-recovery

Use the twelve canonical exports from Phase 1. Outputs: report.json, inventory.json (per-source coverage), and primary_observations.json (recovered review observations). Keep private, outside the public checkout. Preserve originals.

Local replay verified all 34 successful changelog Items against the original job /1/41 Items and Requests with exact SHA-256 hashes; Logs hash also matched. Audited 698 retained event records (316 with day-date candidates), including 2 source arrays with identity collisions. The bounded seven-source adapter recovered 206 observations, checked against 244 exact text locators and 53 original event record fingerprints:

- Gemini CLI 34 version announcement headings (not proof of stable release).
- DeepSeek 23 explicit date/heading pairs (no date inheritance for nested headings).
- Warp 8 release headings (not build timestamp inference).
- PostHog 65 and Sentry 10 dated cards (publisher-wide scope, not blanket attribution to AI Observability or Seer).
- Hyper3D 38 month-scoped Rodin documentation notices (no fabricated day).
- Prime Intellect 28 announcement index entries (not release proof; article bodies not observed).

53 observations match a unique previously undated event title; 87 have no exact existing event title match, which is not proof they are distinct new events. 66 month-only or blog-index observations do not participate in release identity linking. Duplicate or ambiguous title/date pairs are not silently merged, and conflicting old dates are not overwritten. The original release array remains unchanged.

28 local synthetic tests passed. Twenty-seven sources yielded no new observations under these selected layouts; some already have retained events, and others need further evidence. No verified distinct-release total, independently verified facts, production alerts, or complete recent-window assertion is inferred. This is not a general live parser release. Phase 2D should now assess accuracy and overlap, prioritize material gaps, and decide what to improve in the live extraction path before the next acquisition campaign.
