# AgentFuse Crawlers — Trustworthy Intelligence Implementation Plan

**Version:** 1.0 · **Prepared:** 2026-10-31 · **Repository:** https://github.com/m1qaweb/agentfuse-crawlers  
**Basis:** GitHub `main` at `2a93d3c5bf4a0876df4c5f806c7ff57d589e0a1d`; the owner's October 30–31 Zyte Items, Requests, and Logs exports; the 460-source deep audit; Scrapy 2.18 and Zyte API documentation.  
**Purpose:** An actionable engineering specification for a dependable, low-cost official-source intelligence collection layer for AgentFuse. **This document is a plan, not an assertion that the upgrades are already implemented.**

## 0. Executive decision

**Keep exactly three spiders:** `official_documentation`, `official_changelogs`, and `official_pricing`. Keep Scrapy Cloud and the existing curated source IDs. Do **not** introduce MCP discovery, a fourth spider, paid browser/anti-blocking services, an LLM-centric crawler, or automatic writes to AgentFuse production data.

The current crawler is **operational but not yet information-reliable**. Scrapy successfully reached the end of all three October 31 runs and emitted **460/460 expected source Items**, yet only **246/460 (53.5%)** had `status=captured`. Even `captured` means only that a useful-looking page was parsed; it is neither proof of a complete knowledge inventory nor a verified vendor assertion. Some “captured” pages have objectively incorrect newest-release dates or clipped review evidence.

**Core design change:** replace “one page + guessed latest date + one hash” as the primary intelligence unit with a three-layer evidence model:

1. **Source observations:** provenance, scope, HTTP/policy health, extraction completeness, current HTML snapshot and diagnostics.
2. **Typed candidates:** individual dated release events, exact pricing observations and documentation sections with their own stable identity, content hashes, source locators and uncertainty.
3. **Verified decisions:** a separate review/export boundary. Nothing becomes an AgentFuse advisor fact merely because a page returned HTTP 200 or a parser found a number/date.

Prioritize **precision and the ability to say “unknown”** over maximizing the raw capture percentage. A source marked `needs_review` is better than a plausible but falsely dated or incomplete announcement.

### Non-negotiable constraints

- Exactly the existing three Scrapy spider names; internal extractor modules and optional support scripts are allowed.
- HTTPS, official first-party URLs and explicit source registry; no arbitrary spider-supplied URL, captcha bypass, unauthorized login, stealth rotation or invented redirects.
- Respect robots.txt and publishers' terms. Treat unresolved robots 429 and anti-bot failures as review/temporary pause, not permission to bypass.
- No automatic AgentFuse Supabase writes, catalog mutation, recommendation approval, or new external paid Zyte features.
- Maintain backward-readable v2.1 Items and offline exports while versioning all new records.
- The one-unit, modest-memory Scrapy Cloud deployment must remain viable.
- Full-inventory coverage is **not** the same as full-documentation coverage: an official docs landing page is only a landing page.
- HTTP Date, Last-Modified, CDN Age and `fetched_at_utc` are **not** vendor release publication timestamps.

## 1. Baseline: objectively observed on October 31

The user's three jobs actually selected `cohort=all`, not `cohort=proven`. This is explicitly shown by the start logs. The `source_cohort` field in an Item labels the *source's historical membership*, not the *job's requested scope*. The repository currently has 460 configured URLs across 194 provider names, with nine original historical “proven crawl” IDs—not nine independently verified sources.

| Spider | Requested and reported | Captured | Partial | Review | Redirect rejected | HTTP error | Elapsed |
|---|---:|---:|---:|---:|---:|---:|---:|
| Documentation | 194 | 104 | 0 | 75 | 11 | 4 | 9.6 min |
| Pricing | 177 | 114 | 3 | 44 | 10 | 6 | 8.2 min |
| Changelogs | 89 | 28 | 10 | 48 | 2 | 1 | 4.0 min |
| **Total** | **460** | **246** | **13** | **167** | **23** | **11** | **21.8 min** |

All 460 source IDs were accounted for; zero duplicate or missing source records; all `approved_for_advisor=false`. Peak observed crawler memory was approximately 160 MiB, which means **quality, not current CPU/RAM use, is the immediate constraint**.

Additional directly observed defects:

| Finding | Count / examples | Why it matters |
|---|---|---|
| Incorrect “latest” date while marked captured | Cursor 2026-10-16 vs visible Oct 20; Render 2023-06-30 vs visible Oct 29; xAI 2025-12-16 vs newer-looking October entries without an explicit year | An incorrect date creates false freshness and missed releases |
| Missing changelog date detection | 47/89 source records | Generic heading extraction misses cards, version lists, GitHub releases and metadata dates |
| Partial changelog | 10: six text-cap breaches, four section-cap breaches | New release evidence can be buried or clipped |
| Partial pricing | Gemini API, AWS Bedrock and Oracle OCI: 40 tables captured but more exist | Potentially wrong model/tier cost comparison |
| Captured pages with clipped section excerpts | 20 across categories | A changed hash can be shown without the actual changed words |
| Captured pages with zero semantic sections | 6 | Hash comparison lacks meaningful explanation |
| Canonical-path mismatches | 65 (57 docs, 7 pricing, 1 changelog) | Many ordinary homepage/canonical conventions create noisy review warnings |
| Cross-host redirects rejected | 23 | Legitimate migrations require manual validation; redirects cannot be silently trusted |
| HTTP 403/404 source errors | 11 | Missing information and incorrect URLs must be visible |
| No obvious billing amount/details | 19 pricing pages | Could mean enterprise-only pricing, JS-only content or a bad URL |
| Insufficient text | 16 pages, including `kiro_docs` with zero words | HTTP 200 is not a useful documentation capture |
| Cache Age over one day | 14 source records | Stale-CDN risk; not proof of a newer vendor publication |
| `v0.app/robots.txt` returned 429 | Across the three jobs | Source-policy status is unresolved despite successful content responses |

