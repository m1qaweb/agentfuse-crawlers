# P19A1 — Manual Original Changelog HTML Capture and Frozen Release Replay

**State:** offline-first implementation following P12 release-owned identity v3
and the November 2 AgentFuse accuracy plan. **No publisher website requests,
Zyte jobs, source changes or real-world publisher accuracy evaluation were
performed in this PR.** All tests use invented HTML.

## Why this step matters

The baseline has 89 configured official changelog sources, 21 sources with
colliding event IDs, many clipped history windows, and **zero independently
verified latest publications**. Synthetic HTML does not prove any particular
vendor publishes release dates with a particular layout. Parsed Zyte Items
do not reconstruct the original publisher DOM.

P19A1 lets an operator obtain **original first-party HTML bytes** when
explicitly permitted, pin URL/hash/capture time, replay the unchanged
installed extractor, compare two frozen rounds, and prepare blind human
review tasks. It never publishes verified releases.

## 1. Read-only plan (zero network)

    python -m scripts.capture_release_html \
      --source-ids kiro_changelog,devin_changelog

Outputs exact pinned source URLs, robots locations and source registry/manifest
SHA-256 pins with no GET requests. Choose 1–5 exact source IDs per manual
batch. Blocked lifecycle sources stay blocked. Configured source URLs are
not, by themselves, publisher collection permissions.

## 2. Manual capture only after source-specific publisher-policy preflight

**P19A5 update:** A generic batch policy note is no longer sufficient for
real publisher capture. First preregister the P19A4 selection and complete
its per-source private policy ledger. See
P19A5_PUBLISHER_POLICY_PREFLIGHT.md for the exact prepare/validate
commands and rules. One blocked publisher holds the entire selected wave.

Before --capture, independently check publisher terms, robots, site
ownership and private retention rights. Never bypass authentication,
CAPTCHAs, paywalls, bot controls, denied access or unfriendly 403/429.

    python -m scripts.capture_release_html \
      --source-ids kiro_changelog \
      --capture --policy-reviewed \
      --policy-review-note "Each selected publisher's ownership, terms, robots, exact scope and private retention rights were individually reviewed." \
      --pilot-plan output/private/changelog-pilot-plan-1/pilot_selection_plan.json \
      --policy-ledger output/private/changelog-pilot-policy-filled-1/source_policy_review_filled.json \
      --out-dir output/private/changelog-pilot-captures-1/wave_01

Fetches only exact publisher robots.txt and the pinned HTTPS changelog URL.
Refuses redirects/retries, non-UTF-8 HTML, oversized 8MB responses, and
access-challenge HTML. Preserves existing Scrapy user agent and minimum
delay. It is opt-in and does not schedule any work.

The **private new-only output** contains unchanged raw HTML, checksums,
capture time, frozen_release_snapshots.json, and capture_audit.json with
response/robots metadata. A failure deletes incomplete new output.
Never commit publisher HTML or operator review notes. HTTP Last-Modified
and Date are not release publication timestamps.

The historical Nov 2 Zyte Items cannot reconstruct exact publisher HTML;
any newly captured HTML is a **new observation**, not a historical replay.

## 3. Offline immutable release replay

    python -m scripts.replay_release_snapshots \
      --replay \
      --manifest output/private/p19a1-kiro-round-1/frozen_release_snapshots.json \
      --snapshot-root output/private/p19a1-kiro-round-1 \
      --out-dir output/private/p19a1-kiro-replay-1

This is entirely offline. It records actual installed package fingerprint,
source/product-owner ambiguity, recognized release IDs, exact date
provenance, identity collisions, order and truncated recent windows.

Even when release_window_complete is true, the meaning is only a
complete **recognized window on the fetched page**. It is NOT a complete
vendor release catalog or a verified latest publication.

## 4. Independent human review tasks

    python -m scripts.replay_release_snapshots \
      --blind-review-tasks \
      --after output/private/p19a1-kiro-replay-1/changelog_html_replay.json \
      --out-dir output/private/p19a1-kiro-blind-review

The task packet is source-round-robin, max 15 per source and 120 total,
with bounded omissions. It creates blank reviewer A/B templates. No
crawler-predicted date or announcement title is supplied as expected
truth. Reviewers independently inspect preserved HTML, identify the
real publisher release owner, date/version/permalink and exact evidence
locator, including explicit negative/ambiguous cases.

These templates DO NOT certify independent gold. A separate P19A2 scorer
must verify dual-reviewer agreement on the same immutable snapshots, with
holdout examples, before precision/recall claims are appropriate.

## 5. Two manually captured source rounds

Only after publisher review, capture the same source ID later into a
separate private directory, replay again with the **same parser package**,
then compare:

    python -m scripts.replay_release_snapshots \
      --compare \
      --before output/private/p19a1-kiro-replay-1/changelog_html_replay.json \
      --after output/private/p19a1-kiro-replay-2/changelog_html_replay.json \
      --out-dir output/private/p19a1-kiro-two-round-review

The comparator refuses changed parser fingerprint, source URL, source
lifecycle, event identity revision and nonincreasing capture times.
Incomplete, colliding, body-clipped and blocked source windows are held
with no candidate changes. A first capture never produces alerts.

For comparable windows:
- Stable event ID with edited date or body -> existing event review
- First observed unique release ID -> reviewer candidate, NOT released today
- Date-scoped generic heading -> ambiguous identity/date review only
- Unknown or future dates -> date review, not inferred publication
- Reordered/unchanged events -> no candidate changes
- Disappearing events -> never automatic deletion/deprecation

No new-release alerts or advisor approvals are created.

## What still blocks P19 rollout

Real permitted original HTML captures, diverse independent owner/date
reference labels, verified source scope, and two comparable capture rounds.
Kiro/Devin/OpenAI/Codex/Claude Code source behavior must be assessed
on authentic bytes before claiming accuracy gains. Existing conservative
P12 parser rules are unchanged in this PR.

Later P19A2 should score independently reviewed gold and add carefully
selected official feed/page-family adapters where allowed. Neither a
successful synthetic replay nor a larger number of extracted events
justifies another 460-source Zyte crawl or automatic alert activation.

No publisher permission changes, Zyte scheduling, new spiders or
AgentFuse/Supabase production DB writes are included.
