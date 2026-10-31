# PR05 — Documentation coverage, product scope and canonical review

**Status:** isolated PR branch. Offline code tests are necessary but do not establish live Zyte success. Requires PR04 integration before deployment.

## Why this exists

A successfully fetched docs landing page proves only that a particular URL responded. It does **not** prove that a product supports every feature mentioned in its navigation, or that the crawler covered the whole documentation hierarchy.

The October 31 audit observed 194 documentation sources, 75 review-needed captures, 11 rejected redirects, and 4 HTTP errors; `kiro_docs` was among the insufficient-text sources. The same audit counted 65 canonical-path warnings *across all categories*, not just documentation. None of those issues is automatically fixed by adding parser code.

## Implemented boundaries

- Continue using **only** `official_documentation` alongside the existing changelog and pricing spiders; all 460 source IDs and URL strings remain unchanged.
- `data/documentation_profiles.json` pins 22 high-priority documentation IDs to their existing official URL, provider, expected page purpose, product scope, topics to examine, and pending-validation status. **This is curation metadata, not a claim of vendor capability support.**
- `documentation_evidence_schema=1.0` emits observed page purpose, scope status, exact source-linked topical section excerpts/hashes, and separate unverified review state. Topic names mean **this section discusses the topic**, not that a feature is supported.
- `documentation_corpus_coverage=single_url_only` is always explicit. Overview/index pages are not comparable technical-capability coverage.
- Exact-URL profile mismatches, undersized HTML shells, link-only indexes, known ambiguous product scopes and incomplete evidence fail closed.
- Canonical classification distinguishes equivalent HTTPS same-host index/slash conventions from real same-host product/path changes and external/unsafe values. This **never grants an HTTP redirect**.
- Documentation section evidence is bounded (64 section summaries at 1,200 characters; 16 topical evidence candidates at 520 characters each). Additional serialized Item safeguards flag any budget-driven loss of tables or excerpts. Full source/section hashes are retained when possible.
- No source page, topic, price, release event or documentation string can become an approved advisor fact. All downstream recommendation publication remains out of scope.

## Known source work still requiring live validation

1. **Kiro:** `https://kiro.dev/docs/` returned no substantive text in the October 31 Zyte export. Inspect current response HTML, status, canonical and rendered DOM. Official Kiro guide `https://kiro.dev/docs/getting-started/first-project/` is a *possible separate scoped guide*, not a silent substitution for the documentation home. Its indexing in public search does not prove Zyte can fetch usable HTML. Do not add headless browsers or bypass access policies to force capture.
2. **Google Cloud:** `google_cloud_ai_docs` is mapped to a Gemini Enterprise Agent Platform path, while the manifest provider name is broader. The profile declares the exact path's product, but flags unresolved product scope until human review. Do not credit generic Vertex AI features to the narrower product.
3. **Canonical warnings:** the original 65 cases must be triaged against full source observations before approved changes to the manifest. Equivalent /index.html/slash routes may be normalized; cross-host and unrelated-product changes remain review.
4. **Unprofiled docs:** the other configured documentation IDs remain source observations and are not qualified as scoped capability references merely because text was extracted.

## Offline validation

Run after PR04 is present:

```bash
python -m pytest -q
scrapy list
python -m build --wheel
```

Assert exactly three spiders, all 460 manifest URLs preserved, 22 metadata profiles loaded, no raw-source fact approved, Kiro empty capture flagged, source-page/index distinctions, and Item size under the configured target.

## Safe live canaries (manual only)

Use the deployment/manifest/selection SHA recorded in PR01 run context and only exact pinned source IDs. Never enable unattended `cohort=all` to validate this change.

- `kiro_docs`: compare HTML and the configured source URL; verify a substantive page or keep `needs_review`.
- `openai_api_docs`, `claude_code_docs`: confirm these are landing/overview captures, not comprehensive API coverage.
- `aws_bedrock_docs`, `oracle_oci_generative_ai_docs`: inspect scoped topic candidates and source anchors without interpreting them as capability support.
- `google_cloud_ai_docs`: keep the explicit product mismatch review until intended scope is confirmed.
- A safe same-host canonical equivalence and a true different-product path: confirm only equivalence is suppressed.
- A large documentation page: confirm retention of hashes, explicit item-budget warnings, no invented extra facts, and one source-summary Item per requested ID.

**Go/no-go:** Unit tests and CI alone do not validate DOM freshness, publisher ownership, robots status, or real-world precision. Keep PR05 unmerged/unreleased until the canaries are reviewed and PR04 has been integrated safely.

**No changes:** live Zyte jobs/schedules, AgentFuse production DB, approved advisor facts, third-party proxy services, source URLs or spider count.
