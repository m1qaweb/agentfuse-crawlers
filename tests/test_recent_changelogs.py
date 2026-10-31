"""PR03: newest-window extraction, official Markdown fallback, and Item budget."""

import copy
from datetime import date, timedelta

from scrapy import Request
from scrapy.http import HtmlResponse, TextResponse

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.markdown_releases import (
    allowed_markdown_url, parse_markdown_releases,
)
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.recent_window import (
    ITEM_TARGET_BYTES, WindowAccumulator, compact_changelog_record,
    serialized_size,
)
from agentfuse_crawlers.spiders.official import ChangelogSpider
from agentfuse_crawlers.sources import load_sources
from scripts.compare_exports import _healthy, compare, review_queue


HTML_URL = "https://code.claude.com/docs/en/changelog"
ALT = "https://code.claude.com/docs/en/changelog.md"
SID = "claude_code_changelog"
SOURCE = next(s for s in load_sources() if s["id"] == SID)


def sample_event(i, *, day=None, version=None, body_lost=False):
    return {
        "event_id": SID + ":" + str(i),
        "version": version or f"2.1.{i}",
        "published_at": day,
        "body_text_truncated": body_lost,
    }


def test_newest_first_bounded_window_excludes_older_history_only():
    acc = WindowAccumulator(limit=20)
    today = date(2026, 10, 31)
    for i in range(200):
        acc.add(sample_event(
            i, day=(today - timedelta(days=i)).isoformat(),
            version=f"2.1.{200-i}",
        ))
    info = acc.finish()
    assert info["total"] == 200
    assert info["omitted"] == 180
    assert info["order"] == "newest_first"
    assert info["basis"] == "explicit_publication_dates"
    assert info["window_complete"] is True
    assert [x["event_id"] for x in info["events"]] == [
        SID + ":" + str(i) for i in range(20)
    ]


def test_oldest_first_bounded_window_selects_latest_tail_in_reverse_order():
    acc = WindowAccumulator(limit=20)
    today = date(2026, 10, 31)
    for i in range(200):
        acc.add(sample_event(
            i, day=(today - timedelta(days=199 - i)).isoformat(),
            version=f"2.1.{i + 1}",
        ))
    info = acc.finish()
    assert info["order"] == "oldest_first"
    assert info["window_complete"] is True
    assert [e["version"] for e in info["events"]][:3] == [
        "2.1.200", "2.1.199", "2.1.198",
    ]


def test_mixed_date_and_unknown_year_disables_complete_window():
    acc = WindowAccumulator(limit=10)
    acc.add(sample_event(1, day=None, version="2.0.3"))
    acc.add(sample_event(2, day="2026-10-29", version="2.0.2"))
    acc.add(sample_event(3, day="2026-10-30", version="2.0.4"))
    info = acc.finish()
    assert info["window_complete"] is False
    assert info["basis"] == "numeric_versions_no_date_inference" or \
        info["basis"] == "mixed_or_undated_entries"
    assert info["order"] == "unknown"


def test_old_historical_body_loss_does_not_mislabel_recent_evidence():
    acc = WindowAccumulator(limit=5)
    today = date(2026, 10, 31)
    for i in range(20):
        acc.add(sample_event(i,
                             day=(today - timedelta(days=i)).isoformat(),
                             body_lost=(i == 19)))
    info = acc.finish()
    assert info["window_complete"] is True
    assert info["body_loss_count"] == 1
    assert info["recent_body_loss_count"] == 0
    assert info["omitted"] == 15


def test_official_markdown_parse_keeps_recent_versions_without_fake_dates():
    markdown = "# Changelog\n\n" + "".join(
        f"## 2.1.{i}\n\n- Updated API workflow v2.1.{i}\n"
        "- Fixed tool compatibility details.\n\n"
        for i in reversed(range(1, 601))
    )
    info = parse_markdown_releases(markdown, SID, HTML_URL, ALT)
    assert info["release_event_count"] == 600
    assert info["release_events_truncated"] is True
    assert info["release_recent_event_count"] == 80
    assert info["release_historical_event_count_omitted"] == 520
    assert [x["version"] for x in info["release_events"][:3]] == [
        "2.1.600", "2.1.599", "2.1.598",
    ]
    assert info["release_window_complete"] is True
    assert info["release_order_basis"] == "numeric_versions_no_date_inference"
    assert info["latest_release_date_candidate"] is None
    assert info["release_dated_event_count"] == 0
    assert all(x["approved_for_advisor"] is False for x in info["release_events"])
    assert info["release_events"][0]["evidence_locator"]["markdown_line_start"] > 0
    assert info["content_sha256"]


