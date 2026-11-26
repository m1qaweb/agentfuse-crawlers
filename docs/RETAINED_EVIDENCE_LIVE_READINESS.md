# Phase 2D: retained evidence audit and first live extraction correction

## Actual evidence audit (November 26, 2026)

All twelve original Dashboard export SHA-256 values matched the historical
consolidation report. All 251 primary Item/Request pairs matched the exact
original array rows. Running the three merged retained recovery adapters against
the historical consolidated observations reproduced the three private reports and
all 408 candidate records byte-semantically (114 pricing, 88 documentation, 206
changelog). This is deterministic replay, not independent factual verification.
All candidates remain unapproved and unverified.

Successful HTTP 200 source breakdown:

| Category | Count | Material historical gaps |
| --- | ---: | --- |
| Pricing | 97 | 58 no structured rate evidence; 26 unresolved rate dimensions; 6 stale, 6 insufficient, 1 product scope |
| Documentation | 69 | 24 scope not established; 7 product marker only in body; 3 stale; 2 index-only; 2 canonical mismatch; 2 insufficient; 2 JS shell; 1 product ambiguity; 26 captured |
| Changelog | 34 | 15 no events; 10 missing dates; 6 ambiguous latest; 2 identity collisions; 1 captured |

The observed heading layouts supply a small, material live-parser correction:
49/49 retained Gemini CLI announcement headings and 49/51 retained Warp version
headings match the new recognizer and provide explicit valid dates. The other
two Warp headings are date-only and do not qualify. Eight retained DeepSeek
section headings match the labeled date-group recognizer. These figures describe
retained headings, not a new live crawl or a projected count of recovered releases.

## Live parser correction

Exact source/URL/heading-level matching is required. Gemini CLI announcements
keep their full titles and explicit dates, with no stable-channel assertion.
Warp versioned headings distinguish the displayed calendar date from the full
build-version string. DeepSeek labeled h2 dates apply only to direct h3 entries;
nested detail headings, prose, subsequent unrelated headings, and impossible
dates cannot inherit or establish a false day. The HTML release identity
revision changes from v5 to v6: older HTML snapshots require a fresh baseline,
not synthetic first-seen release alerts. Markdown extraction is unchanged.

The 16 standalone recognizer regressions passed locally on Python 3.13.
Integration tests exercise the existing extractor in normal repository CI.
The original HTML bodies are unavailable in the Dashboard exports; synthetic
DOM tests do not establish live-site coverage, precision or freshness.
No publisher rights or source eligibility changes, paid requests, product
ownership approvals, or new production facts are introduced.

## Decision before final campaign

Do not extend historical source-specific recovery indefinitely. The original
HTML structure, product mapping, conditional pricing semantics and publisher
review remain necessary for additional material live pricing/documentation
changes. A 95% independently adjudicated precision target is not yet measured.
Use these reports to prioritize the final acquisition scope, canonical and hold
review, and targeted live canary assessment in the existing deployment workflow.
Do not run an unrestricted 460-source crawl or promote candidates to AgentFuse
production.
