"""P17B3 manual HTML acquisition tests: 100% synthetic, NO network."""
import hashlib
import io
import json
import os
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentfuse_crawlers.settings import USER_AGENT, DOWNLOAD_DELAY
from agentfuse_crawlers.sources import load_sources
from scripts.capture_pricing_html import (
    AGENT, MIN_DELAY, MAX_PAGE_BYTES, MAX_ROBOTS_BYTES, NoRedirect,
    _fetch_exact, _robots_url, capture_plan, capture_pricing_html, main,
)
from scripts.replay_pricing_snapshots import (
    replay_pricing_snapshots, validate_snapshot_manifest,
)

KNOWN = {s["id"]: s for s in load_sources()}
SID = "fireworks_ai_pricing"
URL = KNOWN[SID]["url"]
ROBOT_URL = _robots_url(KNOWN[SID])
ALLOWED = b"User-agent: *\nAllow: /\n"
DENIED = b"User-agent: AgentFuseResearchBot\nDisallow: /serverless/pricing\n"
POLICY_NOTE = (
    "Operator checked first-party publisher terms and permitted public-page "
    "research scope, including collection frequency and private retention."
)
HTML = (
    "<html><head><title>Pricing Fixture</title></head><body><main>"
    "<h1>Pricing Fixture</h1><h2>Text and vision models</h2>"
    "<p>In each Standard or Priority cell, prices are input / cached input / "
    "output (USD per 1M tokens), in that order.</p>"
    "<table><thead><tr><th>Model</th><th>Standard</th></tr></thead><tbody>"
    "<tr><th><strong>Ember-1</strong></th><td>$3.00 / $0.30 / $15.00</td>"
    "</tr></tbody></table></main></body></html>"
).encode("utf-8")


class FakeHTTPResponse(io.BytesIO):
    """Original urllib HTTPResponse subset; no socket, proxy, TLS or network."""

    def __init__(self, data, *, url, status=200, mime="text/html",
                 more_headers=None, final_url=None):
        super().__init__(data)
        self._url = final_url or url
        self.status = status
        self.headers = {
            "Content-Type": mime,
            "Content-Length": str(len(data)),
            "Date": "Mon, 02 Nov 2026 12:00:00 GMT",
        }
        if more_headers:
            self.headers.update(more_headers)

    def geturl(self):
        return self._url


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.requests.append({
            "url": url,
            "agent": request.get_header("User-agent"),
            "method": request.get_method(),
            "timeout": timeout,
        })
        payload = self.routes[url]
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, dict):
            return FakeHTTPResponse(**payload, url=url)
        return FakeHTTPResponse(
            payload, url=url, mime=(
                "text/plain" if url.endswith("/robots.txt") else
                "text/html; charset=utf-8"
            ),
        )


def fake_opener(robots=ALLOWED, body=HTML, *, html_options=None):
    routes = {ROBOT_URL: robots}
    routes[URL] = dict(data=body, **(html_options or {}))
    return FakeOpener(routes)


def manual_capture(tmp_path, opener=None, *, sid=SID, note=POLICY_NOTE):
    out = tmp_path / "private_capture"
    fake = opener or fake_opener()
    sleeps = []
    manifest, audit = capture_pricing_html(
        [sid], out, policy_review_note=note,
        opener=fake, sleep_fn=sleeps.append,
        clock=lambda: datetime(2026, 11, 2, 19, 59, tzinfo=timezone.utc),
    )
    return out, manifest, audit, fake, sleeps


def test_no_network_plan_uses_exact_pinned_source():
    plan = capture_plan([SID])
    assert plan["sources"][0]["source_id"] == SID
    assert plan["sources"][0]["official_source_url"] == URL
    assert plan["sources"][0]["robots_url"] == ROBOT_URL
    assert plan["network_requests_performed"] == 0
    assert plan["captures_created"] == 0
    assert plan["publisher_policy_review_required"] is True
    assert plan["approved_for_advisor"] is False
    assert AGENT == USER_AGENT
    assert MIN_DELAY == DOWNLOAD_DELAY


def test_cli_plan_defaults_to_no_network(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["capture", "--source-ids", SID],
    )
    main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["sources"][0]["official_source_url"] == URL
    assert plan["network_requests_performed"] == 0
    assert not plan["approved_for_advisor"]


