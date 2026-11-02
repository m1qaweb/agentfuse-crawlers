# P18A2 — Reviewed Documentation Child Pages and Opt-In Private Capture

**State:** offline-safe implementation. The committed review registry has
**zero approved pages**. This does not establish new publisher permissions,
load a complete documentation corpus or approve AgentFuse capability facts.

## What changed since P18A1?

- P18A1 creates bounded **candidate human-review tasks** from Zyte
  documentation Items with no automatic collection rights.
- P18A2 introduces a **separate, exact, human-reviewed registry** that
  references original tasks, with policy evidence, product/canonical
  review, locale, version and expiration.
- Manual collection defaults to **zero network requests**. A nonempty
  registry requires the original P18A1 review packet. Explicit operator
  selection of 1-5 exact reviewed page IDs plus permission attestation
  is required before any HTML request.
- An allowed response is original HTML bytes with immutable SHA-256
  provenance, NOT a verified technical capability or advisor fact.

## 1. Default zero-network validation

    python -m scripts.capture_documentation_children

Expected: reviewed_registry_entries = 0, selected_count = 0,
network_requests_performed = 0, advisor_approved_facts = 0.

The tracked registry is at registries/approved_doc_pages_v1.json and
is intentionally empty. Do **not** add sample records as if an official
publisher approved them. Human review must happen first.

## 2. Generate the P18A1 packet; independently review exact pages

Use the actual preserved Zyte documentation Items (not fabricated rows):

    python -m scripts.plan_documentation_children \
      --items /private/archive/items_official_documentation_12.json \
      --source-ids openai_api_docs,anthropic_api_docs,gemini_api_docs \
      --per-source 8 --max-total 24 \
      --out-dir output/private/p18a2-human-queue

Review every first-party page for actual product ownership, its precise
canonical, site terms, robots and permitted research/retention, technical
topic, locale and version. Same host, HTTP 200, hashes and provisional
product-label hints are NOT independent approvals.

The registry has exactly one entry per allowed P18A1 task with fields:

- page_id: derived by the P18A2 page_id() helper from exact source/URL.
- source_id, source_url, child_url, product_id, task_id,
  parent_snapshot_sha256 and review_packet_sha256: exact packet bindings.
- policy_review: decision = permitted_single_manual_static_capture,
  an HTTPS publisher policy evidence URL, reviewed_by,
  reviewed_at_utc (timezone aware), expires_at_utc (<=90 days from review)
  and substantive review_note. This attests review; it cannot prove it.
- product_review: decision = exact_product_page_reviewed, reviewed_by,
  reviewed_at_utc, official_canonical_url, locale, version, and a
  technical_topic from the existing P13 topic taxonomy.
- capture_method = static_html, approved_for_manual_capture = true,
  approved_for_unattended_collection = false and approved_for_advisor = false.

Operator identity, raw page bodies, unpublished policy notes and packets
should live in output/private or another restricted location. You may
pass --registry /private/approved_doc_pages_v1.json to use a private
reviewed registry rather than committing those records. Do not guess
missing P18A1 snapshot hashes or canonical ownership.

## 3. Read-only validation against the exact reviewed packet

    python -m scripts.capture_documentation_children \
      --registry /private/approved_doc_pages_v1.json \
      --review-packet output/private/p18a2-human-queue/child_review_packet.json \
      --page-ids PAGE_ID_FROM_REVIEWED_REGISTRY

This produces a JSON **read-only plan**. It verifies source manifest,
lifecycle, product-profile SHA-256 pins, task and packet integrity,
product/canonical identity, expiry and quarantine. An unreviewed page
cannot be selected. SHA-256 is not a signature or a publisher permission.

## 4. Explicit manual original HTML capture

Only once the exact real first-party publisher page and terms have been
independently reviewed and the review record is valid:

    python -m scripts.capture_documentation_children \
      --registry /private/approved_doc_pages_v1.json \
      --review-packet output/private/p18a2-human-queue/child_review_packet.json \
      --page-ids PAGE_ID_FROM_REVIEWED_REGISTRY \
      --capture --policy-reviewed \
      --policy-review-note "Reviewed current publisher terms, robots and retention rules and confirmed this exact public research capture is permitted." \
      --out-dir output/private/p18a2-first-manual-capture

This requests no more than five exact reviewed pages. It checks robots
on each child URL before fetching HTML, uses the existing user agent
and minimum polite delay, rejects redirects, challenges, wrong content
types and unsafe canonicals, and bounds UTF-8 original HTML to 8 MB.

Original bytes plus child_html_snapshots.json and capture_audit.json are
written to new, private, non-symlink output only. Failed batches remove
their partial output. If the publisher page has no canonical, it remains
unverified; a different canonical triggers a stop for human review.

The collector NEVER follows returned links, auto-renders JavaScript,
bypasses bot restrictions, schedules work, expands the 460-source
manifest, writes to production Supabase or approves a capability fact.

## 5. Acceptance and remaining dependencies

- Python 3.12/3.14 CI must pass using entirely synthetic/fake HTTP tests.
- No crawler package changes: expect unchanged deployable fingerprint.
- No publisher requests are made as part of this engineering PR.
- P18A does not pass its 10-products x 8-approved-pages pilot target
  until actual real policy-reviewed subpages have been captured.
- Next P18B: offline, original-snapshot-bound technical claim candidates,
  followed by independent capability review and held-out precision.
- P17B real price accuracy also remains unmeasured until permitted
  publisher HTML is captured and two reviewers label actual rate cells.
- Do not rerun all 460 Zyte sources just to improve capture counts.
