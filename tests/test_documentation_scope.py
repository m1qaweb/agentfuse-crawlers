"""P05: documentation page scope and canonical review safety regressions."""

import json

from agentfuse_crawlers.documentation_scope import (
    _serialized_size, canonical_relationship, compact_documentation_record,
    extract_documentation_evidence, load_documentation_profiles,
)
from agentfuse_crawlers.extensions.coverage import _comparable
from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.sources import load_sources


def html(markup, source_id, url):
    return extract_evidence(
        "<html><head><title>Documentation</title></head><body><main>" +
        markup + "</main></body></html>",
        url, category="documentation", source_id=source_id,
    )


def test_profiles_are_pinned_without_growing_or_rewriting_460_urls():
    profiles = load_documentation_profiles()
    sources = load_sources()
    assert len(sources) == 460
    assert len(profiles) == 22
    manifest = {x["id"]: x for x in sources}
    assert all(manifest[sid]["url"] == p["source_url"] for sid, p in profiles.items())
    assert all(p["approved_for_advisor"] is False for p in profiles.values())


def test_kiro_historical_empty_crawl_remains_explicitly_unusable():
    ev = html("<h1>Kiro documentation</h1>", "kiro_docs", "https://kiro.dev/docs/")
    assert ev["documentation_product_scope"] == "Kiro"
    assert ev["documentation_known_capture_issue"]
    assert ev["documentation_scope_status"] == "insufficient_content"
    assert ev["documentation_corpus_coverage"] == "single_url_only"
    assert assess_capture("documentation", ev, ev["text"]) == (
        "needs_review", "documentation_insufficient_content"
    )


def test_kiro_link_only_index_does_not_count_as_complete_technical_docs():
    links = "".join(
        f'<a href="/docs/guide-{i}/">Guide {i} integration details and topics</a>'
        for i in range(32)
    )
    ev = html("<h1>Kiro docs</h1><div>" + links + "</div>",
              "kiro_docs", "https://kiro.dev/docs/")
    assert ev["documentation_scope_status"] == "index_only"
    assert not ev["documentation_topic_candidates"]
    assert ev["documentation_all_capabilities_verified"] is False
    assert assess_capture("documentation", ev, ev["text"]) == (
        "needs_review", "documentation_link_index_only"
    )


def test_scoped_reference_yields_topics_with_evidence_not_support_claims():
    url = "https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html"
    ev = html(
        "<h1>Amazon Bedrock</h1>"
        "<p>This documentation introduces the Amazon Bedrock service and its "
        "technical interfaces, deployment configuration, and prerequisites for "
        "building applications through managed foundation model services.</p>"
        "<h2 id='models'>Supported model catalog</h2>"
        "<p>Available model listings are organized in the platform reference "
        "and their applicability depends on provider, service location and "
        "request mode; consult each referenced entry for the latest limits.</p>"
        "<p>Detailed sections discuss service availability, compatibility, "
        "workload restrictions and interfaces used by application developers.</p>",
        "aws_bedrock_docs", url,
    )
    assert ev["documentation_evidence_schema"] == "1.0"
    assert ev["documentation_scope_status"] == "scoped_page"
    assert ev["documentation_product_scope"] == "Amazon Bedrock"
    assert ev["documentation_topic_candidates"]
    row = ev["documentation_topic_candidates"][0]
    assert row["topic_hint"] == "model_catalog"
    assert row["section_sha256"] and row["source_url"].startswith(url)
    assert row["capability_support_verified"] is False
    assert row["approved_for_advisor"] is False
    assert ev["documentation_corpus_coverage"] == "single_url_only"


def test_overview_remains_overview_even_when_it_mentions_features():
    url = "https://developers.openai.com/api/docs"
    ev = html(
        "<h1>OpenAI API documentation</h1>"
        "<p>This is an introductory portal to the API documentation, covering "
        "general concepts for developers and the available reference pages. "
        "Detailed implementation instructions live on their own pages.</p>"
        "<h2>Authentication and API keys</h2>"
        "<p>Read the authentication reference for precise permission and "
        "identity requirements. This page summarizes the API onboarding path.</p>"
        "<p>Explore the rest of the documentation for full details, limitations, "
        "supported operations, restrictions and availability.</p>",
        "openai_api_docs", url,
    )
    assert ev["documentation_scope_status"] == "overview_only"
    row = dict(ev, category="documentation", status="captured")
    assert not _comparable(row)
    assert ev["documentation_all_capabilities_verified"] is False


def test_profiles_fail_closed_on_url_or_product_scope_mismatch():
    ev = html(
        "<h1>Another product</h1><p>" + ("Detailed technical instructions. " * 12)
        + "</p>", "openai_api_docs", "https://developers.openai.com/other-docs"
    )
    assert ev["documentation_profile_status"] == "profile_url_mismatch"
    assert assess_capture("documentation", ev, ev["text"]) == (
        "needs_review", "documentation_source_profile_url_mismatch"
    )


