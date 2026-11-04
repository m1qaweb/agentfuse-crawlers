"""P06: strict lifecycle, honest policy states and offline source triage."""

import asyncio
import json

import pytest
from scrapy import Request

from agentfuse_crawlers.source_lifecycle import (
    _same_official_host_evidence,
    _validate_approval,
    collection_decision,
    load_lifecycle_registry,
    registry_revision_sha256,
    source_lifecycle,
    source_lifecycle_summary,
)
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.spiders.official import (
    ChangelogSpider, DocumentationSpider, PricingSpider,
)
from scripts.triage_sources import _safe_url, generate_triage, write_triage


SOURCES = {source["id"]: source for source in load_sources()}


async def _run_start(spider):
    return [entry async for entry in spider.start()]


def test_460_source_manifest_remains_unmodified_and_unapproved():
    summary = source_lifecycle_summary()
    assert summary["manifest_source_count"] == 460
    assert summary["states"]["quarantined"] == 3
    assert summary["states"]["degraded"] == 3
    assert summary["states"]["needs_validation"] == 454
    assert summary["reviewed_collection_eligible"] == 0
    assert len(registry_revision_sha256()) == 64
    assert summary["source_registry_sha256"] == registry_revision_sha256()


def test_every_override_is_pinned_to_the_exact_approved_manifest_source_url():
    registry = load_lifecycle_registry()
    assert registry["default_state"] == "needs_validation"
    for sid, profile in registry["overrides"].items():
        assert profile["source_url"] == SOURCES[sid]["url"]
        assert profile["approval"] is None
        assert profile["state"] != "validated_for_collection"


@pytest.mark.parametrize("id", ["v0_docs", "v0_pricing", "v0_changelog"])
def test_unresolved_v0_is_quarantined_even_when_id_is_explicit(id):
    source = SOURCES[id]
    profile = source_lifecycle(source)
    assert profile["policy_status"] == "unresolved"
    assert profile["state"] == "quarantined"
    for mode in ("validation", "monitor"):
        assert collection_decision(source, mode) == (
            False, "policy_unresolved_or_quarantined"
        )
    spider_type = {
        "documentation": DocumentationSpider,
        "pricing": PricingSpider,
        "changelog": ChangelogSpider,
    }[source["category"]]
    spider = spider_type(cohort="all", source_ids=id, collection_mode="validation")
    emitted = asyncio.run(_run_start(spider))
    assert len(emitted) == 1
    assert isinstance(emitted[0], dict)
    assert emitted[0]["status"] == "source_quarantined"
    assert emitted[0]["http_status"] is None
    assert emitted[0]["source_policy_status"] == "unresolved"
    assert emitted[0]["approved_for_advisor"] is False


def test_unreviewed_proven_crawl_is_not_assumed_allowed_for_monitor():
    source = SOURCES["openai_api_docs"]
    assert source_lifecycle(source)["state"] == "needs_validation"
    assert collection_decision(source, "monitor") == (
        False, "monitor_requires_reviewed_collection_approval"
    )
    spider = DocumentationSpider(source_ids=source["id"], collection_mode="monitor")
    emitted = asyncio.run(_run_start(spider))
    assert len(emitted) == 1 and isinstance(emitted[0], dict)
    assert emitted[0]["status"] == "source_not_validated_for_monitor"
    assert emitted[0]["collection_eligible_for_unattended"] is False
    assert emitted[0]["requested_cohort"] == "proven"