def test_manual_capture_writes_unmodified_html_and_p17b2_manifest(tmp_path):
    root, manifest, audit, fake, sleeps = manual_capture(tmp_path)
    assert root.is_dir()
    assert audit["network_requests_performed"] == 2
    assert audit["capture_source_count"] == 1
    assert audit["robots_checks"] == 1
    assert audit["publisher_policy_review_operator_attested"] is True
    assert audit["publisher_policy_independently_verified"] is False
    assert audit["advisor_fact_approvals"] == 0
    assert audit["scheduled_job_created"] is False
    assert [x["url"] for x in fake.requests] == [ROBOT_URL, URL]
    assert all(x["agent"] == USER_AGENT and x["method"] == "GET"
               for x in fake.requests)
    assert sleeps == [3]
    assert len(manifest["snapshots"]) == 1
    item = manifest["snapshots"][0]
    assert item["source_id"] == SID
    snap = item["snapshot"]
    raw = (root / snap["file"]).read_bytes()
    assert raw == HTML
    assert snap["sha256"] == hashlib.sha256(HTML).hexdigest()
    assert snap["request_url"] == snap["final_url"] == URL
    assert snap["media_type"] == "text/html"
    assert snap["capture_method"] == "static_html"
    assert snap["capture_origin_review_status"] == (
        "operator_supplied_unverified"
    )
    assert not manifest["approved_for_advisor"]
    assert json.loads((root / "frozen_snapshots.json").read_text()) == manifest
    assert json.loads((root / "capture_audit.json").read_text()) == audit
    assert oct(root.stat().st_mode & 0o777) == "0o700"
    assert all(oct(p.stat().st_mode & 0o777) == "0o600"
               for p in root.iterdir() if p.is_file())
    validate_snapshot_manifest(manifest)
    replay = replay_pricing_snapshots(manifest, root)
    assert replay["source_count"] == 1
    assert replay["sources"][0]["pricing_legend_backed_triplet_cells_split"] == 1
    assert replay["sources"][0]["observed_component_count"] == 3
    assert not replay["sources"][0]["approved_for_advisor"]
    assert replay["network_requests_performed"] == 0


@pytest.mark.parametrize("bad", [
    [],
    ["v0_pricing"],
    ["fireworks_ai_docs"],
    ["not_a_source"],
    ["https://docs.fireworks.ai/serverless/pricing"],
    [SID, SID],
    [x["id"] for x in load_sources() if x["category"] == "pricing"][:6],
])
def test_plan_rejects_unscoped_duplicate_or_blocked_source_ids(bad):
    with pytest.raises(ValueError):
        capture_plan(bad)


def test_publisher_policy_note_required_before_robots_or_html(tmp_path):
    op = fake_opener()
    for note in ("", "yes", "I have reviewed it."):
        with pytest.raises(ValueError, match="policy review"):
            capture_pricing_html(
                [SID], tmp_path / "secret", policy_review_note=note,
                opener=op, sleep_fn=lambda _: None,
            )
    assert op.requests == []
    assert not (tmp_path / "secret").exists()


def test_robots_disallow_is_hard_stop_before_original_html(tmp_path):
    op = fake_opener(robots=DENIED)
    with pytest.raises(ValueError, match="robots disallows"):
        capture_pricing_html(
            [SID], tmp_path / "secret",
            policy_review_note=POLICY_NOTE, opener=op,
            sleep_fn=lambda _: None,
        )
    assert [x["url"] for x in op.requests] == [ROBOT_URL]
    assert not (tmp_path / "secret").exists()


def test_robots_missing_or_unauthorized_is_not_assumed_allowed(tmp_path):
    for case in (
        urllib.error.HTTPError(ROBOT_URL, 404, "Missing", {}, None),
        dict(data=b"<html>blocked</html>", mime="text/html"),
        dict(data=b"User-agent: *\nDisallow: /\n", mime="text/plain"),
    ):
        op = fake_opener()
        op.routes[ROBOT_URL] = case
        with pytest.raises(ValueError):
            capture_pricing_html(
                [SID], tmp_path / "no_source",
                policy_review_note=POLICY_NOTE, opener=op,
                sleep_fn=lambda _: None,
            )
        assert not (tmp_path / "no_source").exists()
        assert len(op.requests) == 1


def test_robots_large_crawl_delay_fails_closed(tmp_path):
    op = fake_opener(robots=(
        b"User-agent: AgentFuseResearchBot\n"
        b"Crawl-delay: 45\nAllow: /\n"
    ))
    with pytest.raises(ValueError, match="crawl-delay"):
        capture_pricing_html(
            [SID], tmp_path / "secret",
            policy_review_note=POLICY_NOTE, opener=op,
            sleep_fn=lambda _: None,
        )
    assert len(op.requests) == 1


@pytest.mark.parametrize("html_options,error", [
    ({"mime": "application/json"}, "content type"),
    ({"mime": "text/html; charset=iso-8859-1"}, "Non-UTF-8"),
    ({"more_headers": {"Content-Encoding": "gzip"}}, "Compressed"),
    ({"more_headers": {"Content-Length": str(MAX_PAGE_BYTES + 1)}},
     "bounded byte size"),
    ({"final_url": "https://evil.invalid/secret"}, "Redirect"),
    ({"status": 301}, "non-200"),
    ({"status": 403}, "non-200"),
])
def test_bad_http_capture_is_rejected_and_private_files_rolled_back(
        tmp_path, html_options, error):
    op = fake_opener(html_options=html_options)
    with pytest.raises(ValueError, match=error):
        capture_pricing_html(
            [SID], tmp_path / "secret",
            policy_review_note=POLICY_NOTE, opener=op,
            sleep_fn=lambda _: None,
        )
    assert not (tmp_path / "secret").exists()
    assert len(op.requests) == 2


