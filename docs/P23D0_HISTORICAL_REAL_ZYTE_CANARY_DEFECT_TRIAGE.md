# P23D0 — Verified historical Zyte defects, not a new crawl

**Evidence date: November 4, 2026. Reviewed: November 7, 2026.**

This is an engineering triage of the user's nine authentic historical Zyte
Dashboard exports, not a current publisher fact, accuracy certification,
legal permission or a fresh crawl. All **nine original files** had the exact
SHA-256 hashes pinned in the existing P21A audit implementation
(scripts/audit_nov04_inventory.py). No raw HTML, pricing text, Logs,
request URLs, credentials or private original files are committed here.

## 1. Actual historical 460-source Items and request footprint

| Category | Items | Captured | Needs review | Partial | Redirect rejected | HTTP errors | Quarantined |
|---|---:|---:|---:|---:|---:|---:|---:|
| Documentation | 194 | 51 | 124 | 0 | 14 | 4 | 1 |
| Pricing | 177 | 0 | 158 | 1 | 11 | 6 | 1 |
| Changelog | 89 | 14 | 69 | 1 | 3 | 1 | 1 |
| **Total** | **460** | **65** | **351** | **2** | **28** | **11** | **3** |

**Captured is an Item diagnostic, NOT independently verified accurate or
complete data and not permission for use by AgentFuse.** Historical capture
percentages are not predictions of current site behavior.

| Category | Requests | Exact configured-source URLs | robots.txt URL requests | Other URL requests (mostly redirect chains) |
|---|---:|---:|---:|---:|
| Documentation | 463 | 193 | 198 | 72 |
| Pricing | 368 | 176 | 177 | 15 |
| Changelog | 161 | 89 | 70 | 2 |
| **Total** | **992** | **458** | **445** | **89** |

This URL classification counts exact source URL equality and robots.txt
path suffix only. It does NOT prove the other 89 URLs are permitted, or
that 992 historical HTTP requests imply any particular future billing,
budget, site rights or safe retry limit.

Original Items SHA-256 as already frozen by P21A:
- Docs: 9e8166b9bc43baf4efe60d95fb3f728f0374d16b9530fcff44aaadcb1e492e78
- Pricing: e55b786b3d7f9d8290432a343220e827e81e0beba4ad41651c9abe8e37b10663
- Changes: 3a06ffb552493e89ec04c76d0d4cac4a108b587a8b6bb7bd5e11b25e3cac188c

## 2. Three original Wave 1 pilot sources — observed November 4 blockers

| Original ID | Historical Item/status | First diagnostic reasons | Next human check |
|---|---|---|---|
| **kiro_docs** | needs_review / HTTP 200 | documentation_javascript_shell_suspected; documentation_insufficient_content; documentation_child_links_not_approved_for_crawl | Independently resolve Kiro/AWS rights first; if approved, inspect whether exact original URL still serves a JavaScript shell; never auto-fetch unreviewed child paths |
| **gemini_api_pricing** | rejected_redirect / HTTP 301 | cross_host_or_non_https_redirect; source_redirect_requires_review | Verify current canonical/ownership and permitted path; don't force or follow an unreviewed redirect in Zyte |
| **openai_api_changelog** | needs_review / HTTP 200 | release_event_identity_collision; source_product_alias_not_in_title; text_exceeds_capture_limit | Review release identities and dates against legally retained original HTML; do not accept an inferred latest-release claim |

P23D0 records these as **dated historical review hints only** in the
existing first-canary Actions artifact. They do not change the P23B
source-access decision, the original canary selection or the spider code.

Across the original preregistered 18 sources / 36 planned rounds, the
historical 18 source Items had **5 captured, 10 needs_review,
2 partial_capture, 1 rejected_redirect**. Of the six original pricing
sources, **zero** had a historical captured status. None of these
Items were independently verified human gold or permission evidence.

## 3. Next concrete phase — genuine source review, then one canary

The source-access registry and bulk-plan registry remain empty. The
initial Gemini rejected redirect, Kiro JS shell, and OpenAI release
collisions mean blindly running even the three pilot sources is
unlikely to resolve actual completeness and rights questions.

**FIRST REAL ZYTE JOB (not full):** after a human genuinely reviews
an exact source URL's site terms/robots/ownership/retention rights,
merge the per-source P23B decision, independently confirm the
deployed Zyte package fingerprint and budget, then manually run
ONE permitted source/round. Preserve the actual Items/Requests/Logs
and original HTML where licensed. Perform a second distinct round
only after real review and stop on 403/429, changed redirects or robots.

**FULL STAGED 460-ID INVENTORY, LATER:** only after genuine access
determinations for URLs actually to be fetched; real independently
reviewed two-round category canaries; evidence-driven parser fixes
P23D; P23E exact bounded authorization and P23F small-shard cost/error
checks. P23G must still account for **all 460** IDs, including
denied/unreviewed/held sources without sending those GETs.

Until then, **FULL ZYTE CRAWL: NO-GO**. Do not infer any
publisher license from this historical evidence.

Human review tracker: https://github.com/m1qaweb/agentfuse-crawlers/issues/85
