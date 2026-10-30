"""A 200 response and a recent fetch are not verification of latest vendor facts."""

from scrapy.http import Headers

from agentfuse_crawlers.quality import (
    assess_capture, http_date_candidate, response_freshness,
)


def evidence(**kwargs):
    return {
        "title": "Official release notes",
        "word_count": 100,
        "sections": [{"date_candidate": "2026-10-30"}],
        "visible_latest_date_candidate": "2026-10-30",
        "sections_truncated": False,
        "tables_truncated": False,
        "tables": [],
        "prose_paragraphs": 2,
        "main_link_text_ratio": 0.1,
        **kwargs,
    }


def test_official_changelog_with_dated_sections_is_only_captured_not_approved():
    text = "New API capabilities described clearly. " * 20
    assert assess_capture("changelog", evidence(), text) == ("captured", "")


def test_changelog_requires_date_evidence_for_automatic_comparable_capture():
    ev = evidence()
    ev["visible_latest_date_candidate"] = ""
    assert assess_capture("changelog", ev, "New APIs. " * 100)[0] == "needs_review"


def test_price_without_observable_amount_or_billing_details_is_not_captured():
    ev = evidence()
    assert assess_capture("pricing", ev, "A product catalog is available. " * 30)[0] == "needs_review"
    assert assess_capture("pricing", ev, "Price per million tokens $1.50. " * 30) == ("captured", "")


def test_link_only_documentation_landing_is_not_complete_documentation():
    ev = evidence()
    ev.update(main_link_text_ratio=0.97, prose_paragraphs=0)
    assert assess_capture("documentation", ev, "Model docs quickstart. " * 40)[0] == "needs_review"


def test_truncation_in_pricing_tables_and_changelogs_prevents_complete_capture():
    ev = evidence()
    ev["tables_truncated"] = True
    assert assess_capture("pricing", ev, "$1 per million tokens " * 40)[0] == "partial_capture"
    ev["tables_truncated"] = False
    ev["sections_truncated"] = True
    assert assess_capture("changelog", ev, "Release note details " * 40)[0] == "partial_capture"


def test_cache_and_javascript_shell_avoid_false_freshness():
    ev = evidence()
    text = "Details about API releases. " * 35
    assert assess_capture("changelog", ev, text, cached=True)[0] == "needs_review"
    assert assess_capture("changelog", ev, text, cache_warnings=["reported_cache_age_over_one_day"])[0] == "needs_review"
    assert assess_capture("changelog", ev, "Enable JavaScript to view this. " * 40)[0] == "needs_review"
    assert assess_capture("changelog", ev, "Verify you are human " * 40)[0] == "blocked"


def test_http_date_metadata_does_not_establish_vendor_publication():
    headers = Headers({
        "Date": "Fri, 30 Oct 2026 12:00:00 GMT",
        "Age": "90001",
        "Cache-Control": "public, max-age=600",
    })
    info = response_freshness(headers)
    assert info["origin_response_date"] == "2026-10-30T12:00:00+00:00"
    assert info["reported_cache_age_seconds"] == 90001
    assert info["latest_publication_verified"] is False
    assert "reported_cache_age_over_one_day" in info["freshness_warnings"]
    assert http_date_candidate("nonsense") == ""


def test_empty_server_date_or_age_not_invented():
    info = response_freshness(Headers())
    assert info["origin_response_date"] == ""
    assert info["reported_cache_age_seconds"] is None
    assert info["latest_publication_verified"] is False
