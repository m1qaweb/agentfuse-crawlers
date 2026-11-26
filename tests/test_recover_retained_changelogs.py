import pytest

from scripts.recover_retained_changelogs import digest, recover, recover_item


def item(sid='deepseek_changelog', text='Date: 2026-11-13\u200b\nSynthetic model update\u200b\nA synthetic model supports a new test feature.', **kwargs):
    row = {'source_id': sid, 'category': 'changelog', 'http_status': 200, 'text': text,
           'source_url': 'https://example.com/changelog', 'canonical_url': 'https://example.com/changelog/',
           'fetched_at_utc': '2026-11-26T00:00:00Z', 'zyte_job_id': '1/2/3', 'content_sha256': 'c'*64,
           'review_status': 'unverified', 'approved_for_advisor': False, 'release_events': [],
           'latest_publication_verified': False, 'source_product_ownership_verified': False,
           'public_diagnostic_publisher_rights_independently_verified': False,
           'quality_axes': {'content_capture_status': 'text_observed_unverified'}}
    row.update(kwargs)
    return row


def event(title, sid='deepseek_changelog', published=None, suffix='a'):
    return {'source_id': sid, 'title': title, 'event_id': sid+':'+suffix*24,
            'body_sha256': 'b'*64, 'published_at': published, 'approved_for_advisor': False, 'review_status': 'unverified'}


def entry(row=None):
    row = item() if row is None else row
    return {'source_id': row['source_id'], 'item': row, 'approved_for_advisor': False,
            'evidence': {'http_status': 200, 'job_id': '1/2/3', 'items_sha256': 'a'*64, 'requests_sha256': 'b'*64,
                         'item_index': 0, 'request_index': 1}}


def test_exact_locator_and_review_only_link():
    row = item(release_events=[event('Synthetic model update\u200b')])
    state, rr = recover_item(row)
    assert state == 'review_candidates' and len(rr) == 1
    c = rr[0]
    assert c['displayed_date_candidate'] == '2026-11-13' and c['date_precision'] == 'day'
    assert c['existing_event_link_state'] == 'unique_undated_title'
    assert c['existing_event_reference']['event_sha256'] == digest(row['release_events'][0])
    for loc in c['evidence_locators']:
        assert row['text'][loc['start']:loc['end']] == loc['evidence_text']
        assert digest(loc['evidence_text']) == loc['evidence_sha256']
    assert c['approved_for_advisor'] is c['publication_date_verified'] is c['alert_eligible'] is False


def test_deepseek_does_not_inherit_date_for_subheading():
    row = item(text=item()['text']+'\nOther model update\u200b\nThis is an undated nested heading with a date mentioned in prose: 2026-11-19.')
    assert [c['title'] for c in recover_item(row)[1]] == ['Synthetic model update']


@pytest.mark.parametrize('day', ['2026-02-30', '2026-11-27'])
def test_impossible_and_future_date_rejected(day):
    assert not recover_item(item(text=item()['text'].replace('2026-11-13', day)))[1]


def test_release_header_not_build_date():
    text = '2026.11.19 (v0.2026.11.18.08.17)\nSection titled “2026.11.19 (v0.2026.11.18.08.17)”\nImprovements\nSynthetic feature is available.'
    rr = recover_item(item('warp_changelog', text))[1]
    assert len(rr) == 1 and rr[0]['displayed_date_candidate'] == '2026-11-19'
    assert rr[0]['version_label'] == 'v0.2026.11.18.08.17'
    assert not recover_item(item('warp_changelog', text.replace('Section titled', 'Example')))[1]


def test_gemini_announcement_not_stable_release_claim():
    title = 'Announcements: v0.64.0 - 2026-10-13'
    text = title+'\nSection titled “'+title+'”\nSynthetic notes for this version.'
    rr = recover_item(item('gemini_cli_changelog', text))[1]
    assert rr[0]['record_kind'] == 'dated_announcement_heading'
    assert not recover_item(item('gemini_cli_changelog', text.replace('Section titled', 'Example')))[1]


def test_publisher_wide_cards_not_ai_product_attribution():
    text = 'Synthetic warehouse update\nNovember 20, 2026 · Example Team\nA synthetic warehouse now supports a test feature.'
    rr = recover_item(item('posthog_ai_observability_changelog', text))[1]
    assert len(rr) == 1 and 'publisher_wide_not_ai_product_attribution' in rr[0]['normalization_blockers']
    text = 'Synthetic SDK update\nA new synthetic SDK has a test feature.\nNovember 20, 2026Read On →'
    rr = recover_item(item('sentry_seer_changelog', text))[1]
    assert len(rr) == 1 and 'publisher_wide_not_ai_product_attribution' in rr[0]['normalization_blockers']


