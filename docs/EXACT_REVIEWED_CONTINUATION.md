# Phase 3C — Exact reviewed continuation (not launch authorization)

The historical campaign already has 200 HTTP 200 sources. Do not pad a
continuation to the P25 fresh-campaign minimum of 200 merely to achieve
cumulative coverage. This narrow offline companion to P26A uses the existing
P21B exact reviewed-subset schema. It is not a replacement policy or a launcher.

## Inputs and command

Use the private, canonical Phase 1 inventory.json (460 original identities,
200 HTTP 200, 51 redirects, 209 without primary responses). Its canonical JSON
SHA-256 is b4f9310004b90f02c0c98bac1fd39227df11c3d6fd262abcc9d8ba2a8b7fe14b.
Do not edit it after a manifest migration.

The scope file is private and explicitly selects missing source IDs and
intended exact URLs. It has exactly these top-level fields:

    {
      "kind": "exact_continuation_review_scope_NOT_AUTHORIZATION",
      "current_manifest_sha256": "<actual current manifest digest>",
      "targets": [
        {
          "source_id": "<historically missing source ID>",
          "source_url": "<exact intended HTTPS URL>",
          "hold_resolution_note": ""
        }
      ]
    }

Blank hold notes are appropriate for pending review, not clearance.
A target with historical group holds needs actual documented disposition
in its installed exact-source review's evidence_note. Include every
inherited historical group ID and recorded reason, and copy that substantive
disposition into hold_resolution_note. This is clerical consistency
checking, not verification of the human's conclusion. Changing origins
cannot erase a historical hold; current containment components inherit
the historical holds of their members. Current lifecycle checks also apply.
Resolve any relevant new containment issues independently.

    python -m scripts.prepare_reviewed_continuation \
      --historical-inventory /private/consolidated/inventory.json \
      --scope /private/continuation_scope_REVIEW_ONLY.json \
      --out-dir /private/new-continuation

The CLI checks the historical fingerprint, original ordered source identities,
current manifest and exact requested URL, installed access/plan registries,
and current per-source bulk review using P21B. Duplicate, unknown or already
acquired IDs and colliding/unsafe URLs fail closed. The planner refuses
to replace an existing full-category plan. It emits a NO-GO report and only
if every selected target has the required reviews, an unsigned draft for
each selected nonempty category. No implicit fallback, quota padding, or
partial selection. A smaller explicit scope can be reviewed separately.

Drafts contain full category selection IDs, exact reviewed subsets in
manifest order, exact hashes and request counts with zero redirects. The
approval name and timestamps are blank and policy attestation false, so
the existing runtime plan validator rejects them. A named accountable
operator must review and complete these fields before a separate reviewed
registry change. Keep unrelated existing plans and review any replacement
explicitly. Expiry and package/deployment verification remain required.
The existing three-argument convenience is applicable only to the uniquely
matching installed full-category plan, after all gates pass. No arguments
for a new executable run are issued by this tool.

## November 26 real review outcome

After the Phase 3B 30-candidate review, five more URLs are conservatively
excluded pending applicable permission or policy scope resolution:

- AI21 documentation: [website terms](https://www.ai21.com/terms-of-service/)
  and [service terms](https://www.ai21.com/terms-policies/terms-of-use/)
  restrict automated access/use; confirm exact page applicability.
- Hyperbolic documentation: [terms](https://www.hyperbolic.ai/terms), section 7,
  restrict scraping and archive use; search indexing exception is not clearance.
- You.com documentation: [terms](https://about.you.com/legal/terms) restrict
  programmatic extraction and scraping absent applicable permission.
- LangWatch documentation: [terms](https://langwatch.ai/legal/terms-conditions)
  restrict commercial exploitation and automated platform use; distinguish
  website terms from separate licensed repository content.
- W&B Weave pricing: [website terms](https://wandb.ai/site/website-terms-of-use/)
  restrict copying the website without written permission; planned raw
  archival workflow has no demonstrated clearance.

The separate [Mintlify docs MIT license](https://github.com/mintlify/mintlify-docs/blob/main/LICENSE),
[Vapi docs repository](https://github.com/VapiAI/docs) with MIT license,
and [LangWatch monorepo Apache license](https://github.com/langwatch/langwatch/blob/main/LICENSE.md)
are research leads for independently licensed source acquisition. Confirm
exact file license, exceptions, provenance, access terms and notices.
These do not establish permission for hosted website crawling or count as
Zyte acquisitions. Do not use an alternative transport to bypass a denial.

The private supplemental review packet also records policy links for seven
other source IDs; none supplies positive exact-URL/robots/retention clearance.
No current crawler-UA robots review was completed in this pass.

Actual pure-builder replay on the SHA-bound historical inventory, unchanged
manifest and containment mapping, and inspected empty installed access and
plan registries: 25 proposed targets (18 docs, 5 pricing, 2 changelogs);
24 manifest migrations required, 25 missing exact access reviews, 13 missing
historical hold dispositions; zero ready and zero unsigned drafts. The
conditional cumulative ceiling of this pool is 225 HTTP 200 sources, not
a forecast. Twenty-five more successes beyond this pool would still be
needed to reach 250. The private packet contains the proposed scope and
blank review fields; it is not an importable signed registry.

Sixteen isolated local regressions passed. The actual P21B integration test
was skipped locally because the full crawler package could not be cloned in
the execution environment; normal repository CI must exercise it. No runtime,
manifest, access or lifecycle registry changed; no publisher data committed,
new fact verified, paid request made, or hold released.

Next: complete actual human source review and permitted migrations; use
the exact continuation planner only after installing the corresponding
reviews. Additional coding alone cannot satisfy those review dependencies.