def test_official_markdown_html_source_url_remains_first_party_allowlisted():
    assert allowed_markdown_url(SOURCE) == ALT
    fake = dict(SOURCE, url="https://evil.invalid/another")
    assert allowed_markdown_url(fake) is None
    assert allowed_markdown_url({
        "id": "random_changelog", "url": HTML_URL,
    }) is None


def test_markdown_body_overflow_is_flagged_and_keeps_review_link():
    markdown = "# Changelog\n## 2.1.5\n" + ("Long change detail. " * 2000)
    info = parse_markdown_releases(markdown, SID, HTML_URL, ALT)
    evt = info["release_events"][0]
    assert evt["body_text_truncated"] is True
    assert evt["excerpt_truncated"] is True
    assert evt["permalink"] == HTML_URL
    assert evt["evidence_locator"]["markdown_source_url"] == ALT


def test_large_changelog_html_exposes_recent_date_window_and_history_loss():
    today = date(2026, 10, 31)
    markup = "<html><main><h1>Changelog</h1>" + "".join(
        f'<h2>{(today - timedelta(days=i)).isoformat()}</h2>'
        f'<h3 id="release-{i}">Version v1.{300-i}.0</h3>'
        "<p>" + ("Release details for new APIs, tools and supported models. " * 44)
        + "</p>"
        for i in range(140)
    ) + "</main></html>"
    evidence = extract_evidence(
        markup, HTML_URL, category="changelog", source_id=SID,
    )
    assert len(evidence["text"]) > 250_000
    assert evidence["sections_truncated"] is True
    assert evidence["release_event_count"] == 140
    assert evidence["release_events_truncated"] is True
    assert evidence["release_window_complete"] is True
    assert evidence["release_order_direction"] == "newest_first"
    assert evidence["latest_release_date_candidate"] == "2026-10-31"
    assert assess_capture("changelog", evidence, evidence["text"]) == ("captured", "")


def test_compaction_never_silently_discards_recent_evidence_or_source_identity():
    text = ("Historic documentation and repeated release notes. " * 20000)
    row = {
        "source_id": SID, "source_url": HTML_URL,
        "category": "changelog", "status": "captured",
        "content_sha256": "full-page-hash",
        "requested_cohort": "proven",
        "release_events_schema": "1.1",
        "release_window_complete": True,
        "release_events": [{
            "event_id": SID + ":" + str(i),
            "excerpt": "New feature " * 300,
            "excerpt_truncated": False,
            "body_text_truncated": False,
            "body_sha256": "h" * 64,
        } for i in range(80)],
        "sections": [{
            "section_id": "old-" + str(i),
            "excerpt": "historic change details " * 300,
            "excerpt_truncated": False,
        } for i in range(180)],
        "sections_truncated": False, "tables": [],
        "approved_for_advisor": False,
    }
    compact = compact_changelog_record(row, text)
    assert compact["source_id"] == SID
    assert compact["requested_cohort"] == "proven"
    assert compact["release_events"][0]["body_sha256"] == "h" * 64
    assert len(compact["release_events"]) == 80
    assert len(compact["text"]) <= 24000
    assert compact["historical_text_truncated"] is True
    assert compact["sections_truncated"] is True
    assert compact["approved_for_advisor"] is False
    assert serialized_size(compact) <= ITEM_TARGET_BYTES


def html_response(html):
    return HtmlResponse(
        url=HTML_URL, status=200,
        body=html.encode("utf-8"), encoding="utf-8",
        headers={"Content-Type": "text/html"},
        request=Request(HTML_URL),
    )


def markdown_response(body, request, status=200, content_type="text/markdown"):
    return TextResponse(
        url=ALT, status=status,
        body=body.encode("utf-8"), encoding="utf-8",
        headers={"Content-Type": content_type},
        request=request,
    )


