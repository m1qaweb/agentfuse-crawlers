# P22B1 — Visible-HTML pricing scope isolation

**Status:** Production parser safety fix; synthetic regression evidence ONLY.
No actual publisher HTML, human pricing gold, source permission, new publisher
requests or Zyte jobs were supplied or created by this PR.

Follows P22A3's offline two-reviewer plus third-adjudicator pipeline.
That pipeline can score genuine future captures, but does not retroactively
verify current pricing facts.

## Defect addressed

The existing parser removed navigation, sidebars, footers, scripts and
templates before pricing extraction, but did not exclude all explicitly
nonvisible HTML elements. Currency, rates, product names and region/tier
content inside these elements could be scanned as if it were visible:

- HTML boolean hidden or inert elements (including hidden="false");
- aria-hidden="true" (already partly handled in the prior cleaner);
- closed details and dialog components;
- inline CSS display:none, visibility:hidden / collapse,
  content-visibility:hidden or opacity:0.

Inactive old pricing tabs might be incorrectly joined with a visible
product's rates. This is a potential false-positive normalization path,
NOT proof that any named publisher currently has this defect.

## Implementation

Files:

- agentfuse_crawlers/pricing_visibility.py — new deterministic,
  shared static-HTML visibility predicate. Inline CSS respects the
  final declaration of the highest !important priority.
- agentfuse_crawlers/extract.py — **pricing category only**: prune
  explicitly nonvisible DOM before table/card extraction; a root
  main hidden by its ancestor cannot emit a visible rate.
- agentfuse_crawlers/pricing_scope.py — do not inherit currency,
  region, unit or tier from hidden source statements. Hidden
  tables do not consume pending scope for the next visible table.
- agentfuse_crawlers/pricing_evidence.py — exclude hidden table
  elements and heading context from direct helper calls.
- agentfuse_crawlers/pricing_cards.py — hidden price cards and
  card-local declarations are not live pricing evidence.

New unverified pricing diagnostics:
- pricing_explicitly_hidden_subtrees_omitted: number of explicitly
  hidden subtrees excluded within selected main content.
- pricing_scope_visibility_revision:
  static_explicitly_nonvisible_html_exclusion_v1
- pricing_static_visible_page_only: true

All observations retain approved_for_advisor=false. No missing
currency, region, plan or billing unit is inferred automatically.
Previously valid visible table/card normalization should remain
compatible; positive regression tests assert this.

## Scientific and product limitations

Static HTML is NOT a renderer. External CSS, responsive classes,
shadow DOM, JavaScript and dynamic application state may change
the set of displayed source prices after page load. A closed
details component or hidden plan tab may represent a real
selectable vendor price. P22B1 now **withholds** such content rather
than treating it as visible/current. This may reduce recall.

pricing_inventory_complete=true continues to mean only that
recognized pricing structure in the fetched, visible static
HTML was scanned; it does NOT mean all the vendor's hidden tabs,
regions, products or historical price schedules were captured.
A hidden-subtree count is a triage indicator, not a confirmed
number of hidden prices.

Use P22A1 exact original-page captures, P22A2 independently
performed full-page A/B reviews, and P22A3 third-person source
matching to measure actual false positives and false negatives.
Do not use CI test outcomes as real publisher-accuracy metrics.

## Tests and rollout

New tests/test_p22b1_visible_pricing_html.py provides entirely
SYNTHETIC regression examples: visible price controls, hidden
price tables/cards, hidden currency/region/tier statements,
conflicting source currency, hidden root/ancestor, CSS priority,
direct helper usage and nonpricing category stability.

Require full green Python 3.12 and 3.14 CI before merge.

**This PR changes the actual deployable Python package.** Its
SHA-256 fingerprint intentionally changes. GitHub CI only proves
built eggs have matching bytes, not what Zyte has deployed.
After manual code review and merge, verify the ACTUALLY deployed
Zyte egg revision and use one genuinely permitted single-source
manual validation smoke test. P21B's per-URL policy reviews and
exact bulk run authorization requirements remain in force.

Do not trigger the full 460-source Zyte crawl. Bulk publisher
permissions and genuine independently scored original-page
accuracy are still missing. Future P22B fixes should respond
to ACTUAL P22A3-reviewed pricing errors, not guessed source facts.