def test_default_three_source_smoke_now_holds_all_unreviewed_urls():
    # P21B: even the old implicit proven cohort of three is multi-source
    # validation. It may not trigger three publisher GETs without a
    # real source-by-source Git-reviewed authorization and run plan.
    for spider_type in (DocumentationSpider, PricingSpider, ChangelogSpider):
        spider = spider_type()
        emitted = asyncio.run(_run_start(spider))
        assert len(emitted) == 3
        assert all(isinstance(entry, dict) for entry in emitted)
        assert all(entry["status"] == "source_bulk_validation_not_approved"
                   and entry["http_status"] is None for entry in emitted)
        assert all(entry["quality_axes"]["fetch_status"] ==
                   "not_attempted_by_bulk_access_policy" for entry in emitted)
        assert spider.source_registry_sha256 == registry_revision_sha256()
        assert spider.collection_mode == "validation"
        sample = spider._base_record(spider.selected[0])
        assert sample["source_policy_status"] == "not_reviewed"
        assert sample["source_lifecycle_state"] == "needs_validation"
        assert sample["collection_mode"] == "validation"
        assert sample["approved_for_advisor"] is False
        assert sample["validation_scope"] == "bulk_reviewed_plan_required"


def test_explicit_all_cohort_does_not_fetch_quarantined_urls():
    spider = DocumentationSpider(
        cohort="all", confirm_full_inventory="yes", source_ids="v0_docs"
    )
    emitted = asyncio.run(_run_start(spider))
    assert len(emitted) == 1
    assert not isinstance(emitted[0], Request)


def test_degraded_source_remains_validation_only():
    source = SOURCES["kiro_docs"]
    assert source_lifecycle(source)["state"] == "degraded"
    assert collection_decision(source, "validation") == (
        True, "manual_validation_only"
    )
    assert collection_decision(source, "monitor")[0] is False


def test_invalid_mode_fails_closed_in_spider_and_decision():
    with pytest.raises(ValueError, match="collection_mode"):
        DocumentationSpider(collection_mode="bypass")
    with pytest.raises(ValueError, match="collection_mode"):
        collection_decision(SOURCES["openai_api_docs"], "forced")


def test_registry_refuses_fabricated_url_and_unknown_id():
    with pytest.raises(ValueError, match="exact current manifest"):
        source_lifecycle(dict(SOURCES["openai_api_docs"], url="https://evil.invalid/docs"))
    with pytest.raises(ValueError, match="exact current manifest"):
        source_lifecycle(dict(SOURCES["openai_api_docs"], id="unlisted_docs"))


def test_reviewer_evidence_refuses_cross_host_http_query_credentials_and_ip():
    original = SOURCES["openai_api_docs"]["url"]
    assert _same_official_host_evidence(original, original)
    for candidate in (
        "http://developers.openai.com/docs",
        "https://evil.invalid/docs",
        "https://user:secret@developers.openai.com/docs",
        "https://developers.openai.com:1234/docs",
        "https://developers.openai.com/docs?token=topsecret",
        "https://127.0.0.1/docs",
        "https://developers.openai.com:bad/docs",
    ):
        assert not _same_official_host_evidence(candidate, original)


def test_manual_approval_contract_requires_two_distinct_runs_and_policy_evidence():
    source = SOURCES["openai_api_docs"]
    approval = {
        "reviewed_by": "named-source-reviewer",
        "reviewed_at_utc": "2026-10-31T09:30:00Z",
        "official_ownership_url": source["url"],
        "publisher_access_policy_url": source["url"],
        "product_scope": "OpenAI API",
        "successful_job_ids": ["example-job-one", "example-job-two"],
    }
    _validate_approval(source, {"approval": approval})
    with pytest.raises(ValueError):
        _validate_approval(source, {"approval": dict(approval, successful_job_ids=["same", "same"])})
    with pytest.raises(ValueError):
        _validate_approval(source, {"approval": dict(approval, reviewed_at_utc="2026-10-31")})
    with pytest.raises(ValueError):
        _validate_approval(source, {"approval": dict(approval, official_ownership_url="https://evil.invalid")})


def test_triage_without_exports_is_honest_about_all_460_unknowns():
    rows = generate_triage({})
    assert len(rows) == 460
    assert {x["review_status"] for x in rows} == {"pending_human_review"}
    assert all(x["observed_status"] == "unobserved" for x in rows)
    assert all("not_observed_in_supplied_exports" in x["finding_codes"] for x in rows)
    assert next(x for x in rows if x["source_id"] == "v0_docs")["policy_status"] == "unresolved"


