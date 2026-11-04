"""P19A5: source-by-source, operator-attested publisher-policy review ledger.

No website requests, legal approvals, automatic provider facts or publisher
permission grants. A reviewed exact source may be *eligible to attempt one*
manual P19A1 validation fetch only if humans independently checked
publisher ownership, terms, robots behavior, retention and target scope.

The frozen P19A4 pilot is NOT silently resampled if any source is blocked.
Blocked, unresolved and never-reviewed sources stay in the original sample.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)
from scripts.prepare_release_pilot import _read_plan, _recheck_plan
from scripts.replay_release_snapshots import _capture_time, _digest

VERSION = "1.0"
LEDGER_KIND = "p19a5_source_specific_publisher_policy_reviews_operator_attested"
RECEIPT_KIND = "p19a5_offline_policy_preflight_not_permission"
DECISION_ELIGIBLE = "operator_attested_one_manual_capture_eligible"
DECISION_HELD = frozenset({
    "pending_review", "blocked_by_publisher_terms", "blocked_by_robots",
    "blocked_by_access_controls", "deferred_product_ownership",
    "deferred_policy_unclear", "deferred_retention_rights",
    "deferred_source_unavailable",
})
DECISIONS = DECISION_HELD | {DECISION_ELIGIBLE}
REVIEW_FIELDS = frozenset({
    "source_id", "source_url", "robots_url", "decision",
    "reviewer_id", "reviewed_at_utc", "ownership_evidence_url",
    "access_policy_evidence_url", "scope_and_retention_note",
    "robots_review_attested", "lawful_private_retention_attested",
    "publisher_scope_attested", "approved_for_advisor",
})
ROOT_FIELDS = frozenset({
    "schema_version", "kind", "pilot_plan_sha256",
    "source_manifest_sha256", "source_registry_sha256",
    "reviews", "network_requests_performed", "new_source_permissions",
    "approved_for_advisor",
})
SAFE_REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{4,79}$")
MAX_NOTE = 1200


def policy_template(plan):
    """Unfilled, source-complete review sheet; intentionally zero approvals."""
    reviews = []
    for batch in plan["batches"]:
        for source in batch["sources"]:
            reviews.append({
                "source_id": source["source_id"],
                "source_url": source["source_url"],
                "robots_url": source["robots_url"],
                "decision": "pending_review",
                "reviewer_id": None,
                "reviewed_at_utc": None,
                "ownership_evidence_url": None,
                "access_policy_evidence_url": None,
                "scope_and_retention_note": None,
                "robots_review_attested": False,
                "lawful_private_retention_attested": False,
                "publisher_scope_attested": False,
                "approved_for_advisor": False,
            })
    return {
        "schema_version": VERSION,
        "kind": LEDGER_KIND,
        "pilot_plan_sha256": plan["plan_sha256"],
        "source_manifest_sha256": plan["source_manifest_sha256"],
        "source_registry_sha256": plan["source_registry_sha256"],
        "reviews": reviews,
        "network_requests_performed": 0,
        "new_source_permissions": 0,
        "approved_for_advisor": False,
    }


def _evidence_url(value, source, *, same_host):
    if (not isinstance(value, str) or not 13 <= len(value) <= 850
            or not value.isascii() or any(
                c in value for c in ("\\", "%", "#", "?", "@")
            ) or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
        raise ValueError("Missing or malformed operator-cited HTTPS evidence URL")
    try:
        u = urlsplit(value)
        official = urlsplit(source["source_url"])
        if (u.scheme != "https" or not u.hostname
                or u.username is not None or u.password is not None
                or u.port not in (None, 443) or u.query or u.fragment
                or (same_host and u.hostname != official.hostname)):
            raise ValueError("Evidence URL is not a reviewable official HTTPS page")
    except ValueError as exc:
        raise ValueError("Invalid/foreign publisher evidence URL") from exc
    return value


def _status_review(row, source, now):
    if not isinstance(row, dict) or set(row) != REVIEW_FIELDS:
        raise ValueError("Unexpected policy review row fields")
    for key in ("source_id", "source_url", "robots_url"):
        if row.get(key) != source[key]:
            raise ValueError("Policy review source/URL/robots changed from frozen plan")
    if row.get("approved_for_advisor") is not False:
        raise ValueError("Policy research can never approve publisher facts")
    decision = row.get("decision")
    if decision not in DECISIONS:
        raise ValueError("Unrecognized publisher-policy review outcome")
    flags = (
        row.get("robots_review_attested"),
        row.get("lawful_private_retention_attested"),
        row.get("publisher_scope_attested"),
    )
    if any(type(flag) is not bool for flag in flags):
        raise ValueError("Review attestations must be explicit booleans")
    if decision == "pending_review":
        if (any(flag is True for flag in flags)
                or any(row.get(field) is not None for field in (
                    "reviewer_id", "reviewed_at_utc", "ownership_evidence_url",
                    "access_policy_evidence_url", "scope_and_retention_note",
                ))):
            raise ValueError("Unreviewed source cannot invent policy evidence")
        return False
    reviewer = row.get("reviewer_id")
    if (not isinstance(reviewer, str) or not SAFE_REVIEWER.fullmatch(reviewer)
            or reviewer.startswith("REPLACE")):
        raise ValueError("Source-specific policy decision needs human reviewer ID")
    when = _capture_time(row.get("reviewed_at_utc"))
    if when > now + timedelta(minutes=5):
        raise ValueError("Policy research review time is in the future")
    note = row.get("scope_and_retention_note")
    if (not isinstance(note, str)
            or not 60 <= len(note.strip()) <= MAX_NOTE):
        raise ValueError("Publisher-specific review note needs 60-1200 characters")
    ownership = row.get("ownership_evidence_url")
    access = row.get("access_policy_evidence_url")
    # Blocked or unresolved sources may have no legal page; do not fabricate
    # an arbitrary URL as proof. Present references still must be HTTPS.
    if ownership is not None:
        _evidence_url(ownership, source, same_host=True)
    if access is not None:
        _evidence_url(access, source, same_host=False)
    if decision == DECISION_ELIGIBLE:
        if (flags != (True, True, True)
                or not ownership or not access):
            raise ValueError(
                "Manual validation requires three affirmative per-source "
                "attestations and both real publisher evidence URLs"
            )
        return True
    if any(flags):
        raise ValueError(
            "Blocked/deferred publisher policy review cannot retain "
            "a partial affirmative capture attestation"
        )
    return False


def validate_policy_ledger(plan, ledger, *, selection_key, now=None):
    """Return private readiness by exact frozen source, no automatic approval."""
    frozen = _recheck_plan(plan, selection_key=selection_key)
    if (not isinstance(ledger, dict) or set(ledger) != ROOT_FIELDS
            or ledger.get("schema_version") != VERSION
            or ledger.get("kind") != LEDGER_KIND
            or ledger.get("pilot_plan_sha256") != frozen["plan_sha256"]
            or ledger.get("source_manifest_sha256") !=
                frozen["source_manifest_sha256"]
            or ledger.get("source_registry_sha256") !=
                frozen["source_registry_sha256"]
            or ledger.get("approved_for_advisor") is not False
            or ledger.get("network_requests_performed") != 0
            or ledger.get("new_source_permissions") != 0
            or not isinstance(ledger.get("reviews"), list)):
        raise ValueError("Malformed, stale or privileged publisher-policy ledger")
    expected = policy_template(frozen)
    planned = {s["source_id"]: s for s in expected["reviews"]}
    if len(ledger["reviews"]) != len(planned):
        raise ValueError("Missing or duplicated source policy review rows")
    seen = {}
    clock = datetime.now(timezone.utc) if now is None else now
    if (not isinstance(clock, datetime)
            or clock.tzinfo is None or clock.utcoffset() is None):
        raise ValueError("Policy review clock must be timezone-aware")
    for review in ledger["reviews"]:
        if not isinstance(review, dict):
            raise ValueError("Invalid source policy review record")
        sid = review.get("source_id")
        if not isinstance(sid, str) or sid not in planned or sid in seen:
            raise ValueError("Duplicate or unknown source in policy ledger")
        eligible = _status_review(review, planned[sid], clock)
        seen[sid] = (eligible, review["decision"])
    decisions = {}
    waves = []
    for wave in frozen["batches"]:
        ready, held = [], []
        for sid in wave["source_ids"]:
            eligible, state = seen[sid]
            decisions[sid] = state
            (ready if eligible else held).append(sid)
        waves.append({
            "batch_id": wave["batch_id"],
            "planned_source_ids": list(wave["source_ids"]),
            "operator_attested_capture_eligible_source_ids": ready,
            "held_source_ids": held,
            "all_batch_sources_operator_attested_eligible":
                len(ready) == len(wave["source_ids"]),
            "no_automatic_publisher_requests": True,
        })
    eligible_count = sum(v[0] for v in seen.values())
    summary = {
        "schema_version": VERSION,
        "kind": RECEIPT_KIND,
        "frozen_pilot_plan_sha256": frozen["plan_sha256"],
        "source_manifest_sha256": frozen["source_manifest_sha256"],
        "source_registry_sha256": frozen["source_registry_sha256"],
        "ledger_sha256": _digest(ledger),
        "source_count": frozen["source_count"],
        "operator_attested_attempt_eligible_count": eligible_count,
        "held_or_pending_source_count": len(planned) - eligible_count,
        "decision_counts": dict(sorted({
            s: list(decisions.values()).count(s) for s in DECISIONS
            if s in decisions.values()
        }.items())),
        "batches": waves,
        "all_frozen_sources_operator_attested_eligible":
            eligible_count == len(planned),
        "publisher_terms_and_robots_independently_verified": False,
        "human_policy_research_operator_attested_only": True,
        "raw_html_fetch_authorized_by_platform": False,
        "network_requests_performed": 0,
        "new_source_permissions": 0,
        "zyte_jobs_created": 0,
        "advisor_approved_facts": 0,
        "approved_for_advisor": False,
    }
    summary["receipt_sha256"] = _digest(summary)
    return summary


def require_batch_capture_review(plan, ledger, *, source_ids, selection_key):
    """Apply exact wave gate for explicitly operator-triggered P19A1 capture."""
    receipt = validate_policy_ledger(
        plan, ledger, selection_key=selection_key,
    )
    if (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 5
            or any(not isinstance(sid, str) for sid in source_ids)
            or len(set(source_ids)) != len(source_ids)):
        raise ValueError("Select 1-5 distinct exact frozen changelog sources")
    matches = []
    for wave in receipt["batches"]:
        planned = wave["planned_source_ids"]
        # Strict original order, one frozen wave only; no reordered or
        # cross-wave capture that could hide denied publisher sources.
        subset = [sid for sid in planned if sid in source_ids]
        if subset == source_ids:
            matches.append(wave)
    if len(matches) != 1:
        raise ValueError(
            "Manual capture must match one ordered, nonempty frozen pilot wave subset"
        )
    permitted = set(matches[0]["operator_attested_capture_eligible_source_ids"])
    if not set(source_ids) <= permitted:
        raise ValueError(
            "At least one requested publisher source is held by "
            "source-specific policy review"
        )
    # The receipt covers the WHOLE frozen plan, not just captured sources:
    # blocked/unavailable sources stay visible to P19A6 attrition reporting.
    return receipt


def _write_json(path, value):
    _write_private(
        path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--validate", action="store_true")
    parser.add_argument("--pilot-plan", type=Path, required=True)
    parser.add_argument("--policy-ledger", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    selection_key = os.environ.get("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY", "")
    if not selection_key:
        parser.error("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY required")
    plan = _read_plan(args.pilot_plan)
    frozen = _recheck_plan(plan, selection_key=selection_key)
    if args.prepare:
        if args.policy_ledger:
            parser.error("--prepare does not accept a completed ledger")
        record = policy_template(frozen)
        name = "source_policy_review_template.json"
    else:
        if not args.policy_ledger:
            parser.error("--validate requires the filled --policy-ledger")
        record = validate_policy_ledger(
            frozen, _read_plan(args.policy_ledger),
            selection_key=selection_key,
        )
        name = "source_policy_preflight_receipt.json"
    root = _private_new_directory(args.out_dir)
    try:
        _write_json(root / name, record)
    except Exception:
        shutil.rmtree(root)
        raise
    print(json.dumps({
        "private_result": str(root / name),
        "source_count": frozen["source_count"],
        "operator_attested_attempt_eligible_count":
            record.get("operator_attested_attempt_eligible_count", 0),
        "held_or_pending_source_count":
            record.get("held_or_pending_source_count", frozen["source_count"]),
        "new_source_permissions": 0,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "advisor_approved_facts": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
