"""Deterministic, unverified documentation scope and section evidence.

One configured documentation URL is one observed *page*, never proof of
the whole docs corpus or of product capability support.
"""

import hashlib
import json
import re
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit, urlunsplit

from agentfuse_crawlers.sources import load_sources

SCHEMA_VERSION = "1.0"
MAX_CANDIDATES = 16
MAX_EXCERPT = 520
ALLOWED_PAGE_TYPES = frozenset({"overview", "guide", "reference", "index"})
TOPIC_PATTERNS = {
    "model_catalog": r"\b(models?|model catalog|available models?)\b",
    "authentication": r"\b(auth(entication|orization)?|api keys?|oauth|credentials?)\b",
    "rate_limits": r"\b(rate limits?|quotas?|throughput|usage limits?)\b",
    "regions": r"\b(regions?|geograph(y|ic)|availability zones?)\b",
    "modalities": r"\b(multimodal|image|audio|video|vision|modalities)\b",
    "tool_use": r"\b(tool( calling| use)?|function calling|function calls?)\b",
    "tools_and_mcp": r"\b(mcp|tools?|integrations?|extensions?)\b",
    "structured_output": r"\b(structured output|json schema|json mode)\b",
    "sdk": r"\b(sdks?|client librar(y|ies)|quickstart|installation)\b",
    "limitations": r"\b(limitations?|restrictions?|known issues|unsupported)\b",
}
TOPIC_REGEX = {
    key: re.compile(pattern, re.IGNORECASE)
    for key, pattern in TOPIC_PATTERNS.items()
}


@lru_cache(maxsize=1)
def load_documentation_profiles():
    """Load optional exact-URL profiles. Changes cannot silently retarget IDs."""
    raw = files("agentfuse_crawlers").joinpath(
        "data/documentation_profiles.json"
    ).read_text(encoding="utf-8")
    registry = json.loads(raw)
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported documentation profile schema")
    profiles = registry.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Documentation profiles must be a mapping")
    manifest = {s["id"]: s for s in load_sources()}
    for source_id, profile in profiles.items():
        source = manifest.get(source_id)
        if not source or source["category"] != "documentation":
            raise ValueError("Unknown documentation profile ID: " + source_id)
        if profile.get("source_url") != source["url"]:
            raise ValueError("Documentation profile URL differs from manifest: " + source_id)
        if profile.get("provider") != source["provider"]:
            raise ValueError("Documentation profile provider mismatch: " + source_id)
        if profile.get("expected_page_type") not in ALLOWED_PAGE_TYPES:
            raise ValueError("Invalid documentation page purpose: " + source_id)
        if not profile.get("product_scope"):
            raise ValueError("Missing product scope: " + source_id)
        if profile.get("approved_for_advisor") is not False:
            raise ValueError("Documentation profiles cannot approve facts")
        if profile.get("review_status") != "pending_live_validation":
            raise ValueError("Documentation profiles must remain unverified")
        topics = profile.get("target_topics")
        if not isinstance(topics, list) or not topics or (
            set(topics) - set(TOPIC_PATTERNS)
        ):
            raise ValueError("Invalid documentation topic taxonomy: " + source_id)
    return profiles


def _same_official_host(url, source_url):
    target, source = urlsplit(url), urlsplit(source_url)
    return bool(
        target.scheme == "https" and target.hostname
        and target.hostname == source.hostname
        and target.port in (None, 443)
        and not target.username and not target.password
    )


def _normalized_path(path):
    # Safe structural equivalences, not guesses that two products are the same.
    path = re.sub(r"/(?:index\.html?|index/)$", "/", path or "/",
                  flags=re.IGNORECASE)
    return (path.rstrip("/") or "/").casefold()


def canonical_relationship(source_url, candidate):
    """Informational canonical triage; never authorize fetching the candidate."""
    if not candidate:
        return {"relation": "missing", "review_url": None}
    parsed = urlsplit(candidate)
    if not _same_official_host(candidate, source_url):
        return {"relation": "external_or_unsafe_ignored", "review_url": None}
    review_url = urlunsplit(("https", parsed.hostname, parsed.path or "/", "", ""))
    expected_path = _normalized_path(urlsplit(source_url).path)
    found_path = _normalized_path(parsed.path)
    return {
        "relation": "equivalent_path" if expected_path == found_path
                    else "same_host_path_differs",
        "review_url": review_url,
    }


def _topics_for_heading(heading):
    return [
        topic for topic, pattern in TOPIC_REGEX.items()
        if pattern.search(heading)
    ]


