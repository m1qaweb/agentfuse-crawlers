# P23C2 — Offline Zyte Requests, Logs & Original HTML Corroboration

**Status:** Offline evidence validator, **not** a crawl, access permission,
remote Zyte attestation, reproducible human gold, or production readiness GO.

**Depends on:** P23A audit, P23B single-source access gate, P23C1 exact
immutable Items archive/18-source 36-round evidence receipt, and optionally
P22A1 private original HTML accession.

## Why

A P23C1 Items archive can be internally self-consistent yet omit the HTTP
request trail, off-manifest redirect attempts, robots/429 evidence, error logs,
and original publisher HTML. Merely comparing Item status/HTTP 200 to its
own archive does not prove the crawler made only its intended publisher GET
or that the page contains correctly interpreted pricing/release/capability data.

P23C2 independently **parses the operator-supplied raw JSON Lines exports**
as defined by Zyte's published [Requests API](https://docs.zyte.com/scrapy-cloud/usage/reference/http/requests.html)
and [Logs API](https://docs.zyte.com/scrapy-cloud/usage/reference/http/logs.html).
It binds those exports to the *same original source and round* as P23C1.
It can also verify an independent P22A1 original HTML capture, with a
**separate provenance flag**: a SHA-verified P22A1 capture is **not** assumed
to be the very same response body returned by the archived Zyte job.

## 1. Generate blank receipts (zero network, no local clone required)

After merge: GitHub → Actions → **Prepare Zyte UI preflight (no crawl)**
→ Run workflow on `main`. Download the artifact:

- `p23c1-blank/zyte_canary_job_receipts_BLANK.json` — 18 IDs and 36 job slots
- `p23c2-blank/raw_requests_logs_receipt_index_BLANK.json` — 18 IDs and 36
  Requests/Logs file receipt slots, **all null**
- `p22a1-blank/source_policy_and_capture_ledger_BLANK.json` — original HTML
  and private publisher-review template, **no HTML supplied**

Or from a reviewed local checkout:

```bash
python -m scripts.p23c2_zyte_requests_logs_html_gate \
  --prepare --out-dir output/private/p23c2-blank-01
```

Never commit **filled** receipts, raw Requests/Logs, publisher correspondence,
credentials, original HTML, human labels or sensitive log messages.

## 2. Required human/operator prerequisites

**P23B remains fail-closed:** do not run even one live publisher GET until an
actual human has checked the exact first-party source URL, owner, robots.txt,
terms, research scope and retention permissions, and merged a valid current
`single_validation` review in
`agentfuse_crawlers/data/validation_access_reviews.json`.
The registry is currently empty. Neither P23C1 nor P23C2 grants access.

For each legally permitted selected source:

1. Independently verify actual production Zyte deployed package fingerprint
   and inspect the review expiry and operator cost budget.
2. Use the P20A **exact single-source** args. Run a bounded real validation job
   only after explicit human approval. Repeat as a **different** job for round
   two. Do not substitute a different publisher after a denial.
3. Preserve official Job metadata, Items, **all** Requests, and **all** Logs.
   P23C1's `archive_jobs` already captures immutable Items+metadata.
4. Export original Zyte Requests and Logs as **JSON Lines**, not screenshots or
   snippets, into an access-controlled offline directory. The Zyte API's
   Request objects require `time` (epoch milliseconds), `method`, `url`,
   `status`, `duration`, `rs`. Logs require `level` and `message`, with
   optional `time`. Never put API keys in URLs or repository files. The
   current P23C2 implementation **does not download** these exports.
5. Obtain source-owned original publisher HTML via separately authorized
   P22A1 methods. A source-summary Item is **not** HTML and its text hash is
   **not** the original HTML-byte hash.

Private file layout example, with substituted real job IDs only:

```text
/secure/p23c2-raw/
  123456_1_789/requests.jl
  123456_1_789/logs.jl
/secure/p23c-zyte-archives/
  jobs/123456_1_789/envelope.json
  jobs/123456_1_789/index.json
  jobs/123456_1_789/items.jsonl.gz
```

In a **private copy** of the P23C2 index, fill the matching exact job ID and
the `requests`/`logs` receipts:

```json
{
  "round": 1,
  "zyte_job_id": "123456/1/789",
  "requests": {
    "file": "123456_1_789/requests.jl",
    "sha256": "ACTUAL_LOWERCASE_SHA256"
  },
  "logs": {
    "file": "123456_1_789/logs.jl",
    "sha256": "ACTUAL_LOWERCASE_SHA256"
  }
}
```

Compute hashes from the actual bytes. Missing exports are **null**, not
fabricated empty exports. A genuine zero-request job may have a zero-byte
JSONL Requests export: it is valid *attrition evidence*, not a success.

## 3. Offline audit using reviewed evidence

```bash
python -m scripts.p23c2_zyte_requests_logs_html_gate \
  --audit \
  --p23c1-private-receipts /secure/p23c1-jobs_FILLED.json \
  --raw-export-index /secure/p23c2-raw-index_FILLED.json \
  --archive-root /secure/p23c-zyte-archives \
  --export-root /secure/p23c2-raw \
  --out-dir /secure/p23c2-audit-01
```

Optionally add the **both-or-neither** P22A1 inputs:

```text
--p22a1-private-ledger /secure/p22a1-source-policy-and-HTML_FILLED.json
--html-root /secure/p22a1-original-publisher-html
```

Internally, the validator **recomputes P23C1** from the original immutable
Items archives and source-policy registry, then parses the raw Zyte JSONL.
It checks the exact source URL and spider, actual item/request HTTP statuses,
GET vs unexpected methods, permitted `/robots.txt` path, off-manifest
URLs, duplicate primary requests, Request/Log timestamps, optional downloader
request-count parity, 401/403/407/429, log ERROR/CRITICAL, file SHA-256 and
safe bounded paths. No raw log strings are emitted in the audit.

If P22A1 HTML is supplied, the existing `stage_data` verifier independently
checks all **36** frozen source-rounds, exact source URL, first-party operator
policy, SHA-256, original HTML bytes, method, timestamp, redirects, and
parser-owned unverified evidence. A source-round can be flagged for
nearby-capture mismatch without claiming the file is the identical Zyte
HTTP response body.

Output (NEW, private, no overwrite):

- `zyte_original_evidence_36_rounds_NO_GO.json`
- `all_36_round_evidence.csv`

These preserve denied/held/not-captured source-rounds and categorize missing
or contradictory receipts. Unverified, changed URL, time drift, missing
Requests/Logs, source 429, and error logs are **not** counted as clean canaries.

## 4. Hard limitations and stop conditions

- `status` is always **NO_GO**, regardless of how many synthetic or
  operator-supplied files match. SHA-256 integrity is not an independent
  signature from Zyte or the publisher; a malicious operator can fabricate
  mutually consistent exports.
- A Requests/Logs file is not automatically certified **complete**. Parity
  with official Scrapy downloader stats helps expose missing rows but is not
  cryptographic proof. Any absent count/Request/Log receipt is a hold.
- P22A1 original publisher HTML is a *separate capture* unless the exact Zyte
  response-body provenance is independently established in a future phase.
- A zero Request/Log export can be genuine attrition but is **never** a
  successful source fetch; all 36 study slots remain.
- This is evidence gathering, **not** pricing accuracy: P22A2/P22A3 dual
  independent human review and adjudication still have to happen on actual
  permitted original publisher bytes.
- Never bypass 403/429, robots, CAPTCHA, source-specific access review,
  changed-path redirects or policy holds. Never auto-run 460 source GETs.

## 5. Next phase and verification

```bash
python -m pytest -q tests/test_p23c2_zyte_requests_logs_html_gate.py
python -m pytest -q
```

Next critical work is **P23C3: genuine reviewed publisher decisions and
1–3 permitted two-round canaries** with complete original Zyte Requests,
Logs and HTML provenance. Only then can P23C4 independently measure
per-category extraction accuracy and P23D fix real problems. P23E–G
cannot safely execute a full-inventory campaign before those gates pass.
