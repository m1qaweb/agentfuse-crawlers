# P23D1A — Replay historical canary Jobs after policy and package rotation

**Status: offline historical-provenance verifier, never crawl authorization.**

The source-specific human access registry has a <=30-day review lifetime.
Approving a second publisher changes the registry SHA-256 and the deployed
package fingerprint. **Previously collected evidence cannot be audited
against later package bytes or later publisher decisions.** Before this phase,
P23C1 tied *every* archived source-round to today's policy and package and
therefore could make a legitimate earlier job impossible to review after the
next access PR, package deployment, review expiry, or revocation.

P23D1A corrects this **archive-versus-authorization** boundary.

## What this phase enables

The existing P23C1 Items archive gate, P23C2 Requests/Logs/HTML gate, and
P23C3A **read-only** completed-job downloader can now opt into reviewing
past job evidence against the exact **as-run access registry** and
**compiled .egg package bytes** claimed by each already-archived Item.
The current source manifest and lifecycle registry remain frozen to P20A:
this is not a general way to bypass scope/selection changes.

**Default behavior remains strict and unchanged:** without historical
flags, an archived job must still agree with the current packaged access
registry and current package fingerprint. Neither mode authorizes a
publisher request, Zyte job start, remote deployment or advisor facts.

The user must supply both historical roots (never only one). For
each archived source-round with a real completed Zyte Job ID, the verifier:

1. Reloads its immutable P23C1 Item archive.
2. Reads the Item's as-run policy and package SHA-256, rejecting non-hex values.
3. Opens a **private source-policy file** whose basename equals the
   policy fingerprint in that Item.
4. Checks policy fields, exact first-party URL/category and positive
   source-specific single_validation decision **as of the job start
   timestamp**. An expired decision may be historical evidence; it is
   **NOT** current permission to crawl again.
5. Opens a non-symlink **compiled legacy .egg file** whose basename
   equals the Item's deployed-package fingerprint, verifies bounded
   members, rejects ZIP member paths, symlinks and duplicates, then
   recomputes the package content fingerprint from actual archived Python
   and JSON bytes.
6. Confirms the embedded package's access registry is identical to the
   preserved review snapshot, including all other reviewed sources.
7. Rechecks original P23C1 exact source/manifest/lifecycle/job arg
   pinning, original 18/36 rows, original Item/provenance hashes,
   genuine Job ID shape, and source-specific review time window.
8. Emits **NO_GO** and separate indicators identifying the number of
   locally verified *historical* source-round contexts.

An invented or edited review file cannot pass merely because someone
renamed it: both its canonical JSON digest and actual package contents
must match two independent Item claims. **Still, operator-supplied
files and hashes are NOT independent cryptographic signatures from
Zyte or the publisher.** Separate operator verification of deployed
package identity, real publisher rights and accuracy remains required.

## Private archive layout (all files kept OFF GitHub)

    /secure/p23d1-reviews/
      <exact_64_hex_access_registry_sha256>.json
      <another_64_hex_access_registry_sha256>.json
    /secure/p23d1-eggs/
      <exact_64_hex_package_fingerprint>.egg
      <another_64_hex_package_fingerprint>.egg
    /secure/p23c-zyte-archives/jobs/
      <one_per_completed_real_job>/
        envelope.json
        index.json
        items.jsonl.gz

The policy snapshot is **the exact JSON registry that was packaged for
that job**, not a later summary or a synthetic test reviewer. The egg
must contain agentfuse_crawlers/data/validation_access_reviews.json
with the exact same content. Human reviewer names/terms notes and
potentially sensitive job source metadata require private retention.

Where needed, rebuild the historic egg from its original Git revision
and compare actual bytes independently with the deployed Zyte revision.
The offline tool cannot establish that Zyte remotely executed a local
egg; always preserve original Job metadata, remote deploy version, and
operator evidence separately.

