# P19A2 — Blind Full-Page Release Census and Owner/Date Gold Diagnostics

## Why source-wide gold, not candidate-only review?

P19A1 safely captures original HTML and yields review-only event candidates.
Its blind task list is derived from **recognized** events, so it cannot
measure recall: a release the parser completely missed has no task.

P19A2 creates a separate **full ORIGINAL HTML page census** for two
independent human reviewers. Neither reviewer receives inferred release
IDs, titles or publication dates. Both enumerate **every publisher release
visible on the frozen page**, including releases missed by the parser,
undated records, false positives, and cards lacking a unique owner link.

Then a strict offline scorer binds those labels to P19A1's same raw HTML
bytes, current parser fingerprint and original source manifest.
Disagreements, incomplete census, ambiguous ownership, publisher-policy
uncertainty, access-challenge pages, or >80 parser-truncated windows
cannot silently become a high accuracy statistic.

**Important:** A matching SHA-256 authenticates only local bytes. Even
independently agreeing reviewers do NOT cryptographically authenticate
the publisher, prove reviewer independence or authorize product facts,
a changelog news feed, new source policies, or AgentFuse recommendations.

## 1. Prerequisite: genuinely permitted P19A1 original HTML

The P19A1 original HTML capture and offline replay must exist first.
Use docs/P19A1_ORIGINAL_RELEASE_REPLAY_RUNBOOK.md. Never fabricate
capture times or use dashboard Items as if they were original publisher
HTML. Publisher terms, robots and retention rights must be independently
checked by the operator before any live capture.

Run P19A2 on 1–5 exact first-party changelog sources per frozen batch.
No P19A2 command accesses the network.

## 2. Privately freeze a stable group-level holdout split

Create a private random HMAC key (32–256 printable ASCII characters),
keep it OUT of Git, console output, shared screenshots and reviewer
packets. Freeze the key before adapting the parser or inspecting errors.

    export AGENTFUSE_RELEASE_GOLD_SPLIT_KEY='replace-with-your-own-long-random-private-key'

An exact provider_id from the static P16A product registry groups the
sources when available; otherwise their manifest provider label is
used as an *unverified* provisional group. A deterministic HMAC yields
development vs holdout by provider, NOT by individual release. The
split key is not saved to the packet (a one-way commitment is stored).
Do not intentionally choose different split keys until the holdout
looks better, and do not tune the parser on holdout groups.

## 3. Prepare completely blind full-page reviewer templates

    python -m scripts.score_release_gold \
      --prepare \
      --replay output/private/p19a1-kiro-replay-1/changelog_html_replay.json \
      --capture-manifest output/private/p19a1-kiro-round-1/frozen_release_snapshots.json \
      --snapshot-root output/private/p19a1-kiro-round-1 \
      --holdout-percent 25 \
      --out-dir output/private/p19a2-kiro-census-1

The three resulting private JSON files are:

- blind_source_census_packet.json — source ID, exact frozen URL,
  original SHA-256, P19A1 replay digest, page task ID, provisional
  provider group and frozen development/holdout partition.
- reviewer_a_template.json and reviewer_b_template.json — no predicted
  releases, dates, titles or model-generated reference values.

A source-wide task intentionally exists even when the parser extracted
ZERO releases. This is essential to discover false negatives.

## 4. Each real reviewer independently inventories the entire page

Each reviewer must inspect the exact hash-pinned HTML without viewing
the predicted P19A1 event list or another reviewer's labels. Record
a distinct genuine reviewer identifier, set
independent_blind_review_attested = true, and fill **every** source review.

For a completed source review:

- reviewed_full_visible_html = true
- event_list_complete = true only if the **full visible snapshot**
  was examined, not just the first cards or an 80-event window
- release_count_observed = len(events) + unattributed_release_count
- unattributed_release_count = number of visible releases that have no
  independently identifiable release-owned URL
- census_note = substantive description of what was checked
- reviewed_at_utc = timezone-aware timestamp after the HTML capture
- approved_for_advisor = false (always)

For every release in events, provide exactly these attributes:

| Field | Required meaning |
|---|---|
| owner_url | An exact first-party #heading-or-card-id on the original changelog page, or a unique linked path NESTED under its configured changelog URL. A shared index or unrelated docs guide is NOT an owner. |
| publisher_title | Human-transcribed real card title found in the exact release-owned DOM. |
| version | Full visible version, or null. |
| date_status | explicit_publication_day, explicitly_undated, or ambiguous. |
| published_at | YYYY-MM-DD only for explicit publication day; otherwise null. |
| date_evidence_text | Full publisher date text WITH YEAR in its card or supported time element; blank if undated/ambiguous. |
| publisher_evidence_quote | Unique 24–450-character excerpt appearing inside the release-owned card in the exact frozen HTML. |
| review_note | 24–1200-character rationale explaining publisher ownership, dates and uncertainty. |
| approved_for_advisor | false; no reviewing person can bypass this. |

