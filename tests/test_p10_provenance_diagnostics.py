"""P10 package provenance and independent diagnostics regression coverage."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scrapy.http import HtmlResponse

from agentfuse_crawlers.diagnostics import AXES, derive_diagnostics
from agentfuse_crawlers.extensions.coverage import SourceCoverageAudit
from agentfuse_crawlers.run_context import (
    PACKAGE_FINGERPRINT_KIND, build_run_context, fingerprint_entries,
    package_fingerprint,
)
from agentfuse_crawlers.sources import select_sources
from agentfuse_crawlers.spiders.official import DocumentationSpider, PricingSpider
from scripts.report_diagnostics import summarize


def test_package_digest_is_nonempty_and_not_overrideable_by_fake_git_env(monkeypatch):
    monkeypatch.setenv("AGENTFUSE_DEPLOY_REVISION", "not-a-valid-commit")
    source = select_sources("pricing", "proven")[:1]
    ctx = build_run_context("official_pricing", "proven", source)
    assert len(ctx["deployment_revision"]) == 64
    assert ctx["deployment_revision"] == package_fingerprint()
    assert ctx["deployment_revision_kind"] == PACKAGE_FINGERPRINT_KIND
    assert ctx["deployment_source_revision_claim"] == ""
    monkeypatch.setenv("AGENTFUSE_DEPLOY_REVISION", "abcdef1234567890")
    next_ctx = build_run_context("official_pricing", "proven", source)
    assert next_ctx["deployment_revision"] == ctx["deployment_revision"]
    assert next_ctx["deployment_source_revision_claim"] == "abcdef1234567890"


def test_fingerprint_rejects_missing_sources_and_detects_changed_bytes():
    with pytest.raises(ValueError, match="Missing"):
        fingerprint_entries([("run_context.py", b"a")])
    rows = [("run_context.py", b"one"), ("data/sources.json", b"two")]
    changed = [("run_context.py", b"ONE"), ("data/sources.json", b"two")]
    assert fingerprint_entries(rows) == fingerprint_entries(list(reversed(rows)))
    assert fingerprint_entries(rows) != fingerprint_entries(changed)
    with pytest.raises(ValueError, match="duplicated"):
        fingerprint_entries(rows + [rows[0]])


def test_secondary_canonical_and_docs_scope_issues_both_survive_primary_error():
    source = {
        "source_id": "example_docs", "source_url": "https://example.org/docs/",
        "final_url": "https://example.org/docs/", "canonical_url": "https://example.org/docs/intro",
        "category": "documentation", "status": "needs_review",
        "error": "canonical_path_differs", "http_status": 200, "word_count": 200,
        "content_sha256": hashlib.sha256(b"example").hexdigest(),
        "documentation_evidence_schema": "1.0",
        "documentation_scope_status": "scope_not_established",
        "documentation_canonical_relation": "same_host_path_differs",
        "source_policy_status": "not_reviewed",
        "freshness_warnings": ["reported_cache_age_over_one_day"],
    }
    d = derive_diagnostics(source)
    assert d["diagnostic_schema"] == "1.0"
    assert {"canonical_path_differs", "documentation_scope_not_established",
            "reported_cache_age_over_one_day"} <= set(d["diagnostic_reason_codes"])
    assert d["quality_axes"]["source_identity_status"] == "review_required"
    assert d["quality_axes"]["freshness_status"] == "cache_or_clock_review"
    assert d["quality_axes"]["alert_eligibility"] == "blocked_unverified"
    assert set(d["quality_axes"]) == set(AXES)
    assert source["error"] == "canonical_path_differs"


def test_pricing_and_changelog_concurrent_issues_preserved():
    price = derive_diagnostics({
        "category": "pricing", "status": "needs_review",
        "error": "canonical_path_differs", "source_url": "https://example.com/pricing",
        "canonical_url": "https://example.com/pricing-v2",
        "pricing_evidence_schema": "1.0", "pricing_inventory_complete": False,
        "pricing_observation_count": 12, "pricing_comparable_candidate_count": 0,
        "pricing_table_scan_truncated": True, "source_policy_status": "not_reviewed",
    })
    assert {"canonical_path_differs", "pricing_inventory_incomplete",
            "pricing_rate_dimensions_unresolved"} <= set(price["diagnostic_reason_codes"])
    assert price["quality_axes"]["completeness_status"] == "partial"
    change = derive_diagnostics({
        "category": "changelog", "status": "partial_capture",
        "error": "recent_release_body_incomplete", "release_events_schema": "1.1",
        "release_event_count": 80, "release_dated_event_count": 50,
        "release_event_identity_collision": True,
        "release_window_complete": False, "release_recent_body_loss_count": 2,
        "latest_release_date_candidate": None,
    })
    assert {"release_event_identity_collision", "recent_release_body_incomplete",
            "latest_release_date_ambiguous", "release_window_incomplete"} <= set(
                change["diagnostic_reason_codes"]
            )


def test_lifecycle_quarantine_retains_one_diagnostic_item_without_network():
    spider = DocumentationSpider(source_ids="v0_docs", cohort="all")
    import asyncio
    results = asyncio.run(_collect(spider))
    assert len(results) == 1
    record = results[0]
    assert record["source_id"] == "v0_docs"
    assert record["status"] == "source_quarantined"
    assert record["quality_axes"]["fetch_status"] == "not_attempted_by_lifecycle"
    assert record["quality_axes"]["access_policy_status"] == "quarantined_or_unresolved"
    assert len(record["deployment_revision"]) == 64


async def _collect(spider):
    return [r async for r in spider.start()]


def test_real_parser_item_has_diagnostics_and_no_status_semantics_change():
    spider = PricingSpider(source_ids="openai_api_pricing")
    s = spider.selected[0]
    html = ("<main><h1>Pricing</h1><p>"
            + "Pricing details available for multiple model usage tiers. " * 15
            + "</p></main>")
    response = HtmlResponse(
        url=s["url"], body=html.encode(), encoding="utf-8",
        status=200, headers={"Content-Type": "text/html"},
    )
    item = list(spider.parse_page(response, s))[0]
    assert item["status"] == "needs_review"
    assert item["error"] == "pricing_no_structured_rate_evidence"
    assert item["diagnostic_schema"] == "1.0"
    assert "pricing_no_structured_rate_evidence" in item["diagnostic_reason_codes"]
    assert item["approved_for_advisor"] is False


class Stats:
    def __init__(self):
        self.rows = {}

    def set_value(self, name, value):
        self.rows[name] = value


class Logger:
    def warning(self, *args):
        pass

    def error(self, *args):
        pass


def test_coverage_counts_axes_reasons_and_does_not_swallow_missing_diagnostics():
    stats = Stats()
    audit = SourceCoverageAudit(SimpleNamespace(stats=stats))
    spider = SimpleNamespace(
        name="official_documentation", selected=[{"id": "a"}, {"id": "b"}],
        logger=Logger(), run_context=None,
    )
    for source_id, scope, primary in [
        ("a", "scope_not_established", "canonical_path_differs"),
        ("b", "overview_only", ""),
    ]:
        row = {
            "source_id": source_id, "source_url": "https://example.org/docs",
            "final_url": "https://example.org/docs", "schema_version": "2.1",
            "category": "documentation", "status": "needs_review",
            "documentation_evidence_schema": "1.0",
            "documentation_scope_status": scope,
            "error": primary, "approved_for_advisor": False,
        }
        row.update(derive_diagnostics(row))
        audit.item_scraped(row, None, spider)
    audit.summary(spider)
    assert stats.rows["agentfuse/diagnostics/reason/documentation_scope_not_established"] == 1
    assert stats.rows["agentfuse/diagnostics/reason/canonical_path_differs"] == 1
    assert stats.rows["agentfuse/coverage/multiple_diagnostic_reasons_sources"] >= 1
    assert stats.rows["agentfuse/coverage/missing_modern_diagnostics"] == 0

    missing_stats = Stats()
    missing_audit = SourceCoverageAudit(SimpleNamespace(stats=missing_stats))
    modern = {
        "source_id": "a", "status": "captured", "schema_version": "2.1",
        "approved_for_advisor": False,
    }
    missing_audit.item_scraped(modern, None, spider)
    missing_audit.summary(spider)
    assert missing_stats.rows["agentfuse/coverage/missing_modern_diagnostics"] == 1


def test_offline_report_preserves_legacy_origin_without_approvals(tmp_path):
    from agentfuse_crawlers.sources import load_sources
    first = next(s for s in load_sources() if s["id"] == "openai_api_pricing")
    old = {
        "source_id": first["id"], "source_url": first["url"],
        "category": "pricing", "status": "needs_review",
        "error": "pricing_rate_dimensions_unresolved",
        "pricing_evidence_schema": "1.0", "pricing_inventory_complete": True,
        "pricing_observation_count": 20,
        "pricing_comparable_candidate_count": 0,
        "zyte_job_id": "883514/3/8",
    }
    path = tmp_path / "items.json"
    path.write_text(json.dumps([old]), encoding="utf-8")
    report = summarize([path])
    assert report["summary"]["source_item_count"] == 1
    assert report["summary"]["deployment_authorized"] is False
    assert report["rows"][0]["diagnostic_origin"] == "recomputed_from_legacy_export"
    assert "pricing_rate_dimensions_unresolved" in report["summary"]["concurrent_reasons"]