def test_invalid_utf8_page_is_not_silently_recoded(tmp_path):
    op = fake_opener(body=b"<html>\xffbad</html>")
    with pytest.raises(ValueError, match="UTF-8"):
        capture_pricing_html(
            [SID], tmp_path / "secret",
            policy_review_note=POLICY_NOTE, opener=op,
            sleep_fn=lambda _: None,
        )
    assert not (tmp_path / "secret").exists()


def test_robots_size_cap_stops_malformed_large_robots(tmp_path):
    op = fake_opener(robots=b"# " + b"X" * MAX_ROBOTS_BYTES)
    with pytest.raises(ValueError, match="bounded byte size"):
        capture_pricing_html(
            [SID], tmp_path / "secret",
            policy_review_note=POLICY_NOTE, opener=op,
            sleep_fn=lambda _: None,
        )


def test_existing_or_symlink_output_is_rejected_before_network(tmp_path):
    fake = fake_opener()
    target = tmp_path / "secret"
    target.mkdir()
    with pytest.raises(ValueError, match="fresh"):
        capture_pricing_html(
            [SID], target, policy_review_note=POLICY_NOTE,
            opener=fake, sleep_fn=lambda _: None,
        )
    assert fake.requests == []
    link = tmp_path / "shortcut"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="fresh"):
        capture_pricing_html(
            [SID], link, policy_review_note=POLICY_NOTE,
            opener=fake, sleep_fn=lambda _: None,
        )
    assert fake.requests == []


def test_fail_on_one_host_does_not_download_other_hosts(tmp_path):
    source_a = KNOWN["fireworks_ai_pricing"]
    source_b = KNOWN["gemini_api_pricing"]
    url_b = source_b["url"]
    rb = _robots_url(source_b)
    op = FakeOpener({
        ROBOT_URL: ALLOWED, rb: b"User-agent: *\nDisallow: /\n",
        URL: HTML, url_b: HTML,
    })
    with pytest.raises(ValueError, match="robots disallows"):
        capture_pricing_html(
            [source_a["id"], source_b["id"]],
            tmp_path / "secret",
            policy_review_note=POLICY_NOTE,
            opener=op, sleep_fn=lambda _: None,
        )
    assert [x["url"] for x in op.requests] == [ROBOT_URL, rb]
    assert not (tmp_path / "secret").exists()


def test_second_http_error_rolls_back_prior_successful_capture(tmp_path):
    source_b = KNOWN["gemini_api_pricing"]
    url_b = source_b["url"]
    rb = _robots_url(source_b)
    op = FakeOpener({
        ROBOT_URL: ALLOWED, rb: ALLOWED,
        URL: HTML,
        url_b: dict(data=HTML, status=403),
    })
    with pytest.raises(ValueError, match="non-200"):
        capture_pricing_html(
            [SID, source_b["id"]], tmp_path / "secret",
            policy_review_note=POLICY_NOTE,
            opener=op, sleep_fn=lambda _: None,
        )
    assert [x["url"] for x in op.requests] == [
        ROBOT_URL, rb, URL, url_b,
    ]
    assert not (tmp_path / "secret").exists()


def test_shared_robots_host_fetched_once_and_every_source_path_checked(tmp_path):
    ids = ["aws_bedrock_pricing", "aws_sagemaker_ai_pricing"]
    src_a, src_b = [KNOWN[s] for s in ids]
    url = _robots_url(src_a)
    assert url == _robots_url(src_b)
    op = FakeOpener({
        url: b"User-agent: *\nAllow: /\n",
        src_a["url"]: HTML,
        src_b["url"]: HTML,
    })
    sleeps = []
    manifest, audit = capture_pricing_html(
        ids, tmp_path / "private_batch",
        policy_review_note=POLICY_NOTE, opener=op,
        sleep_fn=sleeps.append,
        clock=lambda: datetime(2026, 11, 2, tzinfo=timezone.utc),
    )
    assert len(manifest["snapshots"]) == 2
    assert audit["robots_checks"] == 1
    assert audit["network_requests_performed"] == 3
    assert sleeps == [3, 3]
    assert [x["url"] for x in op.requests] == [
        url, src_a["url"], src_b["url"],
    ]
    assert not audit["approved_for_advisor"]


def test_shared_robots_host_checks_each_page_disallow_before_any_html(tmp_path):
    ids = ["aws_bedrock_pricing", "aws_sagemaker_ai_pricing"]
    src_a, src_b = [KNOWN[s] for s in ids]
    robots = (
        b"User-agent: *\n"
        b"Disallow: /sagemaker-ai/pricing/\n"
        b"Allow: /\n"
    )
    op = FakeOpener({
        _robots_url(src_a): robots,
        src_a["url"]: HTML,
        src_b["url"]: HTML,
    })
    with pytest.raises(ValueError, match="robots disallows"):
        capture_pricing_html(
            ids, tmp_path / "not_captured",
            policy_review_note=POLICY_NOTE, opener=op,
            sleep_fn=lambda _: None,
        )
    assert len(op.requests) == 1
    assert not (tmp_path / "not_captured").exists()


def test_redirect_handler_is_explicitly_disabled():
    assert NoRedirect().redirect_request(
        None, None, 301, "Moved", {},
        "https://evil.invalid/redirected",
    ) is None
