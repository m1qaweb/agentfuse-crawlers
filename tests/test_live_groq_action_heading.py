"""Live HTML extractor integration on synthetic action-heading layouts."""
from lxml import html

from agentfuse_crawlers.release_events import extract_release_events
from agentfuse_crawlers.release_heading_layouts import GROQ_ACTION_SCOPE

SID, URL = GROQ_ACTION_SCOPE


def extract(markup, sid=SID, url=URL):
    return extract_release_events(html.fromstring('<main>' + markup + '</main>'), url, sid)


ADDED = '<h3 id="example-model"><span>Added</span>Example 3.6</h3><p>Example addition.</p>'
DEPRECATED = '<h3 id="example-model"><span>Deprecated</span>Example 3.6</h3><p>Example deprecation.</p>'


def test_shared_subject_anchor_distinct_provisional_actions():
    data = extract(ADDED + DEPRECATED)
    events = data['release_events']
    assert data['release_identity_revision'] == 'release_owner_date_scope_v7_groq_action'
    assert len(events) == data['release_event_count'] == data['release_action_identity_review_count'] == 2
    assert len({e['event_id'] for e in events}) == 2
    assert {e['permalink'] for e in events} == {URL + '#example-model'}
    assert all(e['version'] is None and e['published_at'] is None for e in events)
    assert all(e['identity_basis'] == 'groq_action_anchor_review_only'
               and e['release_identity_requires_manual_review'] is True
               and e['approved_for_advisor'] is False for e in events)
    assert data['release_event_identity_collision'] is False
    assert data['release_window_complete'] is False
    assert data['latest_release_date_candidate'] is None
    assert data['latest_publication_verified'] is data['approved_for_advisor'] is False
    reordered = extract(DEPRECATED + ADDED)
    assert {e['title']: e['event_id'] for e in events} == {
        e['title']: e['event_id'] for e in reordered['release_events']}


def test_same_action_and_anchor_still_collides():
    data = extract(ADDED + ADDED)
    assert data['release_event_count'] == 2
    assert data['release_event_identity_collision'] is True
    assert data['release_window_complete'] is False


def test_explicitly_dated_action_never_makes_comparable_window():
    data = extract('<p>November 27, 2026</p>' + ADDED)
    event = data['release_events'][0]
    assert event['published_at'] == '2026-11-27'
    assert event['version'] is None
    assert data['release_window_complete'] is False
    assert data['latest_release_date_candidate'] is None
    assert data['latest_release_date_status'] == 'action_identity_requires_review'


def test_undated_action_and_multiple_sdk_versions_preserved_without_release_version():
    data = extract('<h3 id="sdk-change">ChangedPython SDK v1.2.0 and TypeScript SDK v2.3.0</h3>'
                   '<p>Synthetic SDK update.</p>'
                   '<h3 id="example-capability">AddedExample Capability</h3>'
                   '<p>Synthetic feature.</p>')
    assert data['release_event_count'] == 2
    assert all(e['version'] is None and e['published_at'] is None
               for e in data['release_events'])
    assert 'v1.2.0 and TypeScript SDK v2.3.0' in data['release_events'][0]['title']


def test_action_handling_not_applied_to_other_source_or_nonmatching_url():
    for sid, url in [('other_changelog', URL), (SID, URL + '/other')]:
        data = extract(ADDED + DEPRECATED, sid=sid, url=url)
        assert data['release_identity_revision'] == 'release_owner_date_scope_v6'
        assert data['release_action_identity_review_count'] == 0
        assert data['release_event_identity_collision'] is True
        assert all(e['version'] == '3.6' for e in data['release_events'])
