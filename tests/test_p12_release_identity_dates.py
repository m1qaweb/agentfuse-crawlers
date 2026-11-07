"""P12 synthetic release-date / identity regression suite. Not vendor truth."""
import copy
import pytest

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.markdown_releases import parse_markdown_releases
from scripts.compare_exports import compare, review_queue
from scripts.evaluate_run import _release_delta, _source_identity

URL = "https://developers.openai.com/api/docs/changelog"
SID = "openai_api_changelog"


def crawl(body):
    return extract_evidence(
        "<html><head><title>Example changelog</title></head><body><main>"
        + body + "</main></body></html>", URL,
        category="changelog", source_id=SID,
    )


def snapshot(data, fetched="2026-10-31T12:00:00Z"):
    return {
        "source_id": SID, "provider": "OpenAI",
        "source_url": URL, "category": "changelog",
        "status": "captured", "content_sha256": data["content_sha256"],
        "release_events_schema": data["release_events_schema"],
        "release_identity_revision": data["release_identity_revision"],
        "release_events": data["release_events"],
        "release_window_complete": data["release_window_complete"],
        "release_event_identity_collision": data["release_event_identity_collision"],
        "release_recent_body_loss_count": 0,
        "fetched_at_utc": fetched, "sections": [],
        "approved_for_advisor": False,
    }


def generic(day, title="Bug fixes"):
    return (
        "<h2>October, 2026</h2><div>Oct " + str(day) + "</div>"
        "<h3>" + title + "</h3><p>Example reliability details.</p>"
    )


@pytest.mark.parametrize("title", [
    "Bug fixes", "Added", "What's Changed", "Highlights",
    "Bug fixes and reliability improvements", "New features",
])
def test_repeating_generic_titles_two_dates_are_distinct_but_review_only(title):
    first = "<div>Oct 30</div><h3>" + title + "</h3><p>First details.</p>"
    second = "<div>Oct 28</div><h3>" + title + "</h3><p>Earlier details.</p>"
    item = crawl("<h2>October, 2026</h2>" + first + second)
    assert item["release_event_identity_collision"] is False
    assert len(item["release_events"]) == 2
    assert len({e["event_id"] for e in item["release_events"]}) == 2
    assert item["release_date_scoped_generic_event_count"] == 2
    assert all(e["identity_basis"] == "date_scoped_generic_heading_review_only"
               and e["release_identity_requires_manual_review"]
               for e in item["release_events"])
    assert item["release_identity_revision"] == "release_owner_date_scope_v5"
    assert item["latest_publication_verified"] is False
    assert item["approved_for_advisor"] is False
    reversed_item = crawl("<h2>October, 2026</h2>" + second + first)
    assert {e["event_id"] for e in item["release_events"]} == {
        e["event_id"] for e in reversed_item["release_events"]
    }


def test_same_day_generic_duplicate_keeps_collision():
    item = crawl("<h2>October, 2026</h2>"
                 "<div>Oct 30</div><h3>Bug fixes</h3><p>One.</p>"
                 "<div>Oct 30</div><h3>Bug fixes</h3><p>Two.</p>")
    assert item["release_event_identity_collision"]
    assert not item["release_window_complete"]
    assert item["latest_release_date_candidate"] is None


def test_unknown_year_generic_duplicate_still_collides():
    item = crawl("<p>Oct 30</p><h2>Bug fixes</h2><p>First.</p>"
                 "<p>Oct 29</p><h2>Bug fixes</h2><p>Second.</p>")
    assert item["release_event_identity_collision"]
    assert all(e["published_at"] is None for e in item["release_events"])


def test_specific_heading_date_correction_keeps_identity():
    a = crawl(generic(28, "New model endpoint"))
    b = crawl(generic(30, "New model endpoint"))
    assert a["release_events"][0]["event_id"] == b["release_events"][0]["event_id"]
    assert a["release_events"][0]["published_at"] == "2026-10-28"
    assert b["release_events"][0]["published_at"] == "2026-10-30"


def test_generic_date_correction_never_becomes_new_release_alert():
    a = snapshot(crawl(generic(28)), "2026-10-29T12:00:00Z")
    b = snapshot(crawl(generic(30)), "2026-10-31T12:00:00Z")
    assert a["release_events"][0]["event_id"] != b["release_events"][0]["event_id"]
    queue = review_queue({SID: b}, {SID: a}, compare({SID: b}, {SID: a}))
    assert len(queue) == 1
    assert queue[0]["change_type"] == "release_date_scoped_identity_review"
    assert "date correction" in queue[0]["interpretation_warning"]
    assert queue[0]["approved_for_advisor"] is False
    changes = _release_delta(b, a)
    assert len(changes) == 1
    assert changes[0]["change_type"] == "needs_review"
    assert changes[0]["reason"] == "date_scoped_generic_heading_requires_manual_matching"


