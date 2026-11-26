"""P20B — produce exact Zyte UI arguments WITHOUT contacting Zyte/publishers.

This is a copy/paste guide, not an authority to schedule or monitor all
publishers. A full collection requires the P20A human source-specific
preflight, representative real canaries and separate operator approval.

Read exact checked-in manifest and lifecycle fingerprints, produce one
full-inventory *diagnostic* plan per existing spider, never an executable
job, API token, request, external service call or permission approval.
"""
import argparse
import csv
import io
import json
import shutil
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import (
    load_sources, select_sources,
)
from agentfuse_crawlers import validation_access as policy
from scripts.canary_rollout import SPIDERS
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)
from scripts.replay_release_snapshots import _digest

SCHEMA = "1.0"
KIND = "p20b_manual_zyte_ui_instructions_not_crawl_permission"
EXPECTED = {"documentation": 194, "pricing": 177, "changelog": 89}
ORDER = ("changelog", "pricing", "documentation")
CSV_FIELDS = (
    "spider", "category", "configured_source_count", "job_units",
    "priority", "cohort", "confirm_full_inventory", "collection_mode",
    "expected_manifest_sha256", "expected_selection_ids_sha256",
    "expected_source_registry_sha256", "human_authorization_status",
    "expected_package_sha256", "local_plan_status", "local_plan_primary_request_cap",
)


def inspect_local_full_category_plan(selected, category, package_sha):
    """Evaluate exactly the same installed plan as the three-argument spider.

    No runtime permission is changed. Local plan eligibility is NOT evidence
    of remote deployment, publisher rights, or permission to click Run.
    """
    result = {
        "status": "no_matching_reviewed_plan",
        "plan_id": None,
        "plan_sha256": None,
        "authorized_source_ids_sha256": None,
        "locally_eligible_source_count": 0,
        "max_primary_requests": 0,
        "max_redirects_per_source": 0,
        "plan_expires_at_utc": None,
        "remote_deployment_verified": False,
        "run_authorized_by_guide": False,
    }
    try:
        match = policy.matching_full_inventory_plan(
            selected=selected, category=category, cohort="all",
        )
        if match is None:
            return result
        pid, plan_sha = match
        decision = policy.authorize_bulk_run(
            selected=selected, category=category, cohort="all",
            collection_mode="validation", plan_id=pid,
            expected_plan_sha256=plan_sha,
            expected_package_sha256=package_sha,
            current_package_sha256=package_sha,
        )
        permitted = [s for s in selected
                     if s["id"] in decision["authorized_source_ids"]]
        if (decision["decision"] != "exact_git_reviewed_bounded_run_plan"
                or not permitted
                or len(permitted) != decision["max_primary_requests"]):
            raise ValueError("No nonempty exact reviewed subset")
        result.update(
            status="locally_valid_reviewed_plan_NOT_REMOTE_VERIFIED",
            plan_id=pid,
            plan_sha256=plan_sha,
            authorized_source_ids_sha256=selection_ids_sha256(permitted),
            locally_eligible_source_count=len(permitted),
            max_primary_requests=decision["max_primary_requests"],
            max_redirects_per_source=decision["max_redirects_per_source"],
            plan_expires_at_utc=decision["plan_expires_at_utc"],
        )
    except (ValueError, KeyError, TypeError):
        # Never expose a launchable-looking receipt if the installed policy
        # is expired, ambiguous, malformed or pinned to different bytes.
        result["status"] = "invalid_or_ambiguous_reviewed_plan"
    return result


