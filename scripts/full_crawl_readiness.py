"""P23A: fail-closed, zero-network, unified 460-ID Zyte crawl preflight.

This is a read-only audit of PACKAGED policy, NOT independent proof of
publisher permission, a deployed Zyte egg, real canaries, or a signed budget.
It cannot authorize a publisher GET or mint a human approval. P23B/C/E will
supply independently verified inputs for future readiness transitions.
"""
import argparse
import csv
import io
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256, source_lifecycle,
)
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.validation_access import (
    authorize_bulk_run, bulk_plan_revision_sha256, digest,
    load_access_registry, load_run_plan_registry, validate_access_registry,
    validate_plan_registry, validation_access_decision,
    validation_access_revision_sha256,
)
from scripts.full_inventory_readiness import EXPECTED, WAVES
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)

VERSION = "1.0"
KIND = "p23a_source_complete_offline_preflight_NOT_CRAWL_AUTHORIZATION"
# Frozen Nov 4 manifest identity: review this constant, never silently
# accept URL/source substitutions merely because the count remains 460.
FROZEN_MANIFEST_SHA256 = (
    "231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933"
)
COLUMNS = (
    "source_id", "provider", "category", "source_url", "frozen_canary",
    "lifecycle_state", "technical_validation_eligible", "access_review",
    "access_review_expired", "single_scope_current", "bulk_scope_current",
    "approved_local_plan_id", "planned_primary_source_get",
    "source_disposition",
)


def _clock(now):
    value = datetime.now(timezone.utc) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Readiness clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _inventory(sources):
    if (len(sources) != 460
            or len({s["id"] for s in sources}) != 460
            or len({s["url"] for s in sources}) != 460
            or dict(Counter(s["category"] for s in sources)) != EXPECTED
            or manifest_sha256(sources) != FROZEN_MANIFEST_SHA256):
        raise ValueError("P23A frozen 460-ID source/URL manifest drift: review before proceeding")
    frozen = [sid for wave in WAVES for sid, _ in wave]
    if len(frozen) != 18 or len(set(frozen)) != 18 or not set(frozen) <= {
            s["id"] for s in sources}:
        raise ValueError("P20A 18-source two-wave canary denominator drift")
    return set(frozen)


