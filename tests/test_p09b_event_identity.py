"""P09B: source-owned release identity vs supporting documentation links.

These are short original examples shaped after observed October 31 Zyte
identity collisions (OpenAI, Anthropic, Gemini, Antigravity). They are NOT
copies of vendor release prose or independently verified publisher dates.
"""

import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.quality import assess_capture
from scripts.compare_exports import compare, review_queue

EXAMPLE_SOURCES = {
    "openai_api_changelog": "https://developers.openai.com/api/docs/changelog",
    "anthropic_api_changelog": "https://platform.claude.com/docs/en/release-notes/overview",
    "gemini_api_changelog": "https://ai.google.dev/gemini-api/docs/changelog",
    "google_antigravity_changelog": "https://antigravity.google/docs/changelog",
}


def crawl(source_id, markup):
    url = EXAMPLE_SOURCES[source_id]
    return extract_evidence(
        "<html><head><title>Official synthetic changelog</title></head>"
        "<body><main>" + markup + "</main></body></html>",
        url, category="changelog", source_id=source_id,
    )


@pytest.mark.parametrize(("source_id", "doc"), [
    ("openai_api_changelog", "/api/docs/guides/decisions"),
    ("anthropic_api_changelog", "/docs/en/build-with-claude/fast-mode"),
    ("gemini_api_changelog", "/gemini-api/docs/computer-use"),
])
def test_distinct_publisher_announcements_sharing_a_docs_link_keep_distinct_ids(
    source_id, doc,
):
    text = (
        "<h2>October, 2026</h2>"
        "<div>Oct 30</div>"
        f"<h3>New feature became generally available <a href='{doc}'>Guide</a></h3>"
        "<p>First separate synthetic announcement with verified date layout.</p>"
        "<div>Oct 23</div>"
        f"<h3>Preview of feature started <a href='{doc}'>Guide</a></h3>"
        "<p>Second distinct synthetic announcement with its own date.</p>"
    )
    ev = crawl(source_id, text)
    first, second = ev["release_events"]
    assert first["published_at"] == "2026-10-30"
    assert second["published_at"] == "2026-10-23"
    assert first["event_id"] != second["event_id"]
    assert ev["release_event_identity_collision"] is False
    assert first["permalink"] == EXAMPLE_SOURCES[source_id]
    assert second["permalink"] == EXAMPLE_SOURCES[source_id]
    assert first["related_documentation_urls"][0].endswith(doc)
    assert first["identity_basis"] == "stable_title_and_version_no_date"
    assert first["approved_for_advisor"] is False
    assert second["approved_for_advisor"] is False


def test_antigravity_shared_releases_index_does_not_collapse_versioned_events():
    page = "".join(
        f"<h2>v2.28.{i} <a href='/releases'>Release notes</a></h2>"
        f"<p>Changes for version two point twenty eight dot {i}.</p>"
        for i in range(5, 0, -1)
    )
    ev = crawl("google_antigravity_changelog", page)
    assert ev["release_event_count"] == 5
    assert len({x["event_id"] for x in ev["release_events"]}) == 5
    assert ev["release_event_identity_collision"] is False
    assert all(x["permalink"] == EXAMPLE_SOURCES["google_antigravity_changelog"]
               for x in ev["release_events"])
    assert all(x["published_at"] is None for x in ev["release_events"])
    assert ev["latest_release_date_candidate"] is None
    assert ev["latest_release_date_status"] == "ambiguous_undated_or_collision"


def test_publisher_date_correction_without_announcement_anchor_preserves_event_id():
    old = crawl("openai_api_changelog",
        "<h2>October, 2026</h2><div>Oct 28</div>"
        "<h3>Example service is available</h3>"
        "<p>First synthetic description.</p>"
    )
    new = crawl("openai_api_changelog",
        "<h2>October, 2026</h2><div>Oct 30</div>"
        "<h3>Example service is available</h3>"
        "<p>First synthetic description.</p>"
    )
    assert old["release_events"][0]["event_id"] == new["release_events"][0]["event_id"]
    assert old["release_events"][0]["published_at"] == "2026-10-28"
    assert new["release_events"][0]["published_at"] == "2026-10-30"


def test_announcement_permalink_nested_under_current_changelog_is_accepted():
    ev = crawl("openai_api_changelog",
        "<h2>October, 2026</h2><div>Oct 28</div>"
        "<h3>Service available <a href='/api/docs/changelog/october-service?"
        "secret=not-to-store'>Read</a></h3>"
        "<p>Unique release-owned reference, not a generic model page.</p>"
    )
    row = ev["release_events"][0]
    assert row["permalink"] == (
        "https://developers.openai.com/api/docs/changelog/october-service"
    )
    assert row["identity_basis"] == "release_owned_permalink"
    assert "secret" not in repr(row)


def test_unrelated_model_link_cannot_override_announcement_owned_heading_anchor():
    ev = crawl("gemini_api_changelog",
        "<h2>October, 2026</h2><div>Oct 30</div>"
        "<h3 id='release-model-a'>Added model A "
        "<a href='/gemini-api/docs/models'>Models</a></h3>"
        "<p>New variant available for selected customers.</p>"
    )
    row = ev["release_events"][0]
    assert row["permalink"] == EXAMPLE_SOURCES["gemini_api_changelog"] + "#release-model-a"
    assert row["identity_basis"] == "release_owned_permalink"
    assert row["related_documentation_urls"][0].endswith("/gemini-api/docs/models")