def test_google_cloud_known_scope_change_is_not_silently_approved():
    url = "https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning"
    ev = html(
        "<h1>Gemini Enterprise Agent Platform</h1><p>" +
        ("Product-specific technical guidance and prerequisites. " * 12)
        + "</p>", "google_cloud_ai_docs", url
    )
    assert ev["documentation_requires_product_review"] is True
    assert ev["documentation_product_scope"] == "Gemini Enterprise Agent Platform"
    assert assess_capture("documentation", ev, ev["text"]) == (
        "needs_review", "documentation_product_scope_ambiguous"
    )


def test_canonical_equivalences_do_not_trigger_foreign_source_trust():
    base = "https://kiro.dev/docs/"
    assert canonical_relationship(base, "https://kiro.dev/docs/index.html")["relation"] == "equivalent_path"
    assert canonical_relationship(base, "https://kiro.dev/docs")["relation"] == "equivalent_path"
    assert canonical_relationship(base, "https://kiro.dev/docs/other-product/")["relation"] == "same_host_path_differs"
    ignored = canonical_relationship(base, "https://external.example/docs/")
    assert ignored["relation"] == "external_or_unsafe_ignored"
    assert ignored["review_url"] is None
    assert canonical_relationship(base, "http://kiro.dev/docs/")["relation"] == "external_or_unsafe_ignored"


def test_topic_heading_without_substantive_body_is_not_a_fact():
    ev = extract_documentation_evidence(
        "https://official.example/docs/reference", "unknown_docs",
        sections=[{"heading": "Model support", "excerpt": "Models", "section_id": "1",
                   "section_url": "https://official.example/docs/reference#1",
                   "sha256": "abc"}],
        title="Models", text="Models", prose_paragraphs=0, link_text_ratio=0.0,
    )
    assert ev["documentation_topic_candidates"] == []
    assert ev["documentation_profile_status"] == "unprofiled"


def test_bounded_documentation_item_discloses_omissions():
    record = {
        "status": "captured", "source_id": "aws_bedrock_docs",
        "source_url": "https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html",
        "content_sha256": "full-hash", "approved_for_advisor": False,
        "text": "long " * 7000,
        "sections": [{"section_id": "1", "excerpt": "section " * 1500,
                      "sha256": "unchanged-full-hash"}],
        "tables": [{"rows": ["large " * 3000]}],
        "documentation_topic_candidates": [
            {"source_url": "https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html",
             "excerpt": "support " * 2000}],
        "documentation_topic_candidate_omitted": 0,
    }
    bounded = compact_documentation_record(record, record["text"], target_bytes=6000)
    assert _serialized_size(bounded) <= 6000
    assert bounded["status"] == "partial_capture"
    assert bounded["documentation_item_budget_truncated"] is True
    assert bounded["tables_truncated"] is True
    assert bounded["content_sha256"] == "full-hash"
    assert bounded["approved_for_advisor"] is False
    assert bounded["documentation_tables_evidence_omitted"] == 1


def test_bounded_documentation_sections_report_truncation():
    url = "https://official.example/docs/reference"
    many = "<h1>Technical documentation</h1>" + "".join(
        f"<h2>Configuration {i}</h2><p>Technical reference specification and "
        f"associated functionality for implementing scoped applications {i}.</p>"
        for i in range(90)
    )
    ev = html(many, "unprofiled_docs", url)
    assert ev["sections_truncated"] is True
    assert ev["documentation_source_sections_truncated"] is True
    assert ev["documentation_corpus_coverage"] == "single_url_only"
    assert ev["documentation_all_capabilities_verified"] is False


def test_wrong_product_page_cannot_inherit_bedrock_scope_from_profile():
    url = "https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html"
    ev = html(
        "<h1>Generic cloud infrastructure</h1><p>" +
        ("This document describes a separate compute and storage service. " * 10)
        + "</p>", "aws_bedrock_docs", url,
    )
    assert ev["documentation_product_scope_signal"] == "marker_not_found"
    assert assess_capture("documentation", ev, ev["text"]) == (
        "needs_review", "documentation_product_scope_not_demonstrated"
    )


def test_canonical_case_and_parameters_are_not_assumed_equivalent():
    url = "https://docs.example.com/API/docs/"
    assert canonical_relationship(
        url, "https://docs.example.com/api/docs/"
    )["relation"] == "same_host_path_differs"
    assert canonical_relationship(
        url, "https://docs.example.com/API/docs/?product=other"
    )["relation"] == "same_host_parameters_review"
    assert canonical_relationship(
        url, "https://docs.example.com:bad/API/docs/"
    )["relation"] == "external_or_unsafe_ignored"
