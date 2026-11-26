import pytest

from scripts.recover_retained_documentation import digest, recover, recover_item


def item(sid='devin_docs', text='Devin is an autonomous AI software engineer that runs synthetic tasks.', **kwargs):
    row = {'source_id': sid, 'category': 'documentation', 'http_status': 200, 'text': text,
           'source_url': 'https://example.com/docs', 'title': 'Synthetic documentation',
           'content_sha256': 'c'*64, 'fetched_at_utc': '2026-11-26T00:00:00Z', 'zyte_job_id': '1/2/3',
           'review_status': 'unverified', 'approved_for_advisor': False,
           'public_diagnostic_publisher_rights_independently_verified': False, 'documentation_all_capabilities_verified': False,
           'documentation_scope_status': 'scope_not_established', 'documentation_canonical_relation': 'equivalent_path',
           'quality_axes': {'content_capture_status': 'text_observed_unverified'}}
    row.update(kwargs)
    return row


def entry(row=None):
    row = item() if row is None else row
    return {'source_id': row['source_id'], 'item': row, 'approved_for_advisor': False,
            'evidence': {'http_status': 200, 'job_id': row['zyte_job_id'], 'item_index': 0, 'request_index': 1,
                         'items_sha256': 'a'*64, 'requests_sha256': 'b'*64}}


def test_exact_offsets_and_unverified_scope():
    row = item()
    state, candidates = recover_item(row)
    assert state == 'review_candidates' and len(candidates) == 1
    c = candidates[0]
    loc = c['evidence_locator']
    assert row[loc['field']][loc['start']:loc['end']] == c['evidence_text']
    assert digest(c['evidence_text']) == c['evidence_sha256']
    assert c['approved_for_advisor'] is c['all_capabilities_verified'] is c['product_identity_verified'] is False
    assert 'original_documentation_scope_unresolved' in c['normalization_blockers']


def test_navigation_and_example_mentions_never_promoted():
    row = item(text='Features\nSDK\nMCP\nAPI\nExample: Devin is an autonomous AI software engineer.',
               documentation_nav_candidates=[{'label': 'Devin API'}])
    assert recover_item(row)[1] == []
    assert recover_item(item(sid='unknown_docs'))[1] == []


def test_section_fallback_and_truncated_boundary():
    statement = 'Agents operate within Projects and synthetic workspaces.'
    s = {'section_id': 'start', 'heading': 'Synthetic', 'excerpt': 'Synthetic\n'+statement+'\nMore.', 'excerpt_truncated': True}
    row = item(sid='google_antigravity_docs', text='', text_sample='Start', sections=[s])
    _, candidates = recover_item(row)
    assert len(candidates) == 1
    loc = candidates[0]['evidence_locator']
    assert loc['field'] == 'sections.excerpt' and loc['section_index'] == 0
    assert s['excerpt'][loc['start']:loc['end']] == statement
    assert 'reduced_retained_evidence' in candidates[0]['normalization_blockers']
    s['excerpt'] = 'Synthetic\n'+statement
    assert recover_item(row)[1] == []


def test_ambiguous_repetition_is_not_resolved_by_first_occurrence():
    row = item()
    row['text'] += '\n'+row['text']
    assert recover_item(row)[1] == []


@pytest.mark.parametrize('changes,state', [
    ({'freshness_warnings': ['stale']}, 'freshness_review_required'),
    ({'source_product_title_conflict': True}, 'product_scope_review_required'),
    ({'documentation_scope_review_reason': 'Wrong product'}, 'product_scope_review_required'),
    ({'documentation_canonical_relation': 'same_host_path_differs'}, 'canonical_review_required'),
    ({'documentation_scope_status': 'index_only'}, 'insufficient_or_index_only'),
    ({'quality_axes': {'content_capture_status': 'insufficient_text'}}, 'insufficient_or_index_only'),
    ({'source_id': 'browserless_docs'}, 'embedded_setup_prompt_not_fact_evidence')])
def test_excluded_sources(changes, state):
    assert recover_item(item(**changes)) == (state, [])


def test_lifecycle_and_product_boundaries():
    row = item('ibm_watsonx_ai_docs', 'Infer text\nPOST /ml/v1/text/generation\nInfer the next tokens for a synthetic model.\nThis API is legacy, use a synthetic alternative.')
    _, rr = recover_item(row)
    assert len(rr) == 1 and rr[0]['topic'] == 'lifecycle_notice'
    assert '/ml/v1/text/generation' in rr[0]['evidence_text']
    assert 'effective_date_and_lifecycle_review_required' in rr[0]['normalization_blockers']


def test_coverage_separate_from_fact_counts():
    good = entry()
    blocked = entry(item(sid='another_docs', documentation_scope_status='index_only'))
    report, rr = recover([good, blocked])
    assert report['source_count'] == 2 and report['sources_with_candidates'] == 1
    assert report['candidate_count'] == 1 and report['independently_verified_facts'] == 0
    assert report['navigation_links_promoted'] == 0
    assert rr[0]['primary_evidence'] == good['evidence']


@pytest.mark.parametrize('mutation', ['duplicate', 'approved', 'rights', 'all_caps', 'wrong_job', 'digest', 'bad_index'])
def test_provenance_rejects_unbound_or_privileged_evidence(mutation):
    e = entry()
    if mutation == 'approved':
        e['approved_for_advisor'] = True
    elif mutation == 'rights':
        e['item']['public_diagnostic_publisher_rights_independently_verified'] = True
    elif mutation == 'all_caps':
        e['item']['documentation_all_capabilities_verified'] = True
    elif mutation == 'wrong_job':
        e['evidence']['job_id'] = '4/5/6'
    elif mutation == 'digest':
        e['evidence']['items_sha256'] = 'bad'
    elif mutation == 'bad_index':
        e['evidence']['request_index'] = -1
    with pytest.raises(ValueError):
        recover([e, e] if mutation == 'duplicate' else [e])