Additional cases: `claude_code_changelog` yielded **169,639 words and zero semantic sections**; `openai_api_changelog` grouped all October entries into **one** section; `supabase_changelog` reached the 180-section limit; `cloudflare_workers_ai_changelog` includes general Cloudflare product notices. The Google Cloud source was moved from Vertex AI release notes to a page concerning **Gemini Enterprise Agent Platform**—not necessarily an identical product scope.

**Caution:** percentages above are capture *status rates*, not measured recall, factual correctness, or release coverage. No claim that a provider published a new release may be derived solely from this audit.

## 2. Current repository review and specific deficiencies

### `agentfuse_crawlers/extract.py`

- `_sections()` assumes most release events map to `h2/h3/h4` headings. Some vendors use `h1`, cards, `<time>` beside the title, a Markdown code block, version metadata, or plain list items.
- `_date_from_month_group()` attaches the **first** matching day to an entire month group, and `visible_latest_date_candidate` takes the maximum date it happened to detect. Neither answers “what is the latest individual release.”
- The 180-section ceiling, 6,000-character excerpt ceiling and 40-table ceiling truncate useful evidence. A 250,000-character page limit is applied later in `official.py`.
- `content_sha256` covers flattened page text, including some template/landing noise. `section_id` often depends on heading spelling or duplicate position; this generates false event changes when HTML layout changes.
- Pricing table cells are preserved but headers are not resolved into explicit row/column dimensions. Flattened prose cannot safely become model prices.
- The code has no release event identity, no authoritative publication/effective date relationship, no price-unit normalization, no source-page completeness claim and no provider/product scope check.

### `agentfuse_crawlers/quality.py`

- Status is mostly one scalar (`captured`/`needs_review`/`partial_capture`) based on heuristics. It does not distinguish transport success from semantic extraction completeness, policy state or vendor-fact review.
- A single found price symbol can mark a complex pricing page captured, even if its usable rate rows are not resolved.
- A syntactically plausible `visible_latest_date_candidate` can mark a changelog captured even when newer entries were missed.
- A CDN `Age` warning is useful but should not be confused with proof of stale *publisher* information.

### `agentfuse_crawlers/spiders/official.py` and `settings.py`

- The current default is `cohort="all"`; a manual run with omitted arguments silently targets 460 URLs. This likely caused the October 31 all-scope run when proven was intended.
- `source_cohort` does not record the actual request cohort, manifest revision, source selection digest, deployment revision, or job ID.
- Same-origin redirect limits protect against arbitrary cross-host movement, which is good; canonical/path differences currently result in many unhelpful, non-prioritized warnings.
- Retry and robots-policy behavior are not turned into an explicit per-source policy-state decision.
- `fetched_at_utc` is the record construction time; it is not the vendor's publication date.

### `agentfuse_crawlers/sources.py` and source data

- The 460-entry array is a useful allowlist but stores only `id`, `provider`, `category` and `url`. It lacks product scope, desired page type, extraction strategy, reviewer status, approved replacement host/path and verification evidence.
- `proven_sources.json` is a historical crawl-cohort shortcut, not a qualified production-ready registry.
- Offset-based candidate batches change membership when the registry is edited or a candidate is promoted to proven.

### `scripts/compare_exports.py`, `scripts/download_zyte.py` and `extensions/coverage.py`

- `compare_exports.py` primarily reports page/section SHA changes. It cannot differentiate a genuinely new vendor event from a changed navigation menu or a modified old announcement.
- `cohort=auto` infers scope from the Items' `source_cohort` labels; this is unsafe for arbitrary selected subsets and gives no deployment/manifest comparability guarantee.
- The downloader handles one job and a single download response. It does not yet implement a fully checked, paginated, immutable archive with job metadata and replay checks.
- The coverage extension correctly checks **item count**, but a job can report `finished` with 214 unusable or incomplete items. A run-level *quality outcome* must be separate.
- The GitHub workflow validates packaging and unit tests, but a passing build does not prove the matching code is deployed in Zyte; compare deploy ID/SHA explicitly.

## 3. Target architecture — three spiders, typed extractors

```text
Zyte periodic jobs / deliberate test runs
     |
     | exactly three spiders, manifest source IDs only
     v
[Scope guard + manifest revision + source-policy decision]
     |
     v
[Polite HTTPS fetch, retry/backoff, same-source redirect policy]
     |
     v
[Capture envelope: transport, canonical, cache, body, extractor provenance]
     |
     +--> Documentation adapter --> scoped sections / capabilities / limits
     +--> Changelog adapter ----> dated release EVENT candidates
     +--> Pricing adapter ------> complete raw rate observations
     |
     v
[Quality gates: source health + recent-window completeness + unit/date checks]
     |
     v
[One source-summary Item per source; bounded evidence details]
     |
     v
[Archive job metadata, immutable snapshots, latest-good state]
     |
     v
[Semantic event/rate/section diffs; baseline is never "new"]
     |
     v
[Pending review with exact publisher evidence]
     |
     v
[Future explicit approved-fact export, separate from production DB]
```

Extractor adapters are **ordinary Python modules behind the same spiders**. Add `agentfuse_crawlers/extractors/` for deterministic, tested helpers, optionally with a small number of publisher-specific profiles. Do not create new Scrapy spider classes for each provider.

Separate the four meanings of quality:

| Axis | Values | Interpretation |
|---|---|---|
| Transport/policy | allowed, blocked, error, unresolved | Can the source be fetched lawfully? |
| Source relevance | right product, ambiguous, wrong product | Does this page substantiate the intended provider/product? |
| Extraction coverage | recent_window_complete, partial, unknown | Did the parser recover the *relevant* current portion? |
| Fact approval | unverified, reviewed, approved, rejected | May a fact affect recommendations? |

A run can be **complete in accounting** and **unhealthy in evidence quality**. Keep these distinctions explicit in Items, summary stats and review output.

### Proposed v3 envelope (illustrative, backward-compatible)

