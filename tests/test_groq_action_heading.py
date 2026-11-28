"""Synthetic representatives of the observed Groq action/anchor layout."""
import pytest

from agentfuse_crawlers.release_heading_layouts import GROQ_ACTION_SCOPE, groq_action_heading

SID, URL = GROQ_ACTION_SCOPE
ANCHOR = 'example-model-36'


@pytest.mark.parametrize('title,action', [
    ('AddedExample 3.6', 'added'),
    ('DeprecatedExample 3.6', 'deprecated'),
    ('Removed Example 3.6', 'removed'),
    ('Changed Python SDK v1.2.0 and TypeScript SDK v2.1.0', 'changed'),
])
def test_exact_labeled_action(title, action):
    assert groq_action_heading(SID, URL, 3, title, ANCHOR, URL + '#' + ANCHOR) == action


@pytest.mark.parametrize('title', [
    'Added', 'Added   ', 'Addedness of a feature', 'Feature added',
    'Deprecated example\nOther heading', 'Removed' + 'X' * 250,
])
def test_ambiguous_or_clipped_heading(title):
    assert groq_action_heading(SID, URL, 3, title, ANCHOR, URL + '#' + ANCHOR) is None


@pytest.mark.parametrize('sid,url,level,anchor,link', [
    ('other_changelog', URL, 3, ANCHOR, URL + '#' + ANCHOR),
    (SID, URL + '/other', 3, ANCHOR, URL + '/other#' + ANCHOR),
    (SID, URL, 2, ANCHOR, URL + '#' + ANCHOR),
    (SID, URL, 3, '', URL),
    (SID, URL, 3, '../bad', URL + '#../bad'),
    (SID, URL, 3, ANCHOR, URL + '#other'),
])
def test_no_unowned_or_wrong_scope(sid, url, level, anchor, link):
    assert groq_action_heading(sid, url, level, 'AddedExample 3.6', anchor, link) is None
