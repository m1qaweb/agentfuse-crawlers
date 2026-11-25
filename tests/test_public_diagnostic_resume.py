"""Nov 25 real-campaign shape regressions, using only synthetic responses.

The descriptor carries private export hashes and public manifest IDs, not
publisher page bodies or asserted permission. All tests below are offline.
"""
import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from scrapy import Request
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse

from agentfuse_crawlers import public_diagnostic as public
from agentfuse_crawlers import validation_access as policy
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.spiders import official
from agentfuse_crawlers.validation_containment import (
    Containment, GLOBAL_HOLD, GROUP_HOLD, INTEGRITY_STOP, ORDINARY_REDIRECT,
    PROXY_STOP, REDIRECT_BARRIER, SYSTEMIC_STOP, TRANSPORT_STOP, group_index,
    ordinary_redirect_target,
)
from agentfuse_crawlers.validation_downloader import ValidationDownloadGate, ValidationPreRobotsGuard


def scope_clock():
    scope = public.load_public_diagnostic_scope()
    return scope, policy._utc(scope["observed_at_utc"]) + timedelta(hours=1)


def spider_at(monkeypatch, *, resume=True, **kwargs):
    scope, now = scope_clock()
    monkeypatch.setattr(official, "authorize_public_diagnostic",
                        lambda **kw: public.authorize_public_diagnostic(**kw, now=now))
    args = dict(cohort="all", collection_mode="validation",
                confirm_full_inventory=public.PUBLIC_RESUME if resume else public.PUBLIC_DIAGNOSTIC)
    args.update(kwargs)
    spider = official.DocumentationSpider(**args)
    return spider, now


def start_rows(spider):
    async def collect():
        return [row async for row in spider.start()]
    return asyncio.run(collect())


def test_resume_is_exact_manifest_order_and_never_repeats_the_ten_attempts_or_prior_holds(monkeypatch):
    scope, now = scope_clock()
    descriptor = public.load_public_diagnostic_resume(scope)
    groups, _ = group_index(load_sources())
    rows = select_sources("documentation", "all")
    original = [s["id"] for s in rows if s["id"] in scope["source_ids"]]
    prior = set(descriptor["prior_attempted_ids"])
    held = set(descriptor["prior_held_groups"])
    expected = [sid for sid in original if sid not in prior and groups[sid] not in held]
    assert len(original) == 123
    assert len(prior) == 10 and len(held) == 22
    assert len(expected) == 96 and expected == descriptor["source_ids"]
    assert policy.digest(expected) == "cd73c9590f4cb3e6250d9df470eef2d253ce7447f1bed6cf6d2a942ee1595145"
    assert "stackblitz_docs" in expected  # global hold, no observed primary response
    assert sum(sid not in prior and groups[sid] in held for sid in original) == 17
    spider, now = spider_at(monkeypatch)
    result = start_rows(spider)
    requests = [x for x in result if isinstance(x, Request)]
    items = {x["source_id"]: x for x in result if not isinstance(x, Request)}
    assert len(result) == 194 and len(requests) == 96 and len(items) == 98
    assert [x.cb_kwargs["source"]["id"] for x in requests] == expected
    assert len({urlsplit(x.url).netloc for x in requests}) == 95
    assert spider.validation_scope == public.PUBLIC_RESUME
    assert spider.bulk_max_primary_requests == 96
    assert spider.bulk_max_redirects_per_source == 0
    assert all(x.url == x.cb_kwargs["source"]["url"] and x.method == "GET"
               and x.meta["dont_retry"] and x.meta["dont_redirect"] for x in requests)
    assert all(items[sid]["error"] == "public_diagnostic_resume_previously_attempted"
               and items[sid]["http_status"] is None for sid in prior)
    assert all(items[sid]["error"] == "public_diagnostic_resume_prior_publisher_hold"
               for sid in original if sid not in prior and groups[sid] in held)
    assert all(x["approved_for_advisor"] is False
               and x["public_diagnostic_publisher_rights_independently_verified"] is False
               and x["bulk_source_authorized_by_reviewed_plan"] is False
               and x["public_diagnostic_resume_selection_sha256"] == descriptor["selection_sha256"]
               and x["public_diagnostic_resume_candidate_count"] == 96
               and x["public_diagnostic_resume_prior_job_ids"] == descriptor["prior_job_ids"]
               for x in items.values())
    pre = ValidationPreRobotsGuard()
    pre.gate._clock = lambda: now
    gate = ValidationDownloadGate(clock=lambda: now)
    # All 96 real Request objects pass exact admission, without I/O.
    for req in requests:
        assert pre.process_request(req, spider) is None
        assert gate.process_request(req, spider) is None
        assert gate.process_response(req, HtmlResponse(req.url, status=200, request=req), spider).status == 200
    assert len(gate._already_attempted) == 96
    assert not spider._agentfuse_containment.global_reason
    with pytest.raises(IgnoreRequest, match="duplicate_validation_source_get"):
        gate.process_request(requests[0], spider)