```json
{
  "record_type": "source_snapshot",
  "schema_version": "3.0",
  "run": {
    "zyte_job_id": "883514/1/<job>",
    "spider": "official_changelogs",
    "requested_cohort": "candidate",
    "selection_ids_sha256": "<hash>",
    "manifest_sha256": "<hash>",
    "deployment_revision": "<commit-or-deploy-id>"
  },
  "source_id": "cursor_changelog",
  "provider": "Cursor",
  "product_scope": "Cursor",
  "category": "changelog",
  "source_url": "https://cursor.com/changelog",
  "final_url": "https://cursor.com/changelog",
  "fetched_at_utc": "2026-10-31T08:50:00Z",
  "transport_status": "ok",
  "policy_status": "allowed",
  "relevance_status": "right_product",
  "extraction_status": "recent_window_complete",
  "observed_page_hash": "<sha256>",
  "latest_release_date": null,
  "latest_release_date_status": "unknown_until_event_verified",
  "release_event_count": 0,
  "evidence_refs": [],
  "review_status": "unverified",
  "approved_for_advisor": false
}
```

The example uses placeholder values; it is **not a sample scraped fact**. Keep legacy fields for compatibility initially, but **deprecate `visible_latest_date_candidate` as the authoritative “latest release” field**. The actual release date must come from a dated event with explicit provenance. Do not set `latest_release_date` by searching an arbitrary page for the maximum date.

The source-summary Item remains **one per requested source** (preserves the current coverage invariant). Archive large evidence separately or in bounded chunks with a distinct `record_type` and explicitly adjusted accounting. Zyte's Items API documents a **1 MB limit for individual uploaded items**; keep target serialized item payloads comfortably below that threshold. Do not solve large changelogs by emitting a multi-megabyte Item.

## 4. Delivery sequence and PR-sized implementation work

The following PRs are ordered by risk and dependencies. Code names and filenames are **proposals**, not existing modules. Each PR includes tests, a read-only replay, and a rollback path. Never combine all changes in one massive unreviewable PR.

### PR 01 — Safe job scope, versioning and health telemetry (P0)

**Objective:** Prevent an unintended 460-source run and make every result traceable.

**Modify:** `spiders/official.py`, `sources.py`, `extensions/coverage.py`, `quality.py`, `tests/test_start.py`, `tests/test_coverage.py`. Add `agentfuse_crawlers/run_context.py` and `tests/test_run_context.py`.

**Implementation tasks:**

1. Change default spider cohort from `all` to **`proven`**. Full-inventory runs require both an explicit `cohort=all` and a human-readable confirmation argument (e.g., `confirm_full_inventory=yes`). A missing confirmation fails *before scheduling requests*. This is not authentication; it prevents accidental broad jobs.
2. Include `requested_cohort`, exact selected IDs or stable selection hash, `limit`, `offset`, source-manifest hash, deployed revision, spider name, run start UTC and Zyte job ID (where available) in each observation. Keep `source_cohort` as an independent label.
3. Pin batches to an **explicit list of source IDs plus manifest SHA**, not only offset, for reproducible validation even after source promotion. Retain offset for CLI compatibility.
4. Validate every requested ID once; include request/Item/quality counts. Track `coverage_count` separately from `usable_capture_count` and `verified_fact_count`. An all-200 run with empty HTML must fail the quality gate.
5. Emit source health and run health in stats and post-run summary, with alert thresholds as configuration; no attempt to hide failures to make the run appear green.
6. Record source URLs and status transitions without leaking API keys, signed URLs or response-sensitive data.

**Acceptance:** With no cohort argument, exactly three requests per spider source set; explicit guarded full run selects 194/177/89; v2.1 downstream readers still work; a run missing 1 selected ID is reported incomplete; changed source list produces a different manifest hash.

**Tests:** omitted/invalid/explicit full args; mixed proven/candidate records in the same `all` job; source-list reorder; edited manifest; duplicate item; robots error; zero useful captures.

**Rollback:** restore old selection defaults only for compatibility if required, but keep explicit run-scope metadata and deny unreviewed publication.

### PR 02 — Correct, event-level changelog extraction (P0, highest product value)

**Objective:** A vendor's new release becomes one **dated, source-linked event**, not a date inferred from a neighboring heading.

**Modify:** `extract.py` with a backward-compatible facade; new `extractors/changelog.py`, `extractors/common.py`, `extractors/profiles.py`; `quality.py` and the comparator after PR 01.

**Release candidate contract:**

```json
{
  "event_id": "<stable-vendor-event-key>",
  "source_id": "cursor_changelog",
  "product_scope": "Cursor",
  "title": "<vendor title>",
  "version": null,
  "event_type_hint": "release_or_update",
  "published_at": null,
  "published_date_precision": "unknown",
  "published_date_provenance": "none",
  "effective_at": null,
  "observed_first_at_utc": "<first-observation>",
  "observed_last_at_utc": "<latest-observation>",
  "permalink": "<official page/anchor>",
  "evidence_locator": {"selector": "<verified locator>", "text_offset": null},
  "excerpt": "<bounded exact source excerpt>",
  "body_sha256": "<hash-of-normalized-event-content>",
  "recent_window_covered": true,
  "review_status": "unverified",
  "approved_for_advisor": false
}
```

**Rules:**