def build_full_diagnostic_ui_guide():
    sources = load_sources()
    counts = dict(Counter(s["category"] for s in sources))
    if len(sources) != 460 or counts != EXPECTED:
        raise ValueError("Full diagnostic guide must pin 194/177/89 original source IDs")
    manifest = manifest_sha256(sources)
    registry = registry_revision_sha256()
    package_sha = package_fingerprint()
    jobs = []
    for category in ORDER:
        selected = select_sources(category, cohort="all")
        if len(selected) != EXPECTED[category]:
            raise ValueError("Full selection unexpectedly differs from pinned sources")
        blocked = sorted(
            s["id"] for s in selected
            if not collection_decision(s, "validation")[0]
        )
        # The only THREE values the operator needs in the Zyte UI.
        # Source/plan fingerprint pins are derived and checked by the
        # running spider against a uniquely matching packaged review plan.
        args = {
            "cohort": "all",
            "confirm_full_inventory": "yes",
            "collection_mode": "validation",
        }
        scope_fingerprints = {
            "expected_manifest_sha256": manifest,
            "expected_selection_ids_sha256": selection_ids_sha256(selected),
            "expected_source_registry_sha256": registry,
        }
        # A full run must not accidentally include a stale one-source
        # selection/limit/offset or monitoring status from a prior canary.
        if any(key in args for key in (
            "source_ids", "limit", "offset", "monitor",
        )):
            raise ValueError("Unsafe scope argument in full-inventory guide")
        jobs.append({
            "spider": SPIDERS[category],
            "category": category,
            "configured_source_count": len(selected),
            "job_units": 1,
            "priority": "Normal",
            "tags": [],
            "arguments": args,
            "scope_fingerprints_reference_only": scope_fingerprints,
            "local_bulk_plan_preflight": inspect_local_full_category_plan(
                selected, category, package_sha,
            ),
            "explicitly_no_source_ids_argument": True,
            "source_ids_locally_policy_blocked": blocked,
            "operator_review_status":
                "NOT_AUTHORIZED_BY_THIS_PLAN_REQUIRES_PUBLISHER_POLICY_REVIEW",
            "real_gold_verified": False,
            "advisor_fact_approvals": 0,
            "scheduled_jobs": 0,
        })
    if sum(j["configured_source_count"] for j in jobs) != 460:
        raise ValueError("Did not account for all configured source IDs")
    result = {
        "schema_version": SCHEMA,
        "kind": KIND,
        "source_manifest_sha256": manifest,
        "source_registry_sha256": registry,
        "expected_package_sha256_NOT_REMOTE_PROOF": package_sha,
        "locally_eligible_primary_source_count": sum(
            j["local_bulk_plan_preflight"]["locally_eligible_source_count"] for j in jobs
        ),
        "jobs": jobs,
        "manual_spider_jobs": 3,
        "source_ids_accounted_for": 460,
        "all_source_publisher_permissions_verified_here": False,
        "publisher_terms_and_robots_independently_verified": False,
        "live_canary_evidence_supplied_to_this_command": False,
        "full_diagnostic_approved_to_run": False,
        "recurrent_monitoring_approved": False,
        "human_verification_and_approval_needed": [
            "Verify actually deployed Zyte revision equals reviewed source version",
            "Review exact publisher terms, robots, scope and retention for every intended fetch",
            "Complete archived, two-round real cross-category Zyte pilot",
            "Preserve blocked and quarantined URL records rather than request them",
            "Approve one supervised full-inventory diagnostic, not an ongoing schedule",
            "Keep production advisor facts, DB writes and auto-alerts disabled",
        ],
        "new_publisher_permissions_granted": 0,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "deployment_authorized": False,
        "advisor_fact_approvals": 0,
    }
    result["report_sha256"] = _digest(result)
    return result


