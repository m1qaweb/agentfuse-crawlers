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
    # P23B: being explicit is a SCOPE restriction, never access approval.
    assert not isinstance(emitted[0], Request)
    assert emitted[0]["source_id"] == sid
    assert emitted[0]["status"] == "source_single_validation_not_approved"
    assert emitted[0]["error"] == "single_source_policy_not_reviewed"
    assert emitted[0]["http_status"] is None
    assert emitted[0]["approved_for_advisor"] is False
    assert spider.validation_scope == "single_exact_source"
    assert spider.single_validation_required is True
    assert spider.bulk_validation_required is False
    assert spider.bulk_authorized_ids == frozenset()
    assert spider.run_context["selection_source_count"] == 1
    assert emitted[0]["quality_axes"]["fetch_status"] == (
        "not_attempted_by_single_source_access_policy"
    )


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


def test_offline_bulk_policy_report_preserves_all_unreviewed_sources(
        tmp_path, monkeypatch):
    from scripts.audit_bulk_validation_policy import (
        build_policy_readiness, write_policy_readiness,
    )
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: pytest.fail("P21B audit made a publisher request"),
    )
    report, sources = build_policy_readiness()
    assert len(sources) == 460
    assert report["counts"]["configured_source_ids"] == 460
    assert report["counts"]["technically_validatable"] == 457
    assert report["counts"]["reviewed_permitted_for_bulk"] == 0
    assert report["counts"]["missing_review_or_denied"] == 460
    assert report["approved_run_plans_in_deployed_package"] == 0
    assert report["bulk_run_authorized_by_this_audit"] is False
    assert report["new_zyte_jobs"] == 0
    assert report["network_requests_performed"] == 0
    assert len({r["source_id"] for r in sources}) == 460
    assert all(r["can_be_fetched_without_exact_run_plan"] is False
               for r in sources)
    root = tmp_path / "p21b-private"
    write_policy_readiness(report, sources, root)
    assert (root / "bulk_validation_readiness.json").is_file()
    assert (root / "all_460_source_bulk_review_queue.csv").is_file()
    with pytest.raises(ValueError, match="NEW"):
        write_policy_readiness(report, sources, root)


def test_exact_source_redirect_cap_is_enforced_in_synthetic_approved_run(
        monkeypatch):
    from scrapy.http import HtmlResponse
    selected, access, plans, pid, _ = fake_case()
    plan = plans["plans"][pid]
    plan["max_redirects_per_source"] = 0
    _mock_private_registries(monkeypatch, access, plans)
    spider = DocumentationSpider(**_approved_args(pid, policy.digest(plan)))
    assert spider.bulk_max_redirects_per_source == 0
    source = selected[0]
    req = Request(
        source["url"],
        meta={"source_redirect_chain": [], "source_redirect_depth": 0,
              "dont_redirect": True},
    )
    response = HtmlResponse(
        url=source["url"], status=301, request=req,
        headers={"Location": source["url"], "Content-Type": "text/html"},
        body=b"<main>Moved</main>", encoding="utf-8",
    )
    result = list(spider.parse_page(response, source))
    assert len(result) == 1 and isinstance(result[0], dict)
    assert result[0]["status"] == "redirect_needs_review"
    assert result[0]["error"] == "redirect_limit_or_loop"
    assert result[0]["approved_for_advisor"] is False




@pytest.mark.parametrize("category,spider_type", [
    ("documentation", DocumentationSpider),
    ("pricing", PricingSpider),
    ("changelog", ChangelogSpider),
])
@pytest.mark.parametrize("variation", [
    "different_path", "different_query", "explicit_port", "same_host_fragment",
])
def test_bulk_reviewed_exact_url_never_fetches_changed_same_host_target(
        monkeypatch, category, spider_type, variation):
    """No valid original URL review also grants a second same-host URL."""
    from scrapy.http import HtmlResponse

    selected, registry, plans, pid, signed = fake_case(category=category)
    _mock_private_registries(monkeypatch, registry, plans)
    spider = spider_type(
        cohort="all",
        source_ids=",".join(s["id"] for s in selected),
        collection_mode="validation",
        bulk_run_plan_id=pid,
        expected_bulk_plan_sha256=signed,
        expected_deployment_package_sha256=package_fingerprint(),
    )
    assert spider.bulk_validation_required is True
    assert spider.single_validation_required is False
    assert spider.bulk_max_redirects_per_source == 3
    source = selected[0]
    parts = urlsplit(source["url"])
    if variation == "different_path":
        target = parts._replace(path="/unreviewed-new-docs", query="").geturl()
    elif variation == "different_query":
        target = parts._replace(query="authuser=synthetic-test-secret").geturl()
    elif variation == "explicit_port":
        # Network host is unchanged, but the exact URL review does not
        # include a :443 variant and no transparent redirect is granted.
        target = parts._replace(
            netloc=parts.hostname + ":443", query=""
        ).geturl()
    else:
        target = parts._replace(fragment="unreviewed").geturl()
    req = Request(
        source["url"], meta={
            "source_redirect_chain": [], "source_redirect_depth": 0,
            "dont_redirect": True,
        }
    )
    response = HtmlResponse(
        url=source["url"], status=301, request=req,
        headers={"Location": target, "Content-Type": "text/html"},
        body=b"<main>Redirect</main>", encoding="utf-8",
    )
    emitted = list(spider.parse_page(response, source))
    assert len(emitted) == 1 and isinstance(emitted[0], dict)
    row = emitted[0]
    assert row["status"] == "redirect_needs_review"
    assert row["error"] == "bulk_source_redirect_target_requires_review"
    assert row["policy_observation"] == "redirect_not_fetched_without_exact_url_review"
    assert row["approved_for_advisor"] is False
    assert row["source_url"] == source["url"]
    assert row.get("text") is None
    assert "synthetic-test-secret" not in str(row)
    assert "?" not in row["redirect_review_target"]