- Parse explicit `<time datetime>`, machine-readable official release metadata, dated headings, version cards, adjacent date text and source-provided JSON-LD where applicable. Date must belong to **that event**; distinguish publisher date, edit date, future effective/deprecation date and fetch time.
- Resolve month/day without year **only** if an official containing year context exists. For xAI-style headings without a supported year, store `published_at=null` and `published_date_precision=unknown`; never guess from today.
- Recognize ISO dates and common official English formats and reject impossible dates. Do not treat dates mentioned in body text (e.g. “deprecates on November 21”) as publication dates.
- Release IDs prefer official permalink/ID; otherwise compose stable source ID + vendor version/date/title normalized key. Detect ID collisions; preserve event identity when cards reorder.
- For explicit GitHub project `/releases` sources, use the **official GitHub Releases API** as a verified optional source adapter *inside the existing changelog spider* where official repository identity is explicitly registered and request policy permits it. Use `published_at`, tag, release HTML URL, draft/prerelease flags, ETag and pagination. Respect GitHub API rate limits. No untrusted repository names supplied via spider args.
- Support official Markdown changelogs or `llms.txt`-linked Markdown as permitted **alternatives to the same source**, not as a new spider category.
- Keep recent-window semantics, e.g. newest 20 events **or** the recent 45 days plus several overlap events, with bounded pagination when needed. Store `recent_window_complete` separately from `historical_archive_complete`. A truncated historical backlog need not invalidate fully captured new releases.
- Handle edits, deleted records, republished notes, announcement dates and effective dates separately. “Not on current page” never implies vendor deprecation.
- A raw text hash change is **not** a newly published event. The first observation creates a historical baseline. New event detection requires a preceding healthy comparable scan and a stable event identity.

**Source-specific golden tests using short, rights-compliant fixtures:**

| Source | Observed failure | Expected result |
|---|---|---|
| `openai_api_changelog` | Entire October 2026 combined in one section | Separate Oct 30, Oct 28, Oct 26 etc. event records; month is not event |
| `kiro_changelog` | Date before first heading | Oct 28 belongs to correct release card |
| `cursor_changelog` | Latest captured date Oct 16 despite Oct 20 visible | Oct 20 event recognized; no false latest Oct 16 |
| `render_changelog` | Latest guess June 2023 vs Oct 29 tooling versions | Separate Oct 29 CLI/SDK events or source-native grouped release, not 2023 |
| `xai_changelog` | 2025 date extracted from old entry; October year unspecified | Newer entries remain year-unknown without official year evidence |
| `supabase_changelog` | 180-section limit; first Oct 30 not recognized as newest | Current card dated correctly, historical cutoff flagged separately |
| `claude_code_changelog` | 169,639 words; no sections | Explicit date/version release entries from official Markdown or dedicated parser |
| Official GitHub releases | Version exists but HTML date missing | Official `published_at` captured when available; prerelease/draft handled |

**Acceptance:** On a versioned gold set, **100% of published dates have a machine-auditable source locator**, >=99% exact-date precision for explicitly dated events, no inferred year from fetch time, **zero** false “new release” alerts on first-baseline and HTML-reorder tests, and complete detection of the above known newest-entry cases. Unknown is an acceptable outcome when official evidence is ambiguous.

### PR 03 — Bounded large-page capture without silent evidence loss (P0)

**Objective:** Make Claude Code, Codex, Antigravity and other long-running changelogs useful without exhausting a single Zyte unit or pretending to cover an entire history.

**Modify:** `extract.py`, `extractors/changelog.py`, `spiders/official.py`, `quality.py`, `scripts/compare_exports.py`.

1. Stop accumulating an unbounded giant flattened page string as the only useful representation. Select meaningful recent entries from the DOM/official Markdown stream first and normalize each release independently.
2. Retain a bounded diagnostic overview plus complete recent-event evidence within a configurable payload budget. Store `text_total_characters`, `text_retained_characters`, `recent_window_complete`, `historic_text_truncated` and `event_excerpt_truncated` separately.
3. Preserve full hashes of extracted individual events even when a display excerpt is short. If a changed event cannot be displayed fully, generate a review flag with a safe evidence locator and explicit clipping notice.
4. Avoid treating the existing hard caps (180 sections, 40 tables, 250k text) as a measure of truth. Their exceedance becomes an accurately scoped completeness signal.
5. Handle sites with expanding historical releases and pagination. Follow only publisher-approved, product-scoped pages on approved domains, with a strict page/request budget. Never traverse arbitrary “Next” links into unrelated sites.
6. Enforce a hard serialized Zyte Item budget (target <750 KB, absolute API ceiling considered 1 MB). If evidence is bigger, keep source Item compact and archive additional authorized detail separately. Do not emit duplicate source summary records.
7. Preserve retry/timeout behavior; benchmark memory and latency against the October 31 baseline.

**Acceptance:** The targeted oversized changelogs expose at least the newest 20 dated entries where the publisher provides them, with `recent_window_complete=true` only when proven. No clipped changed entry is represented as fully visible. No Zyte Item exceeds the configured safe size. Memory stays comfortably within one unit.

### PR 04 — Pricing evidence completeness and typed rate observations (P0)

**Objective:** Never confuse prices, billing periods, model tiers or usage units.

**Modify:** `extract.py` (existing raw-table compatibility); new `extractors/pricing.py` and `extractors/rate_units.py`; `quality.py`; `scripts/compare_exports.py`; dedicated pricing tests.

**Capture and normalization requirements:**

- Preserve **all relevant** rate-table context: caption, hierarchy (product/region/plan/tier), nested headers, row/col spans, footnotes, minimums, discounts, taxes, free allocations, effective dates and availability notes.
- Enumerate total table count and selected table indices; distinguish relevant/irrelevant/inaccessible/partial tables. The 40-table cap must never produce a complete-looking pricing record.
- Use `Decimal` for numeric rates. Store both the **verbatim displayed price** and any deterministic numeric candidate. An amount is not comparable until currency, denominator (per 1M input tokens; per output token; per hour; per user-month; etc.), region and applicable tier are explicit.
- Treat input/output/cached input/cache write/batch/fast/ultrafast/long-context as distinct price dimensions, not one “model price.”
- Represent “contact sales”, “free”, “usage-based”, “custom” and “not displayed” as different **non-numeric evidence states**. Missing a price is not proof a service is free.
- Distinguish time-scoped promotional rates from base prices, and effective dates from page modification timestamps. Do not choose one region's or one provider's currency by default.
- Derive compact rate-candidate evidence with source URL + table/row/header locator + raw quote + hash. Keep normalization `unverified` until the table alignment and unit parsing pass source-specific tests.
- Offer a targeted official pricing subpage for products too large or heterogeneous to represent with one generic vendor pricing page; still crawled by `official_pricing` only. No unbounded paging or JS bypass.

