import json

from scripts.compare_exports import compare, export, review_queue, read_jsonl


def record(sid, fingerprint, status='captured', category='changelog', sections=None):
    return {'source_id': sid, 'provider': 'OpenAI', 'category': category,
            'status': status, 'content_sha256': fingerprint, 'source_url': 'https://example.com',
            'sections': sections or []}


def section(name, sha):
    return {'section_id': name, 'heading': name, 'sha256': sha,
            'section_url': 'https://example.com/#' + name, 'excerpt': 'New model release available.'}


def test_page_diff_never_claims_new_feature_on_baseline():
    cur = {'a': record('a', 'b'), 'b': record('b', 'a'), 'c': record('c', '', 'http_error')}
    prev = {'a': record('a', 'a'), 'b': record('b', 'a')}
    res = {c['source_id']: c['change_type'] for c in compare(cur, prev)}
    assert res == {'a': 'page_text_changed', 'b': 'unchanged', 'c': 'not_captured'}
    assert compare({'a': record('a', 'x')}, {})[0]['change_type'] == 'new_baseline'
    assert review_queue({'a': record('a', 'x')}, {}, compare({'a': record('a', 'x')}, {})) == []


def test_section_changes_are_evidence_not_approved_announcements():
    old = record('a', 'abc', sections=[section('old', '1'), section('changed', '1')])
    new = record('a', 'def', sections=[section('added', '2'), section('changed', '2')])
    changes = compare({'a': new}, {'a': old})
    queue = review_queue({'a': new}, {'a': old}, changes)
    assert {x['change_type'] for x in queue} == {'section_added', 'section_modified', 'section_removed'}
    assert all(x['approved_for_advisor'] is False for x in queue)


def test_truncated_input_does_not_invent_removed_entries():
    old = record('a', 'abc', sections=[section('old', '1')])
    new = record('a', 'def', sections=[section('new', '2')])
    new['sections_truncated'] = True
    assert not any(x['change_type'] == 'section_removed' for x in
                   review_queue({'a': new}, {'a': old}, compare({'a': new}, {'a': old})))


def test_export_scope_single_spider_and_missing_health(tmp_path):
    current = {'openai_api_pricing': record('openai_api_pricing', 'abc', category='pricing')}
    summary = export(current, {}, tmp_path, category='auto')
    assert summary['categories'] == ['pricing']
    assert summary['sources_expected'] >= 3
    assert summary['sources_captured'] == 1
    assert summary['approved_for_advisor'] == 0
    assert (tmp_path / 'review_queue.jsonl').exists()
    assert (tmp_path / 'status.csv').exists()
    assert json.loads((tmp_path / 'summary.json').read_text())['capture_rate'] < 1


def test_zyte_json_array_and_jsonl_supported(tmp_path):
    row = record('openai_api_pricing', 'aaa', category='pricing')
    a = tmp_path / 'items.json'
    a.write_text(json.dumps([row]))
    b = tmp_path / 'items.jl'
    b.write_text(json.dumps(row) + '\n')
    assert read_jsonl([a])['openai_api_pricing']['content_sha256'] == 'aaa'
    assert read_jsonl([b])['openai_api_pricing']['content_sha256'] == 'aaa'



def test_export_auto_scope_understands_daily_proven_cohort(tmp_path):
    from agentfuse_crawlers.sources import load_sources
    all_proven_changelogs = [
        row for row in load_sources()
        if row['category'] == 'changelog' and row['id'] in {
            'openai_api_changelog', 'anthropic_api_changelog', 'gemini_api_changelog'
        }
    ]
    rows = {}
    for src in all_proven_changelogs:
        item = record(src['id'], 'hash-' + src['id'])
        item['source_cohort'] = 'proven'
        rows[src['id']] = item
    summary = export(rows, {}, tmp_path, category='changelog')
    assert summary['cohort_scope'] == 'proven'
    assert summary['sources_expected'] == 3
    assert summary['sources_captured'] == 3
    assert summary['capture_rate'] == 1


def test_limited_candidate_cohort_does_not_mark_unrequested_sources_missing(tmp_path):
    from agentfuse_crawlers.sources import load_sources, load_proven_source_ids
    proven = load_proven_source_ids()
    candidate = next(s for s in load_sources()
                     if s['category'] == 'pricing' and s['id'] not in proven)
    row = record(candidate['id'], 'sha', category='pricing')
    row['source_cohort'] = 'candidate'
    result = export({candidate['id']: row}, {}, tmp_path,
                    category='pricing', source_ids=candidate['id'])
    assert result['sources_expected'] == 1


def test_v21_mismatched_provider_url_is_rejected(tmp_path):
    import pytest
    row = record('openai_api_pricing', 'sha', category='pricing')
    row.update(schema_version='2.1', source_cohort='proven')
    with pytest.raises(ValueError, match='mismatched source identity'):
        export({'openai_api_pricing': row}, {}, tmp_path, category='pricing')


def test_legacy_truncated_table_snapshot_is_not_a_reliable_price_baseline():
    old = record('a', 'sha1', category='pricing')
    old['tables_truncated'] = True
    new = record('a', 'sha2', category='pricing')
    assert compare({'a': new}, {'a': old})[0]['change_type'] == 'new_baseline'



