# Phase 3B — Public reference research and canonical migration decisions

Research date: 2026-11-26. Base manifest SHA-256:
`231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933`.

This records actual research on the 60-source Phase 3A priority pool. It is
not an access authorization, legal opinion, crawler response, manifest
replacement or signed source review. All twelve original export fingerprints
and 31 historical redirect Item/Request pairs were checked against the
private evidence. The per-source research packet, evidence indices and
uncompleted review worksheet remain private. This document contains only
aggregate findings, public reference URLs and review recommendations.

## Outcome

| Recommended next action | Count |
| --- | ---: |
| Review same-origin URL migration | 15 |
| Review cross-origin URL migration | 13 |
| Review unchanged URL | 2 |
| Exclude pending permission/access resolution | 12 |
| Defer unreadable reference | 12 |
| Resolve product/page scope | 6 |
| Total | 60 |

46 readable public references, 10 unavailable references, two 403 responses
in the reference service, and two pages without readable content.
Public-reference snapshots have displayed crawl ages ranging from today
to six months. These are not fresh Zyte responses or proof of the actual
crawler's UA-specific robots decision. Of the 60 sources, 18 have preliminary
policy research (10 restriction/permission issues, three conditional
Google terms/license checks, five policy links without clearance).
The remaining 42 have no applicable terms review in this pass.

## Exact candidate URL decisions — REVIEW ONLY

These URLs are candidates because public reference evidence corresponds to
the intended page type and product at a preliminary level. They are not
approved crawl targets. For every changed origin, independently verify the
publisher relationship, access policy, exact path, format and applicable
robots. For every existing held group, obtain and document the disposition
before admission. Do not follow redirects to reach these URLs.

| Source ID | Proposed reference URL | Action |
| --- | --- | --- |
| braintrust_changelog | https://www.braintrust.dev/docs/changelog | unchanged |
| weights_biases_weave_pricing | https://wandb.ai/site/pricing/ | unchanged; preserve Weave pricing scope |
| gemini_api_changelog | https://aistudio.google.com/docs/changelog | cross-origin; observed Markdown |
| braintrust_docs | https://docs.braintrust.dev/ | cross-origin |
| friendliai_docs | https://friendli.ai/docs | cross-origin |
| hyperbolic_docs | https://www.hyperbolic.ai/docs/overview/overview | cross-origin |
| langwatch_docs | https://langwatch.ai/docs/introduction | cross-origin |
| lunary_docs | https://docs.lunary.ai/get-started | cross-origin |
| mintlify_docs | https://www.mintlify.com/docs | cross-origin |
| relevance_ai_docs | https://relevanceai.com/docs/get-started/introduction | cross-origin |
| you_com_api_docs | https://you.com/docs/welcome | cross-origin |
| fly_io_pricing | https://docs.fly.io/about/pricing | cross-origin |
| gemini_api_pricing | https://aistudio.google.com/docs/pricing | cross-origin; observed Markdown |
| letta_pricing | https://docs.letta.com/pricing | cross-origin |
| mintlify_pricing | https://www.mintlify.com/pricing | cross-origin |
| make_pricing | https://www.make.com/pricing | same-origin |
| ai21_labs_docs | https://docs.ai21.com/home | same-origin |
| blaxel_docs | https://docs.blaxel.ai/Overview | same-origin |
| greptile_docs | https://www.greptile.com/docs/introduction | same-origin |
| leonardo_ai_docs | https://docs.leonardo.ai/docs/getting-started | same-origin; second redirect |
| linkup_docs | https://docs.linkup.so/pages/documentation/get-started/introduction | same-origin |
| maxim_ai_docs | https://www.getmaxim.ai/docs/introduction/overview | same-origin |
| resemble_ai_docs | https://docs.resemble.ai/welcome | same-origin |
| retell_ai_docs | https://docs.retellai.com/general/introduction | same-origin |
| tavus_docs | https://docs.tavus.io/sections/introduction | same-origin |
| valyu_docs | https://docs.valyu.ai/home | same-origin |
| vapi_docs | https://docs.vapi.ai/quickstart/introduction | same-origin |
| vast_ai_docs | https://docs.vast.ai/guides/get-started | same-origin |
| vellum_docs | https://docs.vellum.ai/home/getting-started/overview | same-origin |
| voyage_ai_docs | https://docs.voyageai.com/docs/introduction | same-origin; second redirect |

The 30 candidate URLs are unique and did not collide with the original
460 configured URLs under another source ID in the private review.
This is a metadata consistency check, not evidence of allowed access.

## Exclude or defer