**Gold sources:** `gemini_api_pricing`, `aws_bedrock_pricing` and `oracle_oci_generative_ai_pricing`, plus OpenAI/Anthropic/Kiro and at least 25 diverse pricing patterns (token APIs, seats, minutes, GPU hours, enterprise-only, regional plans, free tier).

**Acceptance:** No partial/capped table page passes the complete-rate gate. On a human-reviewed set of >=200 rate rows, >=99% correct exact displayed amount+unit+currency, no mixed-tier comparisons, and *zero* numeric rate emitted when required dimensions are missing. Unresolved rows go to review, not the advisor.

### PR 05 — Documentation coverage, product scope and canonical repair (P1)

**Objective:** Collect meaningful technical requirements, not merely vendor homepages.

**Modify:** `extractors/documentation.py`, source metadata/profile data, `sources.py` and docs health tests.

1. Introduce a source profile (by existing source ID) recording **provider, product, page purpose, desired document family and parser family**. Keep the original four-field manifest compatible; store extended metadata in a companion registry or explicitly version the schema.
2. For high-priority products, curate official pages that directly support recommendation dimensions: model availability, input/output modalities, context length, tool calling, structured output, authentication, quotas/rate limits, regions, compatibility/versioning, SDK requirements and limitations. Do this inside `official_documentation`.
3. A docs landing page counts as a **landing-page observation**, not verified coverage of all documentation or all capabilities. Record `document_scope` and `page_type` (overview, reference, limits, model catalog, feature guide).
4. Parse stable heading and content anchors, preserve per-section evidence, normalize relevant template noise and track semantic hashes. Avoid auto-extracting high-level links as proven feature support.
5. Investigate `kiro_docs` and the other seven insufficient-text docs. If current HTML is client-rendered, prefer an official static/Markdown alternative or mark unavailable; no paid browser rendering unless explicitly authorized.
6. Canonical handling: normalize safe equivalences (slash/index conventions) but **review true path/product changes**. Maintain explicitly reviewed official aliases; never blindly adopt external domains or arbitrary canonical URLs.
7. Product scope reviews must catch `cloudflare_workers_ai_changelog` being a general Cloudflare feed and the Gemini Enterprise Agent Platform vs Vertex AI scope mismatch.

**Acceptance:** Every high-priority documentation record declares actual product/page scope and at least one useful target field or honestly states `overview_only`. All 65 original canonical cases are triaged (normalized, corrected, quarantined or explicitly accepted). Zero automatic external redirects.

### PR 06 — Source registry repair, robots safety and lifecycle (P1)

**Objective:** Manage 460 sources as reviewed, explicit assets instead of assuming “present in JSON” equals reliable.

**Modify:** `data/sources.json` with stable IDs preserved; new `data/source_profiles.json` or equivalent; `scripts/plan_validation.py`, `sources.py` and validation tests.

Proposed source lifecycle independent from historical `proven` membership:

```text
discovered -> needs_validation -> validated_for_collection
           -> degraded / quarantined / retired
           -> revalidated (same ID, explicit new URL/version)
```

**One-time triage of current evidence:**

- 65 canonical-path mismatches: normalize safe same-product canonical routes after checking title, scope and host.
- 23 cross-host redirects: record destinations and verify the publisher's official migration; update a source **in Git**, never by following arbitrary cross-host redirects at runtime.
- 11 HTTP 403/404: repair or pause, do not bypass.
- 19 no-billing pricing pages: distinguish “enterprise/contact sales” from actual extraction failure; use an official alternative where available.
- 16 insufficient-text pages: classify JS-only, docs landing shell or dead link.
- 14 long CDN ages: retain an uncertainty flag; require consistency tests before declaring stale vendor content.
- `v0.app/robots.txt` 429 across runs: **quarantine the affected source IDs** until robots/terms and Scrapy behavior are reviewed. No proxy hopping, retries intended to defeat restrictions, or permissive interpretation of an unresolved 429.
- Year-specific Pinecone/Warp paths must be reviewed when the official publisher advances the year. Do not invent URLs.
- Explicitly check publisher/product ownership before treating a GitHub release repository as a vendor's official change log.

A source can be `validated_for_collection` while still having **zero verified facts**. Repeated successful page fetches alone are insufficient for any financial or capability claim.

**Acceptance:** Every known URL issue has a documented resolution/review status and next action. Automated periodic sweeps select only validated, permitted sources. A quarantined URL is not scheduled even when someone requests `cohort=all` without explicit override and legitimate reapproval.

### PR 07 — Reproducible archival and event/price-level change detection (P1)

**Objective:** Make “what changed since the last reliable run?” deterministic, auditable and recoverable after Zyte's retention window.

**Modify:** `scripts/download_zyte.py`, `scripts/compare_exports.py`; new `scripts/archive_jobs.py`, `scripts/evaluate_run.py` and tests. Keep source spiders limited to their three categories.

