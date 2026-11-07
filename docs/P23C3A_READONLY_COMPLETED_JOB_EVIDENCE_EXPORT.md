# P23C3A — Read-only collection of genuine completed Zyte canary evidence

**Status:** Engineering implementation only. **No real canary job or publisher fetch has been run.** Full 460-source diagnostic: **NO-GO**.

P23C1 freezes 18 original publisher sources and 36 source-rounds. P23C2 checks their archived Items, Zyte Requests/Logs exports, and optional separate publisher HTML. P23C3A removes the manual step of downloading every completed job's Requests and Logs, while retaining P23B's source-specific access requirements.

## Prerequisites: human source reviews and permitted real canaries

The production publisher access registry is currently **empty**. A real reviewer must assess first-party ownership, robots restrictions, publisher terms, private retention rights and approved research scope before even one publisher GET. Record genuine evidence and a bounded single_validation scope via the reviewed P23B policy registry. Do NOT fabricate approvals.

These **original Wave 1 sources** are proposed as an initial three-category pilot, not as pre-approved URLs:

| Category | Source ID | Exact URL |
|---|---|---|
| Documentation | kiro_docs | https://kiro.dev/docs/ |
| Pricing | gemini_api_pricing | https://ai.google.dev/gemini-api/docs/pricing |
| Changelog | openai_api_changelog | https://developers.openai.com/api/docs/changelog |

### Initial public policy reconnaissance — November 7, 2026 (NOT approval)

These are research leads for the **human reviewer**, not positive review
records or legal determinations. None has passed all required source-specific
checks; keep all three in not_reviewed until actual operator research:

