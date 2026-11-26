# Historical diagnostic campaign consolidation (Phase 1)

This offline tool reconstructs the exact four November 25–26 jobs, using all 12 byte-pinned Items, Requests and Logs exports. It is not a general-purpose live campaign launcher, rights review, extraction quality certification or advisor publication path. Preserve the originals in private storage. No network requests are made.

From the historical checkout (460-source manifest, original diagnostic scope and 96-source resume scope), arrange the original JSON files in a private directory with the canonical names in JOBS: items_official_<suffix>.json, requests_official_<suffix>.json and log_official_<suffix>.json. A browser-added (1) filename suffix may be removed; bytes must not be modified.

    python -m scripts.consolidate_diagnostic_campaign --input-dir /private/exports --out-dir /private/new-consolidated

Output must be a new directory outside the checkout. Three files are created:

- report.json: source coverage, per-job log reconciliation, hashes, and historical group holds.
- inventory.json: exactly one accounting record per manifest source, retaining every observed accounting row reference separately from primary evidence. A later held row does not erase a prior actual response.
- primary_observations.json: exact retained Items for each unique primary response, with original file digest and zero-based row indices for both Item and matching Request. This is PRIVATE retained publisher evidence; do not commit or publish it.

Historical replay: 460 inventory IDs; 251 primary responses, 200 HTTP 200s, 51 deferred redirects, 209 without primary responses; 189 HTTP 200 Items have the unverified text indicator, and 27 are classified captured. 507 total request records include 256 robots requests. 84 historical group holds (29 packaged plus 55 observed). Only 29 unfetched IDs have no recorded group hold. This is a review pool, not an authorization. Prior successful captures do not clear group holds. Do not reissue these jobs to reproduce the data.

The retained Item payloads are not original HTML bodies. No verified facts, publisher permissions or unattended collection eligibility are inferred. This snapshot is specific to the exact historical manifest and scope; use the historical checkout for replay after future manifest edits. Phase 2 can consume this evidence without paid requests.