1. Read the official Zyte **Jobs API** / job metadata, including job ID, spider name, arguments, deployment ID, completion state and stats. Fetch Items through the official paginated **Items API**, validating total count and record schema. Preserve API key only in secure environment/secret storage, never logs or URLs shown to users.
2. Archive an immutable, timestamped job envelope with per-item SHA-256, manifest revision, run scope, response/request outcome summary and optional compact exact source evidence. Compress files, avoid re-downloading the same job and verify replay checksum. Use a user-controlled durable location; initial local archive is acceptable, then inexpensive object storage if authorized.
3. Keep **latest observed state** separate from **latest healthy comparable state**. A failed source must be displayed as failed without replacing the last known good baseline used for future diffs.
4. Compare only compatible source IDs, product scope, extraction schema, official URL/approved alias and manifest versions. A moved URL or newly introduced parser starts a new baseline when identity/semantics changed.
5. For changelogs, compare **event IDs and event content hashes**. For pricing, compare a typed tuple (provider, product/model, region, plan, service mode, billing unit, currency, date eligibility) and verbatim prices. For docs, compare stable semantic sections.
6. Classify deltas: `new_event_candidate`, `edited_event`, `restored_event`, `rate_change_candidate`, `docs_section_changed`, `source_unavailable`, `source_migrated`, `needs_review`. Do not infer `model_discontinued` from a missing card.
7. First crawl is `historical_baseline`, not a release alert; late additions are `backfilled_event` if publication metadata predates the monitoring window; reordering or template shifts should not create new events.
8. Produce `status.csv`, `changes.csv`, `release_events.jsonl`, `pricing_observations.jsonl`, `review_queue.jsonl`, `run_quality.json` and compressed archival snapshots. Treat these as **unverified evidence**.

**Acceptance:** Replaying exactly the same completed job is idempotent; an archive loss/dedup is detected; export count exactly matches official job metadata after pagination; all events/price observations point to official source locators; a CDN error never generates invented new-release news.

### PR 08 — Offline replay fixtures, quality gates and canary rollout (P0/P1)

**Objective:** Tests that prove meaningful accuracy, not merely that spiders import successfully.

**Modify:** `tests/`, `.github/workflows/validate.yml`, `scripts/plan_validation.py`, `docs/`.

Create a **copyright-respectful** fixture suite containing minimal synthetic/short annotated HTML patterns derived from observed structures; use the full owner's original Zyte exports as **private local replay inputs**, not copied wholesale into a public repo. Freeze clock/timezone in time-sensitive tests.

**Minimum test matrix:**

- Release source fixtures: Cursor, Render, xAI, OpenAI API, Kiro, Supabase, Claude Code, Codex, Antigravity and at least 15 official GitHub release patterns.
- Dates: full/partial/invalid dates, mixed years, publication vs deprecation-effective dates, edit timestamps, future announcements and timezone boundaries.
- Change cases: first baseline, new event, edited old event, event reorder, stale CDN copy, failed current fetch, missing source, source migration, prior schema migration and a historical backfill.
- Pricing: multi-row/col-span headers, >40 tables, pricing footnotes, free/contact-sales, caching modes, input vs output, tiers, region, currency, minimum commitment and promotions.
- Docs: landing-page-only, true reference page, empty HTML shell, inaccessible page, canonical same-host mismatch, wrong-product page and valid official redirect replacement.
- Safety: robots 429/403, status 403/404, cross-host redirect, HTTPS downgrade, private/IP loopback target, unauthorized link expansion, HTML prompt injection and oversized pages.
- Runtime: Zyte package egg, exact three spider registrations, Python/Scrapy version compatibility, source-manifest integrity, bounded memory and Item size.
- Run semantics: request cohort vs source cohort, pinned selection IDs, selected source count, duplicate result, one source missing, completeness score independent of finish reason.

Do not make an untested AI classifier the source of truth. If a model is later used for candidate summaries, keep the original evidence and require deterministic validation plus a human approval gate.

**Acceptance thresholds and monitoring** (engineering targets, **not already achieved**):

| Metric | Suggested gate |
|---|---|
| Source accounting | 100% expected source summary IDs per selected job; anomalies block acceptance |
| Unreviewed facts accepted by advisor | **0** |
| Known false latest dates in regression fixtures | **0** |
| Explicit release-date precision | >=99% on annotated gold examples; ambiguous dates must be null |
| False “new release” on baseline/reordered HTML | **0** on regression corpus |
| Pricing exact amount+currency+unit accuracy | >=99% on >=200 reviewed golden rate rows |
| Price facts with missing units/tier/region requirement | **0** normalized as fully comparable |
| Captured-but-clipped changed evidence | **0** allowed into review as an unqualified complete excerpt |
| High-priority source usable capture | >=95% over two repeat canaries, measured only on eligible/accessible curated sources |
| Mainline memory usage | Prefer <400 MiB on current batch; investigate sharp regressions |
| Source freshness | Collector age and publisher event age reported separately, never conflated |
| Robots 429 in unattended approved scope | **0 unresolved** |
| Cross-host follow without reviewed mapping | **0** |

Do **not** set a blanket “95% captured of all 460” gate while some are inaccessible, wrong-scope or enterprise-only. The denominator for a trustworthy operation is **reviewed, collection-eligible sources**, and retired/quarantined URLs must remain visible in a separate source-health report.

## 5. Source-specific repair playbook

| Priority | Source / group | Next engineering action | Test of success |
|---|---|---|---|
| P0 | `cursor_changelog` | Parse card date near event headline, not only nested heading | Oct 20 observed event dated correctly |
| P0 | `render_changelog` | Capture tooling release dates and dated cards separately | Oct 29 records and no false “latest 2023” |
| P0 | `xai_changelog` | Handle dates lacking year with explicit null/precision; anchor year only from official context | No invented October year or stale “latest” |
| P0 | `openai_api_changelog` | Split monthly sections into dated individual items | Oct 30 and Oct 28 are independent events |
| P0 | `kiro_changelog` | Match leading date to correct article/card | Oct 28 is recognized with evidence locator |
| P0 | `claude_code_changelog` | Official Markdown/structured release parser; newest bounded window | Newest entries usable without 169k-word text capture |
| P0 | `chatgpt_codex_changelog` / `google_antigravity_changelog` | Bound most recent release sections, mark history clipping separately | Recent events complete and stable IDs |
| P0 | `supabase_changelog` | Recognize date adjacent to card; prevent 180-heading overflow from hiding first entry | Oct 30 event with no false history completeness |
| P0 | `gemini_api_pricing` | Provider-aware table selection and exact rate units | All relevant model/tier rows classified; no silent 40-table cutoff |
| P0 | `aws_bedrock_pricing` | Pricing dimension resolver for model/region/throughput | No apples-to-oranges rate candidates |
| P0 | `oracle_oci_generative_ai_pricing` | Capture pricing scope and billing units under large table inventory | No false completeness |
| P1 | `kiro_docs` | Inspect chosen `<main>`, JS-only behavior, official text alternative | Substantive docs or explicit unavailable |
| P1 | `cloudflare_workers_ai_changelog` | Tighten to Workers AI notices or relabel feed scope | No unrelated WAF/network announcement credited to Workers AI |
| P1 | `google_cloud_ai_changelog` | Verify intended product after URL migration; separate Vertex AI if needed | Product scope evidence is correct |
| P1 | `v0_docs`, `v0_pricing`, `v0_changelog` | Review robots 429 and terms; pause pending decision | Policy status resolved before unattended crawl |
| P1 | Canonical/redirect/403/404 set | Manual bulk triage with exact official replacement URLs | 65+23+11 cases have dispositions |
| P2 | Year-pinned release-note URLs | Explicit rollover review as calendar changes | No silently abandoned 2026 archives |

