"""P16A: synthetic source/product identity conflicts and observed page families.

Candidate aliases are NOT human-verified brand/product facts. These tests
use invented HTML; they do not prove publisher accuracy or activate adapters.
"""
import json
from collections import Counter
from copy import deepcopy

import pytest
from scrapy.http import HtmlResponse

from agentfuse_crawlers.diagnostics import derive_diagnostics
from agentfuse_crawlers.provider_profiles import (
    REGISTRY_REVISION, identify_source_product, load_provider_profiles,
)
from agentfuse_crawlers.run_context import (
    manifest_sha256, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.spiders.official import (
    DocumentationSpider, PricingSpider,
)
from scripts.audit_provider_identity import audit_source_product_ownership

ALL = {s["id"]: s for s in load_sources()}


def classify(sid, title, **kwargs):
    return identify_source_product(ALL[sid], {
        "title": title, "description": "", "text": "", **kwargs,
    })


def test_exact_source_profiles_cover_high_value_14_products_and_41_ids():
    profiles = load_provider_profiles()
    assert len(load_sources()) == 460
    assert len(profiles) == 41
    assert len({v["product_id"] for v in profiles.values()}) == 14
    assert {s["category"] for s in profiles.values()} == {
        "documentation", "pricing", "changelog",
    }
    for sid, entry in profiles.items():
        src = ALL[sid]
        assert entry["source_url"] == src["url"]
        assert entry["manifest_provider_label"] == src["provider"]
        assert entry["category"] == src["category"]
        assert entry["review_status"] == "pending_original_publisher_review"
        assert entry["title_aliases"]
        assert entry["product_id"]
    assert profiles["gemini_api_pricing"]["product_id"] != (
        profiles["gemini_cli_pricing"]["product_id"]
    )
    assert profiles["claude_code_docs"]["product_id"] != (
        profiles["anthropic_api_docs"]["product_id"]
    )


def test_candidate_title_alias_is_not_verified_product_owner():
    for sid, title, expected in [
        ("openai_api_docs", "API Platform", "openai_api"),
        ("openai_api_pricing", "Pricing | OpenAI API", "openai_api"),
        ("anthropic_api_pricing", "Pricing - Claude Platform Docs",
         "anthropic_api"),
        ("gemini_api_docs", "Gemini API", "gemini_api"),
        ("claude_code_docs", "Overview - Claude Code Docs", "claude_code"),
        ("github_copilot_pricing", "Plans for GitHub Copilot",
         "github_copilot"),
        ("kiro_changelog", "Changelog - Kiro", "kiro"),
    ]:
        result = classify(sid, title)
        assert result["source_expected_product_id"] == expected
        assert result["source_title_alias_evidence_status"] == (
            "title_alias_candidate_unverified"
        )
        assert result["source_title_alias_observed"]
        assert not result["source_product_title_conflict"]
        assert not result["source_product_ownership_verified"]
        assert len(result["source_product_profile_sha256"]) == 64
        assert result["source_adapter_current"] == "generic_scrapy_evidence"
        assert not result["source_specific_adapter_authorized"]
        assert not result["approved_for_advisor"]


def test_contradictory_product_title_cannot_be_reported_as_correct_owner():
    cases = [
        ("anthropic_api_docs", "Documentation for Claude Code"),
        ("claude_code_pricing", "Pricing - Claude Platform"),
        ("gemini_api_docs", "Gemini CLI documentation"),
        ("gemini_cli_docs", "Gemini API Documentation"),
        ("github_copilot_docs", "Microsoft 365 Copilot documentation"),
        ("openai_api_docs", "Codex documentation"),
        ("openai_api_docs", "Azure OpenAI documentation"),
    ]
    for sid, title in cases:
        outcome = classify(sid, title)
        assert outcome["source_product_title_conflict"], (sid, title)
        assert outcome["source_title_alias_evidence_status"] == (
            "title_conflict_requires_review"
        )
        assert outcome["source_title_conflicting_alias_observed"]
        assert outcome["source_adapter_candidate"] is None
        assert not outcome["source_product_ownership_verified"]
        d = derive_diagnostics({
            **outcome,
            "source_id": sid, "category": ALL[sid]["category"],
            "source_url": ALL[sid]["url"],
            "provider": ALL[sid]["provider"],
            "status": "needs_review", "http_status": 200,
            "source_policy_status": "not_reviewed",
            "source_lifecycle_state": "needs_validation",
            "content_sha256": "c" * 64,
        })
        assert "source_product_title_conflict" in d["diagnostic_reason_codes"]
        assert d["quality_axes"]["source_identity_status"] == "review_required"


def test_generic_title_or_body_only_is_not_product_owner_evidence():
    x = classify(
        "openai_api_pricing", "Pricing",
        text="Welcome to the OpenAI API pricing portal. "
             "These paragraphs are marketing descriptions only.",
    )
    assert x["source_title_alias_evidence_status"] == (
        "body_only_not_owner_proof"
    )
    assert not x["source_product_ownership_verified"]
    assert not x["source_product_title_conflict"]
    d = derive_diagnostics({
        **x, "source_id": "openai_api_pricing",
        "source_url": ALL["openai_api_pricing"]["url"],
        "status": "needs_review", "category": "pricing",
        "source_policy_status": "not_reviewed",
        "source_lifecycle_state": "needs_validation",
    })
    assert "source_product_alias_not_in_title" in d["diagnostic_reason_codes"]
    assert d["quality_axes"]["source_identity_status"] == "review_required"
    desc_only = classify("kiro_docs", "Documentation",
                         description="Kiro setup reference")
    assert desc_only["source_title_alias_evidence_status"] == (
        "description_only_not_owner_proof"
    )


def test_incorrect_brand_substring_and_ambiguous_title_are_not_proof():
    cursor = classify("cursor_docs", "Recursor overview")
    assert cursor["source_title_alias_evidence_status"] == (
        "title_does_not_establish_product_owner"
    )
    xai = classify(
        "xai_docs", "Get started with SpaceX Super Intelligence",
    )
    assert xai["source_expected_product_id"] == "xai"
    assert xai["source_title_alias_evidence_status"] == (
        "title_does_not_establish_product_owner"
    )
    assert not xai["source_product_ownership_verified"]
    ambiguous = classify(
        "aws_bedrock_docs", "Overview",
    )
    assert ambiguous["source_title_alias_evidence_status"] == (
        "title_does_not_establish_product_owner"
    )


def test_unprofiled_source_is_not_assigned_an_arbitrary_product():
    source = ALL["supabase_pricing"]
    r = identify_source_product(source, {
        "title": "OpenAI API price guide",
        "pricing_table_relevant": 4,
        "pricing_observations": [{
            "billing_unit": "per_1m_tokens",
            "model_or_service": "Model Alpha",
        }],
    })
    assert r["source_product_profile_status"] == "not_profiled"
    assert r["source_expected_product_id"] is None
    assert r["source_expected_provider_id"] is None
    assert r["source_adapter_candidate"] is None
    assert r["source_page_family_candidate"] == (
        "token_rate_matrix_candidate"
    )


def test_page_family_requires_actual_structural_evidence_not_provider_name():
    source = "openai_api_pricing"
    for evidence, label in [
        ({"pricing_table_relevant": 4,
          "pricing_observations": [{
              "billing_unit": "per_1m_tokens", "approved_for_advisor": False,
          }]}, "token_rate_matrix_candidate"),
        ({"pricing_table_relevant": 4,
          "pricing_observations": [{
              "billing_unit": "per_month", "approved_for_advisor": False,
          }]}, "subscription_table_candidate"),
        ({"pricing_table_relevant": 3, "pricing_card_total": 4},
         "mixed_table_card_candidate"),
        ({"pricing_card_total": 8}, "pricing_cards_candidate"),
        ({}, "pricing_markup_unresolved"),
    ]:
        result = classify(source, "Pricing | OpenAI API", **evidence)
        assert result["source_page_family_candidate"] == label
        assert result["source_adapter_candidate"] == label
        assert result["source_adapter_selection_status"] == (
            "review_only_no_adapter_enabled"
        )
        assert not result["source_specific_adapter_authorized"]
    doc = classify(
        "kiro_docs", "Docs - Kiro",
        documentation_static_capture_status="javascript_shell_suspected",
        documentation_scope_status="insufficient_content",
    )
    assert doc["source_page_family_candidate"] == (
        "javascript_doc_shell_candidate"
    )
    changes = classify(
        "kiro_changelog", "Changelog - Kiro",
        release_events=[{
            "event_id": "kiro:abc", "published_at": "2026-10-30"
        }],
        release_window_complete=False,
    )
    assert changes["source_page_family_candidate"] == (
        "partial_release_event_candidates"
    )


def test_exact_profile_source_pins_reject_wrong_domain_or_provider():
    src = dict(ALL["openai_api_pricing"])
    for change in [
        {"url": "https://evil.invalid/pricing"},
        {"provider": "OpenAI & Azure"},
        {"category": "documentation"},
    ]:
        modified = dict(src, **change)
        with pytest.raises(ValueError, match="does not match pinned"):
            identify_source_product(modified, {"title": "OpenAI API Pricing"})


def test_unreviewed_alias_registry_rejects_fabricated_approval_and_url(
        monkeypatch, tmp_path):
    import agentfuse_crawlers.provider_profiles as profiles
    original = json.loads(profiles.DATA_PATH.read_text())
    for mutation in (
        lambda o: o.update(approved_for_advisor=True),
        lambda o: o.update(
            automatic_provider_specific_adapter_selection=True
        ),
        lambda o: o["products"][0]["source_ids"][0].update(
            official_source_url="https://evil.invalid/replaced"
        ),
        lambda o: o["products"][0].update(
            title_aliases_candidate_unreviewed=["Pricing"]
        ),
        lambda o: o["products"][0].update(
            source_identity_review_status="already_verified"
        ),
    ):
        payload = deepcopy(original)
        mutation(payload)
        file = tmp_path / "providers_bad.json"
        file.write_text(json.dumps(payload))
        profiles.load_provider_profiles.cache_clear()
        with monkeypatch.context() as ctx:
            ctx.setattr(profiles, "DATA_PATH", file)
            with pytest.raises(ValueError):
                profiles.load_provider_profiles()
        profiles.load_provider_profiles.cache_clear()
    assert len(profiles.load_provider_profiles()) == 41


def test_real_spider_rejects_contradictory_product_title_without_new_crawls():
    sid = "anthropic_api_pricing"
    src = ALL[sid]
    spider = PricingSpider(cohort="all", source_ids=sid,
                           collection_mode="validation")
    body = (
        "<html><head><title>Claude Code pricing</title></head>"
        "<body><main><h1>Claude Code pricing</h1>"
        "<p>Detailed customer plan pricing page for a different product, "
        "not an authorization to attribute an Anthropic API token rate. "
        "The client-side pricing plan prices may change by plan, region, "
        "currency, subscription period, and other publisher conditions.</p>"
        "</main></body></html>"
    )
    response = HtmlResponse(
        url=src["url"], status=200, body=body.encode(),
        headers={"Content-Type": "text/html"}, encoding="utf-8",
    )
    items = list(spider.parse_page(response, src))
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "needs_review"
    assert item["error"] == "source_product_title_conflict"
    assert item["source_product_title_conflict"] is True
    assert item["source_expected_product_id"] == "anthropic_api"
    assert "source_product_title_conflict" in item["diagnostic_reason_codes"]
    assert item["approved_for_advisor"] is False
    assert item["source_specific_adapter_authorized"] is False


def test_normal_title_does_not_modify_existing_generic_spider_status():
    sid = "openai_api_pricing"
    src = ALL[sid]
    spider = PricingSpider(cohort="all", source_ids=sid)
    body = (
        "<html><head><title>Pricing | OpenAI API</title></head>"
        "<body><main><h1>Pricing | OpenAI API</h1>"
        "<p>Official publisher content is only unverified observation, "
        "never an approved financial fact. The scope, currency, model, "
        "billing unit, and conditions require independently checked "
        "publisher evidence before any recommendation is made.</p>"
        "</main></body></html>"
    )
    response = HtmlResponse(
        url=src["url"], status=200, body=body.encode(),
        headers={"Content-Type": "text/html"}, encoding="utf-8",
    )
    items = list(spider.parse_page(response, src))
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "needs_review"
    assert item["error"] in {
        "pricing_no_structured_rate_evidence",
        "pricing_rate_dimensions_unresolved",
        "no_price_or_billing_detail_detected",
        "insufficient_substantive_text",
    }
    assert item["source_expected_product_id"] == "openai_api"
    assert not item["source_product_title_conflict"]
    assert not item["source_product_ownership_verified"]


def _synthetic_460_items():
    categorized = {}
    package = "b" * 64
    for category in ("pricing", "documentation", "changelog"):
        sources = select_sources(category, "all")
        items = []
        for src in sources:
            allowed = collection_decision(src, "validation")[0]
            items.append({
                "source_id": src["id"],
                "category": category, "source_url": src["url"],
                "provider": src["provider"],
                "spider_name": {
                    "pricing": "official_pricing",
                    "documentation": "official_documentation",
                    "changelog": "official_changelogs",
                }[category],
                "zyte_job_id": {
                    "pricing": "883514/3/101",
                    "documentation": "883514/2/101",
                    "changelog": "883514/1/101",
                }[category],
                "manifest_sha256": manifest_sha256(),
                "source_registry_sha256": registry_revision_sha256(),
                "selection_ids_sha256": selection_ids_sha256(sources),
                "selection_source_count": len(sources),
                "requested_cohort": "all", "run_scope_explicit": True,
                "collection_mode": "validation",
                "deployment_revision_kind": "package_py_json_sha256_v1",
                "deployment_revision": package,
                "approved_for_advisor": False,
                "source_policy_status": (
                    "not_reviewed" if allowed else "unresolved"
                ),
                "source_lifecycle_state": (
                    "needs_validation" if allowed else "quarantined"
                ),
                "status": "needs_review" if allowed else "source_quarantined",
                "http_status": 200 if allowed else None,
                "content_sha256": "c" * 64 if allowed else None,
                "pricing_observations": [],
                "documentation_topic_candidates": [],
                "release_events": [],
                "title": "Pricing | OpenAI API" if src["id"] ==
                         "openai_api_pricing" else "",
            })
        categorized[category] = items
    return categorized


def test_offline_full_inventory_review_preserves_460_without_claiming_truth(
        tmp_path):
    data = _synthetic_460_items()
    result = audit_source_product_ownership(data)
    summary = result["summary"]
    assert summary["source_item_count"] == 460
    assert summary["profiled_source_records"] == 41
    assert summary["unprofiled_source_records"] == 419
    assert summary["verified_product_ownership_claims"] == 0
    assert summary["automatically_selected_specific_adapters"] == 0
    assert summary["new_crawl_requests"] == 0
    assert summary["observed_title_signals"]["title_alias_candidate_unverified"] == 1
    assert len(result["sources"]) == 460
    src = next(x for x in result["sources"]
               if x["source_id"] == "openai_api_pricing")
    assert src["expected_product_id"] == "openai_api"
    assert src["observed_page_family"] == "pricing_markup_unresolved"
    assert src["review_action"] == "review_official_title_and_product_owner"
    assert not src["adapter_activated"]
    from scripts.audit_provider_identity import write_ownership_audit
    write_ownership_audit(result, tmp_path)
    assert (tmp_path / "source_product_review_queue.csv").exists()
    assert (tmp_path / "source_product_ownership_summary.json").exists()
    # A title is never enough to approve a product owner.
    assert all(x["review_action"] != "approve_product_identity"
               for x in result["sources"])


def test_offline_audit_aborts_if_a_manifest_source_is_missing():
    data = _synthetic_460_items()
    data["documentation"].pop()
    with pytest.raises(ValueError, match="Missing or extra"):
        audit_source_product_ownership(data)
