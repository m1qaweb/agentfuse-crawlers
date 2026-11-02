# P16B — Source-Pinned Acquisition Comparison (No New Live Crawls)

**Goal:** determine, with real evidence, whether approved alternate acquisition
methods materially improve the existing extractors on difficult official
source pages. This follows merged P16A exact product identity and precedes
P17 provider-specific pricing normalization.

## What is implemented

- Exactly **8 candidate experiments** in
  \`agentfuse_crawlers/data/acquisition_experiments_v1.json\`:
  \`kiro_docs\`, \`cursor_docs\`, \`xai_docs\`, \`github_copilot_docs\`,
  \`gemini_api_docs\` (rendered documentation), \`aws_bedrock_pricing\` and
  \`gemini_api_pricing\` (rendered pricing), and
  \`claude_code_changelog\` (existing official Markdown release path).
  These are **candidates, not approved endpoints or verified improvement**.
- The URLs must match current exact source manifests. Browser-rendered
  candidates are the **same exact HTML URLs**, never a discovered page.
  The Markdown candidate is the **existing first-party allowlisted**
  \`https://code.claude.com/docs/en/changelog.md\`; P16B does not add
  that URL to the 460-source registry or enable new live fetching.
- Registry rejects unreviewed feed URLs, quarantine, arbitrary source
  migrations, query/credential URLs, policy approvals or automatic
  Scrapy method selection.
- \`scripts/compare_acquisition_snapshots.py\` loads privately retained,
  checksum-pinned original UTF-8 static HTML and alternate rendered HTML
  or Markdown. It reuses the **actual current** documentation/pricing/
  changelog extractors and P16A product identity diagnostics.
- Typed comparison includes substantive word count, scoped documentation
  topics, JavaScript shell, pricing observations and fully dimensioned
  rate candidates, release identities and explicit dates, loss/regression,
  source-product title conflict and operator follow-up.
- Outputs are **read-only, no-network** summary JSON, per-source comparison
  JSON and formula-safe CSV with **no raw HTML/full publisher text**.
  No new source URLs, Zyte schedules, replay job submissions, credentials,
  provider adapter activations or advisor approvals are created.

## Step 1 — Generate exact manual experiment plan

\`\`\`bash
python -m scripts.compare_acquisition_snapshots \
  --plan-only --out-dir output/private/p16b
\`\`\`

The generated \`manual_acquisition_experiments.json\` lists every exact
original source URL and candidate acquisition URL with media type. This
is a **manual capture checklist**, NOT Zyte Spider Arguments. Do not paste
it as a scheduled job, because the existing three Scrapy spiders do
**not** support a generic \`rendered_html\` switch.

For **each exact candidate source**, review robots.txt, provider terms,
content ownership and budget before considering ANY new capture. Do not
bypass authentication, CAPTCHAs, anti-bot restrictions, paywalls or
robots controls. On Zyte free tiers, browser rendering can consume
different credits and may not be available; verify your actual plan.

Use a permitted publisher page/source for both methods. The normal
Scrapy static HTML is the baseline. A rendered snapshot may be supplied
only through an explicitly permitted, operator-controlled capture tool;
P16B does not perform or automate rendering. For Claude Code, the known
Markdown alternate already exists in the source-specific crawler path.

**At this stage, if you cannot lawfully obtain the original publisher raw
HTML and an alternate snapshot, do not manufacture captures or assert
that rendering fixed a source. The Nov 2 Dashboard Items are not raw HTML.**

## Step 2 — Privately store exact capture bytes and manifest

Keep original raw publisher capture files in an encrypted private directory
according to the publisher's retention terms. Each comparison has the
strict shape below. Values are *illustrative placeholders*, not observed
publisher captures. Compute SHA-256 from actual file bytes.

\`\`\`json
{
  "schema_version": "1.0",
  "approved_for_advisor": false,
  "pairs": [
    {
      "source_id": "kiro_docs",
      "experiment_id": "p16b_kiro_docs_rendered",
      "static_html": {
        "file": "kiro_static.html",
        "sha256": "SHA256_OF_ORIGINAL_FILE",
        "request_url": "https://kiro.dev/docs/",
        "final_url": "https://kiro.dev/docs/",
        "http_status": 200,
        "media_type": "text/html",
        "capture_method": "static_html",
        "captured_at_utc": "2026-11-02T10:00:00Z",
        "capture_origin_review_status": "operator_supplied_unverified"
      },
      "alternate": {
        "file": "kiro_rendered.html",
        "sha256": "SHA256_OF_RENDERED_FILE",
        "request_url": "https://kiro.dev/docs/",
        "final_url": "https://kiro.dev/docs/",
        "http_status": 200,
        "media_type": "text/html",
        "capture_method": "rendered_html",
        "captured_at_utc": "2026-11-02T10:20:00Z",
        "capture_origin_review_status": "operator_supplied_unverified"
      }
    }
  ]
}
\`\`\`

The runner requires same pinned request/final URL, explicit HTTP 200,
correct format, UTF-8, **exact SHA-256**, local non-symlink relative file
paths, 8 MB file cap and capture timestamps within two hours. No
redirects, unexpected alternate hosts, query tokens or arbitrary new
source URLs may be silently accepted as the same page.

## Step 3 — Compare offline, do NOT start another 460 crawl

\`\`\`bash
python -m scripts.compare_acquisition_snapshots \
  --manifest /private/p16b/approved_capture_manifest.json \
  --snapshot-root /private/p16b/publisher_capture_bytes \
  --out-dir output/private/p16b/quality-comparison
\`\`\`

Outputs:
- \`acquisition_comparison_summary.json\` — number of paired sources,
  observed comparison outcomes, current parser package fingerprint,
  registry hash, explicit **zero network requests/approvals**.
- \`acquisition_comparison_pairs.json\` — source-aligned extraction
  metrics, per-version hashes, title conflict/review reasons. No raw HTML.
- \`acquisition_review_queue.csv\` — source-level comparison and next
  manual verification action.

**Never equate more rendered text with better truth.** A
\`more_comparable_rate_candidates\` or \`more_scoped_docs_candidate\`
outcome is a targeted *review lead*, not verified correctness.
Claude Code Markdown can yield stable version identities without official
publication dates. Do not invent dates for undated versions.

## Exit and next stage

P16B exits when the operator has acquired permitted, contemporaneous
source-pinned raw pairs for the highest-impact sources; the comparison
runs without errors; P15B independent reviewers confirm what improved,
what regressed, and whether the additional rendering costs are justified.
Require a measurable net improvement on untouched original-source gold,
not just unit-test success.

P16C (if worthwhile) can add **narrow operator-enabled** rendered
acquisition for independently policy-approved source IDs, with a strict
cost cap and robots policy; P17 develops exact pricing semantics and
provider-specific extraction. Do not globally render all 460 URLs.

**No live Zyte crawl is needed merely to merge this PR.** Do not run the
next full 460-source spider campaign until provider-quality accuracy gains
are measured using independent publisher evidence.