## 6. How to distinguish data freshness correctly

**“Fetched now” means the crawler contacted an endpoint now; it does not mean the publisher updated its content now.** Model the following timestamps separately:

- `observed_at_utc`: crawler retrieval (always known after response).
- `http_last_modified`: origin/cache metadata, may not reflect content publication.
- `published_at`: official vendor event publication date (only if linked to an individual event).
- `updated_at`: official vendor edit date (if separately exposed).
- `effective_at`: price, migration, feature sunset or plan eligibility effective date.
- `first_seen_at_utc` and `last_seen_at_utc`: when **we** first and last observed the exact event/rate evidence.

For docs without vendor timestamps, the correct claim is “Current snapshot fetched at [time]”, **not** “Docs updated today”. When conditional GET / ETag reuse is eventually added, a `304 Not Modified` response must be linked to the matching stored content version; it does not independently prove the vendor's overall documentation is latest.

For changelogs, define a recent-monitoring window and an explicit **recency confidence**. Unknown publication dates should not be ranked as newly released. If a vendor publishes a release retroactively, log `first_seen_today=true` and `published_at=earlier`: this is a *late discovery*, not a brand-new release.

## 7. Reliable source approval and human review workflow

Each candidate passes the following independent gates before being placed into unattended collection:

1. **Ownership:** URL and permitted alternate domains controlled by the correct publisher/project.
2. **Access:** robots/terms permit the requested collection; no unresolved 429/CAPTCHA restriction.
3. **Product scope:** page actually discusses the intended model/agent/product.
4. **Extraction:** the target information exists and is captured in its relevant newest window.
5. **Dates/units:** critical release dates or pricing units are verifiably attached to the correct record, otherwise explicitly unknown.
6. **Repeatability:** at least two representative successive runs yield stable identities and no unhandled parsing errors.
7. **Review:** a human records acceptance and evidence URL for collection; **separate review** controls whether any *individual fact* may later reach the advisor.

Suggested registry states: `candidate`, `validated_for_collection`, `degraded`, `quarantined`, `retired`. This is separate from per-record `unverified`/`approved` and separate from historic `proven`.

A high-quality crawler may legitimately say “we cannot prove this price/release date.” Do not boost apparent coverage by fabricating certainty or suppressing errors.

## 8. Scheduling, capacity and cost discipline

Maintain owner's already configured cadence **unless changed explicitly**: documentation daily, changelogs daily, pricing Mondays. The jobs should use intentionally selected, approved source cohorts—not assume `cohort=all` is safe just because a one-time 460-source run completed.

The October 31 all-inventory run took ~21.8 minutes combined with peak memory ~160 MiB. This supports using the existing Scrapy Cloud unit at today's load, but does **not** guarantee all future pages remain small or policy-compliant.

- Keep per-domain concurrency 1 and AutoThrottle/download delay; continue to respect robots and response backoff. Repeated 429/503 should trigger bounded retry and then quarantine/review, not proxy circumvention.
- Guard overall job runtime, max decoded response size, page budget and per-record serialized size. Very large pages should switch to bounded recent-entry extraction, not silently drop the newest data.
- Separate `eligible_daily` (high-value changelogs/docs), `eligible_weekly` (pricing and low-change docs) and `validation_only` sources **inside the same three spiders**. This is scheduling metadata, not another spider type.
- Avoid a hard switch from 9 to 460 unattended. First canary a small reviewed tier, then 15-ID candidate batches pinned to manifest version. The original 451 candidates have now been crawled once, but one pass does not validate them.
- If `cohort=all` is desired for periodic jobs, require written resolution of policy blockers, source triage and acceptance thresholds. Keep a “run once” testing option distinct from “run unattended”.
- Do not enable Zyte API rendering, browser add-ons, residential proxies or other paid features without approval.

## 9. Deployment, rollout, rollback and operating runbook

### Before each PR merge

1. Read current `main` head and open PRs; rebase if the source registry moved.
2. Run `python -m pytest -q` and `scrapy list` on supported Python/Scrapy versions. Validate packaged egg, manifest and exactly three registered spiders in CI.
3. Run offline replay on minimal golden fixtures. For the affected category, replay owner's previous Items in a **read-only** staging process with current and old baseline snapshots.
4. Provide a PR note with **before/after** precision, count, Item size and memory measurements; include any remaining unsupported source formats.
5. Merge only after passing CI; verify the corresponding **GitHub commit/deployment ID in Zyte Code & Deploys**. A GitHub pass alone is not proof the hosted job runs new code.

### Canary sequence after each relevant deployment