An entire year/month page cannot be certified from a partial day marker.
HTTP Date, Last-Modified, a release deadline, version digits and crawl
timestamp are **not** publication dates. A unique visible quote does not
prove what the vendor intended; the reviewers must assess that meaning.

If a visible release lacks a unique official anchor, increment
unattributed_release_count instead of assigning the general changelog
index. That source will be HELD from numeric precision/recall until
unattributed identities can be genuinely resolved. If the page is huge
or impossible to inspect completely, mark event_list_complete = false.
Do NOT undercount the visible events to pass the benchmark.

Reviewers can use different supporting quotes; both must independently
show a valid original-card quote, but must agree on owned URL,
title, version and date status/day for comparison.

## 5. Score two genuinely completed independent reviews

    python -m scripts.score_release_gold \
      --score \
      --replay output/private/p19a1-kiro-replay-1/changelog_html_replay.json \
      --capture-manifest output/private/p19a1-kiro-round-1/frozen_release_snapshots.json \
      --snapshot-root output/private/p19a1-kiro-round-1 \
      --packet output/private/p19a2-kiro-census-1/blind_source_census_packet.json \
      --reviewer-a /private/reviewer_a_filled.json \
      --reviewer-b /private/reviewer_b_filled.json \
      --holdout-percent 25 \
      --out-dir output/private/p19a2-kiro-scored

A source can have **diagnostic only** counts when BOTH independent
inventories cover the full original page, both agree, release anchors
are unique and source-owned, the original HTML hash matches, and the
current parser returned a complete recognized event window.

- Owner TP = parser event whose release-owned URL exists in gold.
- Owner FP = parsed event with no gold release owner.
- Owner FN = human gold release owner the parser entirely missed.
- Owner precision = TP/(TP+FP), if denominator is not zero.
- Owner recall = TP/(TP+FN), if denominator is not zero.
- Date exact = matches on TP events with human explicit FULL-YEAR
  publication dates or human explicitly undated decisions. Ambiguous
  reference dates are **excluded**, not silently treated as correct.
- Title and version exact matches are separately counted.
- Reviewer disagreement, unattributable releases, truncated recent
  evidence, content-ownership conflicts or page-level incompleteness
  cause HOLD with **null** source metrics, not fake zero error rates.
- Unknown precision/recall denominators are null, not 0 or 100%.

Provider-group HMAC holdout is preserved. The packet can have only one
pilot provider, in which case one split may be empty and aggregate
benchmark claims remain blocked.

The sample diversity threshold requires at least 5 different provider
groups, 25 agreeing reference releases, at least 2 holdout providers
with 10 agreeing holdout releases, and nonempty development/holdout
samples. This is a **minimum engineering sampling gate**, not a guarantee
of statistical power or an approval to publish vendor facts.

Even if those minimums are met, the report fields stay:

- independently_authenticated_publisher_origin = false
- publisher_truth_verified = false
- generalizable_release_accuracy_established = false
- benchmark_or_adapter_rollout_authorized = false
- new_release_alerts = 0
- advisor_fact_approvals = 0
- deployment_authorized = false

Accuracy metrics produced by synthetic CI tests are NOT evidence of
live vendor recall or precision.

## 6. Pilot decision and next work

Human review requires real first-party captures, independently inspected
release cards and a provider-diverse holdout. These have NOT yet occurred
as part of P19A2 engineering. Begin with 5 permitted publisher sources
for structural/accuracy diagnosis; expand only if the owner/date gold
shows meaningful progress. Do not launch the 460-source Zyte full crawl
merely because synthetic CI is green.

Later P19B should introduce precisely scoped first-party provider page
family adapters only where the source-specific held-out results
demonstrate a measurable gain and date/owner identity remains robust.
Do not optimize to P19A2 holdout observations or claim that the crawler
knows release dates it cannot independently attribute.

The PR changes only off-package scripts, tests and documentation. The
existing 3 spiders, packaged Scrapy code, 460 original source IDs, Zyte
schedules, publisher lifecycle registry and AgentFuse/Supabase data
remain untouched.
