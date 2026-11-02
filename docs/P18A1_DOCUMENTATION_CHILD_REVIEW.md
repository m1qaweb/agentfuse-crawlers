# P18A1 — Offline Documentation Child-Page Review Packets

**Scope:** first deliberately non-network step of P18A in the
2026-11-02 accuracy-first implementation blueprint. This is an operator
review workflow **only**. It does not create an approved page registry,
fetch any new pages, authorize scraping, migrate a canonical URL,
verify product ownership, certify a capability, or alter the advisor.

## Why this step is needed

The Nov 2 baseline contained 194 documentation source summaries, but only
20 pages were classified as scoped technical pages. It also reported more
than 5,000 discovered navigation links, with bounded output omissions.
A navigation link is not proof of product ownership, publisher permission,
page relevance, feature support, or completeness of an entire docs corpus.

The existing P13 documentation triage can produce a CSV of proposed links.
P18A1 adds reproducible, narrowly scoped review tasks that bind each
candidate to its exact source ID, source URL and **tentative** P16A product
identity. It keeps scope conflicts and missing profiles out of the
actionable packet. This is not a shortcut around manual review.

## Offline procedure

1. Obtain the **original exported** Zyte documentation Items JSON files
   through the normal operator archive procedure. Do not synthesize Items
   from current web content. Preserve job/package provenance separately.
2. Select at most 25 relevant parent IDs for a bounded operator packet:

        python -m scripts.plan_documentation_children \
          --items /private/archive/items_official_documentation_12.json \
          --source-ids openai_api_docs,anthropic_api_docs,gemini_api_docs,claude_code_docs \
          --per-source 8 --max-total 32 \
          --out-dir output/private/p18a1-first-pilot

   For an existing full export **without** explicit source IDs, omit that
   selection flag. Unprofiled parents are counted and held. This does
   not make their child URLs collectible.

3. Review the private files:
   - **child_review_packet.json:** stable source/manifest/profile hashes,
     exact unapproved URL/task identities, rejection/omission counts.
   - **child_review_tasks.csv:** formula-safe task sheet for humans.
   - **human_review_notes_template.json:** intentionally blank notes;
     **not** an importable collection allowlist or authorization.

4. Have independent operators establish, **for each exact child page**:
   - first-party publisher ownership and correct API/product/edition;
   - exact URL and canonical path, without guessed redirects;
   - robots, site terms, retention and allowed access method;
   - locale/version, technical relevance and page-family boundaries;
   - explicit human decision for *manual future collection*, if permitted.

   A parent's previous successful HTTP 200 is not policy approval.
   P16A's product ID remains a candidate label, not verified identity.
   The notes template does not automatically promote any record.

5. If publisher policy, ownership or canonical identity cannot be
   independently established, **do not fetch the child**. Record the
   unresolved issue for an operator. Do not change source lifecycle flags
   to make a URL eligible.

## Mandatory safeguards

- Exactly the existing 460 source IDs, 194 docs parents and 3 spiders.
- No requested site access; no Zyte job or browser rendering.
- No automatic child-page discovery or recursive crawling.
- A candidate is rejected if it escapes its exact parent host, candidate
  path-family boundary, or contains query, fragment, percent-encoding,
  dot-segments, double-slashes, backslashes or userinfo. A same-host
  sibling product path is **not** the same product.
- The exporter recomputes P13 source-bound candidate IDs; a forged ID,
  duplicate source row, duplicated URL or preapproved candidate fails.
- Candidate URL claims shared by multiple parents are held as ownership
  conflicts. Product-title conflicts and unprofiled parents are held.
- Fixed per-source and overall budgets, deterministic round-robin;
  omissions are counted. Output does not imply full docs coverage.
- Private, new-only, owner-restricted files. Never commit snapshots,
  operator notes or third-party page bodies into Git.
- No automatic collection permission, advisor approval or fact
  verification can be emitted. This tool cannot unlock permission itself.
- Nothing in the crawler package, Scrapy settings, original source
  manifest, Zyte schedules or the production DB is changed.
  The package fingerprint should be unchanged.

## Next engineering step: P18A2 (separate PR, NOT approved here)

Only after real publisher policy/URL/product decisions exist, propose
a new reviewed child registry with exact source ID, page ID, parent URL,
official child URL, product ID, version, locale, canonical evidence,
publisher access review, reviewer identity/timestamp, allowed capture
method and expiry.

A future opt-in collector must validate every individual record, keep
the original 460 source-summary accounting unchanged, preserve child-page
snapshots and lineage, and default to **no additional requests**.
A normal PR merge must not silently start collection. Even retained HTML
or a parsed technical page yields only unverified capability candidates,
never an AgentFuse advisor fact.

## Known limitations and honest metrics

- Offline review tasks do **not** establish 10 products with 8 independently
  approved technical pages each. P18A exit gates remain open.
- The P13 Items may contain truncated link sets; rejected and missing
  paths are not recovered by this tool.
- Only the subset already represented in tentative P16A product profiles
  can enter this queue. Others stay in the review/mapping backlog.
- Real policy review, permitted capture, original-page verification,
  capability-gold labeling and held-out scoring are still required.
- The P17B2/B3 pricing truth bottleneck remains unsolved until operators
  provide permitted HTML and independent labels.