## 1. Default current review (unchanged)

    python -m scripts.p23c1_zyte_canary_archive_gate \
      --audit \
      --private-receipts /secure/frozen_36_job_receipts.json \
      --archive-root /secure/p23c-zyte-archives \
      --out-dir /secure/p23c1-current-audit-01

A stale review or changed local package may reject the prior job. This is
correct for a current-policy-only comparison, but it is not evidence
deletion or retroactive withdrawal of a previously lawful fetch.

## 2. Historical policy/package verification, zero network

    python -m scripts.p23c1_zyte_canary_archive_gate \
      --audit \
      --private-receipts /secure/frozen_36_job_receipts.json \
      --archive-root /secure/p23c-zyte-archives \
      --historical-policy-root /secure/p23d1-reviews \
      --historical-egg-root /secure/p23d1-eggs \
      --out-dir /secure/p23d1-items-audit-01

The old receipt's expected_package_sha256 may differ from current
main; it remains a valid **immutable historical preparation claim**.
Each real Job's own Item needs separately matching policy and egg
bytes. It is never enough to submit current source reviews.

## 3. Read-only Requests/Logs + P22A1 original HTML

After an actual previously permitted job has completed and its Item
archive is already stored:

    python -m scripts.p23c3a_download_completed_zyte_evidence \
      --preflight \
      --source-id <original_source_id> \
      --p23c1-private-receipts /secure/frozen_36_job_receipts.json \
      --archive-root /secure/p23c-zyte-archives \
      --historical-policy-root /secure/p23d1-reviews \
      --historical-egg-root /secure/p23d1-eggs

With a separate Scrapy Cloud API key, --download-existing may
retrieve that job's *already archived* Requests/Logs through the
official read-only Zyte storage API. It never runs a spider. The
resulting historical P23C2 receipt retains the original frozen
package SHA rather than silently replacing it with today's SHA.

    python -m scripts.p23c2_zyte_requests_logs_html_gate \
      --audit \
      --p23c1-private-receipts /secure/frozen_36_job_receipts.json \
      --raw-export-index /secure/private_36_raw_exports.json \
      --archive-root /secure/p23c-zyte-archives \
      --export-root /secure/private-requests-logs \
      --historical-policy-root /secure/p23d1-reviews \
      --historical-egg-root /secure/p23d1-eggs \
      --out-dir /secure/p23d1-full-evidence-audit-01

P23C2 continues to record missing Requests/Logs, 403/429, extra
redirect requests, empty logs and conflicting statuses as evidence
issues. P22A1 original HTML and independent human gold remain separate
optional inputs, NEVER inferred from archived metadata.

## Hard limits and full Zyte crawl criterion

**At current main:** source access reviews = 0; authorized bulk plans = 0.
No new human decision is fabricated or applied by P23D1A. Historical
replay is for already-completed Jobs only.

**NO FULL ZYTE CRAWL yet.** First: an independently reviewed legitimate
exact-source decision, verified deployed Zyte package/budget, one real
permitted single-source canary and a second distinct round; collect
Items/Requests/Logs/original HTML if licensed and independent human
accuracy reviews. Then implement real defect-based parser corrections
(P23D), reviewed bounded P23E run plans and P23F supervised small
shards. The eventual P23G full inventory reconciles all **460 IDs**
(including held/non-fetched), NOT 460 automatically authorized GETs.

The already-enabled readiness check should notify the operator only
when these conditions have **actually** been documented; a successful
CI run, policy hash or historical report is never sufficient.

## Tests and boundaries

    python -m pytest -q tests/test_p23c1_zyte_canary_archive_gate.py
    python -m pytest -q tests/test_p23c2_zyte_requests_logs_html_gate.py
    python -m pytest -q tests/test_p23c3a_download_completed_zyte_evidence.py
    python -m pytest -q

Tests use fake Scrapy Cloud Jobs and in-memory synthetic review records.
They verify historical expiry/revocation, two different original package
digests across rounds, missing/tampered/symlinked sources, malformed eggs,
source ID pinning, and continued NO_GO across the full 18/36 denominator.
