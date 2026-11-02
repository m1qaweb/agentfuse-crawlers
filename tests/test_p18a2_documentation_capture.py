"""P18A2 reviewed documentation HTML capture -- synthetic, zero publisher GETs."""
import hashlib
import io
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentfuse_crawlers.sources import load_sources
from scripts.capture_documentation_children import (
    DEFAULT_REGISTRY, _inspect_html, capture_documentation_pages,
    capture_plan, main, page_id, validate_registry,
)
from scripts.plan_documentation_children import build_review_packet

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
SID = "openai_api_docs"
SOURCE = {s["id"]: s for s in load_sources()}[SID]
URL = SOURCE["url"].rstrip("/") + "/guides/structured-outputs"
ROBOTS = "https://developers.openai.com/robots.txt"
NOTE = (
    "Independently checked publisher access rules and permitted private "
    "retention of this public documentation page for manual validation."
)
HTML = (
    '<html><head><title>Structured outputs</title>'
    '<link rel="canonical" href="' + URL + '">'
    '</head><body><main><h1>Structured outputs</h1>'
    '<p>This is an INVENTED technical documentation fixture with explicitly '
    'supported JSON schema examples; it is not an actual provider claim.</p>'
    '</main></body></html>'
).encode("utf-8")
ROBOTS_OK = b"User-agent: *\nAllow: /\n"
ROBOTS_DENY = b"User-agent: *\nDisallow: /api/docs/guides\n"


class FakeResponse(io.BytesIO):
    def __init__(self, url, body, *, mime="text/html", status=200,
                 final_url=None, headers=None):
        super().__init__(body)
        self.url = final_url or url
        self.status = status
        self.headers = {
            "Content-Type": mime, "Content-Length": str(len(body)),
            "Date": "Mon, 02 Nov 2026 12:00:00 GMT",
        }
        if headers:
            self.headers.update(headers)

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError("Unexpected network request " + url)
        route = self.routes[url]
        if isinstance(route, Exception):
            raise route
        return route


def page_item(*urls):
    links = []
    for url in urls:
        links.append({
            "candidate_id": hashlib.sha256(
                (SID + "|docs-child|" + url).encode()
            ).hexdigest()[:24],
            "source_id": SID,
            "candidate_url": url,
            "anchor_text": "Structured outputs",
            "found_in": "navigation_or_sidebar",
            "relationship": "same_host_path_family_unverified",
            "review_status": "pending_human_url_and_policy_review",
            "approved_for_crawl": False,
            "approved_for_advisor": False,
        })
    return {
        "source_id": SID, "category": "documentation",
        "provider": SOURCE["provider"], "source_url": SOURCE["url"],
        "status": "captured", "approved_for_advisor": False,
        "source_product_title_conflict": False,
        "content_sha256": "c" * 64,
        "documentation_nav_candidates": links,
        "documentation_canonical_relation": "missing",
        "documentation_canonical_review_url": None,
    }


def review_packet(*urls):
    return build_review_packet([page_item(*(urls or (URL,)))])


def approved_entry(packet, task):
    return {
        "page_id": page_id(task["source_id"], task["candidate_url"]),
        "source_id": task["source_id"],
        "source_url": task["source_url"],
        "product_id": task["product_id_unverified"],
        "child_url": task["candidate_url"],
        "task_id": task["task_id"],
        "parent_snapshot_sha256": task["parent_snapshot_sha256_unverified"],
        "review_packet_sha256": packet["packet_sha256"],
        "policy_review": {
            "decision": "permitted_single_manual_static_capture",
            "publisher_policy_evidence_url": "https://developers.openai.com/api/docs",
            "reviewed_by": "Policy Reviewer",
            "reviewed_at_utc": "2026-11-02T15:00:00Z",
            "expires_at_utc": "2026-11-10T00:00:00Z",
            "review_note": (
                "Manually reviewed the invented first-party research policy "
                "fixture, exact path scope, retention and robots conditions."
            ),
        },
        "product_review": {
            "decision": "exact_product_page_reviewed",
            "reviewed_by": "Product Reviewer",
            "reviewed_at_utc": "2026-11-02T15:10:00Z",
            "official_canonical_url": task["candidate_url"],
            "locale": "en",
            "version": "current",
            "technical_topic": "structured_output",
        },
        "capture_method": "static_html",
        "approved_for_manual_capture": True,
        "approved_for_unattended_collection": False,
        "approved_for_advisor": False,
    }


def registry_from(packet):
    return {
        "schema_version": "1.0",
        "kind": "p18a2_exact_reviewed_documentation_pages_manual_only",
        "approved_for_advisor": False,
        "automatic_collection_enabled": False,
        "entries": [approved_entry(packet, t) for t in packet["tasks"]],
    }


def selected():
    packet = review_packet()
    registry = registry_from(packet)
    return packet, registry, registry["entries"][0]["page_id"]


def fake_routes(*, html=HTML, robots=ROBOTS_OK, extra=None):
    routes = {
        ROBOTS: FakeResponse(ROBOTS, robots, mime="text/plain"),
        URL: FakeResponse(URL, html),
    }
    routes.update(extra or {})
    return FakeOpener(routes)


