"""Conservative, Git-reviewed source lifecycle and collection permissions.

A source's historic "proven" crawl-cohort membership is NOT validation.
This module never performs network requests, reads credentials, or approves facts.
"""

import hashlib
import ipaddress
import json
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit

from agentfuse_crawlers.sources import load_sources

LIFECYCLE_SCHEMA = "1.0"
STATES = frozenset({
    "discovered", "needs_validation", "validated_for_collection",
    "degraded", "quarantined", "retired",
})
POLICY_STATES = frozenset({
    "not_reviewed", "unresolved", "allowed_reviewed", "prohibited_reviewed",
})
COLLECTION_MODES = frozenset({"validation", "monitor"})
SOURCE_DATA_PATH = "data/source_lifecycle.json"


def _same_official_host_evidence(url, source_url):
    """The approval URL only supports its original host, never a migration."""
    try:
        parsed = urlsplit(url)
        expected = urlsplit(source_url)
        if not (parsed.scheme == "https" and parsed.hostname and
                parsed.hostname == expected.hostname and
                parsed.username is None and parsed.password is None and
                parsed.port in (None, 443) and
                not parsed.query and not parsed.fragment):
            return False
        # Explicitly exclude numeric IP literals from reviewer supplied URLs.
        try:
            ipaddress.ip_address(parsed.hostname)
            return False
        except ValueError:
            return True
    except (TypeError, ValueError):
        return False


def _validate_approval(source, entry):
    approval = entry.get("approval")
    if not isinstance(approval, dict):
        raise ValueError("A validated source requires a reviewer and evidence: " + source["id"])
    required = {
        "reviewed_by", "reviewed_at_utc", "official_ownership_url",
        "publisher_access_policy_url", "product_scope", "successful_job_ids",
    }
    if set(approval) != required:
        raise ValueError("Approval is missing required evidence: " + source["id"])
    for key in ("reviewed_by", "product_scope"):
        if not isinstance(approval[key], str) or not approval[key].strip():
            raise ValueError("Missing reviewer or product scope: " + source["id"])
    try:
        reviewed = datetime.fromisoformat(approval["reviewed_at_utc"].replace("Z", "+00:00"))
        if reviewed.tzinfo is None:
            raise ValueError("Date must be timezone-aware")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid approval timestamp: " + source["id"]) from exc
    for key in ("official_ownership_url", "publisher_access_policy_url"):
        if not _same_official_host_evidence(approval[key], source["url"]):
            raise ValueError("Source approval evidence must stay on the pinned official host: " + source["id"])
    jobs = approval["successful_job_ids"]
    if not (isinstance(jobs, list) and len(jobs) >= 2 and
            all(isinstance(job, str) and job.strip() for job in jobs) and
            len(set(jobs)) == len(jobs)):
        raise ValueError("At least two distinct reviewed Zyte job IDs are required: " + source["id"])


@lru_cache(maxsize=1)
def load_lifecycle_registry():
    """Validate all overrides against the immutable 460-URL source manifest."""
    raw = files("agentfuse_crawlers").joinpath(SOURCE_DATA_PATH).read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("schema_version") != LIFECYCLE_SCHEMA:
        raise ValueError("Unknown source lifecycle schema")
    if data.get("default_state") != "needs_validation":
        raise ValueError("Unreviewed manifest entries must default to needs_validation")
    overrides = data.get("overrides")
    if not isinstance(overrides, dict):
        raise ValueError("Source lifecycle overrides must be an object")
    by_id = {s["id"]: s for s in load_sources()}
    for source_id, entry in overrides.items():
        source = by_id.get(source_id)
        if source is None or not isinstance(entry, dict):
            raise ValueError("Unknown or invalid lifecycle override: " + source_id)
        expected = {"source_url", "state", "policy_status", "reason_code", "next_action", "approval"}
        if set(entry) != expected or entry.get("source_url") != source["url"]:
            raise ValueError("Source lifecycle ID/URL or fields do not match manifest: " + source_id)
        state, policy = entry["state"], entry["policy_status"]
        if state not in STATES or policy not in POLICY_STATES:
            raise ValueError("Unknown lifecycle/policy state: " + source_id)
        if not isinstance(entry["reason_code"], str) or not isinstance(entry["next_action"], str):
            raise ValueError("Invalid lifecycle review reason: " + source_id)
        if state == "validated_for_collection":
            if policy != "allowed_reviewed":
                raise ValueError("Validated collection requires reviewed publisher permission")
            _validate_approval(source, entry)
        elif entry["approval"] is not None:
            raise ValueError("Approval evidence may exist only for validated collection sources")
        if state == "quarantined" and policy == "allowed_reviewed":
            raise ValueError("Quarantined sources cannot be marked allowed")
        if state != "validated_for_collection" and policy == "allowed_reviewed":
            raise ValueError("Positive policy approval is not collection approval: " + source_id)
    return data


def registry_revision_sha256():
    registry = load_lifecycle_registry()
    return hashlib.sha256(json.dumps(
        registry, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def source_lifecycle(source):
    """Return reviewed metadata, or an explicitly unreviewed default."""
    by_id = {x["id"]: x for x in load_sources()}
    valid = by_id.get(source.get("id"))
    if valid is None or valid != source:
        raise ValueError("Source must be an exact current manifest entry")
    overrides = load_lifecycle_registry()["overrides"]
    return dict(overrides.get(source["id"]) or {
        "source_url": source["url"],
        "state": "needs_validation",
        "policy_status": "not_reviewed",
        "reason_code": "no_live_source_validation_on_file",
        "next_action": "Review source ownership, robots/terms, product scope and repeatable extraction.",
        "approval": None,
    })


def collection_decision(source, mode="validation"):
    """Validate only by default; monitor mode refuses unapproved sources."""
    if mode not in COLLECTION_MODES:
        raise ValueError("collection_mode must be 'validation' or 'monitor'")
    profile = source_lifecycle(source)
    state, policy = profile["state"], profile["policy_status"]
    if state == "quarantined" or policy in {"unresolved", "prohibited_reviewed"}:
        return False, "policy_unresolved_or_quarantined"
    if state == "retired":
        return False, "source_retired"
    if mode == "monitor" and state != "validated_for_collection":
        return False, "monitor_requires_reviewed_collection_approval"
    return True, "validated_monitor" if mode == "monitor" else "manual_validation_only"


def source_lifecycle_summary():
    from collections import Counter

    counts = Counter(source_lifecycle(source)["state"] for source in load_sources())
    return {
        "schema_version": LIFECYCLE_SCHEMA,
        "manifest_source_count": sum(counts.values()),
        "states": dict(sorted(counts.items())),
        "reviewed_collection_eligible": counts.get("validated_for_collection", 0),
        "source_registry_sha256": registry_revision_sha256(),
    }
