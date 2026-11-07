"""Regression coverage for release-level evidence (not authoritative announcements).

These are short representative layouts; no copyrighted vendor changelog is
mirrored in the test suite.
"""

import copy
from html import escape

import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.release_events import (
    MAX_EVENTS, _date, _inline_heading, extract_release_events,
)
from scripts.compare_exports import compare, review_queue


URL = "https://official.example/changelog"
SID = "openai_api_changelog"


def extract(markup, source_id=SID):
    return extract_evidence(
        "<html><head><title>Changelog</title></head><body><main>"
        + markup + "</main></body></html>",
        URL, category="changelog", source_id=source_id,
    )


def events(markup):
    return extract(markup)["release_events"]


def test_openai_month_group_produces_two_independent_dated_entries():
    data = extract("""
    <h1>API changelog</h1>
    <h2>October, 2026</h2>
    <div>Oct 30</div><h3 id="release-one">New model available</h3>
    <p>New model supports additional API tools.</p>
    <div>Oct 28</div><h3 id="release-two">Extended rate limits</h3>
    <p>Additional tokens supported in selected regions.</p>
    """)
    found = data["release_events"]
    assert [(e["title"], e["published_at"]) for e in found] == [
        ("New model available", "2026-10-30"),
        ("Extended rate limits", "2026-10-28"),
    ]
    assert data["latest_release_date_candidate"] == "2026-10-30"
    assert data["release_dated_event_count"] == 2
    assert all(e["approved_for_advisor"] is False for e in found)
    assert found[0]["permalink"] == URL + "#release-one"
    assert found[1]["event_id"] != found[0]["event_id"]



@pytest.mark.parametrize(("visible", "expected"), [
    ("November 6, 2026", "2026-11-06"),
    ("December 1, 2026", "2026-12-01"),
    ("Nov 6, 2026", "2026-11-06"),
    ("Dec 1, 2026", "2026-12-01"),
    ("6 November 2026", "2026-11-06"),
    ("1 December 2026", "2026-12-01"),
])
def test_all_november_december_publication_date_spellings(visible, expected):
    """Full Nov/Dec names were previously rejected by DATE_WORDS."""
    day, provenance = _date(visible)
    assert day == expected and provenance == "explicit_date"
    data = extract(
        "<article><header><h2 id='dated-release'>New service API capability</h2>"
        "<time itemprop='datePublished'>" + visible + "</time></header>"
        "<p>A separately published, dated official change.</p></article>"
    )
    assert data["release_event_count"] == 1
    event = data["release_events"][0]
    assert event["published_at"] == expected
    assert event["published_date_provenance"] == "adjacent_explicit_date"
    assert data["latest_release_date_candidate"] == expected
    assert event["approved_for_advisor"] is False
    assert data["approved_for_advisor"] is False


def test_november_and_december_standalone_datelines_keep_correct_order():
    data = extract("""
    <h1>API changelog</h1>
    <p>December 1, 2026</p><h2 id="dec">Updated API execution limits</h2>
    <p>New developer settings and configuration details.</p>
    <p>November 6, 2026</p><h2 id="nov">Added model compatibility tools</h2>
    <p>New API model settings and compatible features.</p>
    """)
    assert [(e["title"], e["published_at"]) for e in data["release_events"]] == [
        ("Updated API execution limits", "2026-12-01"),
        ("Added model compatibility tools", "2026-11-06"),
    ]
    assert data["release_order_direction"] == "newest_first"
    assert data["latest_release_date_candidate"] == "2026-12-01"
    assert data["release_event_identity_collision"] is False
    assert data["release_identity_revision"] == "release_owner_date_scope_v4"
    assert not data["latest_publication_verified"]


@pytest.mark.parametrize("invalid", [
    "November 31, 2026",
    "December 32, 2026",
    "November 6, 2026 — planned deprecation",
    "Published this November 6, 2026",
])
def test_full_month_names_do_not_turn_bad_dates_or_prose_into_publications(invalid):
    assert _date(invalid)[0] is None
    data = extract(
        "<h2>Version v2.4.0</h2>"
        "<p>This version documents a planned November 6, 2026 sunset, "
        "not the release publication date.</p>"
    )
    assert data["release_events"][0]["published_at"] is None
    assert data["latest_release_date_candidate"] is None