def test_registry_committed_empty_and_read_only_cli_plan(capsys, monkeypatch):
    registry = json.loads(DEFAULT_REGISTRY.read_text())
    assert registry["entries"] == []
    assert len(load_sources()) == 460
    plan = capture_plan(registry, now=NOW)
    assert plan["selected_count"] == 0
    assert plan["reviewed_registry_entries"] == 0
    assert plan["network_requests_performed"] == 0
    assert plan["advisor_approved_facts"] == 0
    assert plan["automatic_collection_enabled"] is False
    monkeypatch.setattr(sys, "argv", ["capture_documentation_children"])
    main()
    output = json.loads(capsys.readouterr().out)
    assert output["pages_selected_for_manual_capture"] == []
    assert output["new_spider_sources"] == 0


def test_binds_original_packet_product_and_expiry_without_fact_approval():
    packet, registry, pid = selected()
    result = validate_registry(registry, packet, now=NOW)
    assert len(result) == 1
    assert result[0]["page_id"] == pid
    assert result[0]["product_id"] == "openai_api"
    assert result[0]["parent_snapshot_sha256"] == "c" * 64
    assert not result[0]["approved_for_advisor"]
    plan = capture_plan(registry, packet, [pid], now=NOW)
    assert plan["selected_count"] == 1
    assert plan["pages_selected_for_manual_capture"][0]["child_url"] == URL
    assert plan["network_requests_performed"] == 0
    assert plan["new_spider_sources"] == 0


@pytest.mark.parametrize("path,value", [
    (("approved_for_advisor",), True),
    (("automatic_collection_enabled",), True),
    (("entries",0,"approved_for_advisor"), True),
    (("entries",0,"approved_for_unattended_collection"), True),
    (("entries",0,"child_url"), "https://evil.example/api/docs/page"),
    (("entries",0,"source_url"), "https://evil.example/docs"),
    (("entries",0,"product_id"), "claude_code"),
    (("entries",0,"task_id"), "0" * 24),
    (("entries",0,"page_id"), "0" * 24),
    (("entries",0,"parent_snapshot_sha256"), "a" * 64),
    (("entries",0,"review_packet_sha256"), "f" * 64),
    (("entries",0,"policy_review","decision"), "allowed_without_review"),
    (("entries",0,"policy_review","expires_at_utc"), "2026-11-01T00:00:00Z"),
    (("entries",0,"policy_review","reviewed_at_utc"), "2026-12-02T00:00:00Z"),
    (("entries",0,"policy_review","publisher_policy_evidence_url"),
     "http://localhost/private"),
    (("entries",0,"product_review","official_canonical_url"),
     "https://developers.openai.com/codex/docs"),
    (("entries",0,"product_review","technical_topic"), "made_up_topic"),
    (("entries",0,"capture_method"), "browser_bypass"),
])
def test_registry_tampering_expires_or_privilege_raise(path, value):
    packet, registry, _ = selected()
    modified = deepcopy(registry)
    target = modified
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_registry(modified, packet, now=NOW)


def test_packet_integrity_and_review_task_cannot_be_rewritten():
    packet, registry, _ = selected()
    bad = deepcopy(packet)
    bad["tasks"][0]["candidate_url"] = (
        "https://developers.openai.com/api/docs/guides/fake"
    )
    with pytest.raises(ValueError, match="integrity"):
        validate_registry(registry, bad, now=NOW)
    bad = deepcopy(packet)
    bad["approved_for_crawl"] = True
    with pytest.raises(ValueError):
        validate_registry(registry, bad, now=NOW)
    with pytest.raises(ValueError, match="requires matching"):
        validate_registry(registry, None, now=NOW)


def test_duplicate_registry_entries_or_unselected_page_rejected():
    packet, registry, pid = selected()
    bad = deepcopy(registry)
    bad["entries"].append(deepcopy(bad["entries"][0]))
    with pytest.raises(ValueError, match="Repeated"):
        validate_registry(bad, packet, now=NOW)
    with pytest.raises(ValueError, match="Unknown or unapproved"):
        capture_plan(registry, packet, ["a" * 24], now=NOW)
    with pytest.raises(ValueError, match="distinct"):
        capture_plan(registry, packet, [pid, pid], now=NOW)
    with pytest.raises(ValueError, match="Select 1-5"):
        capture_plan(registry, packet, [pid] * 6, now=NOW)


@pytest.mark.parametrize("snippet", [
    "<html><head><meta http-equiv='refresh' content='0;url=/other'></head></html>",
    "<html><head><link rel='canonical' href='https://evil.example/other'></head></html>",
    "<html><head><link rel='canonical' href='/codex/docs'></head></html>",
    "<html><head><link rel='canonical' href='/api/docs/guides/other'></head></html>",
    "<html><head><link rel='canonical' href='?token=secret'></head></html>",
    ("<html><head><link rel='canonical' href='" + URL +
     "'><link rel='canonical' href='" + URL + "'></head></html>"),
    "<html><head><title>Access denied</title></head></html>",
])
def test_canonical_refresh_and_access_challenges_fail_closed(snippet):
    with pytest.raises(ValueError):
        _inspect_html(snippet, URL)


