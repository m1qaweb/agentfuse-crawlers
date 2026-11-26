"""Exercise the live HTML extractor on synthetic representatives of retained layouts."""
from lxml import html
import pytest

from agentfuse_crawlers.release_events import extract_release_events


def extract(sid, url, markup):
    return extract_release_events(html.fromstring('<main>' + markup + '</main>'), url, sid)


@pytest.mark.parametrize('sid,url,level,title,version', [
    ('gemini_cli_changelog', 'https://geminicli.com/docs/changelogs/', 2,
     'Announcements: v0.99.1 - 2026-11-12', '0.99.1'),
    ('warp_changelog', 'https://docs.warp.dev/changelog/2026/', 3,
     '2026.11.12 (v0.2026.11.11.07.42)', '0.2026.11.11.07.42'),
])
def test_actual_extractor_recognizes_exact_heading(sid, url, level, title, version):
    markup = f'<h{level} id="entry">{title}</h{level}><p>Synthetic release notes.</p>'
    result = extract(sid, url, markup)
    assert result['release_identity_revision'] == 'release_owner_date_scope_v6'
    assert result['release_event_count'] == 1
    event = result['release_events'][0]
    assert (event['title'], event['published_at'], event['version']) == (title, '2026-11-12', version)
    assert event['permalink'] == url + '#entry'
    assert event['approved_for_advisor'] is result['latest_publication_verified'] is False
    assert extract('unrelated_changelog', url, markup)['release_events'][0]['published_at'] is None
    assert extract(sid, url + 'other', markup)['release_events'][0]['published_at'] is None


def test_deepseek_group_limits_dates_to_direct_child_headings():
    result = extract('deepseek_changelog', 'https://api-docs.deepseek.com/updates/', '''
      <h2>Date: 2026-11-12&#8203;</h2><p>Page introduction, not a release entry.</p>
      <h4>Unowned deeper heading</h4>
      <h3 id="one">Synthetic new capability</h3><p>First release evidence.</p>
      <h4>Details for v2.1.0</h4><p>Nested version is part of the release body.</p>
      <p>December 1, 2026</p>
      <h3 id="two">Synthetic second capability</h3><p>Second release evidence.</p>
      <h2>Unrelated v4.0.0</h2><p>Undated notes outside the group.</p>
    ''')
    found = result['release_events']
    assert [(e['title'], e['published_at']) for e in found] == [
        ('Synthetic new capability', '2026-11-12'),
        ('Synthetic second capability', '2026-11-12'),
        ('Unrelated v4.0.0', None),
    ]
    assert 'Details for v2.1.0' in found[0]['excerpt']
    assert result['latest_release_date_candidate'] is None


def test_impossible_group_date_clears_previous_day():
    result = extract('deepseek_changelog', 'https://api-docs.deepseek.com/updates/', '''
      <h2>Date: 2026-11-12</h2><h3>First release</h3><p>Synthetic notes.</p>
      <h2>Date: 2026-02-30</h2><h3>Release v3.0.0</h3><p>Undated notes.</p>
    ''')
    assert [(e['title'], e['published_at']) for e in result['release_events']] == [
        ('First release', '2026-11-12'), ('Release v3.0.0', None)]


def test_date_group_does_not_apply_to_different_source():
    result = extract('unknown_changelog', 'https://api-docs.deepseek.com/updates/', '''
      <h2>Date: 2026-11-12&#8203;</h2><h3>Release v3.0.0</h3><p>Synthetic notes.</p>
    ''')
    assert result['release_events'][0]['published_at'] is None


def test_invalid_warp_day_never_substitutes_build_date():
    result = extract('warp_changelog', 'https://docs.warp.dev/changelog/2026/', '''
      <h3>2026.11.31 (v0.2026.11.11.07.42)</h3><p>Synthetic notes.</p>
    ''')
    event = result['release_events'][0]
    assert event['published_at'] is None
    assert event['version'] == '0.2026.11.11.07.42'
