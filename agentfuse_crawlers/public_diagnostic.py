"""One explicit operator-selected public diagnostic scope.

This is project-side authorization to attempt public information collection,
NOT a publisher license, terms review, or approval to republish data.
Existing explicit publisher/lifecycle holds, live robots, exact GET targets,
request budgets and the production/monitoring release gates remain in force.
"""
import json
from datetime import timedelta
from importlib.resources import files

from agentfuse_crawlers import validation_access as policy
from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import collection_decision, registry_revision_sha256
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.validation_containment import group_index

PUBLIC_DIAGNOSTIC = "public_diagnostic"
PUBLIC_GATE = "public_diagnostic_project_scope_only"
SCOPE_PATH = "data/public_diagnostic_scope.json"
KIND = "public_source_diagnostic_scope_NOT_publisher_permission"
FIELDS = {
    "kind", "scope_id", "manifest_sha256", "source_registry_sha256",
    "observed_at_utc", "expires_at_utc", "robots_evidence_run_id",
    "rights_status", "source_ids", "prior_held_groups",
    "preflight_robots_observed_ids",
}


def load_public_diagnostic_scope():
    scope = json.loads(files("agentfuse_crawlers").joinpath(SCOPE_PATH).read_text(encoding="utf-8"))
    sources = load_sources()
    groups, _ = group_index(sources)
    if (not isinstance(scope, dict) or set(scope) != FIELDS
            or scope["kind"] != KIND
            or not isinstance(scope["scope_id"], str)
            or not policy.PLAN_ID.fullmatch(scope["scope_id"])
            or scope["manifest_sha256"] != manifest_sha256()
            or scope["source_registry_sha256"] != registry_revision_sha256()
            or scope["rights_status"] != "individual_publisher_rights_not_independently_verified"
            or not isinstance(scope["robots_evidence_run_id"], str)
            or not scope["robots_evidence_run_id"].isdigit()):
        raise ValueError("Public diagnostic package/manifest scope mismatch")
    for field in ("source_ids", "prior_held_groups", "preflight_robots_observed_ids"):
        values = scope[field]
        if (not isinstance(values, list) or not all(isinstance(v, str) for v in values)
                or len(values) != len(set(values))):
            raise ValueError("Invalid public diagnostic scope IDs")
    ids = set(scope["source_ids"])
    held = set(scope["prior_held_groups"])
    start, end = policy._utc(scope["observed_at_utc"]), policy._utc(scope["expires_at_utc"])
    if (not 200 <= len(ids) <= 300
            or [s["id"] for s in sources if s["id"] in ids] != scope["source_ids"]
            or not held <= set(groups.values())
            or any(groups[sid] in held for sid in ids)
            or not set(scope["preflight_robots_observed_ids"]) <= ids
            or not timedelta(0) < end - start <= timedelta(days=30)):
        raise ValueError("Invalid or out-of-bounds public diagnostic campaign")
    return scope


def public_diagnostic_access_decision(source, scope, *, now=None):
    """The packaged project scope never overrides an actual negative review."""
    clock = policy._now(now)
    if not (policy._utc(scope["observed_at_utc"]) <= clock
            < policy._utc(scope["expires_at_utc"])):
        return False, "public_diagnostic_scope_not_current"
    if source["id"] not in scope["source_ids"]:
        return False, "public_diagnostic_source_not_in_scope"
    allowed, reason = collection_decision(source, "validation")
    if not allowed:
        return False, reason
    registry = policy.load_access_registry()
    if source["id"] in registry["reviews"]:
        # If a real individual decision exists, retain it rather than falling
        # back to public scope after a negative or expired decision.
        return policy.validation_access_decision(
            source, scope="bulk_validation", registry=registry, now=clock,
        )
    return True, PUBLIC_GATE


def authorize_public_diagnostic(*, selected, category, held_groups=None, now=None):
    """One packaged scope + optional narrowing, no 274 fake review records."""
    clock = policy._now(now)
    scope = load_public_diagnostic_scope()
    if not (policy._utc(scope["observed_at_utc"]) <= clock
            < policy._utc(scope["expires_at_utc"])):
        raise ValueError("Public diagnostic scope is not current")
    if selected != select_sources(category, "all"):
        raise ValueError("Public diagnostic requires the full category manifest")
    groups, _ = group_index(load_sources())
    if held_groups is None or held_groups == "":
        extra = set()
    elif isinstance(held_groups, str):
        extra = {part.strip() for part in held_groups.split(",")}
        if not extra <= set(groups.values()):
            raise ValueError("Unknown held publisher group")
    else:
        raise ValueError("Held publisher groups must be comma-separated IDs")
    blocked = set(scope["prior_held_groups"]) | extra
    # Explicit reviewed prohibitions/deferments are also carried at publisher
    # group level. A later operator argument can only narrow this package.
    blocked.update(groups[sid] for sid, record in policy.load_access_registry()["reviews"].items()
                   if record["decision"] != "allowed_reviewed")
    ids = [s["id"] for s in selected if groups[s["id"]] not in blocked
           and public_diagnostic_access_decision(s, scope, now=clock)[0]]
    if not ids:
        raise ValueError("NO-GO: public diagnostic has zero eligible candidate URLs")
    return scope, {
        "authorized_source_ids": frozenset(ids),
        # Legacy internal budget fields; NOT an independently reviewed plan.
        "plan_id": scope["scope_id"],
        "plan_sha256": policy.digest({"scope_sha256": policy.digest(scope),
                                      "category": category, "ids": ids,
                                      "held_groups": sorted(blocked)}),
        "decision": PUBLIC_GATE,
        "max_primary_requests": len(ids),
        "max_redirects_per_source": 0,
        "plan_expires_at_utc": scope["expires_at_utc"],
    }
