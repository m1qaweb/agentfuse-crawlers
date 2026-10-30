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