def test_new_generic_dated_heading_is_only_for_review():
    a = snapshot(crawl(generic(28)))
    b = snapshot(crawl("<h2>October, 2026</h2>"
        "<div>Oct 30</div><h3>Bug fixes</h3><p>New body.</p>"
        "<div>Oct 28</div><h3>Bug fixes</h3><p>Example reliability details.</p>"))
    q = review_queue({SID: b}, {SID: a}, compare({SID: b}, {SID: a}))
    assert "release_event_first_seen" not in [x["change_type"] for x in q]


def test_article_header_published_time_is_not_deleted():
    item = crawl(
        "<article><header><h2>Standalone developer release</h2>"
        "<time itemprop='datePublished' datetime='2026-10-28T09:00:00Z'>"
        "October 28, 2026</time></header><p>Added new API tools.</p></article>"
    )
    e = item["release_events"][0]
    assert e["published_at"] == "2026-10-28"
    assert e["published_date_provenance"] == "html_time_datetime"
    assert e["title"] == "Standalone developer release"


def test_visible_time_without_datetime_is_explicit_publication_date():
    item = crawl(
        "<article><header><time itemprop='datePublished'>Oct 27, 2026</time>"
        "<h2>Developer account preferences</h2></header>"
        "<p>New configuration features.</p></article>"
    )
    assert item["release_events"][0]["published_at"] == "2026-10-27"


def test_labeled_dateline_without_html_time_is_supported():
    item = crawl(
        "<article><p>Published on: Oct 27, 2026</p>"
        "<h2>Developer account preferences</h2>"
        "<p>New configuration features.</p></article>"
    )
    e = item["release_events"][0]
    assert e["published_at"] == "2026-10-27"
    assert e["date_evidence_text"] == "Oct 27, 2026"


def test_modified_time_cannot_turn_into_release_publication_date():
    item = crawl(
        "<article><header><h2>Version v2.1.0</h2>"
        "<time itemprop='dateModified' datetime='2026-10-30'>"
        "Oct 30, 2026</time></header><p>Edited historical notes.</p></article>"
    )
    assert item["release_events"][0]["published_at"] is None


def test_global_site_header_date_is_removed():
    item = crawl(
        "<header><time datetime='2026-10-30'>Oct 30</time></header>"
        "<h2>Version v3.1.0</h2><p>Undated release content.</p>"
    )
    assert item["release_events"][0]["published_at"] is None


def test_article_owned_nested_link_is_sanitized_stable_identity():
    item = crawl(
        "<article><h3>Bug fixes</h3>"
        "<time datetime='2026-10-30'></time>"
        "<a href='/api/docs/changelog/critical-fixes?token=secret'>"
        "Release details</a><p>Important fixes.</p></article>"
    )
    e = item["release_events"][0]
    assert e["identity_basis"] == "release_owned_permalink"
    assert e["permalink"] == URL + "/critical-fixes"
    assert "token=secret" not in repr(e)


def test_unrelated_guide_cannot_override_generic_release_identity():
    item = crawl(
        "<article><h3>Bug fixes</h3><time datetime='2026-10-30'></time>"
        "<a href='/api/docs/guides/shared?token=secret'>Guide</a>"
        "<p>New reliability improvements.</p></article>"
    )
    e = item["release_events"][0]
    assert e["permalink"] == URL
    assert e["identity_basis"] == "date_scoped_generic_heading_review_only"


def test_prose_deprecation_date_is_not_a_release_publication_date():
    item = crawl(
        "<h3>Version v2.3.0</h3>"
        "<p>Deprecation is effective on November 20, 2026.</p>"
    )
    assert item["release_events"][0]["published_at"] is None


def test_mixed_order_dated_evidence_is_kept_without_making_latest_claim():
    item = crawl(
        "<h2>2026-10-30</h2><h3>Feature A</h3><p>Details.</p>"
        "<h2>2026-10-27</h2><h3>Feature B</h3><p>Details.</p>"
        "<h2>2026-10-29</h2><h3>Feature C</h3><p>Details.</p>"
    )
    assert item["release_dated_event_count"] == 3
    assert item["release_order_direction"] == "mixed"
    assert item["latest_release_date_candidate"] is None
    assert len(item["release_individual_date_candidates"]) == 3
    assert all(v["review_status"] == "unverified"
               for v in item["release_individual_date_candidates"])
    assert item["latest_publication_verified"] is False


def test_parser_revision_migration_is_baseline_not_alert():
    data = snapshot(crawl(generic(30)))
    old = copy.deepcopy(data)
    old["release_identity_revision"] = "release_owned_anchor_v2"
    old["release_events"][0]["event_id"] = SID + ":legacy"
    assert _source_identity(data) != _source_identity(old)
    assert compare({SID: data}, {SID: old})[0]["change_type"] == "new_baseline"
    assert review_queue({SID: data}, {SID: old},
                        compare({SID: data}, {SID: old})) == []
    assert _release_delta(data, old) == []


