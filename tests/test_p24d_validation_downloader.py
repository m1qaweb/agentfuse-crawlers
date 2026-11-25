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


@pytest.mark.parametrize("robots", [False, True])
def test_existing_global_stop_holds_late_validation_admissions(monkeypatch, robots):
    src = source()
    mock_policy(monkeypatch, registry(src))
    spider = fake_spider(src)
    spider._agentfuse_validation_stop_reason = "agentfuse_validation_http_429"
    gate = ValidationDownloadGate(clock=lambda: NOW)
    req = _exact_robots(src) if robots else request(src)
    with pytest.raises(IgnoreRequest, match="validation_global_stop_requested"):
        gate.process_request(req, spider)
    assert req.meta[HOLD_META] == "validation_global_stop_requested"
    assert not gate._already_attempted
    assert not gate._robots_attempted


def test_global_validation_stop_latch_does_not_change_monitoring():
    src = source()
    spider = fake_spider(src, mode="monitor")
    spider._agentfuse_validation_stop_reason = "agentfuse_validation_http_429"
    gate = ValidationDownloadGate(clock=lambda: NOW)
    assert gate.process_request(request(src), spider) is None


# R2: actual Scrapy Requests/Responses, fictional reviewed access only.
# No download handler or external publisher is ever called.
def _contained_spider(monkeypatch):
    from agentfuse_crawlers.validation_containment import Containment
    rows = [source(sid) for sid in (
        "aws_bedrock_docs", "aws_sagemaker_ai_docs", "openai_api_docs",
        "anthropic_api_docs", "mistral_docs", "qdrant_docs")]
    access = registry(rows[0], scopes=("bulk_validation",))
    for src in rows[1:]:
        access["reviews"].update(registry(src, scopes=("bulk_validation",))["reviews"])
    mock_policy(monkeypatch, access)
    spider = fake_spider(rows[0], single=False, selected=rows,
                         permitted={s["id"] for s in rows})
    spider.bulk_max_primary_requests = len(rows)
    spider._agentfuse_containment = Containment(spider, load_sources())
    return spider, rows, spider._agentfuse_containment


def test_r2_isolated_rate_limit_blocks_group_before_item_pipeline(monkeypatch):
    from scrapy.http import Response
    from agentfuse_crawlers.validation_containment import GROUP_HOLD
    spider, rows, state = _contained_spider(monkeypatch)
    first, sibling, unrelated = rows[:3]
    gate = ValidationDownloadGate(clock=lambda: NOW)
    req = request(first)
    gate.process_request(req, spider)
    response = Response(req.url, status=429)
    assert gate.process_response(req, response, spider) is response
    assert state.global_reason is None
    assert state.by_source[first["id"]] == state.by_source[sibling["id"]]
    for blocked in (request(sibling), _exact_robots(sibling)):
        with pytest.raises(IgnoreRequest, match=GROUP_HOLD):
            gate.process_request(blocked, spider)
        assert blocked.meta[HOLD_META] == GROUP_HOLD
    assert gate._already_attempted == {first["id"]}
    robots = _exact_robots(unrelated)
    gate.process_request(robots, spider)
    gate.process_response(robots, Response(robots.url, status=404), spider)
    allowed = request(unrelated)
    gate.process_request(allowed, spider)
    gate.process_response(allowed, Response(allowed.url, status=200), spider)
    assert gate._already_attempted == {first["id"], unrelated["id"]}
    assert state.global_reason is None and not state.active


def test_r2_accounts_for_already_admitted_sibling_response(monkeypatch):
    from scrapy.http import Response
    spider, rows, state = _contained_spider(monkeypatch)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    a, b = [request(src) for src in rows[:2]]
    gate.process_request(a, spider)
    gate.process_request(b, spider)
    gate.process_response(a, Response(a.url, status=403), spider)
    assert state.pending_at_hold == {rows[1]["id"]}
    assert gate.process_response(b, Response(b.url, status=200), spider).status == 200
    assert not state.active
    assert state.pending_at_hold == {rows[1]["id"]}


def test_r2_third_distinct_group_is_systemic(monkeypatch):
    from scrapy.http import Response
    from agentfuse_crawlers.validation_containment import SYSTEMIC_STOP, GLOBAL_HOLD
    spider, rows, state = _contained_spider(monkeypatch)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    for src, code in zip((rows[0], rows[2], rows[3]), (403, 429, 302)):
        req = request(src)
        gate.process_request(req, spider)
        gate.process_response(req, Response(req.url, status=code), spider)
    assert state.global_reason == SYSTEMIC_STOP
    for req in (request(rows[4]), _exact_robots(rows[4])):
        with pytest.raises(IgnoreRequest, match=GLOBAL_HOLD):
            gate.process_request(req, spider)