def test_review_export_respects_offset_for_scheduled_job(tmp_path):
    from agentfuse_crawlers.sources import select_sources
    batch = select_sources("changelog", cohort="candidate", offset=15, limit=10)
    rows = {}
    for src in batch:
        entry = record(src["id"], "hash-" + src["id"], category="changelog")
        entry["source_cohort"] = "candidate"
        rows[src["id"]] = entry
    summary = export(rows, {}, tmp_path, category="changelog",
                     cohort="candidate", offset=15, limit=10)
    assert summary["sources_expected"] == 10
    assert summary["sources_captured"] == 10
    assert summary["capture_rate"] == 1
    assert summary["offset_per_category"] == 15
    assert summary["approved_for_advisor"] == 0


def test_export_rejects_out_of_range_offset(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="empty"):
        export({}, {}, tmp_path, category="pricing",
               cohort="candidate", offset=10000, limit=10)



def test_official_url_migration_is_new_baseline_not_fresh_release():
    before = record("google_cloud_ai_changelog", "sha-old")
    after = record("google_cloud_ai_changelog", "sha-new")
    before["source_url"] = "https://docs.cloud.google.com/vertex-ai/docs/release-notes"
    after["source_url"] = "https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes"
    changes = compare({"google_cloud_ai_changelog": after},
                      {"google_cloud_ai_changelog": before})
    assert changes[0]["change_type"] == "new_baseline"
    assert review_queue({"google_cloud_ai_changelog": after},
                        {"google_cloud_ai_changelog": before}, changes) == []



def _versioned_row(source_id, cohort="all"):
    from agentfuse_crawlers.sources import load_sources, select_sources
    from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
    manifest = load_sources()
    src = next(x for x in manifest if x["id"] == source_id)
    batch = select_sources(src["category"], cohort=cohort)
    row = record(source_id, "stable-sha", category=src["category"])
    row.update({
        "schema_version": "2.1",
        "provider": src["provider"],
        "source_url": src["url"],
        "requested_cohort": cohort,
        "selection_source_count": len(batch),
        "selection_ids_sha256": selection_ids_sha256(batch),
        "manifest_sha256": manifest_sha256(manifest),
        "spider_name": {
            "changelog": "official_changelogs",
            "documentation": "official_documentation",
            "pricing": "official_pricing",
        }[src["category"]],
        "run_started_at_utc": "2026-10-31T10:00:00+00:00",
        "zyte_job_id": "883514/1/100",
        "deployment_revision": "",
        "source_cohort": "proven",
    })
    return row


def test_requested_job_cohort_prevents_false_proven_only_scope(tmp_path):
    from agentfuse_crawlers.sources import select_sources
    # One historical proven member found in a job that actually requested ALL.
    row = _versioned_row("openai_api_changelog", cohort="all")
    summary = export({row["source_id"]: row}, {}, tmp_path, category="changelog")
    assert summary["cohort_scope"] == "all"
    assert summary["cohort_source"] == "requested_job"
    assert summary["run_provenance_validation"] == "verified_against_current_manifest_and_args"
    assert summary["sources_expected"] == len(select_sources("changelog", "all"))
    assert summary["sources_captured"] == 1


def test_changed_manifest_hash_fails_closed(tmp_path):
    import pytest
    row = _versioned_row("openai_api_changelog", cohort="proven")
    row["manifest_sha256"] = "another-deployment"
    with pytest.raises(ValueError, match="Manifest fingerprint mismatch"):
        export({row["source_id"]: row}, {}, tmp_path, category="changelog")


def test_mixed_same_category_job_metadata_fails_closed(tmp_path):
    import pytest
    one = _versioned_row("openai_api_changelog", cohort="proven")
    two = _versioned_row("anthropic_api_changelog", cohort="proven")
    two["run_started_at_utc"] = "2026-10-31T11:00:00+00:00"
    with pytest.raises(ValueError, match="Mixed Zyte jobs"):
        export({one["source_id"]: one, two["source_id"]: two},
               {}, tmp_path, category="changelog")


def test_selected_source_id_requires_matching_job_scope_args(tmp_path):
    import pytest
    row = _versioned_row("openai_api_changelog", cohort="all")
    with pytest.raises(ValueError, match="Selection fingerprint mismatch"):
        export({row["source_id"]: row}, {}, tmp_path,
               category="changelog", cohort="all",
               source_ids="openai_api_changelog")



def test_valid_v21_source_identity_passes_and_wrong_provider_fails(tmp_path):
    import pytest
    good = _versioned_row("openai_api_changelog", cohort="proven")
    summary = export({good["source_id"]: good}, {}, tmp_path, category="changelog")
    assert summary["run_provenance_validation"] == "verified_against_current_manifest_and_args"
    bad = dict(good, provider="AnotherCompany")
    with pytest.raises(ValueError, match="mismatched source identity"):
        export({bad["source_id"]: bad}, {}, tmp_path / "bad", category="changelog")



def test_clipped_sections_must_not_generate_false_section_changes():
    old = record("a", "old", sections=[section("release", "s1")])
    newer_section = section("release", "s2")
    newer_section["excerpt_truncated"] = True
    new = record("a", "new", sections=[newer_section])
    changes = compare({"a": new}, {"a": old})
    assert changes[0]["change_type"] == "not_captured"
    assert review_queue({"a": new}, {"a": old}, changes) == []


def test_duplicate_items_in_same_job_are_rejected_at_import(tmp_path):
    import pytest
    row = _versioned_row("openai_api_changelog", cohort="proven")
    data = tmp_path / "duplicate_items.jl"
    data.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="Duplicate source Item"):
        read_jsonl([data])
