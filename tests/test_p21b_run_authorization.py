"""P21B: synthetic fail-closed live request initiation, never publisher GET.

Positive cases use entirely FAKE, in-memory "reviews" and reviewed run
records. They are NOT installed or granted to a real publisher. Both
packaged registries remain EMPTY.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from scrapy import Request

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import (
    registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.spiders.official import (
    ChangelogSpider, DocumentationSpider, PricingSpider,
)
import agentfuse_crawlers.validation_access as policy
from agentfuse_crawlers.diagnostics import derive_diagnostics

NOW = datetime.now(timezone.utc)
HUMAN = "Synthetic Test Reviewer"
NOTE = (
    "SYNTHETIC ONLY: independently verify the exact first-party page owner, "
    "publisher terms and robots restrictions, intended product scope and "
    "private HTML retention rights before ANY real source request. "
    "These tests make NO claims of actual publisher permissions."
)


async def collect(spider):
    return [x async for x in spider.start()]


def source_ids(category, n=3):
    return [s["id"] for s in select_sources(category, cohort="all")[:n]]


def _time(delta):
    return (NOW + delta).isoformat(timespec="seconds")


def _review(source, *, scope=("single_validation", "bulk_validation")):
    host = urlsplit(source["url"]).hostname
    return {
        "source_url": source["url"],
        "category": source["category"],
        "decision": "allowed_reviewed",
        "scopes": list(scope),
        "reviewed_by": HUMAN,
        "reviewed_at_utc": _time(timedelta(hours=-1)),
        "expires_at_utc": _time(timedelta(days=5)),
        "ownership_evidence_url": source["url"],
        "publisher_access_policy_url": "https://" + host + "/terms",
        "robots_url": "https://" + host + "/robots.txt",
        "publisher_terms_reviewed": True,
        "robots_reviewed": True,
        "private_retention_reviewed": True,
        "evidence_note": NOTE,
    }


def fake_case(category="documentation", *, count=3, allowed_count=2):
    ids = source_ids(category, count)
    selected = select_sources(category, "all", source_ids=ids)
    registry = {
        "schema_version": policy.SCHEMA,
        "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {
            s["id"]: _review(s) for s in selected[:allowed_count]
        },
    }
    plan_id = "synthetic_bounded_canary_001"
    plan = {
        "category": category,
        "collection_mode": "validation",
        "cohort": "all",
        "source_ids": [s["id"] for s in selected],
        "authorized_source_ids": [
            s["id"] for s in selected[:allowed_count]
        ],
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "access_registry_sha256":
            policy.validation_access_revision_sha256(registry),
        "selection_ids_sha256": selection_ids_sha256(selected),
        "source_urls_sha256": policy._urls_digest(selected),
        "approved_by": HUMAN,
        "reviewed_at_utc": _time(timedelta(hours=-1)),
        "expires_at_utc": _time(timedelta(hours=4)),
        "max_primary_requests": allowed_count,
        "max_redirects_per_source": 3,
        "purpose": "bounded_human_supervised_diagnostic",
        "publisher_policy_review_attested": True,
    }
    approved = {
        "schema_version": policy.SCHEMA,
        "kind": policy.PLAN_KIND,
        "default_policy": "no_bulk_runs_authorized",
        "plans": {plan_id: plan},
    }
    return selected, registry, approved, plan_id, policy.digest(plan)


def _mock_private_registries(monkeypatch, registry, approved):
    monkeypatch.setattr(policy, "load_access_registry", lambda: registry)
    monkeypatch.setattr(policy, "load_run_plan_registry", lambda: approved)


def _approved_args(plan_id, digest):
    return {
        "cohort": "all",
        "source_ids": ",".join(source_ids("documentation", 3)),
        "collection_mode": "validation",
        "bulk_run_plan_id": plan_id,
        "expected_bulk_plan_sha256": digest,
        "expected_deployment_package_sha256": package_fingerprint(),
    }


def test_packaged_access_and_run_plan_registries_are_empty_and_fail_closed():
    registry = policy.load_access_registry()
    plans = policy.load_run_plan_registry()
    assert registry["reviews"] == {}
    assert plans["plans"] == {}
    assert registry["default_decision"] == "not_reviewed"
    assert plans["default_policy"] == "no_bulk_runs_authorized"
    assert len(policy.validation_access_revision_sha256()) == 64
    assert len(policy.bulk_plan_revision_sha256()) == 64
    for category, spider in (
        ("documentation", DocumentationSpider),
        ("pricing", PricingSpider),
        ("changelog", ChangelogSpider),
    ):
        assert len(collect_result := asyncio.run(
            collect(spider(cohort="all", confirm_full_inventory="yes"))
        )) == {"documentation": 194, "pricing": 177, "changelog": 89}[category]
        assert all(isinstance(x, dict) for x in collect_result)
        assert all(x["status"] in {
            "source_bulk_validation_not_approved", "source_quarantined"
        } for x in collect_result)
        assert all(x["http_status"] is None and x["approved_for_advisor"] is False
                   for x in collect_result)
        assert all(x["policy_observation"].startswith("not_fetched_by_")
                   for x in collect_result)


@pytest.mark.parametrize("spider_type", [
    DocumentationSpider, PricingSpider, ChangelogSpider,
])
def test_single_exact_manual_validation_remains_bounded(spider_type):
    category = spider_type.category
    sid = source_ids(category, 1)[0]
    spider = spider_type(cohort="all", source_ids=sid)
    emitted = asyncio.run(collect(spider))
    assert len(emitted) == 1
    assert isinstance(emitted[0], Request)
    assert emitted[0].cb_kwargs["source"]["id"] == sid
    assert spider.validation_scope == "single_exact_source"
    assert spider.bulk_validation_required is False
    assert spider.bulk_authorized_ids == frozenset()
    assert spider.run_context["selection_source_count"] == 1
    assert emitted[0].meta["dont_redirect"] is True


def test_explicit_single_quarantined_never_fetches_even_with_old_confirmation():
    s = DocumentationSpider(
        cohort="all", source_ids="v0_docs", confirm_full_inventory="yes"
    )
    emitted = asyncio.run(collect(s))
    assert len(emitted) == 1
    assert not isinstance(emitted[0], Request)
    assert emitted[0]["status"] == "source_quarantined"


@pytest.mark.parametrize("args", [
    {"cohort": "all", "source_ids": "openai_api_docs,anthropic_api_docs"},
    {"cohort": "proven"},
    {"cohort": "all", "source_ids": "openai_api_docs,anthropic_api_docs", "limit": 1},
    {"cohort": "all", "limit": 1, "confirm_full_inventory": "yes"},
    {"cohort": "all", "confirm_full_inventory": "yes"},
    {"cohort": "candidate", "limit": 2},
])
def test_bulk_scope_cannot_bypass_with_limit_offset_or_proven(args):
    spider = DocumentationSpider(**args)
    all_rows = asyncio.run(collect(spider))
    assert len(all_rows) == len(spider.selected)
    assert all(not isinstance(x, Request) for x in all_rows)
    assert all(
        x["status"] in {"source_bulk_validation_not_approved", "source_quarantined"}
        for x in all_rows
    )
    assert all(x["http_status"] is None for x in all_rows)


def test_bounded_reviewed_real_spider_integration_only_gets_approved_subset(monkeypatch):
    selected, review, plans, pid, pin = fake_case()
    _mock_private_registries(monkeypatch, review, plans)
    spider = DocumentationSpider(**_approved_args(pid, pin))
    emitted = asyncio.run(collect(spider))
    requests = [row for row in emitted if isinstance(row, Request)]
    held = [row for row in emitted if isinstance(row, dict)]
    assert len(requests) == 2
    assert len(held) == 1
    assert [q.cb_kwargs["source"]["id"] for q in requests] == [
        s["id"] for s in selected[:2]
    ]
    assert held[0]["source_id"] == selected[2]["id"]
    assert held[0]["status"] == "source_bulk_validation_not_approved"
    assert held[0]["error"] == "bulk_source_not_in_authorized_scope"
    assert held[0]["quality_axes"]["fetch_status"] == (
        "not_attempted_by_bulk_access_policy"
    )
    assert held[0]["quality_axes"]["access_policy_status"] == (
        "bulk_validation_unapproved"
    )
    assert spider.bulk_max_primary_requests == 2
    assert spider.bulk_plan_id == pid
    assert spider.bulk_plan_sha256 == pin
    assert all(not q.meta.get("source_bulk_access_bypass") for q in requests)
    assert held[0]["approved_for_advisor"] is False
    assert spider.run_context["deployment_revision"] == package_fingerprint()


@pytest.mark.parametrize("tamper", [
    "wrong_manifest", "wrong_lifecycle", "wrong_review_registry",
    "wrong_selection", "wrong_urls", "wrong_provider_category",
    "wrong_cohort", "wrong_authorized_scope", "too_many_requests",
    "too_many_redirects", "future_plan", "expired_plan",
    "denied_review", "expired_source_review", "missing_retention",
    "wrong_robots_url", "wrong_reviewed_source_url",
    "wrong_terms_scheme", "wrong_ownership_host", "review_future",
    "different_publisher", "wrong_spider", "plan_digest",
    "package_digest", "unknown_plan", "forged_cli_only",
])
def test_synthetic_forged_or_stale_publisher_policy_never_fetches(
        monkeypatch, tamper):
    selected, review, plans, pid, digest = fake_case()
    case = deepcopy(plans)
    registry = deepcopy(review)
    plan = case["plans"][pid]
    one_sid = selected[0]["id"]
    access = registry["reviews"][one_sid]
    spider_kwargs = _approved_args(pid, digest)
    if tamper == "wrong_manifest":
        plan["manifest_sha256"] = "0"*64
    elif tamper == "wrong_lifecycle":
        plan["source_registry_sha256"] = "1"*64
    elif tamper == "wrong_review_registry":
        plan["access_registry_sha256"] = "2"*64
    elif tamper == "wrong_selection":
        plan["selection_ids_sha256"] = "3"*64
    elif tamper == "wrong_urls":
        plan["source_urls_sha256"] = "4"*64
    elif tamper == "wrong_provider_category":
        plan["category"] = "pricing"
    elif tamper == "wrong_cohort":
        plan["cohort"] = "proven"
    elif tamper == "wrong_authorized_scope":
        plan["authorized_source_ids"] = [selected[2]["id"]]
        plan["max_primary_requests"] = 1
    elif tamper == "too_many_requests":
        plan["max_primary_requests"] = 200
    elif tamper == "too_many_redirects":
        plan["max_redirects_per_source"] = 11
    elif tamper == "future_plan":
        plan["reviewed_at_utc"] = _time(timedelta(days=10))
        plan["expires_at_utc"] = _time(timedelta(days=12))
    elif tamper == "expired_plan":
        plan["reviewed_at_utc"] = _time(timedelta(days=-3))
        plan["expires_at_utc"] = _time(timedelta(days=-1))
    elif tamper == "denied_review":
        access["decision"] = "prohibited_reviewed"
        access["scopes"] = []
        access["publisher_terms_reviewed"] = False
        access["robots_reviewed"] = False
        access["private_retention_reviewed"] = False
    elif tamper == "expired_source_review":
        access["reviewed_at_utc"] = _time(timedelta(days=-10))
        access["expires_at_utc"] = _time(timedelta(days=-1))
    elif tamper == "missing_retention":
        access["private_retention_reviewed"] = False
    elif tamper == "wrong_robots_url":
        access["robots_url"] = "https://other.invalid/robots.txt"
    elif tamper == "wrong_reviewed_source_url":
        access["source_url"] = "https://other.invalid/docs"
    elif tamper == "wrong_terms_scheme":
        access["publisher_access_policy_url"] = "http://bad.invalid/terms"
    elif tamper == "wrong_ownership_host":
        access["ownership_evidence_url"] = "https://attacker.invalid/"
    elif tamper == "review_future":
        access["reviewed_at_utc"] = _time(timedelta(days=20))
        access["expires_at_utc"] = _time(timedelta(days=25))
    elif tamper == "different_publisher":
        spider_kwargs["source_ids"] = ",".join(
            source_ids("documentation", 3)[1:]
        )
    elif tamper == "wrong_spider":
        spider_kwargs["cohort"] = "candidate"
    elif tamper == "plan_digest":
        spider_kwargs["expected_bulk_plan_sha256"] = "f"*64
    elif tamper == "package_digest":
        spider_kwargs["expected_deployment_package_sha256"] = "f"*64
    elif tamper == "unknown_plan":
        spider_kwargs["bulk_run_plan_id"] = "unknown_forged_plan"
    elif tamper == "forged_cli_only":
        case["plans"].clear()
    # A correctly reviewed edit would need a fresh pinned SHA in the
    # spider args. Update the SHA ONLY to test deeper integrity gates.
    if tamper not in ("plan_digest", "package_digest"):
        spider_kwargs["expected_bulk_plan_sha256"] = policy.digest(plan)
    _mock_private_registries(monkeypatch, registry, case)
    with pytest.raises(ValueError):
        DocumentationSpider(**spider_kwargs)


@pytest.mark.parametrize("bad", [
    None, "garbage", "http://evil.invalid", "https://evil.invalid?a=key",
    "https://user:secret@example.com", "https://localhost/",
    "https://127.0.0.1/", "https://example.com:wrong/",
])
def test_malformed_external_evidence_url_refused(bad):
    if bad is None:
        with pytest.raises(ValueError):
            policy._https(bad)
    else:
        with pytest.raises(ValueError):
            policy._https(bad)


def test_unknown_or_changed_manifest_record_denied_before_publisher_request():
    source = load_sources()[0]
    permitted = _review(source)
    registry = {
        "schema_version": policy.SCHEMA, "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {source["id"]: permitted},
    }
    policy.validate_access_registry(registry)
    changed = deepcopy(registry)
    changed["reviews"][source["id"]]["source_url"] = (
        "https://evil.invalid/migrated"
    )
    with pytest.raises(ValueError, match="pinned"):
        policy.validate_access_registry(changed)
    changed = deepcopy(registry)
    changed["reviews"]["unknown_new_source"] = changed["reviews"].pop(source["id"])
    with pytest.raises(ValueError, match="Unknown"):
        policy.validate_access_registry(changed)


def test_monitor_never_accepts_bulk_plan_or_uses_validation_access(monkeypatch):
    _, review, plans, pid, pin = fake_case()
    _mock_private_registries(monkeypatch, review, plans)
    with pytest.raises(ValueError, match="Bulk plan flags"):
        DocumentationSpider(
            cohort="all",
            source_ids="openai_api_docs,anthropic_api_docs",
            collection_mode="monitor",
            bulk_run_plan_id=pid,
            expected_bulk_plan_sha256=pin,
        )
    s = DocumentationSpider(
        source_ids="openai_api_docs", collection_mode="monitor"
    )
    rows = asyncio.run(collect(s))
    assert len(rows) == 1 and not isinstance(rows[0], Request)
    assert rows[0]["status"] == "source_not_validated_for_monitor"
    assert rows[0]["approved_for_advisor"] is False


def test_reviewed_permission_is_not_permission_to_monitor():
    selected, reviewed, plans, pid, sha = fake_case()
    for src in selected[:2]:
        allowed, reason = policy.validation_access_decision(
            src, scope="bulk_validation", registry=reviewed,
        )
        assert allowed and reason == "git_reviewed_source_bulk_validation_access"
        from agentfuse_crawlers.source_lifecycle import collection_decision
        assert collection_decision(src, "monitor")[0] is False
    assert policy.digest(plans["plans"][pid]) == sha


def test_lifecycle_quarantine_cannot_be_overridden_by_forged_access():
    src = next(s for s in load_sources() if s["id"] == "v0_docs")
    registry = {
        "schema_version": policy.SCHEMA, "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {src["id"]: _review(src)},
    }
    permitted, reason = policy.validation_access_decision(
        src, scope="bulk_validation", registry=registry
    )
    assert permitted is False
    assert reason == "policy_unresolved_or_quarantined"
