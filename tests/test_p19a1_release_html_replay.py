"""P19A1 original changelog HTML capture/replay: SYNTHETIC ONLY; no web."""
import hashlib
import io
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.capture_release_html import (
    capture_plan, capture_changelog_html, main as capture_cli,
)
from scripts.replay_release_snapshots import (
    _digest, _valid_replay, compare_replays, prepare_blind_release_review,
    replay_changelog_html, source_pins, validate_capture_manifest,
)

SID = "openai_api_changelog"
SOURCE = {s["id"]: s for s in load_sources()}[SID]
URL = SOURCE["url"]
ROBOTS = "https://developers.openai.com/robots.txt"
BEFORE = "2026-11-02T10:00:00Z"
AFTER = "2026-11-02T11:00:00Z"
NOTE = (
    "Publisher documentation permissions, research retention conditions, "
    "and exact public changelog URL were independently reviewed by operator."
)
ROBOTS_OK = b"User-agent: *\nAllow: /\n"
ROBOTS_DENIED = b"User-agent: *\nDisallow: /api/docs/changelog\n"

PARA = (
    "This is synthetic release content invented for deterministic tests. "
    "It describes imaginary API model settings, logging, safety review, "
    "configuration details, compatibility, documentation, and other "
    "changes. It does not establish a real publisher feature or date."
)


def entry(slug, title, day, para=PARA):
    return (
        '<article><header><h2 id="' + slug + '">' + title + '</h2>'
        '<time datetime="' + day + 'T12:00:00Z">'
        + day + '</time></header><p>' + para + '</p></article>'
    )


def page(*records):
    return (
        '<!doctype html><html><head><title>OpenAI API Changelog</title>'
        '</head><body><main><h1>OpenAI API Changelog</h1>'
        + "".join(records) + '</main></body></html>'
    )


OLD_HTML = page(
    entry("r2", "Model preview v2.0.0", "2026-10-28"),
    entry("r1", "Model update v1.9.0", "2026-10-26"),
)
NEW_HTML = page(
    entry("r3", "New API capability v2.1.0", "2026-10-30"),
    entry("r2", "Model preview v2.0.0", "2026-10-28"),
    entry("r1", "Model update v1.9.0", "2026-10-26"),
)
REORDERED_HTML = page(
    entry("r1", "Model update v1.9.0", "2026-10-26"),
    entry("r2", "Model preview v2.0.0", "2026-10-28"),
)


def manifest_entry(root, html, at=BEFORE, sid=SID):
    name = sid + "-" + hashlib.sha256(html.encode()).hexdigest()[:16] + ".html"
    (root / name).write_bytes(html.encode())
    source = {s["id"]: s for s in load_sources()}[sid]
    return {
        "source_id": sid,
        "snapshot": {
            "file": name,
            "sha256": hashlib.sha256(html.encode()).hexdigest(),
            "request_url": source["url"], "final_url": source["url"],
            "http_status": 200, "media_type": "text/html",
            "capture_method": "static_html",
            "captured_at_utc": at,
            "capture_origin_review_status": "operator_supplied_unverified",
        },
    }


def manifest(entries):
    return {
        "schema_version": "1.0",
        "kind": "frozen_original_changelog_html_manifest",
        "expected_manifest_sha256": manifest_sha256(),
        "expected_source_registry_sha256": registry_revision_sha256(),
        "approved_for_advisor": False, "snapshots": entries,
    }


def snapshot(root, html, at):
    return replay_changelog_html(
        manifest([manifest_entry(root, html, at)]), root,
    )


class FakeHTTPResponse(io.BytesIO):
    def __init__(self, url, body, *, final_url=None, status=200,
                 mime="text/html", extra_headers=None):
        super().__init__(body)
        self.url = final_url or url
        self.status = status
        self.headers = {
            "Content-Type": mime, "Content-Length": str(len(body)),
            "Date": "Mon, 02 Nov 2026 11:00:00 GMT",
        }
        self.headers.update(extra_headers or {})

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, mapping):
        self.routes = mapping
        self.calls = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError("Unexpected network operation: " + url)
        return self.routes[url]