Ten source IDs have published terms that restrict the relevant activity or
require permission whose applicability to the exact public page needs
review. Exclude them from the proposed automated continuation pending
applicable permission. Do not interpret a search-engine exception or a
documentation link as commercial archival permission.

| Source ID | Public policy reference | Preliminary reason |
| --- | --- | --- |
| canva_developers_pricing | https://www.canva.com/policies/terms-of-use/ | Service/content scraping restriction, effective November 16, 2026 |
| pipedream_docs | https://pipedream.com/terms | Sections 4.3/4.4 restrict scraping and archival/reuse |
| parallel_web_apis_docs | https://parallel.ai/terms-of-service | Website crawling and significant content storage restrictions |
| cartesia_docs | https://www.cartesia.ai/legal/terms | Section 4.2 service extraction and unauthorized interaction restrictions |
| mem0_docs | https://mem0.ai/terms | Internal-use documentation grant and automated extraction consent restriction |
| agentops_docs | https://app.agentops.ai/tos.pdf | Indexed app-terms excerpt restricts automation; exact docs scope not established |
| featherless_ai_docs | https://featherless.ai/legal/terms-of-service | Extraction restricted unless permitted under terms |
| gladia_docs | https://www.gladia.io/general-terms-of-use-gladia-inc | Site/service automated access restriction; applicable entity needs review |
| fish_audio_docs | https://fish.audio/enterprise-terms/ | Enterprise service extraction restriction; public-docs applicability unresolved |
| bland_ai_docs | https://www.bland.ai/legal/terms | Automation requires permission; no docs-specific clearance established |

CodeSandbox documentation and pricing both returned 403 in the reference
service. Do not retry through alternate transport. These are new research
findings, not historical Zyte barriers or signed lifecycle changes.

Defer unreadable references: cloudinary_ai_changelog, temporal_changelog,
arize_ai_phoenix_docs, brave_search_api_docs, runware_docs, sentry_seer_docs,
tripo_ai_docs, stability_ai_pricing, neon_postgres_docs,
novita_ai_docs, posthog_ai_observability_docs, zapier_docs. An unavailable
reference is not necessarily a denied publisher or failed live crawl.

Resolve product/page scope before proposing a URL: gemini_api_docs
(older reference and inconsistent host migration), tripo_ai_pricing
(Studio rather than API rate card), daytona_docs (v0 vs v2),
helicone_docs (quickstart vs overview), luma_ai_docs (Dream Machine vs
newer Luma API docs), snowflake_cortex_ai_docs (Cortex vs broader AI/ML
overview). Canva's product mismatch is separately recorded in the
policy exclusion above.

## Review priorities and decision

The maximum additional HTTP 200 yield from the 30 remaining candidate
URLs is 30, not a forecast. At the existing historical 200 HTTP 200 sources
this is a conditional ceiling of 230. At least 20 additional successes
outside this group would still be required for 250; at least 70 for 300.
Even resolving all 18 page/scope deferrals would not guarantee 250.
Do not manufacture permissions, refetch successes simply to reach the P25
fresh-run target, or automatically release holds.

Google's [terms](https://policies.google.com/terms?hl=en-US) require
compliance with machine-readable restrictions, and [developer site
policies](https://developers.google.com/terms/site-policies) describe
CC BY 4.0 reuse for pages actually carrying the notice. Confirm exact page
notice, new-host terms, attribution and current robots before reuse. The
new AI Studio robots reference was unavailable; the old ai.google.dev
robots reference was five months old. The [Braintrust terms](https://www.braintrust.dev/legal/terms-of-service),
[Fly.io terms](https://www.fly.io/legal/terms-of-service/),
[Blaxel terms landing page](https://blaxel.ai/legal/terms), and
[Greptile terms](https://www.greptile.com/terms-of-service?format=markdown)
are preliminary policy links, not positive access or retention findings.

No executable manifest change now. A real approved migration must update
the exact manifest bindings, any source-specific profiles, lifecycle
records where relevant, and source reviews and plan hashes; check
containment group recalculation and content-type compatibility. Retire or
leave historical-only the old public diagnostic/resume and G3/P25 pins
rather than silently expanding them. Preserve the historical checkout
at `0bb1707806b6c95e0159b450508ba192315f9f15` for original export replay.
Use the existing strict P21B reviewed-subset full-category plan mechanism
once accountable exact-source attestations are available.

Both installed strict access and bulk-plan registries remain empty.
No URL activated, no hold released, no new primary request authorized,
no fact approved. Next work is real terms/robots/retention review and
migration/authorization decisions on the 30-source pool, followed by
additional high-value held sources where permission can be established.
Do not add another generic crawler or review framework merely to advance
a phase label.
