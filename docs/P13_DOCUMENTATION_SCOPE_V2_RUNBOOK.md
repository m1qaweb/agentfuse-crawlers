# P13 — Documentation scope v2: source-specific evidence and safe review

## Audit issues addressed

The November 1 full-inventory validation found **194** documentation Items:
48 captured, 129 needs_review, 17 other source outcomes. Of HTTP 200
documentation pages, many had scope not established, and 56 had canonical
path mismatches; 33 had both issues. Kiro returned no substantive
documentation content and Google Cloud's pinned URL had a product-scope
mismatch. These are **historic audit observations**, not a new live test.

## What changed

- Curated exact-URL provisional profiles expanded from 22 to 64, with
  product identity words used to prevent source-to-product drift. These
  markers are weak lexical checks and do not independently prove identity,
  much less that a feature is available.
- Each technical topic candidate must have substantive visible prose under
  *the same heading* and match the curated profile's intended topic list.
  Navigation labels and unrelated paragraphs do not prove a capability.
- Documentation parser revision \`docs_scope_v2_review_links\` and each
  source-specific SHA-256 profile digest establish a NEW comparison baseline
  after changes to product purpose or classification; no false "feature
  added" reports from old archive versions.
- Retain bounded metadata about page scripts/app mounts and distinguish
  \`javascript_shell_suspected\` from short static HTML. Kiro is NOT solved
  by adding an unsupported browser mode or guessing alternate URLs.
- Extract up to 24 **unapproved** child-page link candidates from original
  publisher HTML, including navigation before it is stripped for topic
  extraction. The review set is restricted to the original exact host and a
  narrow same-family path prefix. Roots, unrelated products, off-host
  targets, query strings, fragments and percent-encoded ambiguities cannot
  become candidates. Child pages are NEVER fetched or considered a corpus.
- Preserve existing same-host canonical triage and add explicit manual
  migration status. Never follow or rewrite a path just because a publisher
  canonical suggests it, and especially never equate other products.
- Enhance run diagnostics with independent reasons for JavaScript-only
  pages, child-link reviews, canonical migration and bounded navigation
  omissions.
- Tighten comparison/health rules for new parser Items: explicit product
  marker, no known product-scope mismatch, no canonical migration, observed
  static text. Existing unverified source Items remain review-only.

## Offline report (no network / credentials)

Export one or more Zyte Items JSON arrays, then execute:

    python -m scripts.triage_documentation \
      --items items_official_documentation_10.json \
      --out-dir output/p13-docs-triage

Creates \`summary.json\`, \`source_triage.csv\` and
\`review_only_child_links.csv\`. It reports exactly which source IDs were
included, any missing IDs from the 194-source documentation manifest and
actions for operators. The child CSV is **not** a new crawl manifest. URL
validation runs again before export and rejects malicious/unapproved links.

## Manual rollout and source-quality validation

1. **Merge P12 mainline repair PR #27 first.** P13 is stacked on its branch.
   Retarget P13 to main only after P12 is present on main; rerun Python
   3.12 / 3.14 CI before merging.
2. Review package fingerprints, fixed manifest (460), three spiders, source
   lifecycle exclusions, publisher robots controls, and no new network
   requests. Never assume merged means deployed.
3. Deploy only after the operator reviews the Zyte settings, and run
   pinned one-source validation jobs, e.g.:
   - \`source_ids=kiro_docs\` — determine whether the main page is genuinely
     empty, JavaScript-only, a navigation-only index, or an access issue.
   - \`source_ids=google_cloud_ai_docs\` — independently verify intended
     product name and canonical migration; do not assign broad Vertex AI
     capabilities to a different product.
   - \`source_ids=aws_bedrock_docs\` — inspect technical paragraph
     corroboration and child link path boundaries.
   - \`source_ids=openai_api_docs\`, \`source_ids=pinecone_docs\` — verify
     intended overview and provisional profile recognition.
   Use \`cohort=all\`, \`collection_mode=validation\`, and only source IDs
   already approved by the source lifecycle policy.
4. Capture all Items/Requests/Logs and archive immutable run records.
   Compare against the Nov 1 baseline, using a new parser baseline.
5. A domain/path-matched child URL MUST be independently approved for
   robots, publisher restrictions, product scope, and stable canonical
   ownership before *separately* proposing it to the source manifest.
   That would be a future explicitly reviewed PR, never automatic.
6. Independently label real technical documents and actual product-specific
   capabilities before downstream advisor use.

## Known limitations

- One source page ≠ complete documentation corpus.
- HTML-only link discovery cannot expose client-side routes invisible in HTML.
- Exact marker presence is only a source-label hint, not semantic identity
  proof; contradictions and cross-product claims need human checks.
- Code-only pages without 12-word prose paragraphs may be conservatively
  downgraded until a separate structured code/reference extractor exists.
- Root docs portals have no safe same-family path boundary and therefore
  yield no automatically suggested child URLs.
- An Item may be \`captured\` yet still NOT have a verified publisher claim.
- No original Zyte jobs were run by these PRs, and accuracy needs live canary
  review.

P13 does not change the source inventory, publisher access policy,
Zyte schedule/deployment, source lifecycle promotion, Supabase/AgentFuse
database, or automated price/release/advisor approvals.