def test_duplicate_real_announcement_anchor_still_causes_fail_closed_collision():
    ev = crawl("openai_api_changelog",
        "<h2>October, 2026</h2>"
        "<div>Oct 30</div><h3 id='shared'>Release v1.0.0</h3>"
        "<p>Example first entry.</p>"
        "<div>Oct 29</div><h3 id='shared'>Release v2.0.0</h3>"
        "<p>Example second entry.</p>"
    )
    assert ev["release_event_identity_collision"] is True
    assert ev["latest_release_date_candidate"] is None
    assert ev["approved_for_advisor"] is False


def test_generic_repeated_heading_dated_events_are_distinct_review_only():
    ev = crawl("gemini_api_changelog",
        "<h2>October, 2026</h2>"
        "<div>Oct 30</div><h3>Bug fixes</h3><p>First date body.</p>"
        "<div>Oct 29</div><h3>Bug fixes</h3><p>Second date body.</p>"
    )
    assert ev["release_event_identity_collision"] is False
    assert len({x["event_id"] for x in ev["release_events"]}) == 2
    assert ev["release_date_scoped_generic_event_count"] == 2
    assert all(x["release_identity_requires_manual_review"]
               for x in ev["release_events"])
    assert all(x["identity_basis"] == "date_scoped_generic_heading_review_only"
               for x in ev["release_events"])
    assert ev["latest_publication_verified"] is False


def test_documentation_reference_cannot_leak_cross_host_or_url_query_secrets():
    ev = crawl("openai_api_changelog",
        "<h2>October, 2026</h2><div>Oct 30</div>"
        "<h3>Access settings update "
        "<a href='https://evil.invalid/path?api_key=secret'>Docs</a>"
        "<a href='/api/docs/guides/access?token=private'>Guide</a></h3>"
        "<p>Example publisher documentation not release permalink.</p>"
    )
    row = ev["release_events"][0]
    assert row["permalink"] == EXAMPLE_SOURCES["openai_api_changelog"]
    assert row["related_documentation_urls"] == [
        "https://developers.openai.com/api/docs/guides/access"
    ]
    assert "api_key" not in str(row)
    assert "token" not in str(row)


def test_heading_title_over_100_chars_uses_bounded_full_heading_for_stable_identity():
    prefix = "The major technical developer update adds " + "shared context " * 8
    old_title = prefix + "for embedding workloads"
    new_title = prefix + "for image workloads"
    assert old_title[:100] == new_title[:100]
    ev = crawl("openai_api_changelog",
        "<h2>October, 2026</h2>"
        "<div>Oct 30</div><h3>" + old_title + "</h3><p>First body.</p>"
        "<div>Oct 29</div><h3>" + new_title + "</h3><p>Second body.</p>"
    )
    assert ev["release_event_identity_collision"] is False
    assert len({v["event_id"] for v in ev["release_events"]}) == 2


def test_reordering_distinct_guides_linked_releases_never_generates_new_event():
    a = ("<h3>Update A <a href='/api/docs/guides/shared'>Guide</a></h3>"
         "<time datetime='2026-10-30'></time><p>Update A content.</p>")
    b = ("<h3>Update B <a href='/api/docs/guides/shared'>Guide</a></h3>"
         "<time datetime='2026-10-28'></time><p>Update B content.</p>")
    first = crawl("openai_api_changelog", a + b)
    reordered = crawl("openai_api_changelog", b + a)
    assert {x["event_id"] for x in first["release_events"]} == {
        x["event_id"] for x in reordered["release_events"]
    }
    assert first["release_event_identity_collision"] is False
    assert reordered["release_event_identity_collision"] is False


def _snapshot_from_extraction(source_id, extraction):
    """Intentionally minimal capture with identical source identity."""
    return {
        "source_id": source_id,
        "provider": "OpenAI", "category": "changelog",
        "source_url": EXAMPLE_SOURCES[source_id],
        "status": "captured", "content_sha256": "unchanged-page-hash",
        "release_events_schema": extraction["release_events_schema"],
        "release_identity_revision": extraction["release_identity_revision"],
        "release_window_complete": extraction["release_window_complete"],
        "release_event_identity_collision": extraction["release_event_identity_collision"],
        "release_recent_body_loss_count": 0,
        "release_events": extraction["release_events"],
        "approved_for_advisor": False,
    }


def test_legacy_old_archive_is_new_baseline_not_hundreds_of_new_events():
    from copy import deepcopy
    from scripts.evaluate_run import _release_delta, _source_identity

    data = crawl(
        "openai_api_changelog",
        "<h2>October, 2026</h2>"
        "<div>Oct 30</div><h3>New important feature A</h3>"
        "<p>Synthetic event A for integrity testing.</p>"
        "<div>Oct 28</div><h3>Previous important feature B</h3>"
        "<p>Synthetic event B for integrity testing.</p>",
    )
    current = _snapshot_from_extraction("openai_api_changelog", data)
    previous = deepcopy(current)
    previous.pop("release_identity_revision")
    previous["release_events"][0]["event_id"] = "openai_api_changelog:old-id"
    assert _source_identity(current) != _source_identity(previous)
    assert _release_delta(current, previous) == []
    assert compare({"openai_api_changelog": current},
                   {"openai_api_changelog": previous})[0]["change_type"] == "new_baseline"
    assert review_queue(
        {"openai_api_changelog": current},
        {"openai_api_changelog": previous},
        compare({"openai_api_changelog": current},
                {"openai_api_changelog": previous}),
    ) == []


def test_current_identity_revision_is_declared_to_all_release_events():
    data = crawl(
        "google_antigravity_changelog",
        "<h2>v2.28.2</h2><p>Some deployment details.</p>",
    )
    assert data["release_events_schema"] == "1.1"
    assert data["release_identity_revision"] == "release_owner_date_scope_v6"
    assert data["release_events"][0]["identity_basis"] == "stable_title_and_version_no_date"
