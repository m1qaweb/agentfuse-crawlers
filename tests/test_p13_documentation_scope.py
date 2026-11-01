"""P13: exact-URL documentation coverage and review-only child link safety.

All markup is synthetic. No file here approves a vendor claim or publisher
access, and link discovery is explicitly NOT automatic spider scheduling.
"""

from copy import deepcopy

import pytest
from agentfuse_crawlers.documentation_scope import (
    inspect_documentation_dom, load_documentation_profiles,
)
from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.extensions.coverage import _comparable
from scripts.compare_exports import compare, review_queue
from scripts.evaluate_run import _source_identity, _healthy_for_typed_diffs
from scripts.triage_documentation import (
    _safe_csv, triage_documentation_items,
)

ALL = {x["id"]: x for x in load_sources()}


def doc(body, sid="aws_bedrock_docs", head="Documentation"):
    s = ALL[sid]
    return extract_evidence(
        "<html><head><title>" + head + "</title></head><body><main>"
        + body + "</main></body></html>",
        s["url"], category="documentation", source_id=sid,
    )


def record(extraction, sid="aws_bedrock_docs", status="needs_review"):
    src = ALL[sid]
    return {
        **extraction,
        "source_id": sid, "source_url": src["url"],
        "provider": src["provider"], "category": "documentation",
        "status": status, "error": "",
        "approved_for_advisor": False, "http_status": 200,
        "schema_version": "2.1", "sections_truncated": False,
        "documentation_item_budget_truncated": False,
    }


def test_profile_expansion_preserves_460_urls_and_review_only_metadata():
    sources = load_sources()
    profiles = load_documentation_profiles()
    assert len(sources) == 460
    assert len(profiles) == 64
    assert len([s for s in sources if s["category"] == "documentation"]) == 194
    for sid, p in profiles.items():
        src = ALL[sid]
        assert src["category"] == "documentation"
        assert p["source_url"] == src["url"]
        assert p["provider"] == src["provider"]
        assert p["required_scope_markers"]
        assert p["approved_for_advisor"] is False
        assert p["review_status"] == "pending_live_validation"


def test_technical_topic_requires_prose_within_its_own_section():
    s = ALL["aws_bedrock_docs"]
    data = doc(
        "<h1>Amazon Bedrock</h1><h2>Models and supported endpoints</h2>"
        "<ul><li>Catalog</li><li>Models</li></ul>"
        "<h2>General introduction</h2>"
        "<p>This page describes how the Amazon Bedrock service connects "
        "applications to a managed foundation model interface while "
        "explaining the operational considerations for API deployments "
        "and prerequisites associated with service configuration. "
        "Further materials include distinctions between deployment modes, "
        "authentication procedures, operational service boundaries and "
        "limitations which should always be read from exact official "
        "technical product references before making support claims.</p>"
    )
    assert data["documentation_topic_candidates"] == []
    assert data["documentation_scope_status"] == "scope_not_established"
    assert data["documentation_substantive_section_count"] == 1
    assert data["documentation_parser_revision"] == "docs_scope_v2_review_links"
    assert data["documentation_all_capabilities_verified"] is False


def test_locally_corroborated_topic_stays_unverified_and_provenance_scoped():
    data = doc(
        "<h1>Amazon Bedrock</h1><h2 id='models'>Model catalog</h2>"
        "<p>Amazon Bedrock model catalog pages document identity references, "
        "regional requirements, API usage modes and service-specific "
        "configuration details; these source contents require separate review "
        "before any supported-feature conclusion is drawn. "
        "The examples on this page are reference material rather than "
        "guarantees of currently available functions; regional restrictions "
        "and model capability support require confirmation against the "
        "publisher's current, exact model documentation.</p>"
    )
    assert data["documentation_scope_status"] == "scoped_page"
    row = data["documentation_topic_candidates"][0]
    assert row["same_section_substantive_paragraph_count"] == 1
    assert row["topic_evidence_basis"] == "topic_heading_with_local_prose_unverified"
    assert row["approved_for_advisor"] is False
    assert data["documentation_corpus_coverage"] == "single_url_only"
    assert data["documentation_child_pages_automatically_fetched"] == 0