@pytest.mark.parametrize("category,spider_type", [
    ("documentation", DocumentationSpider),
    ("pricing", PricingSpider),
    ("changelog", ChangelogSpider),
])
def test_bulk_does_not_extract_unreviewed_final_url_even_if_200(
        monkeypatch, category, spider_type):
    """Defense in depth for a callback handed a different final URL."""
    from scrapy.http import HtmlResponse

    selected, registry, plans, pid, signed = fake_case(category=category)
    _mock_private_registries(monkeypatch, registry, plans)
    spider = spider_type(
        cohort="all",
        source_ids=",".join(s["id"] for s in selected),
        collection_mode="validation",
        bulk_run_plan_id=pid,
        expected_bulk_plan_sha256=signed,
        expected_deployment_package_sha256=package_fingerprint(),
    )
    source = selected[0]
    unexpected = urlsplit(source["url"])._replace(
        path="/not-in-reviewed-source-manifest", query=""
    ).geturl()
    req = Request(unexpected, meta={"dont_redirect": True})
    response = HtmlResponse(
        url=unexpected, status=200, request=req,
        headers={"Content-Type": "text/html"},
        body=b"<main>Deliberately forged, high quality content and prices.</main>",
        encoding="utf-8",
    )
    rows = list(spider.parse_page(response, source))
    assert len(rows) == 1 and isinstance(rows[0], dict)
    assert rows[0]["status"] == "redirect_needs_review"
    assert rows[0]["error"] == "unreviewed_validation_response_url"
    assert rows[0]["policy_observation"] == "response_url_not_in_exact_review_scope"
    assert rows[0]["approved_for_advisor"] is False
    assert "Deliberately forged" not in str(rows[0])
    assert rows[0]["final_url"] == unexpected


def test_single_source_final_url_defense_in_depth_matches_bulk_policy():
    from scrapy.http import HtmlResponse

    source = next(s for s in load_sources() if s["id"] == "openai_api_docs")
    spider = DocumentationSpider(cohort="all", source_ids=source["id"])
    other = urlsplit(source["url"])._replace(path="/unapproved-second-path").geturl()
    response = HtmlResponse(
        url=other, status=200,
        request=Request(other, meta={"dont_redirect": True}),
        body=b"<main>A well-formed page at a different URL</main>",
        encoding="utf-8", headers={"Content-Type": "text/html"},
    )
    output = list(spider.parse_page(response, source))
    assert len(output) == 1 and isinstance(output[0], dict)
    assert output[0]["status"] == "redirect_needs_review"
    assert output[0]["error"] == "unreviewed_validation_response_url"
    assert output[0]["approved_for_advisor"] is False

def test_access_and_plan_registries_reject_unhashable_source_inputs():
    source = load_sources()[0]
    access = _review(source)
    access["scopes"] = [{"unknown": "bulk_validation"}]
    registry = {
        "schema_version": policy.SCHEMA, "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {source["id"]: access},
    }
    with pytest.raises(ValueError, match="scope"):
        policy.validate_access_registry(registry)
    selected, valid_reviews, plans, pid, _ = fake_case()
    plans["plans"][pid]["authorized_source_ids"] = [{"bad": "id"}]
    with pytest.raises(ValueError, match="scope"):
        policy.validate_plan_registry(plans)