def test_claude_html_oversized_without_events_uses_exact_markdown_fallback():
    spider = ChangelogSpider(cohort="candidate", source_ids=SID)
    html = "<main><h1>Claude Code changelog</h1><p>" + (
        "Full historical release details and updates. " * 10000
    ) + "</p></main>"
    emitted = list(spider.parse_page(html_response(html), SOURCE))
    assert len(emitted) == 1
    req = emitted[0]
    assert isinstance(req, Request)
    assert req.url == ALT
    assert req.meta["dont_redirect"] is True
    assert req.cb_kwargs["source"]["id"] == SID
    assert req.cb_kwargs["primary"]["source_id"] == SID
    assert req.cb_kwargs["primary"]["approved_for_advisor"] is False


def test_markdown_alternate_returns_one_unverified_item_with_recent_versions():
    spider = ChangelogSpider(cohort="candidate", source_ids=SID)
    html = "<main><h1>Changelog</h1><p>" + (
        "Old undated changes. " * 15000
    ) + "</p></main>"
    req = list(spider.parse_page(html_response(html), SOURCE))[0]
    assert isinstance(req, Request)
    md = "# Changelog\n" + "".join(
        f"## 2.1.{n}\n- Tool behavior changes for this version.\n"
        for n in reversed(range(1, 300))
    )
    item = list(spider.parse_official_markdown(
        markdown_response(md, req), **req.cb_kwargs,
    ))[0]
    assert item["source_id"] == SID
    assert item["source_url"] == HTML_URL
    assert item["final_url"] == ALT
    assert item["source_format"] == "official_markdown"
    assert item["markdown_alternate_result"] == "structured_version_evidence"
    assert item["release_events"][0]["version"] == "2.1.299"
    assert item["release_event_count"] == 299
    assert item["release_recent_event_count"] == 80
    assert item["release_window_complete"] is True
    assert item["latest_release_date_candidate"] is None
    assert item["status"] == "needs_review"
    assert item["error"] == "release_events_missing_publication_dates"
    assert item["approved_for_advisor"] is False
    assert serialized_size(item) <= ITEM_TARGET_BYTES


def test_unavailable_markdown_retains_primary_record_without_duplicate_item():
    spider = ChangelogSpider(cohort="candidate", source_ids=SID)
    html = "<main><h1>Changelog</h1><p>" + ("Archived updates. " * 20000) + "</p></main>"
    request = list(spider.parse_page(html_response(html), SOURCE))[0]
    primary = request.cb_kwargs["primary"]
    original_status = primary["status"]
    item = list(spider.parse_official_markdown(
        markdown_response("Not found", request, status=404), **request.cb_kwargs,
    ))[0]
    assert item is primary
    assert item["status"] == original_status
    assert item["markdown_alternate_result"] == "http_error"
    assert item["markdown_alternate_http_status"] == 404
    assert item["approved_for_advisor"] is False


def test_markdown_fallback_wrong_content_type_not_assumed_usable():
    spider = ChangelogSpider(cohort="candidate", source_ids=SID)
    html = "<main><h1>Changelog</h1><p>" + ("Archived updates. " * 20000) + "</p></main>"
    request = list(spider.parse_page(html_response(html), SOURCE))[0]
    item = list(spider.parse_official_markdown(
        markdown_response("<html>Captcha</html>", request,
                          content_type="text/html"), **request.cb_kwargs,
    ))[0]
    assert item["markdown_alternate_result"] == "unsupported_content_type"
    assert item["release_event_count"] == 0


def test_migrating_release_parser_schema_establishes_new_baseline():
    source = {
        "source_id": SID, "source_url": HTML_URL, "provider": "Claude Code",
        "category": "changelog", "status": "captured",
        "content_sha256": "h", "sections": [], "approved_for_advisor": False,
        "release_events_schema": "1.1", "release_window_complete": True,
        "release_events": [{
            "event_id": "v1", "body_sha256": "hash1", "published_at": "2026-10-30",
            "version": "2.1.5", "title": "Release v2.1.5", "permalink": HTML_URL,
        }],
    }
    old = copy.deepcopy(source)
    old["release_events_schema"] = "1.0"
    changes = compare({SID: source}, {SID: old})
    assert review_queue({SID: source}, {SID: old}, changes) == []