def test_month_precision_and_footer_boundary():
    text = 'November 2026\nNew docs: Synthetic docs.\nNew parameter: Added a synthetic field.\nFeatures\nNew feature: A footer example.'
    rr = recover_item(item('hyper3d_rodin_changelog', text))[1]
    assert len(rr) == 2 and all(c['displayed_date_candidate'] == '2026-11' and c['date_precision'] == 'month' for c in rr)
    assert all(c['existing_event_reference'] is None for c in rr)


def test_blog_index_not_release_proof():
    text = 'NOV 19, 2026/ResearchSynthetic research\nNOV 18, 2026/AnnouncementsSynthetic announcement\nNOV 17, 2026/Case StudySynthetic case'
    rr = recover_item(item('prime_intellect_changelog', text))[1]
    assert len(rr) == 1 and rr[0]['record_kind'] == 'announcement_index_entry'
    assert 'article_body_not_observed_not_release_proof' in rr[0]['normalization_blockers']


def test_duplicate_titles_across_dates_do_not_link_to_undated_event():
    text = item()['text']+'\n'+item()['text'].replace('2026-11-13', '2026-11-12')
    rr = recover_item(item(text=text, release_events=[event('Synthetic model update')]))[1]
    assert len(rr) == 2 and all(c['existing_event_link_state'] == 'ambiguous_title_or_identity' and c['existing_event_reference'] is None for c in rr)
    assert not recover_item(item(text=item()['text']+'\n'+item()['text']))[1]


def test_conflicting_retained_date_and_identity_collision_not_overwritten():
    rr = recover_item(item(release_events=[event('Synthetic model update', published='2026-11-12')]))[1]
    assert rr[0]['existing_event_link_state'] == 'date_conflict' and rr[0]['existing_event_reference'] is None
    rr = recover_item(item(release_events=[event('Synthetic model update'), event('Other title')]))[1]
    assert rr[0]['existing_event_link_state'] == 'ambiguous_title_or_identity'


@pytest.mark.parametrize('changes,state', [({'freshness_warnings':['stale']},'freshness_review_required'),
    ({'source_product_title_conflict':True},'identity_or_ui_review_required'),
    ({'release_ui_contamination_requires_review':True},'identity_or_ui_review_required'),
    ({'canonical_url':'https://example.com/other'},'canonical_review_required'),
    ({'quality_axes':{'content_capture_status':'insufficient_text'}},'insufficient_text'),
    ({'source_id':'unselected_changelog'},'layout_not_selected'),
    ({'text_truncated':True},'no_eligible_explicit_date_layout')])
def test_exclusion(changes, state):
    assert recover_item(item(**changes)) == (state, [])


def test_coverage_and_no_distinct_event_inflation():
    row = item(release_events=[event('Synthetic model update')])
    report, rr = recover([entry(row), entry(item('unselected_changelog'))])
    assert report['source_count'] == 2 and report['recovered_observations'] == 1
    assert report['retained_event_records'] == 1 and report['retained_day_date_candidates'] == 0
    assert report['distinct_release_total_verified'] is False and report['alert_eligible_count'] == 0
    assert rr[0]['primary_evidence'] == entry(row)['evidence']


@pytest.mark.parametrize('mutation', ['duplicate','approval','rights','latest','product','bad_job','bad_index','bad_digest','privileged_event'])
def test_reject_invalid_or_privileged_evidence(mutation):
    e = entry()
    if mutation == 'approval':
        e['approved_for_advisor'] = True
    elif mutation == 'rights':
        e['item']['public_diagnostic_publisher_rights_independently_verified'] = True
    elif mutation == 'latest':
        e['item']['latest_publication_verified'] = True
    elif mutation == 'product':
        e['item']['source_product_ownership_verified'] = True
    elif mutation == 'bad_job':
        e['evidence']['job_id'] = '4/5/6'
    elif mutation == 'bad_index':
        e['evidence']['item_index'] = -1
    elif mutation == 'bad_digest':
        e['evidence']['items_sha256'] = 'bad'
    elif mutation == 'privileged_event':
        e['item']['release_events'] = [dict(event('Synthetic model update'), approved_for_advisor=True)]
    with pytest.raises(ValueError):
        recover([e,e] if mutation == 'duplicate' else [e])
