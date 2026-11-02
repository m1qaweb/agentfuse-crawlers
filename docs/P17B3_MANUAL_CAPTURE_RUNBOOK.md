# P17B3 — Private, Operator-Authorized Original HTML Capture

**State:** Draft implementation on top of P17B1 + P17B2 recovery.
All unit tests use synthetic responses and injected fake HTTP transports.
**No actual publisher requests or Zyte jobs were triggered by this PR.**

## Why this is the right next implementation

PR #36 merged into \`main\` on Nov 2 at **15:57:49 UTC**. PR #37
was merged into PR #36's *feature branch* at **15:58:04 UTC**.
As a result, both appeared merged, but the P17B2 replay scripts,
gold scoring, tests and runbook were **not in \`main\`**.

This PR first restores those four P17B2 files **onto the current
\`main\` lineage**, and then enables the missing input for a real
accuracy experiment: **permitted original HTML bytes**, not the Zyte
Dashboard Items summaries.

The original Nov 2 Items cannot reconstruct the raw publisher DOM,
its exact table-section legend, or the revision-specific Fireworks rate
order. They cannot prove whether the P17B1 adapter is accurate.

## Operator default: zero network

From the repo root, list exact proposed source IDs:

\`\`\`bash
python -m scripts.capture_pricing_html \
  --source-ids fireworks_ai_pricing,together_ai_pricing,gemini_api_pricing
\`\`\`

The default only reports source URLs, robots locations, lifecycle
eligibility and current source registry/manifest hashes. It **does not
make requests**.

## Optional: manual real capture of ONE original public page

**Before** using --capture, review the publisher's robots policy,
terms of service and permission to retain raw pages. Do not attempt to
bypass any authentication, bot controls, challenge, paywall or denial.

\`\`\`bash
python -m scripts.capture_pricing_html \
  --source-ids fireworks_ai_pricing \
  --capture --policy-reviewed \
  --policy-review-note "Reviewed publisher terms and privacy rules; this manual public-page capture and private research retention are permitted." \
  --out-dir output/private/p17b3-fireworks-first
\`\`\`

The code, NOT this PR's execution, will:
- Request **only** the exact original source URL from the immutable
  460-source manifest. No arbitrary URLs, no automatic browser
  rendering, no source-ID substitution and no URL migration.
- Fetch same-host \`/robots.txt\` first. If robots is unavailable,
  ambiguous, disallows the bot, is too large, redirects, or requires
  unusual crawl-delay, **abort without fetching the source page**.
- Use the same user agent, delay (at least 3 s), concurrency safety,
  and 8 MB download cap as the existing Scrapy settings. No cookies,
  credentials, automatic redirects, retries, parsing challenges or
  bypassing publisher access controls.
- Refuse any HTML except original UTF-8 \`text/html\` HTTP 200
  with exactly matched request and final URL.
- Store raw **unchanged publisher response bytes**, a SHA-256 hash,
  capture timestamp, the robots hash/permission check and HTTP
  provenance privately at file permissions 0600 and folder 0700.
- Create P17B2-compatible \`frozen_snapshots.json\` and a separate
  \`capture_audit.json\`. The operator's terms-review note is an
  attestation, **not independently verified source policy approval**.
- Refuse existing output folders. If any URL in the selected 1–5
  source batch fails, remove the incomplete newly created folder.
  A failed run cannot accidentally look like a complete benchmark.

**Important:** This local network capture is *opt-in*. It uses
standard-library HTTPS instead of Zyte's browser fetch. If a publisher
rejects the research bot or delivers only a JavaScript shell, **do not
bypass it or infer a price**. Mark that source unsupported by this
method and use the P16B method-evaluation process instead.

## Replay the captured HTML with the CURRENT parser

\`\`\`bash
python -m scripts.replay_pricing_snapshots \
  --replay \
  --manifest output/private/p17b3-fireworks-first/frozen_snapshots.json \
  --snapshot-root output/private/p17b3-fireworks-first \
  --out-dir output/private/p17b3-fireworks-replay
\`\`\`

This command has **no network requests**. Inspect
\`pricing_html_replay.json\`: how many price cells and dimensions
were observed, which rows have unresolved model/region/plan,
inventory completeness and any title-identity conflicts.

To **measure an improvement**, replay the exact same raw bytes
against the old P17A parser and new P17B1 parser in separate
worktrees according to the restored
\`docs/P17B2_FROZEN_HTML_GOLD_RUNBOOK.md\`. Compare the reports,
then use its blind dual-review workflow to independently label
the same original publisher price cells.

Do not declare a real accuracy gain from the code's test fixtures,
extracted observation count, copied paragraph or a high score on
self-judged data. A price with unknown region is still not a
fully scoped, comparable AgentFuse rate.

## Safety, cost and future steps

- Select **at most five exact source IDs** per manual run. Start with
  **one** Fireworks page; widen only after reviewing the raw captured
  HTML and any access/publisher policy problems.
- No new Zyte spider or job argument is introduced. The full
  460-source crawl remains unnecessary.
- Source Lifecycle review status, the 460-source manifest, source URLs,
  Zyte schedules and production Supabase/AgentFuse data are unchanged.
- Raw publisher HTML, human-review labels and private policy notes
  belong in \`output/private/\` (already Git-ignored) or another
  private retention-controlled location. **Never upload them to Git.**
- Source-specific parsing should be expanded only after non-synthetic
  held-out reviewer evaluation demonstrates accurate amounts, model
  attribution, currency, units, date/condition and region.
