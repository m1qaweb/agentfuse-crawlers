# P23D3 — GitHub Releases UI contamination guard (observed old Zyte Items)

**November 7, 2026.** Evidence-based, fail-closed release extraction improvement.
**Never a real publisher access approval, verified release announcement or crawl GO.**

## Real evidence and what it does / does not establish

The previously supplied and **P21A SHA-pinned** original Nov 4 Zyte changelog
Items captured several **obvious GitHub hosting interface strings as if
they were third-party vendor release entries**. Examples in the old Items:

- GitHub Releases listing for `mastra_changelog`: repeated **"Sorry,
  something went wrong."** across multiple archived source dates.
- `chroma_changelog`: repeated **"Uh oh!"** and GitHub's own
  commit-signature metadata headings.
- `continue_changelog`: GitHub's signed-commit metadata was mistaken for
  an event entry.

These are **historical parser observations, not a fresh authorized
GitHub scrape**. The source HTML and human publisher truth have not been
authenticated, so we do not claim that this patch fixes all GitHub
releases or that any real vendor fact is verified.

The source-specific source review registry remains **empty** and there
are **no authorized bulk plans**.

## Production fix

Only when the configured **changelog source host is github.com** (or
www.github.com), the extractor now recognizes a very narrow list of
GitHub-hosting UI headings:

1. Exact `Uh oh!` / `Sorry, something went wrong.` variants.
2. GitHub-signed-commit UI headings, optionally prefixed with a commit
   hash. No other titles are excluded, and occurrences in **ordinary
   explanatory prose** remain intact.

These are **not** emitted as independent provider release events.
A date or timestamp adjacent to one of these UI headings is not
inherited by the next release, and any already recognized entry is
finalized before skipping the contaminating heading.

**Safety-critical distinction:** signed-commit metadata is skipped
without automatically declaring a failed page. A displayed UI **error**
means the GitHub release feed could be incomplete. When present:

- `release_github_ui_error_placeholder_count` increments.
- `release_ui_contamination_requires_review=true`.
- `release_window_complete=false`.
- `latest_release_date_candidate=null`.
- `latest_release_date_status=ambiguous_github_ui_error_placeholder`.
- Quality gate returns `needs_review/github_release_ui_error_placeholder`,
  **even if other dates or releases were recognized**, and no release
  can be automatically approved for the advisor.
- Offline `compare_exports._healthy` rejects the contaminated Item
  even if its `status` field was incorrectly marked `captured`.

The parser keeps the unmodified original publisher Item provenance,
the source's original HTML capture hash, and a conservative count of
filtered UI headings. A missing UI error marker is **not** proof of
completeness, permission, freshness or accuracy.

## Release identity migration

HTML release `release_identity_revision` increments **v4 → v5**.
Previously emitted GitHub UI errors and signature headings may disappear
from `release_events` under v5, and source event windows can differ.

**This must generate a new evidence baseline, never a "new vendor
release" notification or deletion.** The existing revision-aware
offline comparator/evaluation provides this separation; new synthetic
regression tests assert it.

The `release_events_schema=1.1`, full valid non-GitHub HTML release
identity behavior, explicit publication-date requirements, conservative
collision checks, and `approved_for_advisor=false` remain intact.
This is not a generic HTML/browser repair, and does not remove
other GitHub UI chrome or validate any original source's release dates.

## Regression tests

New no-network tests use invented GitHub listings that resemble the
problem **class** but do not reproduce copyrighted vendor copy.
They cover both UI error variants, signature metadata, adjacent
machine-readable time tokens, a valid release following the noise,
no releases beyond the error, non-GitHub pages with the same words,
normal prose containing those words, fail-closed quality, and
v4-v5 baseline migration with no automatic alerts.

No real publisher network access, credentials, original HTML, saved
vendor response bodies, human approvals or Zyte jobs are checked into
this change.

## Operational next step and FULL ZYTE crawl trigger

**This changes production crawler bytes.** After merging, verify the
new `package_py_json_sha256_v1` fingerprint of the Python/JSON Zyte
egg and **independently verify the installed remote Zyte deployment**.
A passing GitHub egg build is not evidence of remote deployment.

The next live action remains a **single genuinely permitted source
canary, not a full crawl**: complete human exact-URL ownership, robots,
terms and retention review and commit a real P23B source-specific
`single_validation` decision; confirm deployed package and costs;
manually execute one limited Zyte job. Inspect original Items,
Requests, Logs and publisher HTML **if legally retained** and get
independent human accuracy review; run one second round only if safe.

Only recommend a **staged full-inventory campaign** after:
genuine per-URL reviews for the fetched subset; two distinct verified
cross-category canary rounds; evidence-based parser fixes; **P23E**
reviewed short-lived exact-source authorization/budgets/stops; and
**P23F** supervised small-shard success. **P23G** accounts for all 460
configured sources including **held/non-fetched** sources. An audit of
460 IDs is not permission for 460 GETs.

**Current full Zyte crawl status: NO-GO.**

Review tracking: [Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85)

Run full tests on Python 3.12 + 3.14 and existing offline no-crawl
preflight; verify the changed package fingerprint. Do not merge
without successful CI and code review.