"""P21B: fail-closed, Git-reviewed source/URL bulk validation policy.

Two separately reviewed, packaged registries must agree:
1) exact per-source URL/terms/robots/private-retention attestations; and
2) an exact, short-lived, single-category run scope with a request budget.

Neither a spider argument nor a hash supplies permission on its own. The
deployed package is the trust boundary. Both registries ship EMPTY today.
No publisher rights, approvals, original HTML, credentials or Zyte jobs are
created. Single explicit-source manual validation and separately approved
unattended monitoring use other policy paths.

IMPORTANT: Package/record hashes prove integrity, NOT publisher authorization.
A static reviewed run record cannot enforce true one-shot consumption without
an external trusted stateful service; do NOT claim it can. A future secure
operator workflow must also verify publisher rights and actual Zyte deployment.
"""
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit

from agentfuse_crawlers.run_context import (
    manifest_sha256, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources

ACCESS_PATH = "data/validation_access_reviews.json"
RUN_PLAN_PATH = "data/bulk_run_authorizations.json"
SCHEMA = "1.0"
ACCESS_KIND = "git_reviewed_source_specific_validation_access_decisions_not_legal_permissions"
PLAN_KIND = "git_reviewed_expiring_bulk_validation_run_plans_not_schedules"
ACCESS_STATES = frozenset({"allowed_reviewed", "prohibited_reviewed", "deferred"})
ACCESS_SCOPES = frozenset({"single_validation", "bulk_validation"})
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{4,79}$")
PLAN_ID = re.compile(r"^[a-z][a-z0-9_-]{5,80}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_SCOPE_SOURCES = 200
MAX_SOURCE_REVIEW_DAYS = 30
MAX_RUN_PLAN_DAYS = 7
ACCESS_FIELDS = frozenset({
    "source_url", "category", "decision", "scopes", "reviewed_by",
    "reviewed_at_utc", "expires_at_utc", "ownership_evidence_url",
    "publisher_access_policy_url", "robots_url", "publisher_terms_reviewed",
    "robots_reviewed", "private_retention_reviewed", "evidence_note",
})
PLAN_FIELDS = frozenset({
    "category", "collection_mode", "cohort", "source_ids",
    "authorized_source_ids", "manifest_sha256", "source_registry_sha256",
    "access_registry_sha256", "selection_ids_sha256", "source_urls_sha256",
    "approved_by", "reviewed_at_utc", "expires_at_utc", "max_primary_requests",
    "purpose", "publisher_policy_review_attested", "max_redirects_per_source",
})


def digest(value):
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc(value):
    if not isinstance(value, str) or len(value) > 35:
        raise ValueError("Publisher-policy date must be timezone-aware")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timezone missing")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid publisher-policy UTC timestamp") from exc


def _https(value, *, expected_host=None, robots=False):
    if (not isinstance(value, str) or not 13 <= len(value) <= 1024
            or any(ord(c) < 33 or ord(c) > 126 for c in value)
            or "\\" in value):
        raise ValueError("Publisher evidence URL must be sanitized HTTPS")
    try:
        u = urlsplit(value)
        if (u.scheme != "https" or not u.hostname
                or u.username or u.password or u.port not in (None, 443)
                or u.query or u.fragment
                or u.hostname.lower() in {"localhost", "localhost.localdomain"}
                or u.hostname.lower().endswith((".localhost", ".local"))
                or (expected_host is not None
                    and u.hostname.lower() != expected_host.lower())
                or (robots and u.path != "/robots.txt")):
            raise ValueError("Publisher evidence URL failed host/scope review")
        try:
            ipaddress.ip_address(u.hostname)
        except ValueError:
            return value
        raise ValueError("Literal IP hosts cannot be evidence authorities")
    except ValueError as exc:
        raise ValueError("Invalid publisher evidence URL") from exc


def _now(now=None):
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise ValueError("Policy clock must be timezone-aware")
    return clock.astimezone(timezone.utc)


def _review_valid(record, source, *, now):
    if not isinstance(record, dict) or set(record) != ACCESS_FIELDS:
        raise ValueError("Incorrect source access review fields")
    if (record["source_url"] != source["url"]
            or record["category"] != source["category"]
            or record["decision"] not in ACCESS_STATES):
        raise ValueError("Source policy review changed exact pinned ID/URL/category")
    scopes = record["scopes"]
    if (not isinstance(scopes, list)
            or any(not isinstance(scope, str) for scope in scopes)
            or len(set(scopes)) != len(scopes)
            or any(scope not in ACCESS_SCOPES for scope in scopes)):
        raise ValueError("Invalid reviewed access scope list")
    who = record["reviewed_by"]
    if not isinstance(who, str) or not NAME.fullmatch(who):
        raise ValueError("Named human access reviewer required")
    start = _utc(record["reviewed_at_utc"])
    if start > now + timedelta(minutes=5):
        raise ValueError("Access review claims future evaluation")
    finish = _utc(record["expires_at_utc"])
    if finish <= start or finish - start > timedelta(days=MAX_SOURCE_REVIEW_DAYS):
        raise ValueError("Source-policy review expiry exceeds 30 days")
    official_host = urlsplit(source["url"]).hostname
    ownership = record["ownership_evidence_url"]
    terms = record["publisher_access_policy_url"]
    robots = record["robots_url"]
    if ownership is not None:
        _https(ownership, expected_host=official_host)
    if terms is not None:
        _https(terms)
    if robots is not None:
        _https(robots, expected_host=official_host, robots=True)
    yes = (
        record["publisher_terms_reviewed"],
        record["robots_reviewed"],
        record["private_retention_reviewed"],
    )
    if any(type(x) is not bool for x in yes):
        raise ValueError("Publisher attestations must be actual booleans")
    note = record["evidence_note"]
    if not isinstance(note, str) or not 80 <= len(note.strip()) <= 1500:
        raise ValueError("Source review requires substantive publisher-specific notes")
    if record["decision"] == "allowed_reviewed":
        if not scopes or yes != (True, True, True) or not all(
            (ownership, terms, robots)
        ):
            raise ValueError("Positive bulk review missing source-specific evidence")
    elif any(yes) or scopes:
        raise ValueError("Denied/deferred source cannot hold affirmative access scopes")
    return record


def validate_access_registry(data, *, now=None):
    clock = _now(now)
    if (not isinstance(data, dict)
            or set(data) != {"schema_version", "kind", "default_decision", "reviews"}
            or data.get("schema_version") != SCHEMA
            or data.get("kind") != ACCESS_KIND
            or data.get("default_decision") != "not_reviewed"
            or not isinstance(data.get("reviews"), dict)):
        raise ValueError("Malformed or privileged source access registry")
    known = {s["id"]: s for s in load_sources()}
    for sid, review in data["reviews"].items():
        if not isinstance(sid, str) or sid not in known:
            raise ValueError("Unknown source access review ID")
        _review_valid(review, known[sid], now=clock)
    return data


@lru_cache(maxsize=1)
def load_access_registry():
    data = json.loads(
        files("agentfuse_crawlers").joinpath(ACCESS_PATH).read_text(encoding="utf-8")
    )
    return validate_access_registry(data)


def validation_access_revision_sha256(registry=None):
    return digest(load_access_registry() if registry is None else registry)


def validation_access_decision(source, *, scope="bulk_validation",
                               registry=None, now=None):
    if scope not in ACCESS_SCOPES:
        raise ValueError("Unknown validation access scope")
    data = load_access_registry() if registry is None else validate_access_registry(
        registry, now=now
    )
    # Independently, the lifecycle registry may prohibit any source fetch.
    allowed_by_lifecycle, lifecycle_reason = collection_decision(
        source, mode="validation",
    )
    if not allowed_by_lifecycle:
        return False, lifecycle_reason
    review = data["reviews"].get(source["id"])
    if not review:
        return False, "bulk_source_policy_not_reviewed"
    if review["decision"] != "allowed_reviewed":
        return False, "bulk_source_policy_denied_or_deferred"
    if _utc(review["expires_at_utc"]) <= _now(now):
        return False, "bulk_source_policy_review_expired"
    if scope not in review["scopes"]:
        return False, "bulk_source_review_scope_not_approved"
    return True, "git_reviewed_source_bulk_validation_access"


def _urls_digest(selected):
    return digest([
        {"source_id": s["id"], "source_url": s["url"], "category": s["category"]}
        for s in selected
    ])


def _plan_valid(plan, *, plan_id, now):
    if not isinstance(plan_id, str) or not PLAN_ID.fullmatch(plan_id):
        raise ValueError("Invalid Git-reviewed bulk plan ID")
    if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS:
        raise ValueError("Malformed Git-reviewed bulk run plan")
    if (plan["collection_mode"] != "validation"
            or plan["category"] not in ("documentation", "pricing", "changelog")
            or plan["cohort"] not in ("all", "proven", "candidate")
            or plan["purpose"] != "bounded_human_supervised_diagnostic"
            or plan["publisher_policy_review_attested"] is not True):
        raise ValueError("Bulk plan is not a reviewed validation diagnostic")
    who = plan["approved_by"]
    if not isinstance(who, str) or not NAME.fullmatch(who):
        raise ValueError("Bulk plan needs a real named human reviewer")
    start, end = _utc(plan["reviewed_at_utc"]), _utc(plan["expires_at_utc"])
    if (start > now + timedelta(minutes=5) or end <= start
            or end - start > timedelta(days=MAX_RUN_PLAN_DAYS)):
        raise ValueError("Invalid bulk plan review time / expiry")
    ids = plan["source_ids"]
    permitted = plan["authorized_source_ids"]
    if (not isinstance(ids, list) or not 2 <= len(ids) <= MAX_SCOPE_SOURCES
            or not all(isinstance(v, str) for v in ids)
            or len(set(ids)) != len(ids)
            or not isinstance(permitted, list)
            or not permitted
            or not all(isinstance(v, str) for v in permitted)
            or len(set(permitted)) != len(permitted)
            or any(x not in ids for x in permitted)
            or [x for x in ids if x in permitted] != permitted):
        raise ValueError("Bulk plan source/authorized ID scope is invalid")
    if (type(plan["max_primary_requests"]) is not int
            or plan["max_primary_requests"] != len(permitted)
            or type(plan["max_redirects_per_source"]) is not int
            or not 0 <= plan["max_redirects_per_source"] <= 3):
        raise ValueError("Bulk run exceeds approved primary/redirect request budget")
    for key in (
        "manifest_sha256", "source_registry_sha256",
        "access_registry_sha256", "selection_ids_sha256", "source_urls_sha256",
    ):
        if not isinstance(plan[key], str) or not SHA256.fullmatch(plan[key]):
            raise ValueError("Missing exact reviewed bulk scope fingerprint")
    return plan


def validate_plan_registry(data, *, now=None):
    clock = _now(now)
    if (not isinstance(data, dict)
            or set(data) != {"schema_version", "kind", "default_policy", "plans"}
            or data.get("schema_version") != SCHEMA
            or data.get("kind") != PLAN_KIND
            or data.get("default_policy") != "no_bulk_runs_authorized"
            or not isinstance(data.get("plans"), dict)):
        raise ValueError("Malformed bulk plan registry")
    for key, plan in data["plans"].items():
        _plan_valid(plan, plan_id=key, now=clock)
    return data


@lru_cache(maxsize=1)
def load_run_plan_registry():
    data = json.loads(
        files("agentfuse_crawlers").joinpath(RUN_PLAN_PATH).read_text(encoding="utf-8")
    )
    return validate_plan_registry(data)


def bulk_plan_revision_sha256(registry=None):
    return digest(load_run_plan_registry() if registry is None else registry)


def authorize_bulk_run(*, selected, category, cohort, collection_mode,
                       plan_id=None, expected_plan_sha256=None,
                       expected_package_sha256=None, current_package_sha256=None,
                       access_registry=None, run_plans=None, now=None):
    """Return EXACT authorized IDs; missing plan means zero publisher GETs.

    Caller may still emit one held Item for each selected source. Invalid or
    spoofed explicit plans raise before start() issues ANY request.
    """
    clock = _now(now)
    access = (load_access_registry() if access_registry is None else
              validate_access_registry(access_registry, now=clock))
    approved = (load_run_plan_registry() if run_plans is None else
                validate_plan_registry(run_plans, now=clock))
    # Defense in depth: the effective loaded records can be cached, replaced,
    # or injected by a test runner. Recheck the exact in-memory policy and
    # run-plan schema at the authorization boundary, not only at load time.
    validate_access_registry(access, now=clock)
    validate_plan_registry(approved, now=clock)
    result = {
        "authorized_source_ids": frozenset(),
        "plan_id": "",
        "plan_sha256": "",
        "access_registry_sha256": validation_access_revision_sha256(access),
        "plan_registry_sha256": bulk_plan_revision_sha256(approved),
        "decision": "bulk_run_plan_not_present",
        "max_primary_requests": 0,
        "max_redirects_per_source": 0,
        "plan_expires_at_utc": None,
    }
    if not selected or len(selected) > MAX_SCOPE_SOURCES:
        raise ValueError("Cannot authorize empty/oversized bulk source selection")
    if collection_mode != "validation":
        raise ValueError("Bulk access plan may not authorize monitoring")
    if plan_id is None:
        if expected_plan_sha256 is not None or expected_package_sha256 is not None:
            raise ValueError("Cannot supply fingerprints without a Git-reviewed plan")
        return result
    if not isinstance(plan_id, str) or not PLAN_ID.fullmatch(plan_id):
        raise ValueError("Invalid Git-reviewed bulk authorization ID")
    plan = approved["plans"].get(plan_id)
    if plan is None:
        raise ValueError("No such Git-reviewed bulk authorization in deployed package")
    expected_plan = digest(plan)
    if (not isinstance(expected_plan_sha256, str)
            or not SHA256.fullmatch(expected_plan_sha256)
            or expected_plan_sha256 != expected_plan):
        raise ValueError("Bulk run-plan SHA differs from deployed Git review")
    if (not isinstance(expected_package_sha256, str)
            or not SHA256.fullmatch(expected_package_sha256)
            or expected_package_sha256 != current_package_sha256):
        raise ValueError("Bulk job's deployed package fingerprint is not pinned")
    if _utc(plan["expires_at_utc"]) <= clock:
        raise ValueError("Bulk authorization expired, no source GET permitted")
    if (plan["category"] != category
            or plan["cohort"] != cohort
            or [s["id"] for s in selected] != plan["source_ids"]
            or plan["selection_ids_sha256"] != selection_ids_sha256(selected)
            or plan["source_urls_sha256"] != _urls_digest(selected)
            or plan["manifest_sha256"] != manifest_sha256()
            or plan["source_registry_sha256"] != registry_revision_sha256()
            or plan["access_registry_sha256"] != validation_access_revision_sha256(access)):
        raise ValueError("Bulk authorization does not match exact deployed publisher scope")
    permitted = frozenset(plan["authorized_source_ids"])
    for src in selected:
        if src["id"] not in permitted:
            continue
        allowed, reason = validation_access_decision(
            src, scope="bulk_validation", registry=access, now=clock,
        )
        if not allowed:
            raise ValueError(
                "Run plan references an unreviewed, denied, expired or "
                "out-of-scope source: " + src["id"] + ":" + reason
            )
    result.update({
        "authorized_source_ids": permitted,
        "plan_id": plan_id, "plan_sha256": expected_plan,
        "decision": "exact_git_reviewed_bounded_run_plan",
        "max_primary_requests": len(permitted),
        "max_redirects_per_source": plan["max_redirects_per_source"],
        "plan_expires_at_utc": plan["expires_at_utc"],
    })
    return result