- **Google Gemini pricing:** public [ai.google.dev/robots.txt](https://ai.google.dev/robots.txt) was readable and specifically disallows URLs containing the authuser query parameter. This alone does **not** establish positive permission for a Zyte crawl or retained original HTML; a reviewer must check current page-specific terms and retention rights. The [Gemini API Additional Terms](https://ai.google.dev/gemini-api/terms) govern the API service; their applicability to scraping public pricing documentation is a separate question.
- **Kiro docs:** [kiro.dev/robots.txt](https://kiro.dev/robots.txt) could not be verified through this research interface. [AWS Service Terms](https://aws.amazon.com/service-terms/) explicitly address Kiro, but this is not a public-docs crawling grant. Hold until robots, applicable site terms and retention rights are independently checked.
- **OpenAI API changelog:** [developers.openai.com/robots.txt](https://developers.openai.com/robots.txt) could not be verified through this interface. Review the [OpenAI policy collection](https://openai.com/policies/) and the agreement actually governing this use; consumer terms, developer agreements and public-docs permissions are not interchangeable. Hold without a current first-party robot/terms review.

**Never translate accessible HTML, a non-disallowing robots directive, or
successful HTTP 200 into affirmative publisher authorization.**

Do not replace a denied source in the scientific 18-source cohort. After a genuine review is merged, separately confirm the exact deployed Zyte package SHA and manual cost approval. Run a bounded **single original source ID**, then a separate second round, using the P20A source/manifest scope arguments. Do NOT run the full inventory. Keep access denials and 403/429 responses as explicit attrition.

## 1. Archive the already-completed real job's metadata and Items

From a trusted private operator environment, after a human actually runs a permitted single-source canary and it finishes:

    python -m scripts.archive_jobs --job-id 123456/1/789 --out-dir /secure/p23c-zyte-archives

This downloads only from the official Zyte storage API. The P23C1 private source/round receipt ledger must contain the **actual** Job ID. Do not invent one.

## 2. Offline source/round preflight: zero Zyte API calls

    python -m scripts.p23c3a_download_completed_zyte_evidence \
      --preflight \
      --source-id kiro_docs \
      --p23c1-private-receipts /secure/p23c1-jobs_FILLED.json \
      --archive-root /secure/p23c-zyte-archives

The tool reuses P23C1's 18/36 scope, immutable archive integrity and actual P23B current access-review validation. It accepts only 1–2 completed jobs for one of the frozen original 18 sources. Without genuine approved source reviews and archived Jobs it **fails closed**, with no publisher or Zyte GETs.

## 3. Read-only retrieval of Requests and Logs for completed jobs

Using a private, secure Scrapy Cloud API key in the ZYTE_SCRAPY_CLOUD_API_KEY environment variable (different from a Zyte API key), run:

    python -m scripts.p23c3a_download_completed_zyte_evidence \
      --download-existing \
      --source-id kiro_docs \
      --p23c1-private-receipts /secure/p23c1-jobs_FILLED.json \
      --archive-root /secure/p23c-zyte-archives \
      --out-dir /secure/kiro-canary-evidence-01

Only read-only HTTPS GETs are made to storage.zyte.com for the specific completed Job metadata, Requests, Requests/stats, and Logs. The client uses Basic authentication via a restricted header, never URL credentials, and refuses redirects.

It compares fresh official job scope, deployment version, spider and item count against the immutable archive. Requests and Logs are paginated using count/start/meta=_key, with explicit ordering validation and size bounds; Requests length must match official Requests/stats totals.input_values. Missing, malformed, duplicate or out-of-order rows fail closed.

A private directory is written **only after all read-only downloads succeed**. It includes:

- One folder per actual job with owner-only requests.jl and logs.jl.
- raw_requests_logs_receipt_index_FILLED.json — 18/36 slots compatible with P23C2; downloaded jobs filled, other rounds retained.
- read_only_completed_job_export_receipt_NOT_GO.json — summary counts and integrity hashes, no sensitive log messages or API key.

Sensitive Logs, filled human ledgers, publisher HTML and credentials **must never be put in GitHub Actions or the Git repository**. Do not automate this on a public runner.

## 4. Run P23C2 offline analysis without additional network requests

    python -m scripts.p23c2_zyte_requests_logs_html_gate \
      --audit \
      --p23c1-private-receipts /secure/p23c1-jobs_FILLED.json \
      --raw-export-index /secure/kiro-canary-evidence-01/raw_requests_logs_receipt_index_FILLED.json \
      --archive-root /secure/p23c-zyte-archives \
      --export-root /secure/kiro-canary-evidence-01 \
      --out-dir /secure/kiro-canary-audit-01

Original publisher HTML remains a separate, legitimately authorized P22A1 operator capture. Zyte Items/Requests/Logs do not themselves prove the original full HTML response body, human price correctness, release-date truth, or source legality. Every audit remains **NO-GO** until real access review, independently examined source HTML, dual human quality labels and final bounded run-plan approval.

## Tested behavior and limitations

- The downloader **never** schedules Zyte jobs, deploys spiders, changes access policy, contacts publishers, overrides robots, or enables monitoring.
- It refuses existing output locations, altered metadata, wrong IDs, unsafe paths, missing/overlapping page keys, excessive rows and invalid Requests stats.
- The operator may run it for **one frozen source's 1–2 finished jobs**, not arbitrary jobs or 460 URLs.
- SHA-256 and a read-only authenticated Scrapy Cloud API observation are not independent proof of response-body provenance or downstream data accuracy.
- Full CI uses synthetic in-memory source policy and a mocked read-only Zyte storage client. Production credentials and real publisher data are never in test fixtures.

References: [Zyte API overview](https://docs.zyte.com/scrapy-cloud/usage/reference/http/index.html), [Requests API](https://docs.zyte.com/scrapy-cloud/usage/reference/http/requests.html), [Logs API](https://docs.zyte.com/scrapy-cloud/usage/reference/http/logs.html), [P23B source-specific review](P23B_SINGLE_SOURCE_VALIDATION_ACCESS.md), [P23C2 audit](P23C2_ZYTE_REQUESTS_LOGS_ORIGINAL_HTML_AUDIT.md).

**Critical next step:** human source-policy decisions and a genuine permitted 1–3-source pilot. Stop accumulating synthetic-only infrastructure until real evidence reveals parser or operational failures.
