# P23C3C — Publisher policy research before the first real Zyte canary

**Research date: 2026-11-07. Status: NO-GO pending independent human decisions.**

This memo advances P23C3 by collecting first-party policy evidence for the
original P20A Wave 1 pilot subset. It does NOT grant publisher permission,
verify real Zyte deployment, start a live job, or approve any data for use.

## Source-specific policy findings

| Original frozen source | Public evidence checked | Unresolved issue and next action |
|---|---|---|
| **Kiro documentation** — kiro_docs | Public https://kiro.dev/docs/ links its footer **Site Terms** to the AWS Site Terms. The AWS Site Terms (June 4, 2025) contain strong restrictions on data mining, robots or similar extraction, copying and commercial reuse without separate permission. | **HOLD / elevated rights risk**. A human must confirm that the AWS terms apply to the intended kiro.dev access and whether a distinct license or explicit authorization permits the proposed Zyte crawl and HTML retention. A public documentation page is not consent. The robots file was inaccessible to the research browser. |
| **Gemini pricing** — gemini_api_pricing | The actual https://ai.google.dev/robots.txt was publicly readable on 2026-11-07. Its generic rule disallows URLs with an authuser query parameter; it does not contain a generic path disallow for the frozen unparameterized pricing URL. Google's Terms of Service, effective July 30, 2026, prohibit automated access that violates machine-readable instructions. | **HOLD / possible first rights-review candidate**, NOT authorized. Human still must verify service-specific terms, permitted method/user agent, current robots, source ownership, right to retain HTML/Logs, and any restrictions on commercial reuse and repetition. Do not request authuser variants. |
| **OpenAI API changelog** — openai_api_changelog | Official https://developers.openai.com/api/docs/changelog was publicly readable. OpenAI's public policy index distinguishes consumer terms from business/developer agreements. | **HOLD / applicable terms and robots unresolved.** The research browser could not verify the developers.openai.com robots file. Consumer service-use restrictions should not be assumed to determine the public docs policy without checking which terms apply. HTTP 200 or linked machine-readable docs are not grants. |

These three original sources are drawn from **18 frozen sources / 36 frozen
source-rounds**. A denied or unresolved source is NOT replaced.

## Specific first-party evidence URLs

### Kiro — investigate first because a restriction is visible

- Documentation source: https://kiro.dev/docs/
- **Site Terms linked by the Kiro docs footer:** https://aws.amazon.com/terms/
  See the LICENSE AND SITE ACCESS section.
- AWS Service Terms (Kiro is listed as an AWS service, but these do not
  themselves license public-docs scraping): https://aws.amazon.com/service-terms/
- Kiro software license (do not presume it covers all documentation):
  https://kiro.dev/license/
- Robots file: https://kiro.dev/robots.txt — **NOT verified here**.

AWS Site Terms state that the standard site-use license excludes certain
robots/data-mining/extraction tools and commercial exploitation unless
separately permitted. The linked terms are a substantial risk signal; a
human reviewer should verify their exact applicability to Kiro's docs
and any independent permission/license. Until then DO NOT run this GET.

### Google — robots accessible; rights still unresolved

- Exact pricing source: https://ai.google.dev/gemini-api/docs/pricing
- Robots observed: https://ai.google.dev/robots.txt
- General Google Terms of Service: https://policies.google.com/terms?hl=en
- Separate Gemini API service terms to examine for applicability:
  https://ai.google.dev/gemini-api/terms

A readable robots file with no general path disallow is **NOT** a grant of
scraping/reuse rights or private HTML retention permission. Only a human
review can resolve the actual intended usage and applicable agreement.

### OpenAI — docs public; robots/terms not verified

- Exact changelog source: https://developers.openai.com/api/docs/changelog
- Policy and terms index: https://openai.com/policies/
- Consumer Terms of Use (possible scope, not necessarily developer docs):
  https://openai.com/policies/terms-of-use/
- Robots: https://developers.openai.com/robots.txt — **NOT verified here**.

Do not assume different OpenAI agreements are interchangeable, nor infer
permission from the public changelog or the availability of Markdown views.

## Operator plan — use existing Issue #85, no more synthetic infrastructure

1. A **real human** checks the actual robots directives (intended crawler
   user agent and exact path), site/service terms, ownership, and whether
   the proposed source requests plus private original HTML retention and
   commercial derived-data reuse are allowed.
2. Kiro's linked AWS restrictions require particularly careful resolution.
   Without appropriate permission, leave Kiro held or explicitly deferred.
   The best first *review* candidate may be Gemini, but this is not an
   authorization to crawl Gemini.
3. For each source, record a genuine permitted/deferred/denied outcome
   supported by first-party evidence and named human review. A positive
   decision belongs in a SEPARATE reviewed Git PR under
   agentfuse_crawlers/data/validation_access_reviews.json, with exact
   source URL, category, single_validation scope and expiry <=30 days.
   Never copy fabricated permissions from synthetic test fixtures.
4. Independently verify actual Zyte installed package fingerprint and
   source-specific budget. Manually run **only ONE bounded exact source
   canary**, if allowed. Stop on 403/429, robots/CAPTCHA, or an unreviewed
   redirect. Archive actual Requests/Logs/Items and original HTML if
   permitted. Repeat as a distinct real second-round job only if safe.
5. Replay existing P23C1/P23C2 and independent P22A2/P22A3 human quality
   reviews against the actual publisher evidence. Fix parsers in P23D
   based on observed failures, not on synthetic success.

## Precisely WHEN a full Zyte crawl is needed

The project census is **460 IDs: 194 documentation, 177 pricing, 89
changelog**. A full inventory campaign accounts for ALL 460 IDs; it
does NOT mean issuing 460 GETs to unreviewed publishers.

The operator should start the first full-inventory shard ONLY AFTER:

- Genuine source-specific access/retention decisions exist for EACH URL
  that will actually be fetched; all others stay held and counted.
- At least two distinct rounds of genuine original-category canary jobs
  have real archived Items/Requests/Logs and privately captured original
  publisher HTML where rights allow, and the findings have been independently
  reviewed for product/date/price accuracy.
- P23D has corrected any observed extraction defects and rerun validation.
- Actual Zyte deploy SHA, budget/quotas, stop thresholds and selected-source
  allowlists are independently confirmed.
- **P23E** issues a reviewed short-lived authorization for the exact
  permitted source subset, and **P23F** completes small-shard supervised
  rollout before attempting the rest.
- **P23G** reconciles all 460 IDs, including explicitly HELD/non-fetched
  sources. No automatic monitoring or production facts are authorized here.

Until these conditions hold, **NO FULL ZYTE CRAWL**. A public URL,
CI success, SHA, robots.txt, API key or LLM policy summary is never a
publisher license or operator authorization.

**This PR scope:** research note and operator handoff only. No crawl,
publisher GET, positive access registry change, real canary or Zyte deploy.
