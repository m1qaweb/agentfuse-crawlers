# P26B — First full-category evidence, even if the job stops

This is a narrow operator extension of P25, not another canary, authorization
framework, or production accuracy gate. No publisher requests, new jobs,
permissions, schedules or deployment changes are made by this tool.

## Freeze before dispatch

After the real source reviews and three plans have been merged, keep the
exact reviewed checkout/commit and installed package, egg, G3 ranked CSV,
P25 report and owner-private launch ledger. The P25 launcher records an
attempt before scheduling and the actual Zyte job ID on acknowledgement.
Use one trusted operator/ledger. Do not edit the receipts. The content
fingerprint is a logical package Python/JSON hash, not the raw egg ZIP hash;
preserve both and separately verify the remote deploy ID/version.

## After EACH finished category, before dispatching the next

Archive metadata and Items immediately using the actual ID from the
launcher receipt:

    python -m scripts.archive_jobs --job-id REAL_JOB_ID --out-dir /secure/p25-archive

With the same reviewed checkout installed and private API key in the
environment, use the exact category's archive path printed by archive_jobs:

    python -m scripts.p26b_campaign_evidence \
      --g3-all460 /secure/g3-nov04-NEW/g3_historical_triage_all460_REVIEW_ONLY.csv \
      --target 300 --category pricing \
      --campaign-sha256 VERIFIED_CAMPAIGN_SHA \
      --ledger-dir /secure/p25-shared-persistent-ledger \
      --archive-dir /secure/p25-archive/jobs/REAL_JOB_ID_WITH_UNDERSCORES \
      --out-dir /secure/p25-pricing-evidence-NEW

Use only if the operator has verified permitted Items, Requests and Logs
retention, storage and TTL. The script performs GETs only to official Zyte
storage: job metadata, bounded paginated Requests, Requests stats, and Logs.
For new P25 launcher receipts it requires exact six-argument scope and
runtime pins, bound to both receipt files and the reconstructed campaign.
Historical compact three-argument receipts remain supported. A
completed but aborted category can be exported; missing Items and target
GETs remain visible. The 4096-request / 20000-log limits and 16/32 MB caps are
retrieval bounds, not a job spend cap. Overflow or inconsistent request
counts fails the export; preserve existing Items and use a separately
verified private manual export if necessary. No blind retry of a job.

The output directory contains private canonical JSONL Requests and Logs,
a receipt with byte digests/counts, archived job and dispatch bindings, and
a per-category diagnostics report. Pagination continues until an explicit
empty page, even after a short nonempty page. Requests counts are checked
against Zyte storage stats and compared with Scrapy's downloader count.
The Logs API has no documented independent count endpoint; an empty
terminal page does not establish that all original logs were retained.
Metadata, logs and requests may not contain the original response HTML.
The tool does not capture bodies or grant retention rights.

Inspect diagnostics.json: missing source IDs, target IDs without a recorded
GET, extra/unreconciled URLs (including possible robots redirects), duplicate
primary GETs, HTTP barriers, time-window violations and status mismatches.
An access barrier, unexpected request, incomplete result or uncertain
deployment must be reviewed before further dispatch. An HTTP 200 and a
captured status still do not verify facts.

## Offline historical replay

Use the exact as-run checkout/package, G3 ranking, original ledger and
archive, even after reviews/plan expire. Repeat the command above replacing
--out-dir with --replay-dir /secure/p25-pricing-evidence-NEW.
The tool reconstructs campaign selection at the attempt timestamp, checks
exact launch and Item bindings, and evaluates recorded primary-request
times against the as-run source/plan windows. It never uses historical
authorization to make new publisher requests. Replays do not access Zyte.
The report is a diagnostic even if every operational check is clean. Raw
metadata digests and local receipts are not signed remote attestations;
keep the original artifacts in trusted private storage. This is not an
independent proof of remote egg identity or of exhaustive server logs.

Repeat for documentation and changelog only when the prior category is
reviewed and the live P25 gates still pass. The older all-three P25 audit
remains available for complete jobs, but should not be the sole tool for
an interrupted campaign. The category evidence reports work independently
after expiry. Same-response HTML and blind human extraction adjudication
remain separate requirements; if evidence cannot legally be retained,
hold those facts as unscorable rather than reconstructing bodies from
Requests/Logs or taking a later page as the same snapshot.

References: [Zyte Job metadata](https://docs.zyte.com/scrapy-cloud/usage/reference/http/jobmeta.html),
[Requests/stats](https://docs.zyte.com/scrapy-cloud/usage/reference/http/requests.html),
[Logs](https://docs.zyte.com/scrapy-cloud/usage/reference/http/logs.html).

Tests: python -m pytest -q tests/test_p25_large_campaign.py
and python -m pytest -q. All tests are synthetic/mock-only.