def build_readiness(*, sources=None, access_registry=None, run_registry=None,
                    now=None):
    """Inspect the current installed package and report only justified states.

    Optional injected registries exist for OFFLINE tests, not CLI permissions.
    Even an apparently valid local plan cannot make a full crawl GO: remote
    deployment, human authorization, budget, and real canaries are absent.
    """
    clock = _clock(now)
    sources = load_sources() if sources is None else sources
    frozen = _inventory(sources)
    access = (load_access_registry() if access_registry is None
              else validate_access_registry(access_registry, now=clock))
    plans = (load_run_plan_registry() if run_registry is None
             else validate_plan_registry(run_registry, now=clock))
    # Revalidate even cached package data. An invalid registry is a hard
    # error, not an opportunity to silently ignore an unsafe record.
    validate_access_registry(access, now=clock)
    validate_plan_registry(plans, now=clock)
    package_sha = package_fingerprint()

    # Check each plan through P21B's ACTUAL production authorization logic.
    # A plan is locally valid only for the exact frozen IDs/order, URL set,
    # review SHA and installed package fingerprint. This is NOT a remote
    # Zyte-deployment attestation or a license to execute the plan.
    plan_ids_by_source = {}
    invalid_plans = []
    overlaps = set()
    for pid, plan in sorted(plans["plans"].items()):
        try:
            selected = select_sources(
                plan["category"], plan["cohort"], source_ids=plan["source_ids"],
            )
            decision = authorize_bulk_run(
                selected=selected, category=plan["category"],
                cohort=plan["cohort"], collection_mode="validation",
                plan_id=pid, expected_plan_sha256=digest(plan),
                expected_package_sha256=package_sha,
                current_package_sha256=package_sha,
                access_registry=access, run_plans=plans, now=clock,
            )
            permitted = decision["authorized_source_ids"]
            if decision["decision"] != "exact_git_reviewed_bounded_run_plan":
                raise ValueError("No exact reviewed plan authorization")
            for sid in permitted:
                if sid in plan_ids_by_source:
                    overlaps.add(sid)
                else:
                    plan_ids_by_source[sid] = pid
        except (ValueError, KeyError, TypeError) as exc:
            invalid_plans.append({
                "plan_id": pid, "hold_reason": str(exc)[:180],
            })
    # Overlapping plans are never treated as unique, safe job accounting.
    for sid in overlaps:
        plan_ids_by_source.pop(sid, None)

    rows = []
    totals = Counter()
    status_counts = Counter()
    for source in sources:
        sid = source["id"]
        possible, _ = collection_decision(source, "validation")
        single, _ = validation_access_decision(
            source, scope="single_validation", registry=access, now=clock,
        )
        bulk, _ = validation_access_decision(
            source, scope="bulk_validation", registry=access, now=clock,
        )
        review = access["reviews"].get(sid)
        state = source_lifecycle(source)["state"]
        expired = bool(
            review and datetime.fromisoformat(
                review["expires_at_utc"].replace("Z", "+00:00")
            ).astimezone(timezone.utc) <= clock
        )
        review_decision = review["decision"] if review else "not_reviewed"
        plan_id = plan_ids_by_source.get(sid, "")
        if not possible:
            disposition = "held_lifecycle"
        elif not review:
            disposition = "held_missing_publisher_review"
        elif expired:
            disposition = "held_expired_publisher_review"
        elif review_decision != "allowed_reviewed":
            disposition = "held_" + review_decision
        elif not bulk:
            disposition = "held_no_bulk_validation_scope"
        elif not plan_id:
            disposition = "held_no_exact_reviewed_run_plan"
        else:
            disposition = "locally_plan_eligible_NOT_AUTHORIZED_TO_RUN"
        status_counts[disposition] += 1
        totals["technical_validation_eligible"] += bool(possible)
        totals["quarantined_or_lifecycle_held"] += not possible
        totals["recorded_source_access_reviews"] += bool(review)
        totals["expired_source_access_reviews"] += expired
        totals["current_single_source_review_attestations"] += single
        totals["current_bulk_source_review_attestations"] += bulk
        totals["locally_plan_eligible_source_ids"] += bool(plan_id)
        totals["frozen_canary_sources_current_single_review"] += (
            sid in frozen and single
        )
        rows.append({
            "source_id": sid,
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "frozen_canary": sid in frozen,
            "lifecycle_state": state,
            "technical_validation_eligible": bool(possible),
            "access_review": review_decision,
            "access_review_expired": expired,
            "single_scope_current": single,
            "bulk_scope_current": bulk,
            "approved_local_plan_id": plan_id,
            "planned_primary_source_get": bool(plan_id),
            "source_disposition": disposition,
        })
    if len(rows) != 460 or sum(status_counts.values()) != 460:
        raise ValueError("Source-level readiness accounting lost IDs")

    blockers = [
        "REAL_TWO_ROUND_CANARY_ARCHIVES_NOT_VERIFIED",
        "ZYTE_REMOTE_DEPLOYMENT_FINGERPRINT_NOT_INDEPENDENTLY_VERIFIED",
        "OPERATOR_BUDGET_AND_ONE_SHOT_APPROVAL_NOT_VERIFIED",
        "P23B_SINGLE_SOURCE_ACCESS_ENFORCEMENT_NOT_VERIFIED_ON_DEPLOYED_ZYTE",
    ]
    if totals["current_bulk_source_review_attestations"] < totals[
            "technical_validation_eligible"]:
        blockers.append("PER_SOURCE_BULK_ACCESS_REVIEWS_INCOMPLETE")
    if totals["locally_plan_eligible_source_ids"] == 0:
        blockers.append("NO_AUTHORIZED_PUBLISHER_GETS_IN_PACKAGED_PLANS")
    if totals["frozen_canary_sources_current_single_review"] < len(frozen):
        blockers.append("FROZEN_CANARY_ACCESS_REVIEWS_INCOMPLETE")
    if invalid_plans:
        blockers.append("RUN_PLANS_REJECTED_BY_P21B")
    if overlaps:
        blockers.append("OVERLAPPING_AUTHORIZED_RUN_PLANS")

    counts = {
        "configured_source_ids": 460,
        "technical_validation_eligible_NOT_permission": totals[
            "technical_validation_eligible"],
        "quarantined_or_lifecycle_held": totals["quarantined_or_lifecycle_held"],
        "publisher_review_records_present": totals["recorded_source_access_reviews"],
        "expired_publisher_reviews": totals["expired_source_access_reviews"],
        "current_single_source_review_attestations_NOT_legal_grants": totals[
            "current_single_source_review_attestations"],
        "current_bulk_review_attestations_NOT_legal_grants": totals[
            "current_bulk_source_review_attestations"],
        "packaged_reviewed_plan_count": len(plans["plans"]),
        "locally_valid_plan_eligible_source_ids_NOT_remote_verified": totals[
            "locally_plan_eligible_source_ids"],
        "actual_publisher_requests_authorized_by_this_report": 0,
        "unreviewed_or_unplanned_source_ids": 460 - totals[
            "locally_plan_eligible_source_ids"],
        "frozen_canary_source_ids": len(frozen),
        "frozen_canary_sources_with_current_single_review": totals[
            "frozen_canary_sources_current_single_review"],
    }
    report = {
        "schema_version": VERSION,
        "kind": KIND,
        "status": "NO_GO",
        "canary_status": "NO_GO",
        "supervised_diagnostic_status": "NO_GO",
        "trusted_monitored_collection_status": "NO_GO",
        "readiness_is_an_authorization": False,
        "publisher_permission_independently_verified": False,
        "deployed_zyte_fingerprint_independently_verified": False,
        "real_canary_job_archives_verified": False,
        "operator_cost_budget_and_signoff_verified": False,
        "p23b_single_source_access_enforcement_verified": False,
        "full_run_approved": False,
        "bulk_run_approved": False,
        "source_manifest_sha256": manifest_sha256(sources),
        "source_registry_sha256": registry_revision_sha256(),
        "source_access_registry_sha256": validation_access_revision_sha256(access),
        "bulk_plan_registry_sha256": bulk_plan_revision_sha256(plans),
        "local_package_sha256_NOT_ZYTE_PROOF": package_sha,
        "expected_category_counts": dict(sorted(EXPECTED.items())),
        "counts": counts,
        "source_disposition_counts": dict(sorted(status_counts.items())),
        "all_source_ids_in_manifest_order": [s["id"] for s in sources],
        "frozen_canary_source_ids": [
            sid for wave in WAVES for sid, _ in wave
        ],
        "invalid_or_stale_run_plan_holds": invalid_plans,
        "overlapping_plan_source_ids": sorted(overlaps),
        "blocker_codes": sorted(set(blockers)),
        "next_action": (
            "P23B: enforce current exact-source access review for single-source "
            "validation. Then complete actual publisher reviews and two-round "
            "canaries before compiling executable full-inventory plans."
        ),
        "approved_for_advisor": False,
        "new_source_permissions": 0,
        "new_zyte_jobs": 0,
        "network_requests_performed": 0,
    }
    report["report_sha256"] = digest(report)
    return report, rows


def write_readiness(report, rows, out_dir):
    """Write only public manifest/policy STATUS, never private filled reviews."""
    root = _private_new_directory(out_dir)
    try:
        _write_private(
            root / "full_crawl_readiness_NO_GO.json",
            (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: _safe_csv(row.get(col, "")) for col in COLUMNS})
        _write_private(
            root / "source_dispositions_460.csv",
            stream.getvalue().encode("utf-8-sig"),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, required=True,
        help="New folder: only local installed-package policy, NO crawl",
    )
    args = parser.parse_args()
    report, rows = build_readiness()
    root = write_readiness(report, rows, args.out_dir)
    print(json.dumps({
        "report": str(root / "full_crawl_readiness_NO_GO.json"),
        "status": report["status"],
        "configured": report["counts"]["configured_source_ids"],
        "currently_reviewed_for_bulk": report["counts"][
            "current_bulk_review_attestations_NOT_legal_grants"],
        "locally_plan_eligible_NOT_authorized_to_run": report["counts"][
            "locally_valid_plan_eligible_source_ids_NOT_remote_verified"],
        "network_requests_performed": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