def _review_snapshot(data, *, status="captured", error=""):
    row = {
        "source_id": SID, "source_url": HTML_URL,
        "provider": "Claude Code", "category": "changelog",
        "status": status, "error": error,
        "content_sha256": data["content_sha256"],
        "release_events_schema": data["release_events_schema"],
        "release_events": data["release_events"],
        "release_window_complete": data["release_window_complete"],
        "release_order_basis": data["release_order_basis"],
        "release_event_identity_collision": data["release_event_identity_collision"],
        "release_events_truncated": data["release_events_truncated"],
        "release_recent_body_loss_count": data["release_recent_body_loss_count"],
        "release_dated_event_count": data["release_dated_event_count"],
        "sections": [], "approved_for_advisor": False,
    }
    if data.get("source_format"):
        row.update(source_format=data["source_format"],
                   markdown_source_url=data["source_markdown_url"])
    return row


def test_new_undated_claude_version_is_reviewable_not_a_dated_release():
    before = parse_markdown_releases(
        "# Changelog\n## 2.1.10\n- First\n## 2.1.9\n- Earlier\n",
        SID, HTML_URL, ALT,
    )
    after = parse_markdown_releases(
        "# Changelog\n## 2.1.11\n- Current\n## 2.1.10\n- First\n"
        "## 2.1.9\n- Earlier\n",
        SID, HTML_URL, ALT,
    )
    old = _review_snapshot(before, status="needs_review",
                           error="release_events_missing_publication_dates")
    new = _review_snapshot(after, status="needs_review",
                           error="release_events_missing_publication_dates")
    assert review_queue({SID: old}, {}, compare({SID: old}, {})) == []
    queue = review_queue({SID: new}, {SID: old}, compare({SID: new}, {SID: old}))
    assert len(queue) == 1
    assert queue[0]["change_type"] == "version_first_seen_date_unknown"
    assert queue[0]["version"] == "2.1.11"
    assert queue[0]["published_at_candidate"] is None
    assert queue[0]["approved_for_advisor"] is False
    assert "publication date unknown" in queue[0]["interpretation_warning"]


def test_undated_version_comparison_rejects_host_spoofing_and_blocked_source():
    first = parse_markdown_releases(
        "# Changelog\n## 2.1.11\n- Current\n## 2.1.10\n- Earlier\n",
        SID, HTML_URL, ALT,
    )
    second = parse_markdown_releases(
        "# Changelog\n## 2.1.12\n- New\n## 2.1.11\n- Current\n"
        "## 2.1.10\n- Earlier\n", SID, HTML_URL, ALT,
    )
    old = _review_snapshot(first, status="needs_review",
                           error="release_events_missing_publication_dates")
    new = _review_snapshot(second, status="needs_review",
                           error="release_events_missing_publication_dates")
    spoofed = dict(new, markdown_source_url="https://evil.invalid/releases")
    blocked = dict(new, status="blocked", error="access_or_login_challenge")
    for item in (spoofed, blocked):
        assert review_queue({SID: item}, {SID: old},
                            compare({SID: item}, {SID: old})) == []


def test_recent_release_diffs_survive_omitted_historical_entries():
    def html_range(start, length):
        return "<html><main><h1>Changelog</h1>" + "".join(
            f'<h2>{(date(2026, 10, 31) - timedelta(days=i)).isoformat()}</h2>'
            f'<h3 id="v{i}">Version v3.{200-i}.0</h3>'
            "<p>Official published changes for supported APIs and tools.</p>"
            for i in range(start, start + length)
        ) + "</main></html>"

    old_data = extract_evidence(
        html_range(1, 130), HTML_URL, category="changelog", source_id=SID,
    )
    new_data = extract_evidence(
        html_range(0, 131), HTML_URL, category="changelog", source_id=SID,
    )
    assert old_data["release_events_truncated"] is True
    assert new_data["release_events_truncated"] is True
    assert old_data["release_window_complete"] is True
    assert new_data["release_window_complete"] is True
    old, new = _review_snapshot(old_data), _review_snapshot(new_data)
    queue = review_queue({SID: new}, {SID: old}, compare({SID: new}, {SID: old}))
    assert [x["change_type"] for x in queue] == ["release_event_first_seen"]
    assert queue[0]["published_at_candidate"] == "2026-10-31"
    assert queue[0]["approved_for_advisor"] is False
