# Phase 4A — Exact source decisions and operator handoff (2026-11-27)

Base: `9f8e5492a08775ff20e17e4b10c4dc81ac34bc20` (PR #123). This is a source-review decision record, not a new planner, a legal opinion, a source-access registry, or a launch authorization. No package code, manifest, lifecycle, containment, authorization or workflow changes.

## Actual evidence check

The operator's November 26 private supplement contains 13 documentation claims and 12 price candidates from three independent official repository snapshots. On November 27, fetched the ten referenced files as base64 bytes at the exact supplied commits, decoded them, and independently recomputed Git blob SHA-1 over the Git header and raw bytes. All ten matched the supplied and returned blob IDs. Also inspected all 25 cited source-line spans, including Fly.io's currency, region and 30-day runtime context. This proves evidence traceability, not independent factual accuracy, effective pricing, exhaustive coverage, or legal clearance.

| Pinned public reference | Verified source blob | Additional verified files |
| --- | --- | --- |
| [Vapi introduction](https://github.com/VapiAI/docs/blob/b5d721e0e7f41673c45bfef24eb8652121387167/fern/quickstart/introduction.mdx) | `70ce6783fedd04788cfd788b7e2f194c2246c191` | LICENSE, README |
| [Fly.io pricing](https://github.com/superfly/docs/blob/eea4acfe680eebda43c19f4d1119e7db5d469e90/about/pricing.mdx) | `251ed270d06106136c7153d986a8b52133aa440d` | LICENSE, README |
| [LangWatch introduction](https://github.com/langwatch/langwatch/blob/991057c617c8e4e9aac1fa770b7775e52e2aba09/docs/introduction.mdx) | `bf4218c6ba6f27a50a7676e4c01b62e97281b5fa` | LICENSE.md, NOTICE, docs/README.md |

MIT/Apache-2.0 license and notice boundaries remain separate from hosted-site collection permission. The Fly.io numbers are conditional candidate rates, not normalized quotes. No raw files, publisher content, private operator supplement or actual review records are committed. These 25 observations are already in the supplement, not 25 additional observations acquired today.

## Disposition of the previous candidate pool

The PR #121 25-target proposal had 18 documentation, 5 pricing and 2 changelog sources. The supplied supplement recommends deferring both Braintrust sources because exact website archival clearance is not established. Current public reference review identifies four more conservative deferrals:

| Source ID | First-party policy | Reason |
| --- | --- | --- |
| vast_ai_docs | [Vast.ai terms](https://vast.ai/terms), version September 1, 2026 | Prohibited activities 7, 10 and 18 explicitly address automated retrieval, database/index creation and pricing comparison; obtain applicable written permission before reconsidering. |
| voyage_ai_docs | [Voyage AI terms](https://www.voyageai.com/tos), section 9 | Restrictions on automated acquisition and copying; exact documentation applicability or an explicit permitted mechanism must be resolved. |
| valyu_docs | [Valyu platform terms](https://platform.valyu.ai/about/terms-of-service), section 7 | Automated extraction and systematic retrieval for databases restricted; determine current applicable docs-specific terms and rights. The third-party Contents API AUP does not grant rights over Valyu's own docs. |
| letta_pricing | [Letta terms](https://www.letta.com/terms-of-service/), sections 5 and 9 | Broad site scope and limited license for use of services; no affirmative commercial archive/reuse clearance identified. The open-source Letta code license is not a license to its hosted pricing page. |

Braintrust: [terms](https://www.braintrust.dev/legal/terms-of-service), defer `braintrust_docs` and `braintrust_changelog` as recorded in the private supplement. These six are recommendations to exclude from the proposed continuation, NOT signed registry decisions or retroactive changes to any previously acquired observation. No retry through alternative transport.

The narrowed pending review pool is 19 (14 docs, 4 pricing, 1 changelog). It is not an independently reviewed or approved run scope. Every proposed URL differs from its original manifest URL. The prior 13 missing hold dispositions applied to the older 25-target pool; do not reuse that count for this subset until replaying the actual historical inventory. No historical hold is released.

| Category | Source ID | Proposed exact reference URL (not activated) |
| --- | --- | --- |
| changelog | gemini_api_changelog | https://aistudio.google.com/docs/changelog |
| pricing | gemini_api_pricing | https://aistudio.google.com/docs/pricing |
| pricing | fly_io_pricing | https://docs.fly.io/about/pricing |
| pricing | mintlify_pricing | https://www.mintlify.com/pricing |
| pricing | make_pricing | https://www.make.com/pricing |
| documentation | friendliai_docs | https://friendli.ai/docs |
| documentation | lunary_docs | https://docs.lunary.ai/get-started |
| documentation | mintlify_docs | https://www.mintlify.com/docs |
| documentation | relevance_ai_docs | https://relevanceai.com/docs/get-started/introduction |
| documentation | blaxel_docs | https://docs.blaxel.ai/Overview |
| documentation | greptile_docs | https://www.greptile.com/docs/introduction |
| documentation | leonardo_ai_docs | https://docs.leonardo.ai/docs/getting-started |
| documentation | linkup_docs | https://docs.linkup.so/pages/documentation/get-started/introduction |
| documentation | maxim_ai_docs | https://www.getmaxim.ai/docs/introduction/overview |
| documentation | resemble_ai_docs | https://docs.resemble.ai/welcome |
| documentation | retell_ai_docs | https://docs.retellai.com/general/introduction |
| documentation | tavus_docs | https://docs.tavus.io/sections/introduction |
| documentation | vapi_docs | https://docs.vapi.ai/quickstart/introduction |
| documentation | vellum_docs | https://docs.vellum.ai/home/getting-started/overview |

All URLs originate from the Phase 3B candidate table. Other than specific observations below, this pass did not individually refresh the other pending targets' page, terms or robots evidence. The remaining 19 could yield at most 19 new HTTP 200s (219 cumulative), not a forecast. A target of 250 would need at least 31 further successes beyond this pool; do not pad or bypass holds to reach it.

## Highest-value concrete source-format finding

Google's [official agent documentation](https://aistudio.google.com/docs/coding-agents.md#machine-readable-docs) explicitly supports same-URL Markdown content negotiation, direct .md endpoints, documentation indexes and a documentation MCP server. The web reference service returned `text/markdown` for the proposed Gemini pricing and changelog URLs, including publisher template syntax and dated release-note headings. This is not a measured response to the Scrapy Cloud crawler's actual request headers/UA. Existing `parse_page` rejects non-HTML primary responses; `markdown_releases.py` supports a specific Claude Code version-heading alternate, not Gemini's date-heading format. Do not migrate either Google source without validating the intended primary response representation. HTML may still be served by normal browser negotiation; do not implement a speculative Markdown parser or turn on alternate requests. The separate `gemini_api_docs` ID was outside the 25-target pool; resolve its actual product/canonical scope separately.

Machine-readable access is a positive signal of intended agent consumption, NOT clearance to archive and reuse for AgentFuse. The [developer site policies](https://developers.google.com/terms/site-policies) explain the CC BY notice for covered pages; the two retrieved Markdown references did not contain that notice. The [Gemini additional terms](https://aistudio.google.com/docs/terms) and applicable general terms must also be assessed. Current robots for the exact AI Studio host could not be inspected through the reference tool. No current AgentFuseResearchBot-specific robots decision, retention review, source approval, or new acquisition is established. Prioritize these two targets for accountable review because they cover pricing and changelog for a core provider.

Vapi and Fly.io remain pending hosted-source review; the separately licensed snapshots above can support factual review without rerunning the hosted URL. LangWatch remains outside the pending hosted pool. The current Blaxel legal landing page links terms dated December 10, 2025; an earlier indexed terms PDF is not sufficient to determine current policy. The inspected Blaxel public docs repository tree did not establish an explicit license. The Temporal documentation tree did not identify a corresponding changelog/release-notes file for `temporal_changelog`; no unrelated SDK release is substituted. The inspected Letta code repository did not identify an exact pricing document. These repository leads are not new source acquisitions.

## Stop condition and next operational step

Both installed strict registries remain empty. The exact crawler-UA robots resources for Google AI Studio, Vapi, Fly.io, Vellum, Retell, Tavus and Linkup were unavailable to the reference tool; this is not a verified denial or a permitted missing robots file. No new primary or paid Zyte request was made.

Do not add another generic source-review framework, count reference-tool fetches as Zyte results, or keep opening speculative parser PRs. The remaining step is actual applicable source access/retention decisions and exact hold disposition by an accountable operator. Narrow the candidate pool to sources with demonstrated permission, preserve the historical 460 identities, and reuse the existing P21B/P26A/Phase 3C preparation. Only after genuine review can the exact URL migrations and scope plans be installed. Run the existing no-crawl dashboard preflight on the eventual package, verify remote deployment identity and the existing G2 read-only account snapshot, then approve a small cross-category live validation. No broad new job until these gates pass. If access evidence remains unavailable, report the resulting coverage limit; production factual adjudication and separately licensed sources can proceed independently.

Current: 200 historical HTTP 200s, 0 new Zyte successes, 0 installed access reviews, 0 installed strict plans. NO-GO. No full CI rerun was performed in this research pass; no deployable code or data changed.