def fake_http(robots=ROBOTS_OK, html=OLD_HTML.encode(), **opts):
    return FakeOpener({
        ROBOTS: FakeHTTPResponse(ROBOTS, robots, mime="text/plain"),
        URL: FakeHTTPResponse(URL, html, **opts),
    })


def test_pinned_source_plan_dry_run_and_no_arbitrary_urls(capsys, monkeypatch):
    pins = source_pins([SID])
    assert len(load_sources()) == 460
    assert pins["sources"][0]["official_source_url"] == URL
    assert pins["network_requests_performed"] == 0
    assert pins["approved_for_advisor"] is False
    monkeypatch.setattr(sys, "argv", [
        "capture_release_html", "--source-ids", SID,
    ])
    capture_cli()
    plan = json.loads(capsys.readouterr().out)
    assert plan["kind"] == "p19a1_read_only_manual_changelog_capture_plan"
    assert plan["sources"][0]["robots_url"] == ROBOTS
    assert plan["network_requests_performed"] == 0
    assert plan["new_spider_sources"] == 0
    for invalid in ("not_a_real_changelog", "openai_api_pricing", "v0_changelog"):
        with pytest.raises(ValueError):
            capture_plan([invalid])
    with pytest.raises(ValueError):
        source_pins([SID, SID])


def test_manual_capture_robots_first_and_private_original_bytes(tmp_path):
    target = tmp_path / "private-original"
    fake = fake_http()
    manifest_, audit = capture_changelog_html(
        [SID], target, policy_review_note=NOTE,
        opener=fake, sleep_fn=lambda _seconds: None,
        clock=lambda: datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc),
    )
    assert fake.calls == [ROBOTS, URL]
    assert audit["network_requests_performed"] == 2
    assert audit["zyte_jobs_created"] == 0
    assert audit["new_release_alerts"] == 0
    assert not audit["approved_for_advisor"]
    assert len(manifest_["snapshots"]) == 1
    sample = manifest_["snapshots"][0]["snapshot"]
    assert (target / sample["file"]).read_bytes() == OLD_HTML.encode()
    assert sample["sha256"] == hashlib.sha256(OLD_HTML.encode()).hexdigest()
    assert validate_capture_manifest(manifest_)[SID]["url"] == URL
    assert json.loads((target / "frozen_release_snapshots.json").read_text()) == manifest_
    replay = replay_changelog_html(manifest_, target)
    assert replay["source_count"] == 1
    assert len(replay["sources"][0]["events"]) == 2
    assert replay["network_requests_performed"] == 0
    assert replay["human_truth_review_completed"] is False
    assert replay["verified_release_events"] == 0
    assert replay["new_release_alerts"] == 0
    assert replay["sources"][0]["release_window_complete"]
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o700
        assert all(f.stat().st_mode & 0o777 == 0o600 for f in target.iterdir())


def test_capture_disallowed_before_source_request_or_directory(tmp_path):
    fake = fake_http(robots=ROBOTS_DENIED)
    target = tmp_path / "denied"
    with pytest.raises(ValueError, match="robots"):
        capture_changelog_html(
            [SID], target, policy_review_note=NOTE,
            opener=fake, sleep_fn=lambda _: None,
        )
    assert fake.calls == [ROBOTS]
    assert not target.exists()


@pytest.mark.parametrize("options", [
    {"status": 302}, {"final_url": "https://evil.example/new"},
    {"mime": "application/json"},
    {"extra_headers": {"Content-Encoding": "gzip"}},
    {"extra_headers": {"Content-Type": "text/html; charset=shift_jis"}},
])
def test_unsafe_http_status_redirect_media_encoding_fail_atomic(tmp_path, options):
    fake = fake_http(**options)
    output = tmp_path / "bad-response"
    with pytest.raises(ValueError):
        capture_changelog_html(
            [SID], output, policy_review_note=NOTE, opener=fake,
            sleep_fn=lambda _: None,
        )
    assert fake.calls == [ROBOTS, URL]
    assert not output.exists()