def test_child_links_are_same_host_same_path_family_never_auto_crawled():
    s = ALL["openai_api_docs"]
    body = """
    <h1>OpenAI API documentation</h1>
    <nav><a href='/api/docs/models'>Model reference</a>
    <a href='/api/docs/authentication'>API authentication</a>
    <a href='https://evil.invalid/steal'>API keys</a>
    <a href='/pricing'>Pricing</a>
    <a href='/api/docs/models?token=abc'>Model token link</a>
    <a href='/api/docs/models#private'>Model fragment</a>
    <a href='/api/docs/%2fsecret'>Encoded ambiguity</a>
    <a href='#local'>Current page anchor</a>
    <a href='/api/docs/models'>Duplicate models</a></nav>
    <p>This is an introductory API documentation portal; its links lead to
    separate pages with technical documentation about authentication,
    models, supported interfaces and developer configuration. This page
    does not itself establish any models or feature capability statements.
    Each linked source must be reviewed for intended product relevance,
    official API support and documentation completeness before a technical
    recommendation is made to another developer.</p>
    """
    result = doc(body, sid=s["id"])
    assert result["documentation_scope_status"] == "overview_only"
    assert result["documentation_corpus_coverage"] == "single_url_only"
    assert result["documentation_child_pages_automatically_fetched"] == 0
    links = result["documentation_nav_candidates"]
    assert {x["candidate_url"] for x in links} == {
        "https://developers.openai.com/api/docs/models",
        "https://developers.openai.com/api/docs/authentication",
    }
    assert all(x["found_in"] == "navigation_or_sidebar" for x in links)
    assert all(x["approved_for_crawl"] is False and
               x["approved_for_advisor"] is False for x in links)
    assert result["documentation_nav_candidate_status"] == "review_only_no_fetch"


def test_same_host_other_product_is_never_included_in_document_children():
    result = doc(
        "<h1>Amazon Bedrock</h1><nav>"
        "<a href='/bedrock/latest/userguide/models.html'>Bedrock models</a>"
        "<a href='/sagemaker/latest/dg/home.html'>SageMaker models</a>"
        "<a href='https://other.example/docs/'>Offhost docs</a></nav>"
    )
    urls = [x["candidate_url"] for x in result["documentation_nav_candidates"]]
    assert urls == [
        "https://docs.aws.amazon.com/bedrock/latest/userguide/models.html"
    ]


def test_root_doc_portal_is_not_a_site_wide_child_url_allowlist():
    result = doc(
        "<h1>Mistral AI documentation</h1>"
        "<a href='/models'>Models guide</a>"
        "<a href='/other-product'>Other product</a>",
        sid="mistral_docs",
    )
    assert result["documentation_nav_path_family"] is None
    assert result["documentation_nav_candidates"] == []


def test_kiro_script_shell_is_not_misreported_as_substantive_docs():
    data = doc(
        "<div id='__next'></div>" + "".join(
            "<script src='/static/asset-{0}.js'></script>".format(n)
            for n in range(8)
        ),
        sid="kiro_docs",
    )
    assert data["documentation_static_capture_status"] == "javascript_shell_suspected"
    assert data["documentation_scope_status"] == "insufficient_content"
    assert data["documentation_product_scope"] == "Kiro"
    assert assess_capture("documentation", data, data["text"]) == (
        "needs_review", "documentation_javascript_shell_suspected"
    )
    assert data["documentation_nav_candidates"] == []
    assert data["documentation_all_capabilities_verified"] is False


def test_kiro_header_only_without_shell_keeps_prior_review_reason():
    result = doc("<h1>Kiro docs</h1>", sid="kiro_docs")
    assert result["documentation_static_capture_status"] == "insufficient_static_text"
    assert assess_capture("documentation", result, result["text"]) == (
        "needs_review", "documentation_insufficient_content"
    )


def test_wrong_product_marker_still_blocks_scoped_comparability():
    data = doc(
        "<h1>Generic cloud platform</h1><h2>Model catalog</h2>"
        "<p>This product hosts managed compute and storage infrastructure "
        "and provides regional configuration and usage management tools. "
        "It is not the Bedrock product described in the source registry.</p>"
    )
    # Body-only references, including negative mentions, do not establish
    # source-to-product identity or a technical support claim.
    assert data["documentation_product_scope_signal"] == (
        "body_only_marker_requires_review"
    )
    assert assess_capture("documentation", data, data["text"]) == (
        "needs_review", "documentation_product_marker_only_in_body"
    )
    row = record(data, status="captured")  # Even a mislabeled status is blocked.
    assert not _comparable(row)
    assert not _healthy_for_typed_diffs(row)


def test_explicit_product_mismatch_without_required_marker_rejected():
    data = doc(
        "<h1>Generic cloud service</h1><h2>Model catalog</h2>"
        "<p>This product hosts managed compute and storage infrastructure "
        "and provides regional configuration and usage management tools. "
        "Consult a service-specific guide for usage and compatibility.</p>"
    )
    assert data["documentation_product_scope_signal"] == "marker_not_found"
    assert assess_capture("documentation", data, data["text"]) == (
        "needs_review", "documentation_product_scope_not_demonstrated"
    )


def test_google_cloud_ai_product_migration_requires_review_even_with_marker():
    data = doc(
        "<h1>Gemini Enterprise Agent Platform</h1>"
        "<h2>Regions</h2><p>Gemini Enterprise Agent Platform documentation "
        "explains regional service requirements and configuration details "
        "for developers. API availability, pricing and integration constraints "
        "are subject to product-specific verification.</p>",
        sid="google_cloud_ai_docs",
    )
    row = record(data, "google_cloud_ai_docs", status="captured")
    assert data["documentation_requires_product_review"] is True
    assert not _comparable(row)
    assert not _healthy_for_typed_diffs(row)


