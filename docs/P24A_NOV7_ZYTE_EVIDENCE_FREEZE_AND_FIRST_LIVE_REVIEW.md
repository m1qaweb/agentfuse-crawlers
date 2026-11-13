# P24A — November 7 Zyte evidence freeze and first live-canary decision checkpoint

**Recorded 2026-11-08 · Scope: P0.1 completed / P0.2 awaiting genuine human policy review · Full 460-source crawl: NO-GO**

This is an **operator-evidence checkpoint**, not a source-access approval or a new synthetic crawler framework. It archives the result of the third November 7 three-spider run and makes the next human decision explicit.

## 1. Verified finished-job evidence

| Spider | Zyte job | Selected IDs | Missing reviewed bulk-plan holds | Quarantined | Publisher GETs in Requests export |
|---|---|---:|---:|---:|---:|
| `official_changelogs` | `883514/1/21` | 89 | 88 | 1 | 0 |
| `official_pricing` | `883514/3/13` | 177 | 176 | 1 | 0 |
| `official_documentation` | `883514/2/20` | 194 | 193 | 1 | 0 |
| **Total** | **3 jobs** | **460** | **457** | **3** | **0** |

For each of the 460 exported source Items, `http_status=null`; the Requests arrays in all three files are empty. Every non-quarantined row identifies `bulk_run_plan_not_present`. The three `v0` sources are quarantined separately. No publisher HTML was retrieved in these jobs: **do not debug parsing or repeat all 460 until an authorized single-source GET exists.**

**Release provenance:** main merge `4c44420852624b961487530d10d9390a6119b341` includes PRs #92 and #93. GitHub Actions [successful main package validation](https://github.com/m1qaweb/agentfuse-crawlers/actions/runs/42404511366) reported package SHA `b936758891f80a1bc4d17e6f5365ca13a65e9e99aed54bd3c4ab89076282bb7d`, exactly matching all three November 7 Zyte Items' runtime fingerprint. A package match is **not** legal authorization or a first-party data capture.

**Private evidence preservation:** the operator separately holds the nine exact original exports and an offline per-file manifest. The file hashes below identify those exports without placing original Items/Requests/Logs, HTML, API keys, or reviewer identities in this public repository.

| Original uploaded export | SHA-256 |
|---|---|
| `items_official_changelogs_21.json` | `27ec3956c7c10d69dabb61b099d2d6695c2acf357e09e18887ce772f2877f4a2` |
| `requests_official_changelogs_21.json` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `log_official_changelogs_21.json` | `83be4b884ab7458f8268ed9d4830f312d35d77b07b5cd6b774eff20440adf9bd` |
| `items_official_pricing_13.json` | `29e2f2bb091e4533e5ec2b3025d59d0bda526f4e979e72aabcbd422828a0627c` |
| `requests_official_pricing_13.json` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `log_official_pricing_13.json` | `c865d120692592c18501a814c088f80ef1a89cbe46ae4c21d4663659df2d7321` |
| `items_official_documentation_20.json` | `9e071a1d3e1dbbc5ecf91ca5d1055ccb45e93d8b422312d8459f690a60d4dc45` |
| `requests_official_documentation_20.json` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `log_official_documentation_20.json` | `536067808e7dc57c3d9aee3fbd6e7134329fe4d01eea4feb0ea2c5ba637b8396` |

## 2. Publisher access — specific unresolved issues

These are research leads, **not grants of permission** and not `allowed_reviewed` source decisions.