@pytest.mark.parametrize("status,body", [
    (403, b"User-agent: *"), (429, b"User-agent: *"), (503, b"User-agent: *"),
    (302, b"User-agent: *"), (200, b"<html>error</html>"),
    (200, b"User-agent: *\nCrawl-delay: 5\n"),
])
def test_r2_unresolved_robots_blocks_linked_group_without_html(monkeypatch, status, body):
    from scrapy.http import Response
    from agentfuse_crawlers.validation_containment import GROUP_HOLD
    spider, rows, state = _contained_spider(monkeypatch)
    src, sibling, unrelated = rows[:3]
    gate = ValidationDownloadGate(clock=lambda: NOW)
    mw, _ = _robots_middleware()
    mw.crawler.spider = spider
    lookup = _exact_robots(src)
    gate.process_request(lookup, spider)
    resp = Response(lookup.url, status=status, body=body,
                    headers={b"Content-Type": b"text/plain"})
    gate.process_response(lookup, resp, spider)
    with pytest.raises(IgnoreRequest):
        asyncio.run(mw._parse_robots(resp, urlsplit(src["url"]).netloc, request(src)))
    with pytest.raises(IgnoreRequest, match=GROUP_HOLD):
        mw.process_request_2(None, request(sibling))
    assert not gate._already_attempted
    assert state.global_reason is None
    gate.process_request(request(unrelated), spider)


@pytest.mark.parametrize("status", [404, 410])
def test_r2_genuine_missing_robots_does_not_hold_group(monkeypatch, status):
    from scrapy.http import Response
    spider, rows, state = _contained_spider(monkeypatch)
    mw, base = _robots_middleware()
    mw.crawler.spider = spider
    parsed = []

    async def parse(self, response, netloc, req):
        parsed.append(response.body)

    monkeypatch.setattr(base, "_parse_robots", parse)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    lookup = _exact_robots(rows[0])
    gate.process_request(lookup, spider)
    resp = Response(lookup.url, status=status, body=b"missing",
                    headers={b"Content-Type": b"text/html"})
    gate.process_response(lookup, resp, spider)
    asyncio.run(mw._parse_robots(resp, urlsplit(rows[0]["url"]).netloc, request(rows[0])))
    assert parsed == [b""]
    assert not state.blocked and state.global_reason is None


@pytest.mark.parametrize("robots", [True, False])
def test_r2_proxy_authentication_failure_is_immediately_global(monkeypatch, robots):
    from scrapy.http import Response
    from agentfuse_crawlers.validation_containment import PROXY_STOP, GLOBAL_HOLD
    spider, rows, state = _contained_spider(monkeypatch)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    req = _exact_robots(rows[0]) if robots else request(rows[0])
    gate.process_request(req, spider)
    gate.process_response(req, Response(req.url, status=407), spider)
    assert state.global_reason == PROXY_STOP
    with pytest.raises(IgnoreRequest, match=GLOBAL_HOLD):
        gate.process_request(request(rows[2]), spider)


def test_r2_pre_robots_guard_rejects_wrong_method_before_lookup(monkeypatch):
    from agentfuse_crawlers.validation_downloader import ValidationPreRobotsGuard
    from agentfuse_crawlers.validation_containment import INTEGRITY_STOP
    spider, rows, state = _contained_spider(monkeypatch)
    early = ValidationPreRobotsGuard()
    early.gate._clock = lambda: NOW
    with pytest.raises(IgnoreRequest, match="validation_pre_robots_source_not_exact"):
        early.process_request(request(rows[0], method="POST"), spider)
    assert state.global_reason == INTEGRITY_STOP


def test_r2_expired_bulk_plan_stops_remaining_admissions(monkeypatch):
    from agentfuse_crawlers.validation_containment import INTEGRITY_STOP, GLOBAL_HOLD
    spider, rows, state = _contained_spider(monkeypatch)
    spider.bulk_plan_expires_at_utc = (NOW - timedelta(seconds=1)).isoformat()
    gate = ValidationDownloadGate(clock=lambda: NOW)
    with pytest.raises(IgnoreRequest, match="download_time_bulk_plan_missing_or_expired"):
        gate.process_request(request(rows[0]), spider)
    assert state.global_reason == INTEGRITY_STOP
    with pytest.raises(IgnoreRequest, match=GLOBAL_HOLD):
        gate.process_request(request(rows[2]), spider)


def test_r2_duplicate_source_attempt_is_systemic(monkeypatch):
    from agentfuse_crawlers.validation_containment import INTEGRITY_STOP
    spider, rows, state = _contained_spider(monkeypatch)
    gate = ValidationDownloadGate(clock=lambda: NOW)
    gate.process_request(request(rows[0]), spider)
    with pytest.raises(IgnoreRequest, match="duplicate_validation_source_get"):
        gate.process_request(request(rows[0]), spider)
    assert state.global_reason == INTEGRITY_STOP