@pytest.mark.parametrize("sid", ["deepseek_docs", "replit_docs", "openai_api_docs"])
@pytest.mark.parametrize("before_robots", [True, False])
def test_resume_exclusions_are_rechecked_in_both_download_gates(monkeypatch, sid, before_robots):
    spider, now = spider_at(monkeypatch)
    source = next(s for s in spider.selected if s["id"] == sid)
    request = Request(source["url"], cb_kwargs={"source": source},
                      meta={"dont_retry": True, "dont_redirect": True})
    gate = ValidationDownloadGate(clock=lambda: now)
    if before_robots:
        pre = ValidationPreRobotsGuard()
        pre.gate = gate
        check = pre.process_request
    else:
        check = gate.process_request
    with pytest.raises(IgnoreRequest):
        check(request, spider)
    assert not gate._already_attempted
    assert spider._agentfuse_containment.global_reason == INTEGRITY_STOP


def test_resume_cannot_widen_and_expiry_is_original(monkeypatch):
    scope, now = scope_clock()
    d = public.load_public_diagnostic_resume(scope)
    rows = select_sources("documentation", "all")
    _, before = public.authorize_public_diagnostic(selected=rows, category="documentation",
                                                   resume=True, now=now)
    groups, _ = group_index(load_sources())
    group = groups[d["source_ids"][0]]
    _, after = public.authorize_public_diagnostic(selected=rows, category="documentation",
                                                  resume=True, held_groups=group, now=now)
    assert after["authorized_source_ids"] < before["authorized_source_ids"]
    assert all(groups[sid] != group for sid in after["authorized_source_ids"])
    assert after["resume_selection_sha256"] != before["resume_selection_sha256"]
    assert before["plan_expires_at_utc"] == after["plan_expires_at_utc"] == scope["expires_at_utc"]
    with pytest.raises(ValueError, match="Unknown held publisher group"):
        public.authorize_public_diagnostic(selected=rows, category="documentation",
                                           resume=True, held_groups="unknown-group", now=now)
    with pytest.raises(ValueError, match="not current"):
        public.authorize_public_diagnostic(selected=rows, category="documentation",
                                           resume=True, now=policy._utc(scope["expires_at_utc"]))
    with pytest.raises(ValueError, match="documentation only"):
        public.authorize_public_diagnostic(selected=select_sources("pricing", "all"),
                                           category="pricing", resume=True, now=now)


@pytest.mark.parametrize("mutation", ["widen", "reorder", "duplicate", "hold", "digest"])
def test_resume_descriptor_is_pinned(monkeypatch, mutation):
    scope, _ = scope_clock()
    d = deepcopy(public.load_public_diagnostic_resume(scope))
    if mutation == "widen":
        d["source_ids"].append("deepseek_docs")
    elif mutation == "reorder":
        d["source_ids"].reverse()
    elif mutation == "duplicate":
        d["source_ids"][0] = d["source_ids"][1]
    elif mutation == "hold":
        d["prior_held_groups"].pop()
    else:
        d["prior_export_sha256"]["items_official_pricing_18.json"] = "0" * 64
    fake = SimpleNamespace(joinpath=lambda _: SimpleNamespace(read_text=lambda **_: json.dumps(d)))
    monkeypatch.setattr(public, "files", lambda _: fake)
    with pytest.raises(ValueError, match="descriptor integrity mismatch"):
        public.load_public_diagnostic_resume(scope)


