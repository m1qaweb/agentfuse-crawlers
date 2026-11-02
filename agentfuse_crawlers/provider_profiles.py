"""P16A: fail-closed source-owned product identity and markup-family candidates.

Two different things must not be conflated:
  - pinned source_id -> *expected* product_id (local unreviewed hypothesis)
  - corroborated publisher product ownership (NOT achieved here)

Observed page structure may suggest a future adapter family, but this
module NEVER activates a new extractor, approves a fact, migrates a URL,
or treats a body-only marketing mention as the page's owner.
"""
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from agentfuse_crawlers.sources import load_sources

SCHEMA = "2.0"
REGISTRY_REVISION = "p16a_candidate_product_identity_v1"
DATA_PATH = Path(__file__).with_name("data") / "provider_profiles_v2.json"
PRODUCT_KINDS = frozenset({
    "model_api", "coding_agent", "managed_inference", "gateway",
    "developer_platform", "subscription_app",
})
CATEGORIES = frozenset({"documentation", "pricing", "changelog"})
GENERIC_ALIASES = frozenset({
    "pricing", "changelog", "documentation", "docs", "release notes",
    "api", "plans", "overview", "guide", "models", "agent",
})
MAX_PROFILES = 80
MAX_ALIASES = 12
MAX_TITLE = 300


def _text(value, max_length=MAX_TITLE):
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value)[:max_length]
                    .casefold().split())


def _contains_alias(haystack, alias):
    # A bounded word/phrase match; "Cursor" must not match a common word
    # inside a longer identifier. Do not use body presence as ownership.
    if not haystack or not alias:
        return False
    needle = re.escape(_text(alias))
    return bool(re.search(r"(?<!\w)" + needle + r"(?!\w)", haystack))


def _validated_aliases(value, label):
    if (not isinstance(value, list) or not 1 <= len(value) <= MAX_ALIASES
            or not all(isinstance(s, str) for s in value)):
        raise ValueError("Invalid provider identity " + label)
    cleaned = [_text(v, 100) for v in value]
    if (any((len(a) < 4 and a not in {"xai"})
            or a in GENERIC_ALIASES for a in cleaned)
            or len(cleaned) != len(set(cleaned))):
        raise ValueError("Generic, duplicate, or short identity title alias")
    return tuple(value)