def test_real_failure_patterns_remain_pending_not_approved():
    item = {
        "source_id": "openai_api_docs",
        "source_url": SOURCES["openai_api_docs"]["url"],
        "http_status": 403,
        "status": "http_error",
        "error": "HTTP 403",
        "fetched_at_utc": "2026-10-31T12:00:00Z",
    }
    rows = generate_triage({item["source_id"]: item})
    doc = next(x for x in rows if x["source_id"] == item["source_id"])
    assert "http_403_404_source_repair" in doc["finding_codes"]
    assert doc["review_status"] == "pending_human_review"
    assert doc["source_url"] == item["source_url"]
    assert "not_observed_in_supplied_exports" not in doc["finding_codes"]


def test_redirect_and_canonical_review_never_autocorrects_registry():
    sid = "kiro_docs"
    observed = {
        "source_id": sid, "status": "rejected_redirect",
        "error": "cross_host_or_non_https_redirect",
        "http_status": 301, "fetched_at_utc": "2026-10-31T12:00:00Z",
        "source_url": SOURCES[sid]["url"],
        "final_url": "https://user:secret@evil.invalid/new?q=token",
        "canonical_url": "https://kiro.dev/docs/new-path?token=secret",
    }
    rows = generate_triage({sid: observed})
    row = next(x for x in rows if x["source_id"] == sid)
    assert "publisher_migration_or_redirect_review" in row["finding_codes"]
    assert row["review_status"] == "pending_human_review"
    assert row["observed_final_url"] == ""
    assert row["observed_canonical_url"] == "https://kiro.dev/docs/new-path"
    assert row["source_url"] == SOURCES[sid]["url"]


def test_cache_age_is_only_uncertainty_not_a_vendor_release_date():
    sid = "gemini_api_docs"
    item = {
        "source_id": sid, "status": "captured", "http_status": 200,
        "reported_cache_age_seconds": 172800,
    }
    row = next(x for x in generate_triage({sid: item}) if x["source_id"] == sid)
    assert "long_cdn_age_uncertain_not_publish_date" in row["finding_codes"]
    assert "effective_date" not in json.dumps(row)


def test_pricing_review_and_empty_kiro_capture_never_become_facts():
    snapshots = {
        "aws_bedrock_pricing": {
            "source_id": "aws_bedrock_pricing",
            "status": "partial_capture",
            "error": "pricing_rate_dimensions_unresolved",
            "pricing_inventory_complete": False,
        },
        "kiro_docs": {
            "source_id": "kiro_docs", "status": "needs_review",
            "error": "insufficient_substantive_text", "word_count": 0,
        },
    }
    rows = {x["source_id"]: x for x in generate_triage(snapshots)}
    assert "pricing_table_inventory_incomplete" in rows["aws_bedrock_pricing"]["finding_codes"]
    assert "pricing_scope_or_billing_review" in rows["aws_bedrock_pricing"]["finding_codes"]
    assert "insufficient_html_or_js_shell" in rows["kiro_docs"]["finding_codes"]
    assert rows["kiro_docs"]["lifecycle_state"] == "degraded"


def test_triage_refuses_unknown_ids_and_does_not_persist_approval(tmp_path):
    with pytest.raises(ValueError, match="unknown source IDs"):
        generate_triage({"fabricated_vendor_docs": {"source_id": "fabricated_vendor_docs"}})
    rows = generate_triage({
        "v0_docs": {"source_id": "v0_docs", "status": "source_quarantined"},
    })
    result = write_triage(rows, tmp_path)
    assert result["source_count"] == 460
    assert result["automatically_approved_sources"] == 0
    assert result["approved_for_advisor"] is False
    parsed = json.loads((tmp_path / "source_review_queue.json").read_text())
    assert len(parsed) == 460
    assert (tmp_path / "source_review_queue.csv").exists()