def test_missing_canonical_does_not_claim_verified_canonical():
    assert _inspect_html("<html><title>Fixture</title></html>", URL) == (
        "canonical_absent_requires_review"
    )


def test_manual_capture_fake_network_creates_private_raw_bytes(tmp_path):
    packet, registry, pid = selected()
    target = tmp_path / "raw-doc-evidence"
    fake = fake_routes()
    clock = lambda: NOW
    manifest, audit = capture_documentation_pages(
        registry, packet, [pid], target,
        policy_review_note=NOTE, opener=fake, sleep_fn=lambda _: None,
        clock=clock,
    )
    assert fake.calls == [ROBOTS, URL]
    assert manifest["approved_for_advisor"] is False
    assert manifest["advisor_approved_facts"] == 0
    assert audit["network_requests_performed"] == 2
    assert audit["scheduled_jobs_created"] == 0
    assert audit["production_database_writes"] == 0
    assert len(manifest["snapshots"]) == 1
    snap = manifest["snapshots"][0]
    stored = target / snap["snapshot"]["file"]
    assert stored.read_bytes() == HTML
    assert snap["snapshot"]["sha256"] == hashlib.sha256(HTML).hexdigest()
    assert snap["snapshot"]["canonical_observation"] == (
        "equivalent_publisher_canonical_observed"
    )
    assert json.loads((target / "child_html_snapshots.json").read_text()) == manifest
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o700
        assert all(x.stat().st_mode & 0o777 == 0o600 for x in target.iterdir())
    with pytest.raises(ValueError, match="new private"):
        capture_documentation_pages(
            registry, packet, [pid], target, policy_review_note=NOTE,
            opener=fake, sleep_fn=lambda _: None, clock=clock,
        )
    assert fake.calls == [ROBOTS, URL]


def test_robots_denial_aborts_before_page_and_without_folder(tmp_path):
    packet, registry, pid = selected()
    fake = fake_routes(robots=ROBOTS_DENY)
    target = tmp_path / "denied"
    with pytest.raises(ValueError, match="robots"):
        capture_documentation_pages(
            registry, packet, [pid], target, policy_review_note=NOTE,
            opener=fake, sleep_fn=lambda _: None, clock=lambda: NOW,
        )
    assert fake.calls == [ROBOTS]
    assert not target.exists()


@pytest.mark.parametrize("override", [
    {"status": 302},
    {"final_url": "https://evil.example/docs"},
    {"mime": "application/json"},
    {"headers": {"Content-Encoding": "gzip"}},
])
def test_redirect_challenge_media_and_encoding_rejected_and_rolled_back(
    tmp_path, override,
):
    packet, registry, pid = selected()
    fake = fake_routes(extra={URL: FakeResponse(URL, HTML, **override)})
    target = tmp_path / "rejected"
    with pytest.raises(ValueError):
        capture_documentation_pages(
            registry, packet, [pid], target, policy_review_note=NOTE,
            opener=fake, sleep_fn=lambda _: None, clock=lambda: NOW,
        )
    assert fake.calls == [ROBOTS, URL]
    assert not target.exists()


def test_exact_page_batch_failure_rolls_back_all_captured_html(tmp_path):
    second = SOURCE["url"].rstrip("/") + "/guides/models"
    packet = review_packet(URL, second)
    registry = registry_from(packet)
    ids = [entry["page_id"] for entry in registry["entries"]]
    assert len(ids) == 2
    fake = fake_routes(extra={
        second: FakeResponse(second, b"<html><title>Access denied</title></html>"),
    })
    target = tmp_path / "atomic"
    with pytest.raises(ValueError, match="challenge"):
        capture_documentation_pages(
            registry, packet, ids, target, policy_review_note=NOTE,
            opener=fake, sleep_fn=lambda _: None, clock=lambda: NOW,
        )
    assert fake.calls == [ROBOTS, URL, second]
    assert not target.exists()


def test_missing_note_invalid_output_and_stale_approval_no_network(tmp_path):
    packet, registry, pid = selected()
    fake = fake_routes()
    with pytest.raises(ValueError, match="note"):
        capture_documentation_pages(
            registry, packet, [pid], tmp_path / "empty-note",
            policy_review_note="brief", opener=fake,
            sleep_fn=lambda _: None, clock=lambda: NOW,
        )
    assert not fake.calls
    with pytest.raises(ValueError, match="expired"):
        capture_documentation_pages(
            registry, packet, [pid], tmp_path / "stale",
            policy_review_note=NOTE, opener=fake,
            sleep_fn=lambda _: None,
            clock=lambda: datetime(2026, 11, 20, tzinfo=timezone.utc),
        )
    assert not fake.calls
    with pytest.raises(ValueError, match="tracked repo"):
        capture_documentation_pages(
            registry, packet, [pid],
            Path(__file__).resolve().parents[1] / "docs" / "child-evidence",
            policy_review_note=NOTE, opener=fake,
            sleep_fn=lambda _: None, clock=lambda: NOW,
        )
    assert not fake.calls
