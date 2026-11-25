"""P24D: offline-only Scrapy source download boundary regression tests.

All positive source reviews in this file are invented and IN MEMORY. They do
not authenticate publisher permission and are never installed in the package.
All Request/HtmlResponse objects are constructed locally: zero network jobs.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from scrapy import Request
from scrapy.exceptions import IgnoreRequest

import agentfuse_crawlers.validation_access as policy
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.spiders.official import DocumentationSpider
from agentfuse_crawlers.validation_downloader import (
    HOLD_META, ValidationDownloadGate, ValidationRobotsMiddleware, ROBOTS_FAILURE_META,
)

NOW = datetime.now(timezone.utc)
NOTE = (
    "SYNTHETIC TEST ONLY. A human has NOT checked ownership, terms, robots, "
    "commercial extraction, publisher HTML retention or per-source cadence. "
    "No publisher permission or job authorization is granted by this test."
)


def source(sid="openai_api_docs"):
    return next(s for s in load_sources() if s["id"] == sid)


def registry(src, scopes=("single_validation",), expiry=None):
    host = urlsplit(src["url"]).hostname
    return {
        "schema_version": policy.SCHEMA,
        "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {
            src["id"]: {
                "source_url": src["url"],
                "category": src["category"],
                "decision": "allowed_reviewed",
                "scopes": list(scopes),
                "reviewed_by": "Fictional Synthetic Reviewer",
                "reviewed_at_utc": (NOW - timedelta(minutes=10)).isoformat(),
                "expires_at_utc": (expiry or NOW + timedelta(days=5)).isoformat(),
                "ownership_evidence_url": src["url"],
                "publisher_access_policy_url": "https://" + host + "/terms",
                "robots_url": "https://" + host + "/robots.txt",
                "publisher_terms_reviewed": True,
                "robots_reviewed": True,
                "private_retention_reviewed": True,
                "evidence_note": NOTE,
            },
        },
    }


def mock_policy(monkeypatch, record):
    policy.validate_access_registry(record, now=NOW)
    monkeypatch.setattr(policy, "load_access_registry", lambda: record)


def request(src, *, url=None, method="GET", source_attached=True, meta=None):
    return Request(
        url or src["url"],
        method=method,
        cb_kwargs={"source": src} if source_attached else {},
        meta=meta or {
            "dont_redirect": True,
            "dont_retry": True,
            "handle_httpstatus_all": True,
        },
    )


def fake_spider(src, *, mode="validation", single=True, expires=None,
                permitted=None, selected=None, plan_id="synthetic_bounded_plan"):
    return SimpleNamespace(
        category=src["category"],
        collection_mode=mode,
        selected=[src] if selected is None else selected,
        single_validation_required=single,
        bulk_validation_required=not single,
        bulk_plan_id=plan_id,
        bulk_authorized_ids=set([src["id"]] if permitted is None else permitted),
        bulk_plan_expires_at_utc=(expires or (
            NOW + timedelta(minutes=5)
        ).isoformat()),
    )


async def collect(spider):
    return [row async for row in spider.start()]


def test_current_synthetic_single_source_request_allowed_only_once(monkeypatch):
    src = source()
    mock_policy(monkeypatch, registry(src))
    spider = DocumentationSpider(cohort="all", source_ids=src["id"])
    outputs = asyncio.run(collect(spider))
    assert len(outputs) == 1 and isinstance(outputs[0], Request)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    assert gate.process_request(outputs[0], spider) is None
    with pytest.raises(IgnoreRequest, match="duplicate_validation_source_get"):
        gate.process_request(outputs[0].copy(), spider)
    assert outputs[0].meta.get(HOLD_META) is None


def test_expiry_between_spider_start_and_download_is_held_as_item(monkeypatch):
    src = source()
    expiry = NOW + timedelta(hours=1)
    mock_policy(monkeypatch, registry(src, expiry=expiry))
    spider = DocumentationSpider(cohort="all", source_ids=src["id"])
    outputs = asyncio.run(collect(spider))
    assert len(outputs) == 1 and isinstance(outputs[0], Request)
    req = outputs[0]
    # The spider was allowed to yield the request; the publisher record then
    # expires while the request remains queued for the downloader.
    gate = ValidationDownloadGate(clock=lambda: NOW + timedelta(hours=2))
    with pytest.raises(IgnoreRequest, match="download_time_single_source_policy_review_expired"):
        gate.process_request(req, spider)
    assert req.meta[HOLD_META] == "download_time_single_source_policy_review_expired"

    # The actual spider errback preserves exactly one status Item, without
    # claiming HTTP status/HTML or an approved vendor fact.
    failure = SimpleNamespace(
        type=IgnoreRequest, value=IgnoreRequest(req.meta[HOLD_META]),
        request=req,
    )
    items = list(spider.record_failure(failure))
    assert len(items) == 1
    assert items[0]["status"] == "source_single_validation_not_approved"
    assert items[0]["policy_observation"] == (
        "not_fetched_by_downloader_time_access_gate"
    )
    assert items[0]["http_status"] is None
    assert items[0]["error"] == req.meta[HOLD_META]
    assert items[0]["approved_for_advisor"] is False


@pytest.mark.parametrize("case,expected", [
    ("changed_path", "validation_source_url_or_method_not_exact"),
    ("post", "validation_source_url_or_method_not_exact"),
    ("redirect_enabled", "validation_source_url_or_method_not_exact"),
    ("retry_enabled", "validation_source_url_or_method_not_exact"),
    ("missing_source", "validation_request_missing_exact_source"),
    ("different_selected", "validation_source_not_in_pinned_selection"),
    ("wrong_category", "validation_source_not_in_pinned_selection"),
    ("unscoped", "validation_scope_not_explicitly_authorized"),
    ("publisher_skips_robots", "publisher_request_cannot_skip_robots"),
])
def test_unreviewed_or_out_of_scope_downloads_fail_closed(
        monkeypatch, case, expected):
    src = source()
    mock_policy(monkeypatch, registry(src))
    spider = fake_spider(src)
    req = request(src)
    if case == "changed_path":
        req = request(src, url=src["url"].rstrip("/") + "/unreviewed")
    elif case == "post":
        req = request(src, method="POST")
    elif case == "redirect_enabled":
        req = request(src, meta={"dont_redirect": False, "dont_retry": True})
    elif case == "retry_enabled":
        req = request(src, meta={"dont_redirect": True, "dont_retry": False})
    elif case == "missing_source":
        req = request(src, source_attached=False)
    elif case == "different_selected":
        spider.selected = [source("anthropic_api_docs")]
    elif case == "wrong_category":
        spider.category = "pricing"
    elif case == "unscoped":
        spider.single_validation_required = False
        spider.bulk_validation_required = False
    elif case == "publisher_skips_robots":
        req = request(src, meta={"dont_obey_robotstxt": True})
    gate = ValidationDownloadGate(clock=lambda: NOW)
    with pytest.raises(IgnoreRequest, match=expected):
        gate.process_request(req, spider)
    assert req.meta[HOLD_META] == expected


def test_bulk_scope_denied_when_plan_expires_or_source_missing(monkeypatch):
    src = source()
    mock_policy(monkeypatch, registry(src, scopes=("bulk_validation",)))
    for opts in (
        {"expires": (NOW - timedelta(seconds=1)).isoformat()},
        {"plan_id": ""},
        {"permitted": set()},
        {"expires": "2026-11-14"},  # Naive timestamp is not approval.
    ):
        spider = fake_spider(src, single=False, **opts)
        gate = ValidationDownloadGate(clock=lambda: NOW)
        req = request(src)
        with pytest.raises(IgnoreRequest, match="download_time_bulk_plan_missing_or_expired"):
            gate.process_request(req, spider)
        assert req.meta[HOLD_META] == "download_time_bulk_plan_missing_or_expired"


def test_current_synthetic_bulk_scope_can_pass_only_once(monkeypatch):
    src = source()
    mock_policy(monkeypatch, registry(src, scopes=("bulk_validation",)))
    spider = fake_spider(src, single=False)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    assert gate.process_request(request(src), spider) is None
    with pytest.raises(IgnoreRequest, match="duplicate_validation_source_get"):
        gate.process_request(request(src), spider)


def test_single_scope_review_does_not_grant_bulk_at_download(monkeypatch):
    src = source()
    mock_policy(monkeypatch, registry(src, scopes=("single_validation",)))
    gate = ValidationDownloadGate(clock=lambda: NOW)
    with pytest.raises(IgnoreRequest, match="download_time_bulk_source_review_scope_not_approved"):
        gate.process_request(request(src), fake_spider(src, single=False))


def test_unreviewed_registry_never_allows_manually_forged_request(monkeypatch):
    src = source()
    empty = {
        "schema_version": policy.SCHEMA,
        "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {},
    }
    monkeypatch.setattr(policy, "load_access_registry", lambda: empty)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    with pytest.raises(IgnoreRequest, match="download_time_single_source_policy_not_reviewed"):
        gate.process_request(request(src), fake_spider(src))


def test_internal_robots_lookup_and_monitoring_remain_separate(monkeypatch):
    src = source()
    mock_policy(monkeypatch, registry(src))
    gate = ValidationDownloadGate(clock=lambda: NOW)
    host = urlsplit(src["url"]).hostname
    robots = Request(
        "https://" + host + "/robots.txt",
        meta={"dont_obey_robotstxt": True},
    )
    assert gate.process_request(robots, fake_spider(src)) is None
    assert robots.meta["dont_redirect"] is True
    assert robots.meta["dont_retry"] is True
    for bad in (
        "https://unreviewed.invalid/robots.txt",
        "https://" + host + "/not-a-robots-file",
        "https://" + host + "/robots.txt?bypass=yes",
    ):
        with pytest.raises(IgnoreRequest, match="unreviewed_robots_lookup_target"):
            gate.process_request(
                Request(bad, meta={"dont_obey_robotstxt": True}),
                fake_spider(src),
            )
    # The existing Scrapy ROBOTSTXT_OBEY=True setting still governs robots.
    monitor = fake_spider(src, mode="monitor")
    assert gate.process_request(request(src, source_attached=False), monitor) is None


def test_strict_robots_middleware_registered_before_source_gate():
    from scrapy.utils.project import get_project_settings
    from agentfuse_crawlers import settings as app_settings

    spider_mw = app_settings.DOWNLOADER_MIDDLEWARES
    assert spider_mw == {
        "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
        "agentfuse_crawlers.validation_downloader.ValidationRobotsMiddleware": 100,
        "agentfuse_crawlers.validation_downloader.ValidationDownloadGate": 110,
    }
    project = get_project_settings()
    assert project.getbool("ROBOTSTXT_OBEY")



def _robots_middleware(mode="validation"):
    from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
    from unittest.mock import Mock
    mw = object.__new__(ValidationRobotsMiddleware)
    mw.crawler = SimpleNamespace(spider=SimpleNamespace(collection_mode=mode))
    mw._stats = Mock()
    return mw, RobotsTxtMiddleware


@pytest.mark.parametrize("status", [401, 403, 429, 503, 302])
def test_runtime_robots_errors_never_parse_as_empty_allow(monkeypatch, status):
    from scrapy.http import Response
    mw, base = _robots_middleware()
    async def forbidden_parse(*args):
        pytest.fail("An unresolved robots response reached Scrapy's parser")
    monkeypatch.setattr(base, "_parse_robots", forbidden_parse)
    src = source()
    req = request(src)
    host = urlsplit(src["url"]).netloc
    resp = Response("https://" + host + "/robots.txt", status=status,
                    headers={b"Content-Type": b"text/plain"}, body=b"Access denied")
    with pytest.raises(IgnoreRequest, match="robots_http_status_unresolved"):
        asyncio.run(mw._parse_robots(resp, host, req))
    with pytest.raises(IgnoreRequest, match="lookup or parse unresolved"):
        mw.process_request_2(None, req)
    assert req.meta[ROBOTS_FAILURE_META] == "robots_lookup_or_parse_unresolved"


def test_valid_rules_and_missing_robots_reach_real_parser_boundary(monkeypatch):
    from scrapy.http import Response
    mw, base = _robots_middleware()
    parsed = []
    async def parse(self, response, netloc, request):
        parsed.append((response.status, response.body))
    monkeypatch.setattr(base, "_parse_robots", parse)
    src = source()
    req = request(src)
    host = urlsplit(src["url"]).netloc
    url = "https://" + host + "/robots.txt"
    rules = b"User-agent: *\nDisallow: /private\n"
    asyncio.run(mw._parse_robots(Response(url, status=200,
                headers={b"Content-Type": b"text/plain"}, body=rules), host, req))
    asyncio.run(mw._parse_robots(Response(url, status=404,
                headers={b"Content-Type": b"text/html"}, body=b"Not found"), host, req))
    assert parsed == [(200, rules), (404, b"")]


def test_robots_parser_failure_is_held_in_validation_but_monitor_unchanged(monkeypatch):
    mw, base = _robots_middleware()
    calls = []
    monkeypatch.setattr(base, "process_request_2", lambda self, rp, req: calls.append(rp))
    req = request(source())
    with pytest.raises(IgnoreRequest):
        mw.process_request_2(None, req)
    assert not calls
    parser = object()
    assert mw.process_request_2(parser, request(source())) is None
    monitor, _ = _robots_middleware("monitor")
    assert monitor.process_request_2(None, request(source())) is None
    assert calls == [parser, None]


def _exact_robots(src, *, url=None):
    return Request(url or ("https://" + urlsplit(src["url"]).netloc + "/robots.txt"),
                   meta={"dont_obey_robotstxt": True})


@pytest.mark.parametrize("opts", [
    {"permitted": set()},
    {"plan_id": ""},
    {"expires": "2026-11-14"},
    {"expires": (NOW - timedelta(seconds=1)).isoformat()},
])
def test_robots_requires_current_bulk_plan(monkeypatch, opts):
    src = source()
    mock_policy(monkeypatch, registry(src, scopes=("bulk_validation",)))
    gate = ValidationDownloadGate(clock=lambda: NOW)
    req = _exact_robots(src)
    with pytest.raises(IgnoreRequest, match="robots_origin_no_current_authorized_source"):
        gate.process_request(req, fake_spider(src, single=False, **opts))
    assert req.meta[HOLD_META] == "robots_origin_no_current_authorized_source"


def test_robots_requires_current_review_even_for_selected_origin(monkeypatch):
    src = source()
    empty = registry(src)
    empty["reviews"] = {}
    mock_policy(monkeypatch, empty)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    with pytest.raises(IgnoreRequest, match="robots_origin_no_current_authorized_source"):
        gate.process_request(_exact_robots(src), fake_spider(src))


def test_robots_cannot_start_after_source_review_expires(monkeypatch):
    src = source()
    mock_policy(monkeypatch, registry(src, expiry=NOW + timedelta(hours=1)))
    gate = ValidationDownloadGate(clock=lambda: NOW + timedelta(hours=2))
    with pytest.raises(IgnoreRequest, match="robots_origin_no_current_authorized_source"):
        gate.process_request(_exact_robots(src), fake_spider(src))


def test_robots_origin_can_be_shared_only_by_current_authorized_source(monkeypatch):
    held = source("aws_bedrock_docs")
    allowed = source("aws_sagemaker_ai_docs")
    assert urlsplit(held["url"]).netloc == urlsplit(allowed["url"]).netloc
    mock_policy(monkeypatch, registry(allowed, scopes=("bulk_validation",)))
    spider = fake_spider(held, single=False, selected=[held, allowed],
                         permitted={allowed["id"]})
    gate = ValidationDownloadGate(clock=lambda: NOW)
    assert gate.process_request(_exact_robots(held), spider) is None
    with pytest.raises(IgnoreRequest, match="duplicate_validation_robots_get"):
        gate.process_request(_exact_robots(allowed), spider)
    # A robots lookup consumes no primary source attempt.
    assert gate.process_request(request(allowed), spider) is None
    with pytest.raises(IgnoreRequest, match="download_time_bulk_source_policy_not_reviewed"):
        gate.process_request(request(held), spider)


def test_robots_rejects_noncanonical_origin(monkeypatch):
    src = source()
    mock_policy(monkeypatch, registry(src))
    gate = ValidationDownloadGate(clock=lambda: NOW)
    url = "https://" + urlsplit(src["url"]).netloc + ":443/robots.txt"
    # Scrapy may normalize an explicit default port away. Use an alternate
    # port to test the actual non-manifest origin, independent of normalization.
    url = url.replace(":443/", ":444/")
    with pytest.raises(IgnoreRequest, match="unreviewed_robots_lookup_target"):
        gate.process_request(_exact_robots(src, url=url), fake_spider(src))