def test_access_challenge_is_never_retained_as_valid_capture(tmp_path):
    fake = fake_http(html=b"<html><title>Access denied</title></html>")
    out = tmp_path / "challenge"
    with pytest.raises(ValueError, match="access challenge"):
        capture_changelog_html(
            [SID], out, policy_review_note=NOTE,
            opener=fake, sleep_fn=lambda _: None,
        )
    assert not out.exists()


def test_capture_invalid_note_and_existing_folder_do_not_make_network(tmp_path):
    fake = fake_http()
    with pytest.raises(ValueError, match="note"):
        capture_changelog_html(
            [SID], tmp_path / "invalid-note",
            policy_review_note="short", opener=fake,
        )
    assert not fake.calls
    folder = tmp_path / "existing"
    folder.mkdir()
    with pytest.raises(ValueError, match="NEW"):
        capture_changelog_html([SID], folder, policy_review_note=NOTE, opener=fake)
    assert not fake.calls
    with pytest.raises(ValueError, match="gitignored"):
        capture_changelog_html(
            [SID],
            Path(__file__).resolve().parents[1] / "docs" / "raw-releases",
            policy_review_note=NOTE, opener=fake,
        )
    assert not fake.calls


def test_replay_is_deterministic_private_and_source_bound(tmp_path):
    original = manifest([manifest_entry(tmp_path, OLD_HTML)])
    report = replay_changelog_html(original, tmp_path)
    assert report == replay_changelog_html(original, tmp_path)
    assert _valid_replay(report)[SID]["source_url"] == URL
    assert len(report["local_package_sha256"]) == 64
    row = report["sources"][0]
    assert row["capture_status"] == "captured"
    assert row["release_event_count_detected"] == 2
    assert not row["source_product_title_conflict"]
    assert all(e["publisher_event_verified"] is False
               and e["approved_for_advisor"] is False for e in row["events"])
    assert set(e["published_at"] for e in row["events"]) == {
        "2026-10-28", "2026-10-26",
    }
    assert "<html" not in json.dumps(report)
    assert PARA not in json.dumps(report)
    assert str(tmp_path) not in json.dumps(report)


@pytest.mark.parametrize("modify,error", [
    (lambda m: m.update(expected_manifest_sha256="f"*64), "Unpinned"),
    (lambda m: m.update(approved_for_advisor=True), "Unpinned"),
    (lambda m: m["snapshots"][0]["snapshot"].update(sha256="0"*64), "SHA-256"),
    (lambda m: m["snapshots"][0]["snapshot"].update(
        final_url="https://evil.example/release"), "URL/redirect"),
    (lambda m: m["snapshots"][0]["snapshot"].update(
        capture_method="rendered_html"), "method or provenance"),
    (lambda m: m["snapshots"][0]["snapshot"].update(
        file="../secret.html"), "path traversal"),
    (lambda m: m["snapshots"][0]["snapshot"].update(http_status=403), "HTTP 200"),
])
def test_forged_snapshot_provenance_rejected(tmp_path, modify, error):
    m = manifest([manifest_entry(tmp_path, OLD_HTML)])
    modify(m)
    with pytest.raises(ValueError, match=error):
        replay_changelog_html(m, tmp_path)


def test_unchanged_or_reordered_events_no_fake_releases(tmp_path):
    a = snapshot(tmp_path, OLD_HTML, BEFORE)
    b = snapshot(tmp_path, REORDERED_HTML, AFTER)
    result = compare_replays(a, b)
    assert result["source_count"] == 1
    assert result["sources"][0]["status"] == "bounded_structural_review_only"
    assert result["sources"][0]["review_deltas"] == []
    assert result["new_release_alerts"] == 0