def test_kiro_dateline_before_heading_is_attached_to_release():
    found = events("""
    <h1>Changelog</h1><p>Oct 28, 2026</p>
    <h2 id="installer">Windows System-Wide Installer</h2>
    <p>Users can install the application system-wide on Windows.</p>
    """)
    assert len(found) == 1
    assert found[0]["published_at"] == "2026-10-28"
    assert found[0]["published_date_provenance"] == "dateline_explicit_date"


def test_cursor_article_time_element_matches_correct_title_not_page_timestamp():
    data = extract("""
    <article><h2 id="current">Agent improvements</h2>
      <time datetime="2026-10-20T12:00:00Z">Oct 20</time>
      <p>Improved code completion and repository navigation.</p></article>
    <article><h2 id="earlier">More settings</h2>
      <time datetime="2026-10-16">Oct 16</time>
      <p>Added settings for a custom editor configuration.</p></article>
    """)
    assert [(x["title"], x["published_at"]) for x in data["release_events"]] == [
        ("Agent improvements", "2026-10-20"),
        ("More settings", "2026-10-16"),
    ]
    assert data["latest_release_date_candidate"] == "2026-10-20"
    assert data["release_events"][0]["published_date_provenance"] == "html_time_datetime"


def test_render_older_date_does_not_hide_newer_event():
    data = extract("""
    <h2>June, 2023</h2><div>Jun 30</div>
    <h3>Old command line version</h3><p>Legacy CLI maintained.</p>
    <h2>October, 2026</h2><div>Oct 29</div>
    <h3>New developer tooling</h3><p>Updated CLI and SDK packages.</p>
    """)
    assert data["latest_release_date_candidate"] == "2026-10-29"


def test_xai_month_day_without_year_does_not_infer_2026_or_claim_latest():
    data = extract("""
    <h1>Release notes</h1><p>Oct 30</p>
    <h2>Expanded supported tools</h2>
    <p>Updated integration modes for new developer environments.</p>
    <p>Dec 16, 2025</p><h2>Earlier release</h2>
    <p>Previous API improvements.</p>
    """)
    assert data["release_events"][0]["published_at"] is None
    assert data["release_events"][0]["published_date_precision"] == "unknown"
    assert data["release_events"][0]["published_date_provenance"] == "dateline_unresolved_month_day"
    assert data["release_events"][1]["published_at"] == "2025-12-16"
    assert data["latest_release_date_candidate"] is None
    assert data["latest_release_date_status"] == "ambiguous_undated_or_collision"


def test_deprecation_effective_date_in_prose_never_becomes_published_at():
    found = events("""
    <h2>Version v2.4.0</h2>
    <p>The older models will be deprecated on November 21, 2026.
       This is an effective date, not the publication date of this note.</p>
    """)
    assert len(found) == 1
    assert found[0]["published_at"] is None
    assert found[0]["version"] == "2.4.0"


def test_version_only_changes_remain_unverified_undated_events():
    data = extract("""
    <h1>Changelog</h1><h2>v2.1.0</h2>
    <ul><li>Added a new command for local development.</li></ul>
    """)
    assert data["release_event_count"] == 1
    assert data["release_events"][0]["version"] == "2.1.0"
    assert data["release_events"][0]["published_at"] is None


def test_datetime_and_inline_prefix_dates_are_validated():
    data = extract("""
    <h2>2026-10-30 — New model endpoint</h2>
    <p>Added the new model endpoint for developer requests.</p>
    """)
    assert data["release_events"][0]["published_at"] == "2026-10-30"
    assert data["release_events"][0]["title"] == "New model endpoint"
    assert data["release_events"][0]["published_date_provenance"] == "heading_inline_explicit_date"
    assert _date("2026-02-30")[0] is None
    assert _date("February 30, 2026")[0] is None
    assert _inline_heading("Deprecation deadline — 2026-11-20", None)[1] is None