@lru_cache(maxsize=1)
def provider_profiles_sha256():
    """Digest of the complete, non-secret proposed profile registry bytes."""
    return hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def load_provider_profiles():
    """Static source pins: registry does not assert verified product ownership."""
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if (data.get("schema_version") != SCHEMA
            or data.get("revision") != REGISTRY_REVISION
            or data.get("review_status") !=
               "all_candidates_pending_independent_official_review"
            or data.get("automatic_provider_specific_adapter_selection") is not False
            or data.get("approved_for_advisor") is not False):
        raise ValueError("Provider identity registry cannot authorize facts or adapters")
    entries = data.get("products")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_PROFILES:
        raise ValueError("Unexpected number of proposed product profiles")
    manifest = {s["id"]: s for s in load_sources()}
    mapping = {}
    products = set()
    for product in entries:
        if not isinstance(product, dict):
            raise ValueError("Malformed provider/product profile")
        pid = product.get("product_id")
        provider = product.get("provider_id")
        if (not isinstance(pid, str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", pid)
                or not isinstance(provider, str) or not re.fullmatch(
                    r"[a-z][a-z0-9_]{1,79}", provider)
                or pid in products
                or product.get("expected_product_kind") not in PRODUCT_KINDS
                or product.get("source_identity_review_status") !=
                   "pending_original_publisher_review"):
            raise ValueError("Invalid or unapproved expected product identity")
        products.add(pid)
        positives = _validated_aliases(
            product.get("title_aliases_candidate_unreviewed"), "positive aliases",
        )
        negative = _validated_aliases(
            product.get("contradictory_title_aliases_candidate_unreviewed"),
            "contradictory aliases",
        )
        if set(map(_text, positives)) & set(map(_text, negative)):
            raise ValueError("An alias cannot corroborate and contradict a product")
        source_entries = product.get("source_ids")
        if not isinstance(source_entries, list) or not 1 <= len(source_entries) <= 3:
            raise ValueError("Product profile needs explicit pinned source entries")
        seen_categories = set()
        for entry in source_entries:
            if not isinstance(entry, dict):
                raise ValueError("Malformed expected source mapping")
            sid = entry.get("source_id")
            source = manifest.get(sid)
            if (not source or sid in mapping
                    or entry.get("official_source_url") != source["url"]
                    or entry.get("manifest_provider_label") != source["provider"]
                    or entry.get("category") != source["category"]
                    or entry.get("category") not in CATEGORIES
                    or entry["category"] in seen_categories):
                raise ValueError("Provider identity registry has unknown/duplicated/unpinned source")
            seen_categories.add(entry["category"])
            mapping[sid] = {
                "provider_id": provider,
                "product_id": pid,
                "product_kind": product["expected_product_kind"],
                "title_aliases": positives,
                "contradictory_title_aliases": negative,
                "source_url": source["url"],
                "manifest_provider_label": source["provider"],
                "category": source["category"],
                "review_status": product["source_identity_review_status"],
            }
    return mapping


def _markup_family(evidence, category):
    """Read structural extractor outputs. No provider names or URLs used."""
    if category == "pricing":
        observations = evidence.get("pricing_observations") or []
        if not isinstance(observations, list):
            observations = []
        if not all(isinstance(x, dict) for x in observations):
            return "pricing_evidence_malformed", ["invalid_observation_shape"]
        units = {x.get("billing_unit") for x in observations}
        unit_tokens = bool(
            units & {"per_1m_tokens", "per_1k_tokens", "per_token"}
        )
        unit_subscriptions = bool(
            units & {"per_month", "per_user_month", "per_seat_month",
                     "per_year", "per_user_year"}
        )
        relevant = evidence.get("pricing_table_relevant") or 0
        card_total = evidence.get("pricing_card_total") or 0
        if not isinstance(relevant, int) or not isinstance(card_total, int):
            return "pricing_evidence_unresolved", ["invalid_table_count"]
        signals = []
        if relevant > 0:
            signals.append("relevant_rate_table_observed")
        if card_total > 0:
            signals.append("bounded_pricing_card_observed")
        if unit_tokens:
            signals.append("explicit_token_billing_unit_observed")
        if unit_subscriptions:
            signals.append("explicit_subscription_billing_unit_observed")
        if relevant > 0 and card_total > 0:
            return "mixed_table_card_candidate", signals
        if relevant > 0 and unit_tokens and unit_subscriptions:
            return "mixed_token_subscription_matrix_candidate", signals
        if relevant > 0 and unit_tokens:
            return "token_rate_matrix_candidate", signals
        if relevant > 0 and unit_subscriptions:
            return "subscription_table_candidate", signals
        if relevant > 0:
            return "rate_table_untyped_candidate", signals
        if card_total > 0:
            return "pricing_cards_candidate", signals
        return "pricing_markup_unresolved", ["no_structured_pricing_evidence"]
    if category == "documentation":
        state = evidence.get("documentation_static_capture_status")
        scope = evidence.get("documentation_scope_status")
        if state == "javascript_shell_suspected":
            return "javascript_doc_shell_candidate", ["js_shell_static_text_inadequate"]
        if scope in {"index_only", "overview_only"}:
            return "docs_navigation_or_overview_candidate", [str(scope)]
        if scope == "scoped_page":
            return "scoped_technical_docs_candidate", ["same_section_prose_candidate"]
        return "documentation_markup_unresolved", ["product_or_topic_scope_not_established"]
    if category == "changelog":
        events = evidence.get("release_events") or []
        if not isinstance(events, list) or not all(isinstance(x, dict) for x in events):
            return "release_markup_unresolved", ["malformed_release_events"]
        if events:
            stable = bool(evidence.get("release_window_complete"))
            if stable and all(x.get("event_id") for x in events):
                return "bounded_release_event_candidates", [
                    "source_owned_release_event_identity_candidates",
                ]
            return "partial_release_event_candidates", [
                "incomplete_or_ambiguous_release_window",
            ]
        return "release_markup_unresolved", ["no_release_events"]
    return "unsupported_category", ["invalid_category"]


def identify_source_product(source, evidence):
    """Return bounded, diagnostic-only identity + family classification.

    Source mapping is a *candidate*. Verified page/product ownership is
    always false until separately reviewed original publisher evidence.
    """
    if not isinstance(source, dict) or not isinstance(evidence, dict):
        raise ValueError("Expected official source and parsed evidence mapping")
    sid = source.get("id")
    category = source.get("category")
    if category not in CATEGORIES:
        raise ValueError("Unknown crawler category")
    family, structural = _markup_family(evidence, category)
    profile = load_provider_profiles().get(sid)
    if profile is not None and (
        source.get("url") != profile["source_url"]
        or source.get("provider") != profile["manifest_provider_label"]
        or category != profile["category"]
    ):
        raise ValueError("Profile source URL, provider or category does not match pinned manifest")
    title = _text(evidence.get("title"))
    description = _text(evidence.get("description"), 500)
    body = _text(evidence.get("text"), 4000)
    if profile is None:
        signal, alias, negative = "not_profiled", "", ""
    else:
        matches = [
            x for x in profile["title_aliases"]
            if _contains_alias(title, x)
        ]
        bad = [
            x for x in profile["contradictory_title_aliases"]
            if _contains_alias(title, x)
        ]
        alias = max(matches, key=len) if matches else ""
        negative = max(bad, key=len) if bad else ""
        if negative:
            signal = "title_conflict_requires_review"
        elif alias:
            signal = "title_alias_candidate_unverified"
        elif any(_contains_alias(description, x)
                 for x in profile["title_aliases"]):
            signal = "description_only_not_owner_proof"
        elif any(_contains_alias(body, x)
                 for x in profile["title_aliases"]):
            signal = "body_only_not_owner_proof"
        else:
            signal = "title_does_not_establish_product_owner"
    return {
        "source_product_identity_schema": SCHEMA,
        "source_product_profile_revision": REGISTRY_REVISION,
        "source_product_profile_sha256": provider_profiles_sha256(),
        "source_expected_provider_id": profile["provider_id"] if profile else None,
        "source_expected_product_id": profile["product_id"] if profile else None,
        "source_expected_product_kind": profile["product_kind"] if profile else None,
        "source_product_profile_status": (
            profile["review_status"] if profile else "not_profiled"
        ),
        "source_title_alias_evidence_status": signal,
        "source_title_alias_observed": alias,
        "source_title_conflicting_alias_observed": negative,
        "source_product_title_conflict": bool(negative),
        "source_product_identity_requires_review": True,
        "source_product_ownership_verified": False,
        "source_page_family_candidate": family,
        "source_page_family_evidence": structural[:5],
        "source_adapter_current": "generic_scrapy_evidence",
        "source_adapter_candidate": (
            family if profile and not negative else None
        ),
        "source_adapter_selection_status": "review_only_no_adapter_enabled",
        "source_specific_adapter_authorized": False,
        "source_canonical_migration_authorized": False,
        "approved_for_advisor": False,
    }