def test_canonical_path_review_is_not_a_migration_or_source_baseline():
    src = ALL["aws_bedrock_docs"]
    raw = (
        "<html><head><link rel='canonical' "
        "href='https://docs.aws.amazon.com/bedrock/latest/userguide/other-product.html'>"
        "</head><body><main><h1>Amazon Bedrock</h1>"
        "<p>Detailed technical documentation for service integration and "
        "configuration with restrictions and capability conditions.</p>"
        "</main></body></html>"
    )
    data = extract_evidence(raw, src["url"],
                           category="documentation", source_id=src["id"])
    row = record(data, status="captured")
    assert data["documentation_canonical_relation"] == "same_host_path_differs"
    assert data["documentation_canonical_migration_status"] == (
        "review_required_never_auto_follow"
    )
    assert not _comparable(row)


def test_profile_change_causes_new_baseline_without_approving_new_claim():
    d = doc(
        "<h1>Amazon Bedrock</h1><h2>Model catalog</h2>"
        "<p>Amazon Bedrock reference documentation discusses region scope "
        "and model configuration, subject to verification on the publisher "
        "documentation portal and independent review.</p>"
    )
    current = record(d, status="captured")
    old = deepcopy(current)
    old["documentation_profile_sha256"] = "a" * 64
    assert _source_identity(current) != _source_identity(old)
    assert compare({current["source_id"]: current},
                   {old["source_id"]: old})[0]["change_type"] == "new_baseline"
    assert review_queue({current["source_id"]: current},
                        {old["source_id"]: old},
                        compare({current["source_id"]: current},
                                {old["source_id"]: old})) == []


def test_triage_report_fails_closed_on_malicious_child_links():
    row = record(doc("<h1>OpenAI API docs</h1>", sid="openai_api_docs"),
                 sid="openai_api_docs")
    row["documentation_nav_candidates"] = [{
        "source_id": "openai_api_docs",
        "candidate_url": "https://evil.invalid/steal",
        "review_status": "pending_human_url_and_policy_review",
        "approved_for_crawl": False, "approved_for_advisor": False,
    }]
    with pytest.raises(ValueError, match="Unsafe/unapproved"):
        triage_documentation_items([row])


def test_triage_requires_exact_pinned_source_identity_and_unique_item():
    row = record(doc("<h1>Kiro docs</h1>", sid="kiro_docs"),
                 sid="kiro_docs")
    assert triage_documentation_items([row])["summary"][
        "complete_docs_manifest_accounted"
    ] is False
    with pytest.raises(ValueError, match="Duplicate"):
        triage_documentation_items([row, deepcopy(row)])
    forged = deepcopy(row)
    forged["source_url"] = "https://offhost.invalid/docs"
    with pytest.raises(ValueError, match="mismatched pinned"):
        triage_documentation_items([forged])


def test_triage_handles_p13_source_and_legacy_without_false_coverage():
    page = doc(
        "<h1>OpenAI API docs</h1>"
        "<nav><a href='/api/docs/models'>Model reference</a></nav>",
        sid="openai_api_docs",
    )
    report = triage_documentation_items([
        record(page, sid="openai_api_docs", status="needs_review"),
    ])
    assert report["summary"]["review_child_link_count"] == 1
    assert report["summary"]["advisor_approved_facts"] == 0
    assert report["summary"]["eligible_new_auto_crawl_urls"] == 0
    assert report["sources"][0]["next_review_action"] == (
        "human_review_same_host_child_pages_and_robots"
    )
    legacy = record(page, sid="openai_api_docs")
    legacy.pop("documentation_nav_candidates", None)
    triage = triage_documentation_items([legacy])
    assert triage["summary"]["review_child_link_count"] == 0


def test_never_execute_spreadsheet_formula_from_page_anchor():
    assert _safe_csv("=WEBSERVICE('http://evil.invalid')").startswith("'")
    assert _safe_csv(" @SUM(1,2)").startswith("'")
    assert _safe_csv("Plain docs title") == "Plain docs title"

def test_introductory_body_only_product_reference_requires_review():
    data = doc(
        "<h1>API overview</h1>"
        "<h2>Models</h2><p>Amazon Bedrock provides managed model "
        "interfaces. This paragraph describes integration prerequisites "
        "for applications but does not itself verify current feature "
        "support, regional availability, supported interfaces or exact "
        "billing modes for a deployed product.</p>"
    )
    assert data["documentation_product_scope_signal"] == (
        "body_only_marker_requires_review"
    )
    assert assess_capture("documentation", data, data["text"]) == (
        "needs_review", "documentation_product_marker_only_in_body"
    )
    assert data["documentation_all_capabilities_verified"] is False