# P23E0: the *operator* may enter only the original three full-category UI
# fields once ONE exact run plan and per-source access decisions have actually
# been reviewed and packaged. No real source is approved by these fixtures.
@pytest.mark.parametrize("category,spider_type,total", [
    ("documentation", DocumentationSpider, 194),
    ("pricing", PricingSpider, 177),
    ("changelog", ChangelogSpider, 89),
])
def test_explicit_three_argument_full_category_auto_resolves_only_reviewed_plan(
        monkeypatch, category, spider_type, total):
    selected, reviews, plans, pid, pin = fake_case(
        category=category, count=total, allowed_count=2,
    )
    _mock_private_registries(monkeypatch, reviews, plans)
    spider = spider_type(
        cohort="all", confirm_full_inventory="yes",
        collection_mode="validation",
    )
    emitted = asyncio.run(collect(spider))
    requests = [x for x in emitted if isinstance(x, Request)]
    assert len(emitted) == total
    assert len(requests) == 2
    assert [r.url for r in requests] == [s["url"] for s in selected[:2]]
    assert spider.bulk_plan_id == pid
    assert spider.bulk_plan_sha256 == pin
    assert spider.bulk_max_primary_requests == 2
    assert spider.bulk_gate_decision == "exact_git_reviewed_bounded_run_plan"
    assert spider.run_context["deployment_revision"] == package_fingerprint()
    for item in emitted[2:]:
        assert not isinstance(item, Request)
        assert item["approved_for_advisor"] is False
        assert item["http_status"] is None


def test_full_auto_plan_is_not_a_bypass_for_source_subset_or_monitor(monkeypatch):
    selected, reviews, plans, _, _ = fake_case(
        count=194, allowed_count=2,
    )
    _mock_private_registries(monkeypatch, reviews, plans)
    # Single-source has a separate, independently reviewed gate.
    one = DocumentationSpider(cohort="all", source_ids=selected[0]["id"])
    assert one.bulk_validation_required is False
    assert one.single_validation_required is True
    # A multi-source subset never automatically borrows the full plan.
    subset = DocumentationSpider(
        cohort="all",
        source_ids=",".join(s["id"] for s in selected[:2]),
        collection_mode="validation",
    )
    assert subset.bulk_plan_id == ""
    held = asyncio.run(collect(subset))
    assert len(held) == 2
    assert all(not isinstance(x, Request) for x in held)
    # A monitored/full job is not re-authorized by validation.
    watched = DocumentationSpider(
        cohort="all", confirm_full_inventory="yes", collection_mode="monitor"
    )
    assert watched.bulk_plan_id == ""
    assert not any(isinstance(x, Request) for x in asyncio.run(collect(watched)))


def test_full_auto_plan_scope_mismatch_does_not_use_other_category(monkeypatch):
    _, reviews, plans, _, _ = fake_case(
        category="documentation", count=194, allowed_count=2,
    )
    _mock_private_registries(monkeypatch, reviews, plans)
    other = PricingSpider(
        cohort="all", confirm_full_inventory="yes", collection_mode="validation",
    )
    assert other.bulk_plan_id == ""
    assert other.bulk_gate_decision == "bulk_run_plan_not_present"
    assert not any(isinstance(x, Request) for x in asyncio.run(collect(other)))


def test_multiple_equally_matching_reviewed_plans_fail_before_network(monkeypatch):
    _, reviews, plans, pid, _ = fake_case(count=194, allowed_count=2)
    plans["plans"]["synthetic_second_full_plan"] = deepcopy(plans["plans"][pid])
    _mock_private_registries(monkeypatch, reviews, plans)
    with pytest.raises(ValueError, match="Ambiguous reviewed full-inventory"):
        DocumentationSpider(cohort="all", confirm_full_inventory="yes")


@pytest.mark.parametrize("tamper", [
    "manifest", "review_digest", "expired_plan", "invalid_access",
])
def test_auto_plan_refuses_stale_and_unreviewed_sources(monkeypatch, tamper):
    selected, reviews, plans, pid, _ = fake_case(count=194, allowed_count=2)
    if tamper == "manifest":
        plans["plans"][pid]["manifest_sha256"] = "0" * 64
    elif tamper == "review_digest":
        plans["plans"][pid]["access_registry_sha256"] = "0" * 64
    elif tamper == "expired_plan":
        plans["plans"][pid]["reviewed_at_utc"] = _time(timedelta(days=-3))
        plans["plans"][pid]["expires_at_utc"] = _time(timedelta(days=-1))
    elif tamper == "invalid_access":
        reviews["reviews"][selected[0]["id"]]["private_retention_reviewed"] = False
    _mock_private_registries(monkeypatch, reviews, plans)
    with pytest.raises(ValueError):
        DocumentationSpider(cohort="all", confirm_full_inventory="yes")


def test_partially_supplied_external_bulk_hashes_are_not_autocorrected(monkeypatch):
    _, reviews, plans, _, _ = fake_case(count=194, allowed_count=2)
    _mock_private_registries(monkeypatch, reviews, plans)
    with pytest.raises(ValueError, match="fingerprints without"):
        DocumentationSpider(
            cohort="all", confirm_full_inventory="yes",
            expected_bulk_plan_sha256="f" * 64,
        )
    with pytest.raises(ValueError, match="Git-reviewed bulk authorization"):
        DocumentationSpider(
            cohort="all", confirm_full_inventory="yes",
            bulk_run_plan_id="unknown_forged_plan",
            expected_bulk_plan_sha256="f" * 64,
            expected_deployment_package_sha256=package_fingerprint(),
        )
