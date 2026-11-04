# P21B — Enforced Source/URL Bulk Validation Authorization

**Status:** Production-code change awaiting review. No publisher access rights, original HTML, Zyte jobs, automatic schedules, adviser facts or database permissions are created by this PR.

## Why this change matters

The November 4 diagnostic attempted 457 nonquarantined publisher pages using collection_mode=validation even though the source lifecycle records still said source_policy_status=not_reviewed. The prior flag confirm_full_inventory=yes only indicated a desire to fetch a wide range of sources; it did NOT provide source-specific publisher permission.

P21B moves the decision to the spider **before it yields a page Request**. Only a separately Git-reviewed exact URL access record **and** an exact authorized run plan can allow a multi-source validation request. Both newly packaged registries ship EMPTY.

## Request scope matrix

| Requested scope | Additional requirements | Available now? |
|---|---|---|
| One explicitly named configured source with source_ids=ONE_ID, zero offset and no limit | Existing lifecycle guard; real human must independently review publisher access and retention before running manually | Technically available, never automatically authorized |
| Default proven cohort (3), comma-separated source IDs, candidate chunks or limit/offset selection | Current publisher URL review, exact reviewed run plan and runtime hashes | NO — no reviewed plans |
| Full category using cohort=all | confirm_full_inventory=yes AND source URL review AND exact reviewed run plan/runtime hashes | NO — confirmation is not permission |
| Unattended monitoring | Existing independently approved validated_for_collection lifecycle | NO — no monitored sources are approved |

A bulk-denied but otherwise lifecycle-eligible source yields one unverified Item:

    status: source_bulk_validation_not_approved
    error: bulk_run_plan_not_present
    http_status: null
    policy_observation: not_fetched_by_bulk_source_access_gate
    approved_for_advisor: false

Three v0 quarantined URLs retain their original source_quarantined status. They are held without fetching. Diagnostics use not_attempted_by_bulk_access_policy, not an HTTP failure, and SourceCoverageAudit counts these separately under agentfuse/coverage/bulk_access_held_sources.

## The two reviewed gates

### 1. Exact URL access review registry

File: agentfuse_crawlers/data/validation_access_reviews.json

Starts with reviews={} and default_decision=not_reviewed. Future human-approved records must pin original source ID, exact URL, category, an allowed/denied/deferred decision, applicable validation scope(s), reviewer and timezone-aware review/expiry (maximum 30 days), first-party ownership evidence URL, publisher access-terms URL, exact-host robots.txt URL, three affirmative access/robots/private-retention attestations, and meaningful publisher-specific review notes.

A missing, stale, denied, quarantined, wrong-host, wrong-product, forged or out-of-scope review can never permit a bulk request. These attestations represent operator research, not proof of a legal grant or publisher agreement.

### 2. Exact expiring Git-reviewed run plan registry

File: agentfuse_crawlers/data/bulk_run_authorizations.json

Starts with plans={} and default_policy=no_bulk_runs_authorized. Any future reviewed plan must name a category and cohort, all selected source IDs in exact manifest order, the approved source subset, manifest/lifecycle/access-review fingerprints, full exact source URL binding, human reviewer, seven-day maximum expiry, one explicit validation purpose, primary-request budget and redirect cap (zero through three). Static reviewed plan data is part of the deployed package. Arbitrary spider arguments and user-supplied checksums cannot mint approvals.

The actual job additionally needs a matching current deployed package fingerprint and exact per-plan SHA-256 supplied as separate Zyte arguments. Those checks guard against stale deployment and copied plans. A checksum is an integrity control, not an independent publisher permission review.

The existing collection_mode=monitor approval remains totally separate and retains the two independently reviewed successful job requirement.

### Sensitive data policy

Do not commit publisher correspondence, confidential contractual terms, raw HTML, passwords or human secrets. Reviewers must assess whether any public official policy URLs and minimal review metadata are appropriate to place in the Git-reviewed package before proposing a new positive review. An unavailable human permission decision stays denied.

## Zyte arguments: before and after

For ONE previously reviewed, exact source:

    Spider: official_changelogs
    Job Units: 1
    Priority: Normal
    cohort = all
    source_ids = openai_api_changelog
    collection_mode = validation

This is a bounded example, not a statement that the publisher has approved it. Independent human publisher-policy review is still required.

For a FUTURE, separately authorized bulk diagnostic, the older arguments remain necessary but are insufficient on their own:

    cohort = all
    confirm_full_inventory = yes
    collection_mode = validation
    expected_manifest_sha256 = [current hash]
    expected_selection_ids_sha256 = [current spider selection hash]
    expected_source_registry_sha256 = [current lifecycle hash]

Additional mandatory rows, only after genuine Git-reviewed records exist:

    bulk_run_plan_id = [existing reviewed plan ID]
    expected_bulk_plan_sha256 = [hash of exact deployed plan]
    expected_deployment_package_sha256 = [ACTUAL deployed package fingerprint]

**There is NO working bulk plan ID in this PR.** A made-up plan ID is rejected before any publisher request. Omitting all new plan arguments yields held source-summary Items, not live publisher evidence. The old three-spider full-crawl UI configuration is now deliberately non-fetching unless separately approved.

## Engineering limits and failure behavior

- A reviewed category run can include at most 200 source IDs and no more initial page Requests than explicitly authorized source IDs.
- Same-host redirect depth respects each reviewed plan cap (0 to 3). Cross-host redirects remain blocked.
- A separately hosted official Markdown alternate is a DIFFERENT URL and is disabled in bulk mode pending a separate URL-specific review.
- Existing robots.txt obedience, two total concurrent requests, one per domain, three-second delay, limited server-error retries and no proxy/CAPTCHA/access-control evasion remain.
- Even 200 responses remain unverified and never auto-approve an AgentFuse price or announcement.
- An access review and run plan are operator attestations checked into a reviewed deployed package. They cannot establish independent legal authorization. **A static run-plan file cannot guarantee one-shot consumption** or prevent a repeat during its brief validity; true single-use needs a future trusted stateful job authorization service.

## Offline policy readiness report

From a reviewed repository checkout:

    python -m scripts.audit_bulk_validation_policy --out-dir output/private/p21b-bulk-audit-1

This creates a NEW owner-private report with a JSON summary and a 460-row CSV. It separates the 457 technically selectable URLs from 0 currently source-reviewed bulk URLs and 0 packaged approved run plans. The audit performs zero publisher or Zyte requests and grants no new rights.

## Merge checklist and next steps

This PR intentionally changes the deployed Python/JSON package fingerprint. GitHub main can trigger automatic Zyte redeployment; do not merge without checking Python 3.12/3.14 CI, code review, exact deployed fingerprint and downstream source accounting.

After an operator-approved merge, verify in Zyte that an unapproved full spider emits held Items for every selected source, with zero source GETs; then, only with individually reviewed publisher access, run a one-source manual smoke test. Recheck original source URL, robots handling, policy skip reasons and source count.

Next is P22A: bounded, genuinely permitted original publisher HTML and independent source-specific human review. A safer bulk launch does not make observed pricing, documentation or release events correct. The November 4 460-source baseline remains the comparison dataset; no new 460-source crawl is needed now.