def test_added_first_observed_not_new_publication_and_existing_date_edit(tmp_path):
    a = snapshot(tmp_path, OLD_HTML, BEFORE)
    b = snapshot(tmp_path, NEW_HTML, AFTER)
    result = compare_replays(a, b)
    delta = result["sources"][0]["review_deltas"]
    assert len(delta) == 1
    assert delta[0]["review_change_kind"] == "first_observed_release_identity_review"
    assert delta[0]["new_release_alert"] is False
    assert delta[0]["first_observed_not_published_today"]
    assert result["independently_verified_publication_dates"] == 0
    corrected = page(
        entry("r2", "Model preview v2.0.0", "2026-10-29"),
        entry("r1", "Model update v1.9.0", "2026-10-26"),
    )
    c = snapshot(tmp_path, corrected, AFTER)
    corrections = compare_replays(a, c)["sources"][0]["review_deltas"]
    assert len(corrections) == 1
    assert corrections[0]["review_change_kind"] == (
        "date_or_publication_evidence_edited_review"
    )


def test_first_baseline_and_date_scoped_generic_are_not_new_alerts(tmp_path):
    base = snapshot(tmp_path, OLD_HTML, BEFORE)
    tasks = prepare_blind_release_review(base)
    assert tasks["human_reviewed_cases"] == 0
    assert tasks["publisher_facts_verified"] == 0
    assert tasks["human_reviewers_required"] == 2
    assert len(tasks["tasks"]) == 2
    assert tasks["tasks"][0]["expected_publication_date_prefilled"] is False
    changed = deepcopy(base)
    item = changed["sources"][0]["events"][0]
    item["event_id"] = SID + ":" + "b" * 24
    item["identity_basis"] = "date_scoped_generic_heading_review_only"
    item["published_at"] = "2026-10-30"
    changed["sources"][0]["captured_at_utc"] = AFTER
    changed["replay_sha256"] = _digest({
        k: v for k, v in changed.items() if k != "replay_sha256"
    })
    # Cannot promote a changed identity to an alert merely because day changed.
    output = compare_replays(base, changed)
    assert output["sources"][0]["review_deltas"][0]["review_change_kind"] == (
        "ambiguous_generic_date_or_identity_review"
    )


def test_two_round_diff_blocks_bad_source_or_parser_or_missing_date(tmp_path):
    old = snapshot(tmp_path, OLD_HTML, BEFORE)
    new = snapshot(tmp_path, NEW_HTML, AFTER)
    mutated = deepcopy(new)
    mutated["local_package_sha256"] = "a" * 64
    mutated["replay_sha256"] = _digest({
        k: v for k, v in mutated.items() if k != "replay_sha256"
    })
    with pytest.raises(ValueError, match="same source and parser"):
        compare_replays(old, mutated)
    mutated = deepcopy(new)
    mutated["sources"][0]["release_identity_revision"] = "breaking_revision"
    mutated["replay_sha256"] = _digest({
        k: v for k, v in mutated.items() if k != "replay_sha256"
    })
    with pytest.raises(ValueError, match="reset baseline"):
        compare_replays(old, mutated)
    bad = deepcopy(new)
    bad["sources"][0]["release_event_identity_collision"] = True
    bad["replay_sha256"] = _digest({
        k: v for k, v in bad.items() if k != "replay_sha256"
    })
    held = compare_replays(old, bad)["sources"][0]
    assert held["status"] == "held_for_review"
    assert held["review_deltas"] == []
    assert held["new_release_alerts"] == 0
    with pytest.raises(ValueError, match="captured later"):
        compare_replays(new, old)


def test_replay_tampering_rejected_and_blind_sampling_bounded(tmp_path):
    report = snapshot(tmp_path, OLD_HTML, BEFORE)
    tampered = deepcopy(report)
    tampered["sources"][0]["events"][0]["approved_for_advisor"] = True
    tampered["replay_sha256"] = _digest({
        k: v for k, v in tampered.items() if k != "replay_sha256"
    })
    with pytest.raises(ValueError, match="privileged"):
        _valid_replay(tampered)
    tampered = deepcopy(report)
    tampered["new_release_alerts"] = 1
    with pytest.raises(ValueError, match="Malformed"):
        _valid_replay(tampered)
    packet = prepare_blind_release_review(report)
    assert packet["tasks"]
    assert all("published_at" not in x and "title" not in x
               for x in packet["tasks"])
    assert packet["approved_for_advisor"] is False