def test_triage_safe_url_never_leaks_token_or_password():
    assert _safe_url("https://example.com/path?q=secret") == "https://example.com/path"
    assert _safe_url("https://user:secret@example.com/path") == ""
    assert _safe_url("http://example.com/path") == ""


def test_pinned_registry_hash_rejects_unexpected_policy_edits():
    expected = registry_revision_sha256()
    spider = DocumentationSpider(
        source_ids="openai_api_docs",
        expected_source_registry_sha256=expected,
    )
    assert spider.source_registry_sha256 == expected
    with pytest.raises(ValueError, match="Source registry changed"):
        DocumentationSpider(
            source_ids="openai_api_docs",
            expected_source_registry_sha256="0" * 64,
        )


def test_validation_planner_accounts_for_quarantined_urls_without_disappearing():
    from scripts.plan_validation import plan_validation

    plan = plan_validation(cohort="candidate", batch_size=100)
    assert plan["source_registry_sha256"] == registry_revision_sha256()
    assert plan["monitor_approved_source_count"] == 0
    assert plan["collection_mode"] == "validation"
    flattened = {id for batch in plan["batches"] for id in batch["source_ids"]}
    assert {"v0_docs", "v0_pricing", "v0_changelog"} <= flattened
    for batch in plan["batches"]:
        assert batch["expected_source_registry_sha256"] == registry_revision_sha256()
        assert batch["expected_network_requests"] == (
            batch["requested_count"] - len(batch["skipped_by_policy_source_ids"])
        )
    quarantined = {
        id for batch in plan["batches"] for id in batch["skipped_by_policy_source_ids"]
    }
    assert quarantined == {"v0_docs", "v0_pricing", "v0_changelog"}


def test_rejected_redirect_keeps_review_only_redacted_target():
    from scrapy.http import HtmlResponse

    source = SOURCES["openai_api_docs"]
    spider = DocumentationSpider(source_ids=source["id"])
    req = Request(source["url"])
    response = HtmlResponse(
        url=source["url"], status=302, request=req,
        headers={"Location": "https://new.example.org/docs?auth=secret"},
        body=b"", encoding="utf-8",
    )
    item = list(spider.parse_page(response, source))[0]
    assert item["status"] == "rejected_redirect"
    assert item["redirect_review_target"] == "https://new.example.org/docs"
    assert item["approved_for_advisor"] is False


def test_historical_audit_import_is_labeled_unverified_and_not_approved(tmp_path):
    from scripts.triage_sources import read_historical_audit

    audit = {
        "audit_date": "2026-10-31",
        "total_source_records": 1,
        "all_captures_unverified": True,
        "sources": [{
            "source_id": "kiro_docs",
            "source_url": SOURCES["kiro_docs"]["url"],
            "status": "needs_review",
            "error": "insufficient_substantive_text",
            "word_count": 0,
            "approved_for_advisor": False,
        }],
    }
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(audit), encoding="utf-8")
    observed = read_historical_audit(path)
    result = write_triage(
        generate_triage(observed), tmp_path / "triage",
        input_basis="historical_compiled_audit_not_live_verified",
    )
    assert result["observed_in_supplied_exports"] == 1
    assert result["unobserved_in_supplied_exports"] == 459
    assert result["input_basis"] == "historical_compiled_audit_not_live_verified"
    assert result["approved_for_advisor"] is False
    path.write_text(json.dumps(dict(audit, total_source_records=2)), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid or not explicitly"):
        read_historical_audit(path)
    path.write_text(json.dumps(dict(audit, sources=[
        dict(audit["sources"][0], approved_for_advisor=True)
    ])), encoding="utf-8")
    with pytest.raises(ValueError, match="unapproved"):
        read_historical_audit(path)