def test_year_month_context_applies_to_nested_headings_only():
    data = extract("""
    <h2 id="date">October 30, 2026</h2>
    <h3>Feature A</h3><p>Added feature A.</p>
    <h3>Feature B</h3><p>Added feature B.</p>
    <h2>Other documentation</h2>
    <h3>General setup</h3><p>Instructions without a release date.</p>
    """)
    assert [(e["title"], e["published_at"]) for e in data["release_events"][:2]] == [
        ("Feature A", "2026-10-30"),
        ("Feature B", "2026-10-30"),
    ]
    assert all(x["published_at"] is None for x in data["release_events"][2:])


def test_undated_newer_heading_disables_claim_about_latest_event():
    data = extract("""
    <h2>v9.0.0</h2><p>New version without a publisher date.</p>
    <h2>2026-10-19</h2><h3>Prior feature update</h3>
    <p>Improved backward compatibility.</p>
    """)
    assert data["release_event_count"] == 2
    assert data["latest_release_date_candidate"] is None


def test_generic_parent_headings_are_not_release_items():
    data = extract("""
    <h1>Changelog</h1><h2>October, 2026</h2>
    <p>Oct 30, 2026</p><h3>Version v3.0.0 released</h3>
    <p>Updated model API behavior.</p>
    """)
    assert len(data["release_events"]) == 1
    assert data["release_events"][0]["title"] == "Version v3.0.0 released"


def test_event_permalink_cannot_escape_official_host():
    data = extract("""
    <h2>2026-10-28</h2>
    <h3>New release <a href="https://attacker.invalid/steal">details</a></h3>
    <p>Official public release details are available on the provider site.</p>
    """)
    assert data["release_events"][0]["permalink"] == URL


def test_events_are_stably_identified_after_card_reordering():
    a = """
    <article><h2 id="release-a">Feature A</h2>
    <time datetime="2026-10-30"></time><p>Improved tool use.</p></article>"""
    b = """
    <article><h2 id="release-b">Feature B</h2>
    <time datetime="2026-10-28"></time><p>Added a new capability.</p></article>"""
    first = extract(a + b)
    later = extract(b + a)
    assert {x["event_id"] for x in first["release_events"]} == {
        x["event_id"] for x in later["release_events"]
    }


def test_explicit_duplicate_release_anchor_requires_review():
    data = extract("""
    <h2 id="same">Release v1.0</h2><time datetime="2026-10-31"></time>
    <p>First update.</p>
    <h2 id="same">Release v1.0</h2><time datetime="2026-10-31"></time>
    <p>Different update.</p>
    """)
    assert data["release_event_identity_collision"] is True
    assert data["latest_release_date_candidate"] is None


def test_bounded_event_cap_is_visible_not_disguised_as_complete():
    markup = "".join(
        f'<h2 id="r{i}">2026-10-30</h2><h3>Release version v1.{i}.0</h3>'
        f'<p>Changes for this release.</p>' for i in range(MAX_EVENTS + 1)
    )
    data = extract(markup)
    assert data["release_event_count"] == MAX_EVENTS + 1
    assert data["release_events_truncated"] is True
    assert len(data["release_events"]) == MAX_EVENTS


def test_changelog_capture_requires_event_dates_not_old_heuristic_date():
    data = extract("""
    <h2>Version v2.3.0</h2><p>New release with enough prose to
    discuss availability, tools, APIs, models and migration prerequisites.
    These product details are unverified source text, not a dated release.
    The exact product version, model availability, provider requirements and
    supported clients must always be checked against independently linked
    official evidence before inclusion in any recommendation or integration.</p>
    """)
    status, reason = assess_capture("changelog", data, data["text"])
    assert status == "needs_review"
    assert reason == "release_events_missing_publication_dates"


def test_date_known_but_more_recent_undated_candidate_is_review_not_captured():
    data = extract("""
    <h2>Version v2.3.0</h2>
    <p>The newest feature adds support for additional developer workflows.</p>
    <h2>Oct 20, 2026</h2><h3>Previous model support</h3>
    <p>The previous release expanded API capabilities for tools and integrations.
    Official release dates, supported versions, access conditions, pricing tiers
    and usage limits require explicit publication evidence and independent review.
    Do not infer any missing dates from the current time or from the URL structure.</p>
    """)
    assert assess_capture("changelog", data, data["text"]) == (
        "needs_review", "latest_release_date_ambiguous",
    )


