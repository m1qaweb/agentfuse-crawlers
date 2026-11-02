# P16A — Expected product identity and observed page-family review

**Status:** Draft PR implementation, requires publisher policy and independent
identity evidence before using any fact in AgentFuse.

## Why P16A exists

The Nov 2 460-source Zyte run proved source accounting but not reliable fact
ownership. A URL under a publisher's host can serve an index page, marketing
landing, client app, model API, another product's pricing, or a shell. The
source URL, a generic \`Pricing\` title, or a product mentioned in the body
is not enough to establish which product a rate, release or capability belongs
to.

Examples in the historical **unreviewed** Zyte exports:
- \`openai_api_docs\` page title \`API Platform\`: potential owner alias,
  not independently reviewed proof of ownership.
- \`claude_code_pricing\`: a Claude plan page, **not automatically a Claude
  API rate table**.
- \`xai_docs\` observed an unexpected landing-page title. It requires
  source/product scope review before using it for claims.
- \`gemini_api_*\` and \`gemini_cli_*\` share branding but are distinct
  products, billing semantics, changelog channels and documentation
  scopes.
- \`aws_bedrock_pricing\` mixes regional inference, token and infrastructure
  billing structures; no one-size-fits-all model-price parser can be trusted.

## Implemented without adding or changing websites

- \`data/provider_profiles_v2.json\`: **14 expected products, 41 exact
  existing source IDs**, pinned to the current URL/provider/category
  manifest. All title aliases and expected product kinds are
  \`pending_original_publisher_review\`; no verified branding or price fact
  is declared.
- \`provider_profiles.py\`: strict registry validation, typed product IDs,
  explicit negative aliases, bounded owner-title analysis, and structural
  markup family candidates. Owner verification stays false and no
  source-specific adapter is authorized.
- \`spiders/official.py\`: attaches bounded identity signals to the
  existing Items, without changing the three spider request sets. The
  only new fail-closed capture change is a **contradictory product title**
  (e.g. a documented Claude API source now serving a Claude Code page),
  which becomes \`needs_review/source_product_title_conflict\`.
- \`diagnostics.py\`: separate owner-title identity reasons remain visible
  alongside original pricing/docs/changelog quality reasons; an unreviewed
  positive alias never authorizes ownership.
- \`scripts/audit_provider_identity.py\`: runs locally against all three
  **old November 2** Dashboard Items exports. It reuses P15A's 460-source
  source/manifest/package validation and produces a review-only queue of
  observed titles, expected product, detected family, contradiction signals,
  and a recommended manual action.

The family classifier may suggest **token-rate tables**, **subscription
tables/cards**, **mixed card/table pricing**, **documentation indexes**,
**JavaScript shells**, **scoped technical sections**, and **bounded release
event markup**. It only consumes observed structural evidence; it does not
impute a model, USD, Global, Standard, rate, published day or a supported
capability from a provider name.

## Offline command — NO Zyte crawl needed

Keep the November 2 Items in a private workspace. From the repository root:

\`\`\`bash
python -m scripts.audit_provider_identity \
  --pricing-items /private/items_official_pricing_10.json \
  --documentation-items /private/items_official_documentation_12.json \
  --changelog-items /private/items_official_changelogs_13.json \
  --out-dir output/private/p16a-owner-audit
\`\`\`

Outputs:
- \`source_product_ownership_summary.json\`: counts by review signal and
  observed family, title-conflict IDs, exactly 460 accountings, deployment
  fingerprint, **zero** verified product-owner facts and adapter activations.
- \`source_product_review_queue.csv\`: one line per original source, 41
  candidates first, conflicts first, no raw page bodies.

**Do not** interpret the page's own title as independent identity review.
Verify the actual publisher product and channel from original official
sources, and document conflicting/stale/moved product URLs separately.
Do not promote a body-only or generic title to trusted ownership.

## Tests and gate

- Preserves exactly 460 source IDs and policy quarantine for three v0 sources.
- Cross-product negatives: Claude Platform vs Claude Code, Gemini API vs
  Gemini CLI, GitHub Copilot vs Microsoft 365 Copilot.
- Same-host mismatches are review signals, not new crawl permissions.
- Generic/no title, body-only aliases and substring false positives remain
  \`unverified\`.
- Corrupted mapping, URL pins, category, alias list and unauthorized review
  status fail closed.
- Exact source/prod identity can be proposed; **no trusted product owner,
  price, release, documentation capability or new parser activation** is
  created by this phase.
- Existing P15A/P15B quality gates and current source registry remain intact.

## Next PR: P16B acquisition method evaluation

After reviewing the high-impact identity conflicts and obtaining permitted
original-page snapshots, compare Scrapy static HTML against official
Markdown/feeds or selective Zyte rendered HTML on **reviewed exact source
IDs**. Measure real substantive text and provider ownership accuracy,
cost and limits. Only a separately audited profile should enable any
new acquisition method or extractor adapter.

Source-specific **pricing normalization** is P17A/P17B and must be judged
against held-out independently reviewed price and billing-unit examples.
No automatic source URL migration, site discovery, Zyte schedule, production
database or advisor data changes are part of P16A.