def _job_text(record):
    lines = [
        "SPIDER: " + record["spider"],
        "CONFIGURED SOURCES: " + str(record["configured_source_count"]),
        "JOB UNITS: 1",
        "PRIORITY: Normal",
        "TAGS: leave empty",
    ]
    gate = record["local_bulk_plan_preflight"]
    lines.extend([
        "LOCAL PLAN STATUS: " + gate["status"],
        "LOCAL PRIMARY REQUEST CAP: " + str(gate["max_primary_requests"]),
    ])
    if gate["status"] == "locally_valid_reviewed_plan_NOT_REMOTE_VERIFIED":
        lines.append("REFERENCE ARGUMENTS (NOT AUTHORIZED TO RUN):")
        for key, value in record["arguments"].items():
            lines.append("  " + key + " = " + value)
    else:
        lines.append("DO NOT RUN: arguments withheld; no usable local reviewed plan.")
    lines.extend([
        "",
        "No bulk_run_plan_id, expected_bulk_plan_sha256 or ",
        "expected_deployment_package_sha256 is needed in the Zyte UI:",
        "the spider locates ONE exact current reviewed plan in its installed package.",
        "If no such reviewed plan exists, a Cloud bulk job refuses startup;",
        "local offline accounting may emit held Items. Do not schedule the job.",
        "Scope fingerprints in the CSV are reference-only, not needed as UI fields.",
        "",
        "REMOVE any older source_ids, limit, offset or collection_mode=monitor.",
        "DO NOT add source_ids (this is the entire category, not one source).",
        "Locally blocked sources are HELD, not fetched: "
            + (", ".join(record["source_ids_locally_policy_blocked"]) or "none"),
        "NOT AUTHORIZED: human publisher access checks, successful real canaries,",
        "matching Zyte deployment, budget and explicit approval are required.",
        "",
    ])
    return "\n".join(lines)


def _csv_bytes(guide):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="raise")
    writer.writeheader()
    for record in guide["jobs"]:
        row = {
            "spider": record["spider"],
            "category": record["category"],
            "configured_source_count": record["configured_source_count"],
            "job_units": record["job_units"],
            "priority": record["priority"],
            **record["arguments"],
            **record["scope_fingerprints_reference_only"],
            "human_authorization_status": record["operator_review_status"],
            "expected_package_sha256": guide["expected_package_sha256_NOT_REMOTE_PROOF"],
            "local_plan_status": record["local_bulk_plan_preflight"]["status"],
            "local_plan_primary_request_cap": record["local_bulk_plan_preflight"]["max_primary_requests"],
        }
        writer.writerow({
            key: _safe_csv(row.get(key, "")) for key in CSV_FIELDS
        })
    return buf.getvalue().encode("utf-8-sig")


def write_zyte_ui_guide(guide, out_dir):
    root = _private_new_directory(out_dir)
    try:
        _write_private(
            root / "zyte_full_3_spiders_NOT_AUTHORIZED.json",
            (json.dumps(guide, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        _write_private(
            root / "zyte_full_3_spiders_NOT_AUTHORIZED.csv",
            _csv_bytes(guide),
        )
        heading = (
            "P20B ZYTE UI REFERENCE — FUTURE SUPERVISED DIAGNOSTIC\n"
            "==============================================================\n\n"
            "NOT AUTHORIZED TO RUN TODAY BY THIS FILE. This is a scope guard\n"
            "and copy/paste reference, not permission for any publisher fetch.\n"
            "Run only after individual access/policy reviews, real cross-category\n"
            "two-round canaries, validated Zyte revision and human approval.\n\n"
            "The screenshot's 1 Job Unit + Normal Priority are appropriate.\n"
            "Run each of the THREE spiders separately; no single spider has 460 IDs.\n\n"
        )
        txt = (heading + "EXPECTED PACKAGE SHA-256 (LOCAL ONLY): "
               + guide["expected_package_sha256_NOT_REMOTE_PROOF"] + "\n\n"
               + "\n".join(_job_text(j) for j in guide["jobs"]))
        _write_private(
            root / "READ_ME_ZYTE_UI_SETTINGS_NOT_AUTHORIZED.txt",
            txt.encode("utf-8"),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    guide = build_full_diagnostic_ui_guide()
    directory = write_zyte_ui_guide(guide, args.out_dir)
    print(json.dumps({
        "private_ui_guide": str(directory),
        "spiders": [j["spider"] for j in guide["jobs"]],
        "source_ids_accounted_for": 460,
        "locally_eligible_primary_source_count": guide["locally_eligible_primary_source_count"],
        "expected_package_sha256_NOT_REMOTE_PROOF": guide["expected_package_sha256_NOT_REMOTE_PROOF"],
        "full_diagnostic_approved_to_run": False,
        "new_publisher_permissions_granted": 0,
        "zyte_jobs_created": 0,
        "network_requests_performed": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