def test_release_evidence_schema_is_changelog_only():
    doc = extract_evidence(
        "<html><main><h2>2026-10-30</h2><p>This is documentation.</p></main></html>",
        URL, category="documentation", source_id="openai_api_docs",
    )
    assert "release_events" not in doc
    price = extract_evidence(
        "<html><main><h2>2026-10-30</h2><p>Pricing rates and tiers.</p></main></html>",
        URL, category="pricing", source_id="openai_api_pricing",
    )
    assert "release_events" not in price


def snapshot(typ, data):
    """A minimal typed crawl observation for the offline review queue."""
    return {
        "source_id": SID,
        "source_url": URL,
        "provider": "OpenAI",
        "category": "changelog",
        "status": "captured",
        "content_sha256": data["content_sha256"],
        "sections": data["sections"],
        "release_events_schema": data["release_events_schema"],
        "release_events": data["release_events"],
        "release_events_truncated": data["release_events_truncated"],
        "release_window_complete": data["release_window_complete"],
        "release_recent_body_loss_count": data["release_recent_body_loss_count"],
        "release_event_identity_collision": data["release_event_identity_collision"],
        "fetched_at_utc": typ,
    }


def test_first_snapshot_events_are_historical_baseline_not_latest_news():
    data = extract('<h2>Oct 30, 2026</h2><h3>Released model v1.0.0</h3><p>New API.</p>')
    current = {SID: snapshot("2026-10-31", data)}
    assert compare(current, {})[0]["change_type"] == "new_baseline"
    assert review_queue(current, {}, compare(current, {})) == []


def test_added_event_is_first_seen_observation_not_published_today():
    one = '<h2 id="a">2026-10-28</h2><h3>Version v1.0</h3><p>Original note.</p>'
    two = '<h2 id="b">2026-10-30</h2><h3>Version v2.0</h3><p>New note.</p>'
    old = snapshot("2026-10-30", extract(one))
    new = snapshot("2026-10-31", extract(two + one))
    changes = compare({SID: new}, {SID: old})
    queue = review_queue({SID: new}, {SID: old}, changes)
    added = [x for x in queue if x["change_type"] == "release_event_first_seen"]
    assert len(added) == 1
    assert added[0]["published_at_candidate"] == "2026-10-30"
    assert "NOT necessarily first published today" in added[0]["interpretation_warning"]
    assert added[0]["approved_for_advisor"] is False
    assert all(x["change_type"] != "page_changed_unclassified" for x in queue)


def test_release_body_edit_is_not_duplicate_new_release():
    olddata = extract("""
    <h2>2026-10-30</h2><h3 id="one">Version v2.0.0</h3>
    <p>Initial version description.</p>""")
    newdata = extract("""
    <h2>2026-10-30</h2><h3 id="one">Version v2.0.0</h3>
    <p>Corrected description of this version.</p>""")
    old, new = snapshot("a", olddata), snapshot("b", newdata)
    queue = review_queue({SID: new}, {SID: old}, compare({SID: new}, {SID: old}))
    assert [x["change_type"] for x in queue] == ["release_event_edited"]


def test_reordered_cards_do_not_create_release_events():
    a = '<h2 id="first">2026-10-30</h2><h3>First event</h3><p>Details.</p>'
    b = '<h2 id="second">2026-10-29</h2><h3>Second event</h3><p>Details.</p>'
    old, new = snapshot("old", extract(a + b)), snapshot("new", extract(b + a))
    queue = review_queue({SID: new}, {SID: old}, compare({SID: new}, {SID: old}))
    assert queue == []


def test_no_event_removal_claim_when_recent_feed_drops_old_entry():
    a = '<h2 id="a">2026-10-28</h2><h3>Older event</h3><p>Old details.</p>'
    b = '<h2 id="b">2026-10-30</h2><h3>Newer event</h3><p>New details.</p>'
    old, new = snapshot("old", extract(a + b)), snapshot("new", extract(b))
    queue = review_queue({SID: new}, {SID: old}, compare({SID: new}, {SID: old}))
    assert queue == []


def test_schema_migration_from_legacy_is_not_a_new_vendor_release():
    now = snapshot("now", extract(
        '<h2>2026-10-30</h2><h3>Model v1.0</h3><p>New release.</p>'
    ))
    legacy = dict(now)
    legacy.pop("release_events_schema")
    legacy.pop("release_events")
    legacy["content_sha256"] = "old-sha"
    queue = review_queue({SID: now}, {SID: legacy}, compare({SID: now}, {SID: legacy}))
    assert queue == []



