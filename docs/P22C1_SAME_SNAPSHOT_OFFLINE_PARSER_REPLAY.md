# P22C1 — Offline same-snapshot pricing row-window replay

**Status: OFFLINE ONLY.** No publisher requests, permissions, Zyte jobs,
production rate approvals or actual human-reviewed publisher accuracy.

P22C0 (the previous local handoff) implemented an immutable HTML
inventory and receipt checker. It did NOT generate real parser receipts.
This integrated P22C1 extends that foundation by invoking the
**existing production pricing extractor** on bounded views derived
from ONE operator-supplied original HTML snapshot.

## What is implemented

- Source ID/URL bound to the exact live 460-source manifest. The manifest,
  lifecycle and parser package SHA are computed from the repo, not user flags.
- Byte-exact original UTF-8 HTML hash required; 8 MiB source cap.
  Operator must independently verify publisher access and private
  HTML retention BEFORE collecting the original. This script grants NO
  access and does not authenticate publisher origin.
- Same P22B1 visibility and P22B2 currency checks as the deployed
  extractor; same conservative price/model/region/tier analysis.
- Exact source table row inventory with direct DOM row SHA, bounded
  original 1–128 data-row windows, and preserved original table headers.
  A 400-data-row + one-header table yields SEVEN windows at 64 rows.
- For each window, derive a temporary HTML view with ONLY the chosen
  data rows of that table, keeping all other page-wide source context,
  invoke the existing extract_evidence pricing parser, then map
  temporary row indexes to the source's ORIGINAL absolute row indexes.
  Every candidate carries original cell SHA, window ID, source URL and
  an explicitly unverified typed value.
- Refuse overflowing (>300 observations), clipped parser runs,
  multi-row/column spans, nested grids, changed relevant-table
  identity, ambiguous cell indexes, conflicting fully typed rates
  and forged/missing/overlapping window receipts.
- The assembler RECOMPUTES every frozen window receipt from the same
  original bytes and CURRENT parser. A claimed empty complete
  receipt or modified amount does not pass.
- Cards are never duplicated across table row windows, but P22C1
  deliberately does not establish price-card or whole-vendor coverage.
  A source with no detected tables is NOT a vendor no-price negative.
- No existing production spider, schedule, data registry, package,
  P21B publisher-policy rule or original source manifest was changed.

This differs from scripts/assemble_pricing_windows.py, which requires
separate real Zyte jobs for TABLE windows. P22C1 uses no Zyte jobs:
its windows are ALL tied to one offline, original-byte-frozen page.

## Private operator workflow (no web requests)

First obtain legitimately permitted original publisher HTML and
independent human access/robots/retention review under P22A1. Never
commit raw HTML, completed reviews or human reference labels to GitHub.

Compute the SHA-256 of the private exact source HTML file:

    sha256sum /secure/original_vendor_pricing.html

1. Freeze plan:

    python -m scripts.p22c_same_snapshot_replay \
      --plan \
      --original-html /secure/original_vendor_pricing.html \
      --source-id openai_api_pricing \
      --expected-html-sha256 ACTUAL_SOURCE_HTML_SHA256 \
      --rows-per-window 64 \
      --out /secure/p22c_source_plan.json

Source ID here is an illustration, not publisher access authorization.

2. Run the real parser against SAME original bytes OFFLINE:

    python -m scripts.p22c_same_snapshot_replay \
      --run-offline \
      --original-html /secure/original_vendor_pricing.html \
      --frozen-plan /secure/p22c_source_plan.json \
      --out /secure/p22c_production_parser_receipts.json

3. Verify/assemble all source windows:

    python -m scripts.p22c_same_snapshot_replay \
      --assemble \
      --original-html /secure/original_vendor_pricing.html \
      --frozen-plan /secure/p22c_source_plan.json \
      --receipts /secure/p22c_production_parser_receipts.json \
      --out /secure/p22c_original_row_diagnostics.json

All outputs are new-only, 0600 private files on POSIX. No
publisher HTTP GET, Zyte job, database change or adviser approval.

## Interpretation and limits

recognized_row_window_coverage_complete=true proves ONLY that
every planned bounded visible table-row view was processed without
the listed structural holds. It does NOT prove all prices were found,
that the amounts are correct, or that the publisher's full catalog,
dynamic tabs, cards, regions or historical rates were captured.

A derived bounded view is not the publisher's exact original HTML.
Its result is anchored to the original source SHA and original
source-cell SHA plus coordinates. Missing CSS, JavaScript, shadow
DOM and tabs are outside static capture scope.

P22C1 is intentionally conservative about rowspan/colspan and
nested tables because these can change table cell meaning across
row-window boundaries. Fully qualified rate identity conflicts
across windows are rejected rather than chosen arbitrarily.

The runtime deliberately reparses the original bytes when verifying
each receipt. Very large private sources can incur substantial local
CPU cost; source/window/byte/receipt budgets bound inputs. Never
run this at unbounded frequency.

**Next P22C2 gate:** first obtain actual permitted source HTML
and P22A1-3 independently reviewed true/false pricing cases.
Demonstrate that same-snapshot row slicing improves SOURCE-WIDE
accuracy over the old 250-row / 300-observation limits without
incorrect regional/tier/model attribution. Only then consider a
separate, explicitly approved live bounded spider opt-in. Do not
turn on 460-source bulk crawling without P21B publisher policies,
reviewed run plans, and independent source accuracy evidence.