@pytest.mark.parametrize("kwargs", [
    {"collection_mode": "monitor"}, {"cohort": "proven"}, {"source_ids": "xai_docs"},
    {"limit": "1"}, {"offset": "1"}, {"bulk_run_plan_id": "unrelated_plan"},
    {"expected_bulk_plan_sha256": "0" * 64}, {"expected_deployment_package_sha256": "0" * 64},
])
def test_resume_is_not_a_generic_access_mode(kwargs):
    args = dict(cohort="all", confirm_full_inventory=public.PUBLIC_RESUME)
    args.update(kwargs)
    with pytest.raises(ValueError):
        official.DocumentationSpider(**args)


@pytest.mark.parametrize("cls", [official.PricingSpider, official.ChangelogSpider])
def test_resume_never_admits_a_non_documentation_spider(cls):
    with pytest.raises(ValueError, match="documentation only"):
        cls(cohort="all", confirm_full_inventory=public.PUBLIC_RESUME)


def test_resume_respects_a_new_negative_review(monkeypatch):
    scope, now = scope_clock()
    d = public.load_public_diagnostic_resume(scope)
    source = next(s for s in load_sources() if s["id"] == d["source_ids"][0])
    registry = {
        "schema_version": policy.SCHEMA, "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed", "reviews": {source["id"]: {
            "source_url": source["url"], "category": source["category"],
            "decision": "deferred", "scopes": [], "reviewed_by": "Synthetic test reviewer",
            "reviewed_at_utc": (now - timedelta(minutes=10)).isoformat(),
            "expires_at_utc": (now + timedelta(days=1)).isoformat(),
            "ownership_evidence_url": None, "publisher_access_policy_url": None,
            "robots_url": None, "publisher_terms_reviewed": False,
            "robots_reviewed": False, "private_retention_reviewed": False,
            "evidence_note": "Synthetic negative test record only, never installed or actual permission.",
        }},
    }
    policy.validate_access_registry(registry, now=now)
    monkeypatch.setattr(policy, "load_access_registry", lambda: registry)
    _, decision = public.authorize_public_diagnostic(
        selected=select_sources("documentation", "all"), category="documentation", resume=True, now=now)
    groups, _ = group_index(load_sources())
    assert all(groups[sid] != groups[source["id"]] for sid in decision["authorized_source_ids"])


def test_real_job40_redirect_sequence_does_not_stop_other_publishers(monkeypatch):
    spider, now = spider_at(monkeypatch, resume=False)
    requests = {x.cb_kwargs["source"]["id"]: x for x in start_rows(spider) if isinstance(x, Request)}
    gate = ValidationDownloadGate(clock=lambda: now)
    state = spider._agentfuse_containment
    for sid in ("google_antigravity_docs", "deepseek_docs", "chutes_ai_docs",
                "cloudinary_ai_docs", "ibm_watsonx_ai_docs", "groqcloud_docs"):
        req = requests[sid]
        gate.process_request(req, spider)
        gate.process_response(req, HtmlResponse(req.url, status=200, request=req), spider)
        state.annotate({"source_id": sid, "http_status": 200, "status": "needs_review"})
    moves = [
        ("hume_ai_docs", 307, "https://dev.hume.ai/audio-decisions/docs/overview"),
        ("writer_ai_studio_docs", 308, "https://dev.writer.com/home/introduction"),
        ("adobe_firefly_services_docs", 301, "https://developer.adobe.com/firefly-services/docs/guides/"),
        ("ideogram_api_docs", 307, "https://developer.ideogram.ai/ideogram-api/api-overview"),
    ]
    # The fourth redirect was already admitted when the third arrived in
    # job 40. Exercise the actual gate and parser, then duplicate Item
    # observation (the coverage signal) without following any destination.
    for i, (sid, status, target) in enumerate(moves):
        req = requests[sid]
        if i != 3:
            gate.process_request(req, spider)
        if i == 2:
            gate.process_request(requests[moves[3][0]], spider)
        response = HtmlResponse(req.url, status=status, request=req,
                                headers={b"Location": target.encode("ascii")})
        assert gate.process_response(req, response, spider) is response
        items = list(spider.parse_page(response, req.cb_kwargs["source"]))
        assert len(items) == 1 and not isinstance(items[0], Request)
        item = items[0]
        assert item["status"] == "redirect_needs_review"
        assert item["redirect_review_target"] == target
        assert item["validation_containment_block_reason"] == ORDINARY_REDIRECT
        state.observe(item)
        assert state.hold(state.by_source[sid]) == GROUP_HOLD
        assert state.global_reason is None
    assert len(state.blocked) == 4 and not state.recent_blocked_groups
    req = requests["stackblitz_docs"]
    assert gate.process_request(req, spider) is None
    assert not state.global_reason
    assert not set(state.ordinary_redirect_responses).intersection({"stackblitz_docs"})