1. Run each affected spider with explicit `cohort=proven` and inspect the log text. Expected: **3 selected sources** for that category, plus separate robots requests. The original `proven` group includes **Gemini pricing, which is currently only partial**; treat it as a test fixture, not as a verified pricing dataset.
2. Run known repaired IDs explicitly (e.g., `source_ids=cursor_changelog`) and review event count, dates, source links and hash stability.
3. Test the next reviewed 15-source batch with a **manifest-pinned source-ID set**. Compare quality with the October 31 snapshot, ensuring failures are not hidden by old successes.
4. Repeat a second run when content and access status are stable. Promote **collection eligibility** only after source-owner, policy and extraction requirements are met. Never automatically approve facts.
5. Record runtime, rate limits, memory, item sizes, retry reasons, robots health, and vendor/source content changes.
6. If a regression changes date precision, price units, section identity, or permitted redirects: **roll back the Zyte deployment**, retain audit artifacts and mark affected snapshots untrusted. The old verified fact ledger (if implemented later) must not be overwritten.

### Explicit go/no-go gates

**GO for a controlled unattended source subset** only when:
- Request scope and deployment version are proven;
- source access/policy is resolved;
- newest release extraction and price units pass targeted tests;
- no false publication-date inference remains in the release-gold examples;
- comparable state and archival replay are reliable;
- the job-quality summary meets agreed target for **eligible** sources;
- downstream review gates remain enforced.

**NO-GO for automatic advisor updates** until a **separate** reviewed-fact publishing component exists, with approval, validity periods, provenance, supersession and rollback. This crawler repo does not have that component today.

## 10. Proposed milestone / PR backlog

| Order | PR / milestone | Priority | Dependencies | Deliverable / release gate |
|---:|---|---|---|---|
| 1 | Run-scope protection and telemetry | P0 | None | Can't accidentally run all; explicit per-job manifest/scope provenance |
| 2 | Changelog event parser | P0 | 1 | Correct dated recent releases for Cursor/Render/xAI/OpenAI/Kiro |
| 3 | Large-page bounded recent capture | P0 | 2 | Claude Code/Codex/Antigravity and Supabase usable without false completeness |
| 4 | Pricing table and rate evidence engine | P0 | 1 | Gemini/Bedrock/OCI no longer silently incomplete |
| 5 | Documentation source mapping and product checks | P1 | 1 | Kiro and overview-only docs correctly scoped |
| 6 | Source lifecycle, safe redirects and robots review | P1 | 1, 5 | Triage 65 canonical, 23 redirects, 11 HTTP errors, v0 429 |
| 7 | Job archive + semantic diff + review exports | P1 | 2, 4 | Replayable snapshots; release/rate deltas without false “new” |
| 8 | Expanded golden tests + staged operations | P0/P1 | all above | CI quality gates, measured canary results and rollback runbook |

**Suggested minimum viable reliable stage:** PRs **01–04**, plus enough of PR 07 to keep comparable archives and event/rate diffs. Repair high-priority source URLs immediately as they block tests; do not delay the whole project for all 460 URLs to become fully supported.

Do **not** add a RAG system, vector database, generalized agent framework, autonomous source discovery or LLM approval to this collection-layer milestone. Those would increase cost and uncertainty without fixing inaccurate dates and pricing.

## 11. Exact engineer handoff / definition of done

When an implementing agent begins, it should:

- Work from the repository's actual current `main`, not from this document as if all proposed files already exist.
- Create one branch per milestone/PR and keep each diff narrow, testable and reversible.
- Use the October 31 audit as the initial failure inventory; for every resolved failure, provide a regression fixture and a measured before/after outcome.
- Preserve every source ID, schema migration compatibility, the three spider names and no production writes.
- Never reinterpret missing data as a negative fact or an outdated feature. Keep raw vendor evidence untrusted, never follow prompt instructions embedded in it.
- Prefer deterministic extraction and clear `unknown` states. An LLM may suggest a candidate summary in a later reviewed pipeline but must not silently generate release dates or pricing values.
- Prove the deployment/Scrapy Cloud execution matches the tested commit, then test with exact bounded source IDs.
- Ship an explicit quality report showing source-accounting completeness, verified date precision, price-unit accuracy, recent-window completeness, policy health, false novelty rate and outstanding exclusions.
- Do not switch periodic schedules to `cohort=all` or publish into AgentFuse until the go/no-go checklist above passes.

**Definition of done for this plan:** The same three Zyte spiders repeatedly produce *traceable, bounded, current-source observations*; accurately recognize individual recent releases and precise pricing evidence for approved provider scopes; emit explicit unknown/partial/error states elsewhere; provide reproducible archives and semantic diffs; and cannot make an unverified claim appear as an approved recommendation.

## 12. Reference documentation

Primary current code and test references:
- `agentfuse_crawlers/extract.py`, `quality.py`, `sources.py`, `spiders/official.py` and `settings.py`
- `agentfuse_crawlers/extensions/coverage.py`
- `scripts/compare_exports.py`, `scripts/download_zyte.py` and `scripts/plan_validation.py`
- `.github/workflows/validate.yml` and `ARCHITECTURE.md`
- Owner-provided October 30 and October 31 Zyte Items, Requests and Logs, and `agentfuse_zyte_460_source_audit_2026-10-31.json` (private/local evidence, not copied into this public plan)

Relevant upstream official references:
- Scrapy 2.18 stats and lifecycle: https://docs.scrapy.org/en/2.18/topics/stats.html
- Scrapy signals and item accounting: https://docs.scrapy.org/en/2.18/topics/signals.html
- Zyte Jobs API: https://docs.zyte.com/scrapy-cloud/usage/reference/http/jobs.html
- Zyte job metadata: https://docs.zyte.com/scrapy-cloud/usage/reference/http/jobmeta.html
- Zyte Items API, pagination and Item size behavior: https://docs.zyte.com/scrapy-cloud/usage/reference/http/items.html
- Zyte Items downloads: https://docs.zyte.com/scrapy-cloud/usage/items/download.html
- GitHub official releases API: https://docs.github.com/en/rest/releases

**Status at preparation:** Implementation plan only. The running spiders, Zyte schedules, source registry, production database and recommendation engine remain unchanged by this document.