def test_unrelated_undated_page_heading_is_not_release_evidence():
    data = extract("""
    <h1>Changelog</h1><h2>Getting started</h2>
    <p>Documentation for configuration that does not announce a release.</p>
    """)
    assert data["release_event_count"] == 0
    assert data["latest_release_date_candidate"] is None


def test_edit_date_is_not_a_publication_date():
    data = extract("""
    <h2>Version v2.0.0</h2>
    <time itemprop="dateModified" datetime="2026-10-30">Updated</time>
    <p>The notes were corrected without changing their publication date.</p>
    """)
    assert data["release_events"][0]["published_at"] is None


def test_large_release_body_marks_partial_and_cannot_be_compared():
    long_body = "Additional official release note context. " * 900
    data = extract(
        "<h2>2026-10-30</h2><h3>Release v2.0.0</h3><p>"
        + escape(long_body) + "</p>"
    )
    assert data["release_events"][0]["body_text_truncated"] is True
    assert data["release_events"][0]["excerpt_truncated"] is True
    status, reason = assess_capture("changelog", data, data["text"])
    assert status == "partial_capture"
    assert reason == "recent_release_body_incomplete"
    old = snapshot("2026-10-30", data)
    newer = snapshot("2026-10-31", copy.deepcopy(data))
    newer["release_events"][0]["body_sha256"] = "changed-hash"
    current = {SID: newer}
    previous = {SID: old}
    assert review_queue(current, previous, compare(current, previous)) == []


def test_official_permalink_omits_suspicious_query_tokens():
    data = extract("""
    <h2>2026-10-30</h2>
    <h3>Release v1.2.3 <a href="/changelog/release-123?token=secret">Read</a></h3>
    <p>Details linked to the official release URL.</p>
    """)
    assert data["release_events"][0]["permalink"] == "https://official.example/changelog/release-123"
    assert "token" not in data["release_events"][0]["permalink"]



def test_month_group_multiple_entries_on_same_day_keep_each_explicit_date():
    data = extract("""
    <h2>October, 2026</h2>
    <div>Oct 30</div>
    <h3 id="one">Model A</h3><p>New API access tier and tools.</p>
    <h3 id="two">Model B</h3><p>Additional model support.</p>
    <div>Oct 28</div>
    <h3 id="three">Earlier change</h3><p>Previous tools update.</p>
    """)
    assert [(x["title"], x["published_at"]) for x in data["release_events"]] == [
        ("Model A", "2026-10-30"),
        ("Model B", "2026-10-30"),
        ("Earlier change", "2026-10-28"),
    ]


def test_month_group_year_does_not_leak_into_peer_unrelated_heading():
    data = extract("""
    <h2>October, 2026</h2><div>Oct 30</div>
    <h3>Version v2.0.0</h3><p>Changes.</p>
    <h2>Developer setup</h2>
    <h3>Version v3.0.0</h3><p>October rollout not dated by publisher.</p>
    """)
    entries = data["release_events"]
    assert entries[0]["published_at"] == "2026-10-30"
    assert entries[-1]["published_at"] is None
    assert data["latest_release_date_candidate"] is None



def test_official_publication_date_correction_on_same_permalink_is_an_edit():
    old_data = extract("""
    <h2 id="vendor-release">Model v2.0.0</h2>
    <time datetime="2026-10-28"></time><p>API release details.</p>
    """)
    new_data = extract("""
    <h2 id="vendor-release">Model v2.0.0</h2>
    <time datetime="2026-10-30"></time><p>API release details.</p>
    """)
    assert old_data["release_events"][0]["event_id"] == new_data["release_events"][0]["event_id"]
    old, new = snapshot("old", old_data), snapshot("new", new_data)
    queue = review_queue({SID: new}, {SID: old}, compare({SID: new}, {SID: old}))
    assert [x["change_type"] for x in queue] == ["release_event_edited"]
    assert queue[0]["date_candidate"] == "2026-10-30"
    assert queue[0]["approved_for_advisor"] is False
