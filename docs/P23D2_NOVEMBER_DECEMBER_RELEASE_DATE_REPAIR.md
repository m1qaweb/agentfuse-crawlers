# P23D2 — November/December release-date parsing repair

**As of November 7, 2026.** Offline deterministic parser fix only;
**no Zyte or publisher requests**, no policy approvals, no live canaries,
no inferred publisher facts or automatically trusted release announcements.

## Observed production-code defect

The HTML changelog parser's whole-dateline expression
\`DATE_WORDS\` in \`agentfuse_crawlers/release_events.py\` previously
recognized **January–October as full month words**, plus the abbreviations
\`Jan\`–\`Dec\`, but omitted the full spellings **November and December**.

Example before this fix:

- \`Nov 6, 2026\`: recognized as a full publisher date.
- \`November 6, 2026\`: **not recognized** by the same function.
- \`Dec 1, 2026\`: recognized.
- \`December 1, 2026\`: **not recognized**.

This matters immediately because the calendar has reached November 2026.
The date parser's strict whole-dateline logic is shared by visible
\`<time>\` entries, standalone publication datelines, and adjacent event
headings. Missing it could suppress \`published_at\`, the event window's
dated ordering and a candidate newest date in the fetched page.

This is a defect proven by inspection of the **code**, not a claim that
a specific real publisher released a model on a particular day. The
November 4 historical Zyte exports contain substantial existing
changelog-collision and truncation issues; this patch **does not claim
to solve those independently unresolved issues**.

## Fix

1. Add \`November|December\` to the existing full-month alternatives in
   \`DATE_WORDS\`. All twelve full month names are handled by the
   same strict year-explicit date parser as before.
2. Keep calendar validation: \`November 31, 2026\`, a month/day without
   a source-visible year, and explanatory prose about a deadline must
   never become release publication dates.
3. Change the HTML \`release_identity_revision\` from
   \`release_owner_date_scope_v3\` to \`release_owner_date_scope_v4\`.
   This is a **deliberate incompatibility / new evidence baseline**:
   newly recognized dates may change which generic dated headings
   receive provisional review-only IDs. Comparing v3 and v4 as if
   equivalent risks falsely notifying that old vendor releases are new.
4. Preserve \`release_events_schema=1.1\`, existing bounded evidence,
   publication date attribution, conservative collision handling,
   \`latest_publication_verified=false\`, and
   \`approved_for_advisor=false\`.
5. Add tests for November, December, abbreviations, day-first dates,
   HTML \`<time>\`, neighboring datelines, mixed chronology, invalid
   calendar dates, nonpublication prose, and **silent baseline
   migration** from v3 to v4.

**No release identity is auto-promoted on a parser update.**
A recognized dateline is still an unverified candidate, not a
publisher-authenticated publication timestamp.

## Deployment / exact next Zyte action

**This phase changes deployable source bytes.** After merging, verify
the compiled Scrapy Cloud egg fingerprint in CI and then independently
confirm that the **actual remotely installed Zyte deployment**
contains this new package. A successful GitHub build does not
authenticate the currently deployed spider.

**First allowed run (NOT full crawl):** a genuinely human-reviewed
specific publisher source, scoped to its exact approved
\`single_validation\` URL, a bounded budget and one manually
authorized job. Inspect its original Items/Requests/Logs and
publisher HTML if independently permitted; run a separate second
round only after inspection. Date extraction must be validated
against genuine, independently reviewed publisher-owned HTML,
not synthetic HTML tests alone.

Publisher access review tracker:
[Issue #85](https://github.com/m1qaweb/agentfuse-crawlers/issues/85).

### When the FULL Zyte crawl becomes appropriate

**No full crawl yet.** Both packaged source reviews and bulk plans
currently have empty approval maps, and no real current permitted
two-round category canaries have been independently validated.

A staged full-inventory run is appropriate **only after**:
genuine exact-URL policy/robots/retention decisions,
real cross-category two-round canaries and human accuracy grading,
any empirically necessary parser fixes,
P23E short-lived bounded source-subset authorizations,
actual Zyte deployment and budget verification, and P23F
supervised small shards. P23G must report all **460 source IDs**
but only request **authorized** URLs. Unreviewed, denied,
quarantined or redirected URLs remain held.

The already-configured daily crawl-readiness monitor should
notify the operator only when these conditions actually hold.
This PR cannot grant a new crawl or alter the monitor.

## Verification

\`\`\`bash
python -m pytest -q tests/test_release_events.py
python -m pytest -q tests/test_p09b_event_identity.py
python -m pytest -q tests/test_p12_release_identity_dates.py
python -m pytest -q
\`\`\`

All tests use synthetic offline documents; none connects to
publishers or creates a Zyte job. Verify Python 3.12 and 3.14
plus the existing GitHub no-crawl preflight before merging.
