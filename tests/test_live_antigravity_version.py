"""Synthetic regression for the observed Antigravity heading-version defect."""
import pytest
from lxml import html

from agentfuse_crawlers.release_events import extract_release_events
from agentfuse_crawlers.release_heading_layouts import (
    ANTIGRAVITY_SCOPE, antigravity_h3_version,
)

SID, URL = ANTIGRAVITY_SCOPE


def extract(markup, sid=SID, url=URL):
    return extract_release_events(html.fromstring("<main>" + markup + "</main>"), url, sid)


@pytest.mark.parametrize("title, expected", [
    ("v2.35.1", "2.35.1"),
    ("V1.5.16", "1.5.16"),
    ("v1.2.3-beta.1", "1.2.3-beta.1"),
    ("Example 3.8 Flash", None),
    ("AGY 2.0 Bug fixes", None),
    ("AGY 2.0 Bug Fixes", None),
    ("Feature v2.3.4 for example", None),
    ("2.35.1", None),
    ("v2.35.1 with more text", None),
    ("v2.35", None),
    ("", None),
    (None, None),
])
def test_literal_version_only(title, expected):
    assert antigravity_h3_version(title) == expected


def test_undated_numeric_notes_do_not_become_colliding_releases():
    data = extract(
        "<h3>Example 2.0 Bug fixes</h3><p>Synthetic notes one.</p>"
        "<h3>Example 2.0 Bug Fixes</h3><p>Synthetic notes two.</p>"
        "<h3>v2.1.0</h3><p>November 24, 2026</p><p>Synthetic release.</p>"
    )
    assert data["release_event_count"] == 1
    assert data["release_unsubstantiated_version_heading_count"] == 2
    assert data["release_events"][0]["version"] == "2.1.0"
    assert data["release_events"][0]["published_at"] == "2026-11-24"
    assert data["release_event_identity_collision"] is False
    assert data["release_identity_revision"] == "release_owner_date_scope_v7_antigravity_h3_version"
    assert data["latest_release_date_candidate"] is None
    assert data["latest_release_date_status"] == "unsubstantiated_version_heading_requires_review"
    assert data["release_window_complete"] is False
    assert data["approved_for_advisor"] is False


def test_dated_model_announcement_is_retained_without_app_version():
    data = extract(
        "<h3 id='feature'>Example Model 3.8</h3>"
        "<time datetime='2026-11-24'></time><p>Synthetic announcement.</p>"
        "<h3>v2.1.0</h3><p>November 23, 2026</p><p>Synthetic release.</p>"
    )
    assert data["release_event_count"] == 2
    first, second = data["release_events"]
    assert first["published_at"] == "2026-11-24"
    assert first["version"] is None
    assert first["release_identity_requires_manual_review"] is True
    assert first["approved_for_advisor"] is False
    assert first["permalink"] == URL + "#feature"
    assert second["version"] == "2.1.0"
    assert data["release_unsubstantiated_version_heading_count"] == 1
    assert data["release_window_complete"] is False
    assert data["latest_release_date_candidate"] is None


def test_genuine_duplicate_version_heading_still_collides():
    markup = "<h3>v2.1.0</h3><p>Synthetic duplicate.</p>"
    data = extract(markup + markup)
    assert data["release_event_count"] == 2
    assert data["release_unsubstantiated_version_heading_count"] == 0
    assert data["release_event_identity_collision"] is True
    assert data["release_window_complete"] is False


@pytest.mark.parametrize("sid,url,level", [
    ("other_changelog", URL, 3), (SID, URL + "/other", 3), (SID, URL, 2),
])
def test_other_source_url_or_heading_level_is_unchanged(sid, url, level):
    data = extract(
        f"<h{level}>Example 3.8</h{level}><p>Synthetic notes.</p>",
        sid=sid, url=url,
    )
    assert data["release_event_count"] == 1
    assert data["release_events"][0]["version"] == "3.8"
    assert data["release_unsubstantiated_version_heading_count"] == 0