def test_upgrade_from_prior_month_parser_v3_cannot_create_false_release_alert():
    # A November page that was previously missing its date now has a
    # recognisable first-party date, but this is a parser upgrade.
    # A new publication must NOT be inferred from a changed parser.
    new = snapshot(crawl(
        "<p>November 6, 2026</p><h2>New API capability</h2>"
        "<p>Changelog source text used for a date-regression test.</p>"
    ))
    prior = copy.deepcopy(new)
    prior["release_identity_revision"] = "release_owner_date_scope_v3"
    prior["content_sha256"] = "0" * 64
    assert new["release_identity_revision"] == "release_owner_date_scope_v5"
    assert new["release_events"][0]["published_at"] == "2026-11-06"
    changes = compare({SID: new}, {SID: prior})
    assert [x["change_type"] for x in changes] == ["new_baseline"]
    assert review_queue({SID: new}, {SID: prior}, changes) == []
    assert _release_delta(new, prior) == []


def test_github_ui_filter_v4_to_v5_is_new_baseline_not_vendor_release():
    # GitHub UI error cards and signature metadata could be treated as
    # vendor events in the previous HTML extractor revision. Migration
    # must not declare the remaining source events "new" to customers.
    from agentfuse_crawlers.extract import extract_evidence

    source_url = "https://github.com/chroma-core/chroma/releases"
    sid = "chroma_changelog"
    data = extract_evidence(
        "<html><main><h2>2026-11-06</h2><h3>Uh oh!</h3>"
        "<h2>2026-11-04</h2><h3>Version v2.0.0</h3>"
        "<p>Sample independent source-owned release notes.</p>"
        "</main></html>",
        source_url, category="changelog", source_id=sid,
    )
    assert data["release_identity_revision"] == "release_owner_date_scope_v5"
    assert data["release_github_ui_error_placeholder_count"] == 1
    new = snapshot(data)
    new["source_id"] = sid
    new["source_url"] = source_url
    # Force a healthy synthetic comparator record solely to test revision
    # isolation. Production quality NEVER marks a UI-error page captured.
    new["release_github_ui_error_placeholder_count"] = 0
    new["release_window_complete"] = True
    old = copy.deepcopy(new)
    old["release_identity_revision"] = "release_owner_date_scope_v4"
    old["content_sha256"] = "f" * 64
    assert compare({sid: new}, {sid: old})[0]["change_type"] == "new_baseline"
    assert review_queue(
        {sid: new}, {sid: old}, compare({sid: new}, {sid: old})
    ) == []
    assert _release_delta(new, old) == []


def test_markdown_identity_revision_explicit_without_publication_date():
    data = parse_markdown_releases(
        "# Changelog\n## 2.0.5\n- Stability fixes.\n",
        "claude_code_changelog",
        "https://code.claude.com/docs/en/changelog",
        "https://code.claude.com/docs/en/changelog.md",
    )
    assert data["release_identity_revision"] == "official_markdown_version_v1"
    assert data["release_events"][0]["identity_basis"] == (
        "official_markdown_numeric_version"
    )
    assert data["latest_release_date_candidate"] is None
    assert data["approved_for_advisor"] is False

def test_nested_last_updated_span_never_becomes_published_at():
    item = crawl(
        "<article><header><h3>Version v3.0.0</h3>"
        "<time itemprop='dateModified'><span>Oct 30, 2026</span></time>"
        "</header><p>Notes were edited later.</p></article>"
    )
    assert item["release_events"][0]["published_at"] is None


def test_standalone_last_updated_badge_is_not_release_dateline():
    item = crawl(
        "<span class='last-updated'>Oct 30, 2026</span>"
        "<h2>Version v3.1.0</h2><p>Version description.</p>"
    )
    assert item["release_events"][0]["published_at"] is None


def test_conflicting_time_datetime_and_visible_date_fail_closed():
    item = crawl(
        "<article><header><h2>Version v3.1.0</h2>"
        "<time datetime='2026-10-30'>Oct 28, 2026</time></header>"
        "<p>Source markup gave conflicting publication dates.</p></article>"
    )
    assert item["release_events"][0]["published_at"] is None


def test_concordant_visible_and_machine_date_remains_accepted():
    item = crawl(
        "<article><header><h2>Release A</h2>"
        "<time datetime='2026-10-30T12:00:00Z'>Oct 30, 2026</time>"
        "</header><p>Source markup agrees on the day.</p></article>"
    )
    assert item["release_events"][0]["published_at"] == "2026-10-30"
