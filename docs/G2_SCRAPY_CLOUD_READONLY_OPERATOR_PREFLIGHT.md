# G2 — Operator-run Scrapy Cloud read-only account check (NO-GO)

**Implementation:** the manual-only GitHub Actions workflow `.github/workflows/manual-g2-zyte-readonly-account.yml`, using the pre-existing `scripts/p23e1_zyte_queue_preflight.py` and new `scripts/g2_redact_zyte_snapshot.py`.

**It does not deploy, start, cancel, stop, approve, schedule, or fetch any publisher URL.** It makes exactly **three** bounded, credentialed GET calls to official Scrapy Cloud list endpoints and exports only a whitelisted NO-GO summary. Existing G1 publisher-review blockers and frozen P20A scientific study remain unchanged.

## What can be checked now

- Project-specific **pending and running jobs** (point-in-time; 200 rows per page maximum)
- Project-specific **periodic schedules** (one page; incomplete pagination is explicitly reported)
- Whether the returned queue/schedule pages look complete based on vendor totals
- Zero jobs created and zero publisher requests initiated by this preflight
- Stable hashes of the original read-only snapshot and redacted summary for audit traceability

**What this cannot prove:** exact currently installed/deployed egg bytes, any future jobs, complete schedules beyond the first page, account-specific billable cost, independent publisher permission or reliable extraction. A GitHub commit SHA or local egg/package fingerprint is not proof of the remote deployment. This step cannot mark the crawl GO.

## Execute the first real account inspection

Only the Zyte account/repository operator can complete these steps. The assistant cannot access the private Scrapy Cloud key or the actual deployment with the available connectors.

1. Log into the correct **Scrapy Cloud** account and confirm the project ID from the project URL. Historical AgentFuse project exports use `883514`; **do not assume** it is necessarily the current authorized project.
2. In GitHub `m1qaweb/agentfuse-crawlers`, open **Settings → Secrets and variables → Actions → New repository secret**. Create `ZYTE_SCRAPY_CLOUD_API_KEY` using your **Scrapy Cloud API key**. Do not use the Zyte API product key interchangeably, and never paste a key into chat, a PR, dispatch inputs, or a source file. The manual workflow uses the secret in just the read-only inspection step.
3. Open **Actions → G2 - Inspect Scrapy Cloud account (read only, no crawl) → Run workflow**. Select `main`, enter the **verified project ID**, and dispatch it. This action **cannot schedule a spider**: its only authenticated HTTP calls are those in `scripts/p23e1_zyte_queue_preflight.py`.
4. Inspect the **workflow Job Summary** and download the artifact named `g2-readonly-redacted-preflight-<run-id>`. It is retained for **3 days** and contains only `g2_zyte_redacted_snapshot_NO_GO.json` — counts, snapshot timestamp, completeness flags and SHA-256 digest. **No Zyte job IDs, schedule task arguments, account credentials, source HTML, logs, or original raw queue/schedule records are uploaded.**
5. If the workflow fails because the secret is missing, fix only the secret and retry when authorized; do not hardcode or pass it in a workflow input. If an API call fails, the job fails closed and does not upload a success-looking report.
6. Treat `queue_pages_complete=false` or `periodic_schedule_page_complete=false` as incomplete observations; inspect additional schedule pages manually in Zyte UI. Even two complete, empty snapshots cannot guarantee a job will not start later.

### Local equivalent for the responsible operator

Use this only in a trusted local terminal with private Scrapy Cloud credential already in the environment. Never commit or upload the raw local report:

```bash
# Do NOT put the actual key on the command line or in shared logs.
python -m scripts.p23e1_zyte_queue_preflight \
  --project-id VERIFIED_PROJECT_ID \
  --out-dir output/private/g2-local-snapshot-NEW

python -m scripts.g2_redact_zyte_snapshot \
  --input-report output/private/g2-local-snapshot-NEW/p23e1_zyte_readonly_queue_NO_GO.json \
  --out-dir output/private/g2-local-summary-NEW
```

## Remaining G2 checks outside the Actions snapshot

- **Deployment:** inspect Zyte project's deployment/version history. Correlate it with a reviewed source commit and the exact installed Scrapy package. An old *job version* or a new GitHub merge only shows history, not the presently installed egg bytes. Treat the remote package fingerprint as **unverified** unless independently established.
- **Account-specific cost:** check the actual Scrapy Cloud subscription/unit count, free-tier constraints, schedules, retention limit, and whether the project uses separately billed **Zyte API** extraction/proxy features. Scrapy Cloud units and Zyte API request billing are distinct. Read the account billing panel and approve a numerical job-level spend ceiling **before** any canary. See [Scrapy Cloud pricing](https://docs.zyte.com/scrapy-cloud/pricing.html), [Zyte API pricing](https://docs.zyte.com/zyte-api/pricing.html), [Scrapy Cloud units](https://docs.zyte.com/scrapy-cloud/usage/units.html).
- **Publisher permissions:** the exact source access registry is still empty. Complete genuinely evidenced source-specific human reviews under G1 and Issue #85; do not let the G2 queue snapshot create or imply permission.
- **Pilot:** only after above gates, a human operator may separately authorize a one-source/one-round validation job with a finite stop threshold. Preserve Items, Logs, Requests and original HTML only as permitted, then independently check parser results against original evidence.

## Synthetic test and safety contract

```bash
python -m pytest -q tests/test_g2_readonly_operator_preflight.py
python -m pytest -q
```

The tests use injected fake in-memory API payloads; they verify field allowlisting (including synthetic private job arguments), malformed/tampered source snapshots, incomplete pagination, explicit NO-GO flags, private new-only output and workflow dispatch-only scope.

**Status:** `NO_GO_REAL_ACCOUNT_EVIDENCE_INCOMPLETE` until an actual account-run redacted snapshot exists **and** deployed code, cost and publisher access are separately verified. This commit itself performs **zero Zyte API requests** and zero publisher requests.