@pytest.mark.parametrize("locations", [
    [], [b"/a", b"/b"], [b"http://example.invalid/next"],
    [b"https://other.invalid/next"], [b"//example.invalid/next"],
    [b"https:///docs/new"], [b"https:////docs/new"],
    [b"/login"], [b"/auth/authorize"], [b"/captcha"], [b"/challenge/verify"],
    [b"/docs?token=abc"], [b"/%6cogin"], [b"/a/../docs"],
    [b"/a\\b"], [b"/docs#anchor"], [b"/docs/old"], [b"/a\x00b"],
])
def test_ambiguous_or_suspicious_redirect_is_not_a_routine_move(locations):
    assert ordinary_redirect_target(307, "https://example.invalid/docs/old", locations) is None


def test_ordinary_relative_path_is_deferred_but_never_followed():
    assert ordinary_redirect_target(308, "https://example.invalid/docs", [b"/docs/"]) == "https://example.invalid/docs/"
    assert ordinary_redirect_target(304, "https://example.invalid/docs", [b"/docs/"]) is None
    assert ordinary_redirect_target(308, "https://example.invalid/", [b"https://example.invalid"]) is None


def test_genuine_barriers_still_stop_and_ordinary_redirects_cannot_clear_or_downgrade_holds():
    sources = [dict(id=sid, provider=sid, url="https://" + sid + ".invalid/old")
               for sid in ("a", "b", "c", "d", "e", "f")]
    def make(public_mode):
        return Containment(SimpleNamespace(collection_mode="validation"), sources,
                            consecutive_barriers=public_mode)
    state = make(True)
    # An ordinary move is a monotonic publisher hold, not a reset of the
    # consecutive genuine barrier counter. A later admitted 429 upgrades it.
    state.primary_response("a", "a", 307, sources[0]["url"], [b"/new"])
    assert state.hold("a") == GROUP_HOLD
    state.primary_response("b", "b", 401, sources[1]["url"], [])
    state.primary_response("c", "c", 403, sources[2]["url"], [])
    state.primary_response("a", "a", 429, sources[0]["url"], [])
    assert state.global_reason == SYSTEMIC_STOP
    assert state.blocked["a"] == "agentfuse_validation_http_429"
    assert state.hold("d") == GLOBAL_HOLD
    state = make(True)
    for sid, status in (("a", 451), ("b", 429)):
        state.primary_response(sid, sid, status, "https://" + sid + ".invalid/old", [])
    state.observe({"source_id": "c", "status": "robots_or_policy_denied"})
    assert state.global_reason == SYSTEMIC_STOP
    state = make(True)
    state.observe({"source_id": "a", "status": "blocked", "error": "access_or_login_challenge",
                   "http_status": 200})
    state.primary_response("b", "b", 307, sources[1]["url"], [b"/login"])
    state.primary_response("c", "c", 503, sources[2]["url"], [])
    assert state.global_reason == SYSTEMIC_STOP
    # The strict reviewed-plan path still counts *all* redirects.
    legacy = make(False)
    for sid in ("a", "b", "c"):
        legacy.primary_response(sid, sid, 307, "https://" + sid + ".invalid/old", [b"/new"])
    assert legacy.global_reason == SYSTEMIC_STOP
    for item, reason in (({"http_status": 407}, PROXY_STOP),
                         ({"status": "fetch_error"}, TRANSPORT_STOP)):
        state = make(True)
        state.observe({"source_id": "a", **item})
        assert state.global_reason == reason
    state = make(True)
    state.primary_response("a", "a", 307, sources[0]["url"], [b"/new"])
    # Untrusted or inconsistent Item cannot waive a genuine access signal.
    state.observe({"source_id": "a", "http_status": 307, "status": "redirect_needs_review",
                   "error": "bulk_source_redirect_target_requires_review",
                   "redirect_review_target": "https://a.invalid/other"})
    assert state.blocked["a"] == REDIRECT_BARRIER
