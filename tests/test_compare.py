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