| Frozen P20A Wave 1 source | Verified signal | Before any publisher GET |
|---|---|---|
| `gemini_api_pricing` | November 4 original Zyte Item `883514/3/11` was an **HTTP 301** with `redirect_review_target=https://aistudio.google.com/docs/pricing`. This is a **different hostname** from frozen `https://ai.google.dev/gemini-api/docs/pricing`. On November 8, `https://ai.google.dev/robots.txt` was publicly accessible and disallowed `authuser` query variants. | **HOLD.** Separately verify the destination URL's ownership, applicable site terms, robots directives, and HTML-retention rights. If valid, perform a separately reviewed manifest URL change. Do not silently follow or scrape the new host. |
| `openai_api_changelog` | Public changelog exists. The current research browser could not verify the developer-host robots file. Consumer service terms cannot automatically be substituted for developer website access rules. | **HOLD.** Human reviewer checks exact-host robots, applicable policy, permitted method and retention before positive review. |
| `kiro_docs` | Kiro documentation linked AWS Site Terms; the AWS Site Terms restrict robots/data-mining of the AWS Site under their default site license. Whether/how this binds `kiro.dev` must be determined by a genuine human review. Research browser could not verify exact-host robots. | **HOLD — elevated access risk.** Do not assert this page is licensed for automated commercial collection. |

**Potential separate operational candidate (not a replacement for frozen 18/36 study):** `github_copilot_docs`, `https://docs.github.com/en/copilot`, is already in the manifest. GitHub's official [github/docs README](https://github.com/github/docs#license) states that documentation/content is CC BY 4.0. The exact website's robots directives, applicable usage terms, the particular page's license and the intended crawl/retention method **still need independent review**. Licensed reusable content is not by itself permission to send arbitrary crawler traffic to a host.

### Primary public policy links checked

- [Google robots for original developer host](https://ai.google.dev/robots.txt) — `Disallow: /*?*authuser=`
- [Google Terms of Service](https://policies.google.com/terms?hl=en) — machine-readable restrictions matter
- [Gemini API Additional Terms](https://ai.google.dev/gemini-api/terms) — determine actual scope
- [OpenAI developer-host robots candidate](https://developers.openai.com/robots.txt) — not confirmed by the research browser
- [OpenAI policy index](https://openai.com/policies/) — distinct policies apply to distinct services
- [AWS Site Terms, License and Site Access](https://aws.amazon.com/terms/) — site access/extraction restrictions
- [Kiro-host robots candidate](https://kiro.dev/robots.txt) — not confirmed by the research browser
- [Official GitHub Docs content license](https://github.com/github/docs/blob/main/LICENSE) and [GitHub acceptable use](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)

Do not treat a browser's inability to retrieve a robots file as proof the publisher disallows the path; it is simply **unresolved** for human verification.

## 3. Next executable action — without more code or new hash arguments

The **only outstanding dependency for the first genuine canary** is a real, source-specific publisher-access determination and a small operator budget. Follow [Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85) and [P23B source review schema](P23B_SINGLE_SOURCE_VALIDATION_ACCESS.md).

1. A genuine human reviewer checks the exact **source URL + host** for publisher authority, relevant site/robots terms for `AgentFuseResearchBot`, commercial fact reuse, private HTML retention, and a one-time polite pilot. Record **allowed/deferred/prohibited** honestly; keep frozen-source holds in the study denominator.
2. **Only for an independently substantiated allowed source**, create a **separate, reviewed access-metadata PR** in `agentfuse_crawlers/data/validation_access_reviews.json` with exact URL/category, `scopes=["single_validation"]`, named reviewer, dated <=30-day expiry, real ownership/policy/robots links and substantive evidence note. **No fabricated `true` flags.**
3. Merge, deploy new package and reverify its **new** hash (the policy JSON changes it). Confirm **1 Job Unit**, **Normal** priority, an explicit request/spend budget and that no schedule is enabled.
4. Run one permitted exact-ID spider once with separate Zyte UI arguments:

   ```text
   cohort = all
   source_ids = EXACT_REVIEWED_SOURCE_ID
   collection_mode = validation
   ```

   This single-source test **does not need a bulk plan**. Do not use `confirm_full_inventory`, monitoring, offsets, unreviewed URLs or extra bulk hashes. Keep redirects fail-closed.
5. Archive its **new** Items/Requests/Logs; independently inspect a real primary GET, actual status/URL, substantive original HTML where retention is permitted, and truthful extracted content. Only then consider round 2, the other categories, approved bulk plans and three simple full-category jobs.

**P24A does not populate source approvals, run Zyte, edit manifest, change parser, schedule monitoring or publish trusted facts.** The next code/data PR, if rights are established, must be a genuinely human-reviewed source access entry, not another policy scaffold.
