# PR06 — Source lifecycle, robots safety and source triage

**State:** Draft implementation. No live Zyte runs, schedules, official URLs or AgentFuse production databases changed.

## What changed

- Exactly 3 original spiders and 460 original URLs remain. A companion lifecycle registry is pinned to each source ID and its exact HTTPS URL.
- All unlisted URLs default to **needs_validation**. A historical "proven" crawl cohort is **not** publisher-permission approval.
- The October 31 audit reported unresolved robots.txt HTTP 429 for v0.app. **v0_docs, v0_pricing, v0_changelog** are quarantined until independently reviewed. Neither broad inventory runs nor explicit source IDs can fetch a quarantined URL.
- Known empty HTML (kiro_docs) and Google Cloud product-scope mismatches are marked **degraded**. They may be tested in validation mode but cannot enter approved monitoring.
- New spider argument **collection_mode=validation|monitor** defaults to **validation** for backward compatibility. Monitor mode schedules only human-approved sources with official first-party publisher-policy evidence, product scope and two distinct reviewed Zyte job IDs. **Today zero sources qualify**, by design.
- Each suppressed network request still emits one source-summary Item (source_quarantined, source_retired, source_not_validated_for_monitor), with null HTTP status and the registry revision. Run metrics distinguish source accounting from usable evidence.
- Pinned validation plans record the manifest AND lifecycle-registry revisions and reveal policy-skipped URLs.
- The offline triage script generates review tasks for genuine errors without inventing official redirects or prices.

## Operator workflow

Run the source reviewer offline using previously downloaded Zyte Items (JSON or JSONL):

    python -m scripts.triage_sources --exports output/zyte/documentation.json output/zyte/pricing.json output/zyte/changelogs.json --out-dir output/source-triage

Outputs: source_review_queue.csv, source_review_queue.json and triage_summary.json. Each source ID has one row; sources not found in the provided files remain explicitly **unobserved**. Automatically approved sources always equal zero.

Generate pinned validation batches:

    python -m scripts.plan_validation --cohort candidate --batch-size 15 --out-dir output/validation-plan

Use expected_manifest_sha256, expected_selection_ids_sha256 AND expected_source_registry_sha256 when scheduling a targeted validation. Validation mode is not approval. Explicit cohort=all without IDs still requires confirm_full_inventory=yes.

## Human source review lifecycle

Discovered -> needs_validation -> validated_for_collection; with degraded, quarantined and retired states. HTTP 200 alone never promotes a source. A reviewer must establish:

1. First-party ownership of the exact intended product and URL.
2. Publisher robots.txt/terms permit collection; an unresolved HTTP 429 is NOT permission.
3. Correct product scope, meaningful data extraction and release/date/pricing precision where relevant.
4. Two distinct, stable completed Zyte captures with traceable job IDs.
5. Named human reviewer, timestamp, official ownership URL and policy evidence URL, reviewed in Git.

Only then may a PR set state=validated_for_collection AND policy_status=allowed_reviewed. This approves collection only; source facts remain unverified for the AgentFuse advisor.

Never bypass a restriction with proxies, identity rotation, login workarounds or paid browser rendering. Resolve policy before lifting v0 quarantine. Review official cross-host migrations separately and update fixed manifest URLs only in Git.

## Remaining known issues

The October 31 audit found 65 canonical-path differences, 23 cross-host redirects, 11 HTTP source errors, 19 pricing pages without visible billing, 16 insufficient-text pages and 14 long-CDN-Age observations. This PR adds exact-source triage tooling but **does not assert these historical cases have already been repaired**. Re-run analysis on the owner's archived Items, Requests and Logs before closing review tasks.

Priority sources: v0_app policy blockers, kiro_docs empty HTML, Google Cloud / Gemini Enterprise Agent Platform scope ambiguity, year-pinned changelog paths and official GitHub releases that require ownership confirmation.

## CI, canaries and rollback

Before merging: run 'python -m pytest -q', 'scrapy list' and build the Scrapy Cloud egg. Expect exactly three spiders, 460 unmodified IDs, no outbound request for quarantined sources, one source-summary Item per selected source and zero advisor approvals.

Run targeted source IDs first with collection_mode=validation and pinned manifest/registry hashes. Verify the actual Zyte deployment SHA after controlled deployment. Monitor mode currently schedules no network source requests; this is the intended approval boundary.

Merging to main may trigger a separate Zyte deployment workflow. Coordinate schedules before merge and roll back if the new gating changes expected behavior. Never enable unattended cohort=all without individual source review.

No extra spiders, arbitrary source discovery, paid services, Supabase writes, live schedules, automatic approved facts or silent URL replacements.