def extract_documentation_evidence(
    source_url, source_id, *, sections, title, text, prose_paragraphs,
    link_text_ratio, sections_truncated=False, canonical_candidate="",
):
    """Emit typed *topics* with exact snippets, never 'feature_supported=true'."""
    profiles = load_documentation_profiles()
    profile = profiles.get(source_id)
    profile_status = (
        "unprofiled" if profile is None
        else "profile_url_mismatch" if profile["source_url"] != source_url
        else "curated_pending_live_validation"
    )
    candidates = []
    total = 0
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        excerpt = str(section.get("excerpt") or "").strip()
        # Navigation link labels and headings alone are not capability facts.
        if not heading or len(excerpt.split()) < 12:
            continue
        for topic in _topics_for_heading(heading):
            total += 1
            if len(candidates) >= MAX_CANDIDATES:
                continue
            locator = section.get("section_url") or source_url
            if not _same_official_host(locator, source_url):
                locator = source_url
            candidates.append({
                "candidate_id": hashlib.sha256(
                    (source_id + "|" + str(section.get("section_id")) +
                     "|" + topic).encode("utf-8")
                ).hexdigest()[:24],
                "source_id": source_id,
                "product_scope": profile.get("product_scope") if profile else None,
                "topic_hint": topic,
                "heading": heading[:220],
                "source_url": locator,
                "section_id": section.get("section_id"),
                "section_sha256": section.get("sha256"),
                "excerpt": excerpt[:MAX_EXCERPT],
                "excerpt_truncated": bool(
                    section.get("excerpt_truncated") or len(excerpt) > MAX_EXCERPT
                ),
                "capability_support_verified": False,
                "review_status": "unverified",
                "approved_for_advisor": False,
            })

    words = len(text.split())
    url_path = urlsplit(source_url).path.rstrip("/").lower()
    expected = profile.get("expected_page_type") if profile else None
    # Classification is page-level only. A reference-looking overview is not
    # evidence that all relevant reference URLs have been crawled.
    if words < 45:
        page_type, scope = "insufficient_content", "insufficient_content"
    elif link_text_ratio > 0.65 and prose_paragraphs < 2:
        page_type, scope = "index", "index_only"
    elif expected in {"overview", "index"} or url_path in {"/docs", "/docs/en"}:
        page_type, scope = "overview", "overview_only"
    elif candidates and prose_paragraphs:
        page_type, scope = "reference_or_guide", "scoped_page"
    else:
        page_type, scope = "unclassified", "scope_not_established"

    canonical = canonical_relationship(source_url, canonical_candidate)
    return {
        "documentation_evidence_schema": SCHEMA_VERSION,
        "documentation_profile_status": profile_status,
        "documentation_product_scope": (
            profile.get("product_scope") if profile else None
        ),
        "documentation_expected_page_type": expected or "unknown",
        "documentation_observed_page_type": page_type,
        "documentation_scope_status": scope,
        "documentation_requires_product_review": bool(
            profile and profile.get("requires_scope_review")
        ),
        "documentation_scope_review_reason": (
            profile.get("scope_review_reason") if profile else None
        ),
        "documentation_known_capture_issue": (
            profile.get("known_capture_issue") if profile else None
        ),
        "documentation_corpus_coverage": "single_url_only",
        "documentation_topic_candidates": candidates,
        "documentation_topic_candidate_count": total,
        "documentation_topic_candidate_omitted": max(0, total - len(candidates)),
        "documentation_source_sections_truncated": bool(sections_truncated),
        "documentation_canonical_relation": canonical["relation"],
        "documentation_canonical_review_url": canonical["review_url"],
        "documentation_all_capabilities_verified": False,
    }

def _serialized_size(record):
    return len(json.dumps(
        record, ensure_ascii=False, separators=(",", ":"), default=str,
    ).encode("utf-8"))


def compact_documentation_record(record, full_text, *, target_bytes=650_000):
    """Bound Zyte Items while explicitly describing any lost evidence.

    This only reduces current exported excerpts; hashes/source locators remain.
    A formerly complete capture becomes partial if relevant proof is omitted.
    """
    output = dict(record)
    output["documentation_text_total_characters"] = len(full_text)
    output["documentation_item_budget_truncated"] = False
    if _serialized_size(output) <= target_bytes:
        return output

    output["documentation_item_budget_truncated"] = True
    if "text" in output:
        output["text"] = output["text"][:24_000]
    elif "text_sample" in output:
        output["text_sample"] = output["text_sample"][:500]
    output["text_truncated"] = len(full_text) > len(output.get("text", ""))
    output["status"] = "partial_capture"
    output["error"] = "documentation_item_budget_truncated"
    sections = []
    for section in output.get("sections", []):
        section = dict(section)
        excerpt = section.get("excerpt", "")
        section["excerpt"] = excerpt[:400]
        section["excerpt_truncated"] = bool(
            section.get("excerpt_truncated") or len(excerpt) > 400
        )
        sections.append(section)
    output["sections"] = sections[:32]
    output["sections_truncated"] = bool(
        output.get("sections_truncated") or len(sections) > 32
    )
    candidates = []
    for entry in output.get("documentation_topic_candidates", []):
        entry = dict(entry)
        excerpt = entry.get("excerpt", "")
        entry["excerpt"] = excerpt[:250]
        entry["excerpt_truncated"] = bool(
            entry.get("excerpt_truncated") or len(excerpt) > 250
        )
        candidates.append(entry)
    output["documentation_topic_candidates"] = candidates[:8]
    output["documentation_topic_candidate_omitted"] = (
        output.get("documentation_topic_candidate_omitted", 0)
        + max(0, len(candidates) - 8)
    )
    if output.get("tables"):
        output["documentation_tables_evidence_omitted"] = len(output["tables"])
        output["tables"] = []
        output["tables_truncated"] = True
    if _serialized_size(output) > target_bytes:
        # Keep a small auditable diagnostic, never a misleading "captured".
        output["sections"] = []
        output["sections_truncated"] = True
        output["documentation_topic_candidate_omitted"] += len(
            output["documentation_topic_candidates"]
        )
        output["documentation_topic_candidates"] = []
        output["text"] = output.get("text", "")[:1200]
        output["text_truncated"] = True
    if _serialized_size(output) > target_bytes:
        raise ValueError("Documentation source Item remains over safe budget")
    return output
