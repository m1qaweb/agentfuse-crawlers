"""Explicit public-source diagnostic activation; all tests are offline."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from scrapy import Request
from scrapy.exceptions import IgnoreRequest

from agentfuse_crawlers import public_diagnostic as public
from agentfuse_crawlers import validation_access as policy
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.spiders import official
from agentfuse_crawlers.validation_downloader import ValidationDownloadGate, ValidationPreRobotsGuard
from agentfuse_crawlers.validation_containment import (
    Containment, GROUP_HOLD, SYSTEMIC_STOP, PROXY_STOP, group_index,
)


def scope_clock():
    scope = public.load_public_diagnostic_scope()
    return scope, policy._utc(scope["observed_at_utc"]) + timedelta(hours=1)


def test_packaged_public_scope_is_exact_bounded_and_preserves_holds():
    scope, now = scope_clock()
    groups, _ = group_index(load_sources())
    assert len(scope["source_ids"]) == 274
    assert len(scope["preflight_robots_observed_ids"]) == 160
    assert len(scope["prior_held_groups"]) == 29
    assert not set(scope["prior_held_groups"]) & {groups[sid] for sid in scope["source_ids"]}
    assert scope["rights_status"] == "individual_publisher_rights_not_independently_verified"
    for category, count in (("pricing", 115), ("documentation", 123), ("changelog", 36)):
        _, decision = public.authorize_public_diagnostic(
            selected=select_sources(category, "all"), category=category, now=now)
        assert len(decision["authorized_source_ids"]) == count
        assert decision["max_primary_requests"] == count
        assert decision["max_redirects_per_source"] == 0
        assert decision["decision"] == public.PUBLIC_GATE


@pytest.mark.parametrize("spider_class,count,total", [
    (official.PricingSpider, 115, 177),
    (official.DocumentationSpider, 123, 194),
    (official.ChangelogSpider, 36, 89),
])
def test_three_existing_spiders_emit_real_exact_requests_without_positive_review_records(
        monkeypatch, spider_class, count, total):
    scope, now = scope_clock()
    monkeypatch.setattr(official, "authorize_public_diagnostic",
                        lambda **kw: public.authorize_public_diagnostic(**kw, now=now))
    spider = spider_class(cohort="all", confirm_full_inventory="public_diagnostic",
                          collection_mode="validation")
    async def collect():
        return [row async for row in spider.start()]
    rows = asyncio.run(collect())
    requests = [row for row in rows if isinstance(row, Request)]
    assert len(rows) == total
    assert len(requests) == count
    assert {req.cb_kwargs["source"]["id"] for req in requests} == spider.bulk_authorized_ids
    assert all(req.url == req.cb_kwargs["source"]["url"] and req.method == "GET"
               and req.meta["dont_retry"] and req.meta["dont_redirect"] for req in requests)
    src = requests[0].cb_kwargs["source"]
    item = spider._base_record(src)
    assert item["public_diagnostic_source_in_scope"] is True
    assert item["public_diagnostic_publisher_rights_independently_verified"] is False
    assert item["bulk_source_authorized_by_reviewed_plan"] is False
    assert item["approved_for_advisor"] is False
    assert spider._agentfuse_containment.consecutive_barriers is True
    # Test the actual downloader gates; do not make a network request.
    pre = ValidationPreRobotsGuard()
    pre.gate._clock = lambda: now
    gate = ValidationDownloadGate(clock=lambda: now)
    assert pre.process_request(requests[0], spider) is None
    assert gate.process_request(requests[0], spider) is None
    with pytest.raises(IgnoreRequest, match="duplicate_validation_source_get"):
        gate.process_request(requests[0], spider)


@pytest.mark.parametrize("kwargs", [
    {"collection_mode": "monitor"}, {"cohort": "proven"},
    {"source_ids": "google_antigravity_pricing"}, {"limit": "1"},
    {"offset": "1"}, {"bulk_run_plan_id": "fake_legacy_plan"},
    {"expected_bulk_plan_sha256": "0" * 64},
])
def test_public_diagnostic_is_not_a_generic_access_bypass(kwargs):
    args = dict(cohort="all", confirm_full_inventory="public_diagnostic")
    args.update(kwargs)
    with pytest.raises(ValueError, match="whole-category validation"):
        official.PricingSpider(**args)


def test_scope_expiry_is_enforced_and_later_category_can_only_narrow():
    scope, now = scope_clock()
    category = "pricing"
    selected = select_sources(category, "all")
    _, before = public.authorize_public_diagnostic(selected=selected, category=category, now=now)
    groups, _ = group_index(load_sources())
    group = groups[sorted(before["authorized_source_ids"])[0]]
    _, after = public.authorize_public_diagnostic(selected=selected, category=category,
                                                  held_groups=group, now=now)
    assert after["authorized_source_ids"] < before["authorized_source_ids"]
    assert all(groups[sid] != group for sid in after["authorized_source_ids"])
    with pytest.raises(ValueError, match="Unknown held publisher group"):
        public.authorize_public_diagnostic(selected=selected, category=category,
                                          held_groups="not-a-group", now=now)
    with pytest.raises(ValueError, match="not current"):
        public.authorize_public_diagnostic(selected=selected, category=category,
                                          now=policy._utc(scope["expires_at_utc"]))
    outside = next(s for s in selected if s["id"] not in scope["source_ids"])
    assert public.public_diagnostic_access_decision(outside, scope, now=now)[0] is False


def test_real_negative_policy_record_is_not_overridden(monkeypatch):
    scope, now = scope_clock()
    source = next(s for s in load_sources() if s["id"] in scope["source_ids"])
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
            "evidence_note": "Synthetic negative test record only; not an actual publisher permission or review and never installed.",
        }},
    }
    policy.validate_access_registry(registry, now=now)
    monkeypatch.setattr(policy, "load_access_registry", lambda: registry)
    assert public.public_diagnostic_access_decision(source, scope, now=now)[0] is False
    _, decision = public.authorize_public_diagnostic(
        selected=select_sources(source["category"], "all"), category=source["category"], now=now)
    groups, _ = group_index(load_sources())
    assert all(groups[sid] != groups[source["id"]] for sid in decision["authorized_source_ids"])


def test_diagnostic_global_stop_requires_consecutive_distinct_groups_but_holds_persist():
    sources = [{"id": sid, "provider": sid, "url": "https://" + sid + ".invalid/page"}
               for sid in ("a", "b", "c", "d", "e", "f", "g", "h")]
    spider = SimpleNamespace(collection_mode="validation")
    state = Containment(spider, sources, consecutive_barriers=True)
    for bad, good in (("a", "b"), ("c", "d"), ("e", "f")):
        state.barrier(bad, "agentfuse_validation_http_429")
        state.observe({"source_id": good, "status": "captured", "http_status": 200})
        assert state.hold(bad) == GROUP_HOLD
        assert state.global_reason is None
    for bad in ("b", "d", "f"):
        state.barrier(bad, "agentfuse_validation_http_429")
    assert state.global_reason == SYSTEMIC_STOP
    state = Containment(SimpleNamespace(collection_mode="validation"), sources,
                        consecutive_barriers=True)
    state.observe({"source_id": "g", "status": "http_error", "http_status": 407})
    assert state.global_reason == PROXY_STOP
