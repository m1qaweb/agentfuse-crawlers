"""G2: redact a true P23E1 Zyte account snapshot for restricted Actions output.

Pure OFFLINE processing. Never creates permits, jobs, subscriptions or network
requests. A redacted queue snapshot is NEVER deployed-egg or billing proof.
"""
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from agentfuse_crawlers.validation_access import digest
from scripts.p23e1_zyte_queue_preflight import KIND as SOURCE_KIND, _project
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)

KIND = "g2_redacted_scrapy_cloud_queue_snapshot_NOT_RUN_AUTHORIZATION"
VERSION = "1.0"
OUTPUT_FILE = "g2_zyte_redacted_snapshot_NO_GO.json"
COUNT_KEYS = (
    "pending_jobs_visible", "running_jobs_visible",
    "pending_jobs_reported_total", "running_jobs_reported_total",
    "periodic_schedules_reported_total",
    "enabled_periodic_schedules_visible",
    "disabled_periodic_schedules_visible",
)
REQUIRED_FALSE = (
    "readiness_to_run", "remote_current_deployed_egg_independently_verified",
    "current_zyte_billing_terms_independently_verified",
    "incremental_spend_ceiling_approved_by_operator",
    "periodic_schedules_independently_checked",
    "live_two_round_cross_category_gold_independently_verified",
)
REQUIRED_ZERO = (
    "new_jobs_created_or_modified", "publisher_requests_performed",
    "publisher_permissions_granted", "p23e_bounded_plans_authorized_by_this_report",
)


def redact(report):
    """Explicit field allowlist: never copy job IDs, job args or schedule tasks."""
    if not isinstance(report, dict) or report.get("kind") != SOURCE_KIND:
        raise ValueError("Expected an unmodified P23E1 read-only Zyte snapshot")
    if report.get("status") != (
            "NO_GO_REQUIRES_PUBLISHER_CANARIES_DEPLOYMENT_AND_BUDGET"):
        raise ValueError("P23E1 status changed or attempted to authorize a run")
    if report.get("report_sha256") != digest({
            k: v for k, v in report.items() if k != "report_sha256"
    }):
        raise ValueError("Source P23E1 snapshot digest mismatch")
    if (any(report.get(name) is not False for name in REQUIRED_FALSE)
            or any(type(report.get(name)) is not int or report[name] != 0
                   for name in REQUIRED_ZERO)
            or report.get("only_three_zyte_api_gets") is not True
            or report.get("active_queue_snapshot_non_atomic") is not True):
        raise ValueError("A read-only unprivileged Zyte snapshot is required")

    project = _project(report.get("project_id"))
    try:
        observed = datetime.fromisoformat(report["snapshot_at_utc"])
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError("Invalid timestamp in Zyte snapshot") from exc
    if observed.tzinfo is None:
        raise ValueError("Zyte snapshot timestamp must be timezone-aware")
    for name in COUNT_KEYS:
        if type(report.get(name)) is not int or not 0 <= report[name] <= 100000:
            raise ValueError("Malformed Zyte count: " + name)
    if (report["pending_jobs_visible"] > report["pending_jobs_reported_total"]
            or report["running_jobs_visible"] > report["running_jobs_reported_total"]
            or (report["enabled_periodic_schedules_visible"]
                + report["disabled_periodic_schedules_visible"]
                > report["periodic_schedules_reported_total"])):
        raise ValueError("Inconsistent Zyte page totals")
    if (type(report.get("queue_list_single_pages_complete")) is not bool
            or type(report.get("periodic_schedule_list_complete")) is not bool):
        raise ValueError("Unknown Zyte pagination completeness")
    if (report["queue_list_single_pages_complete"] and (
            report["pending_jobs_visible"] != report["pending_jobs_reported_total"]
            or report["running_jobs_visible"] != report["running_jobs_reported_total"])
            or (report["periodic_schedule_list_complete"] and (
                report["enabled_periodic_schedules_visible"]
                + report["disabled_periodic_schedules_visible"]
                != report["periodic_schedules_reported_total"]))):
        raise ValueError("Claimed complete pages do not reconcile")

    result = {
        "schema_version": VERSION,
        "kind": KIND,
        "status": "NO_GO_REAL_ACCOUNT_EVIDENCE_INCOMPLETE",
        "project_id": project,
        "snapshot_at_utc": observed.isoformat(timespec="seconds"),
        "source_p23e1_report_sha256_NOT_APPROVAL": report["report_sha256"],
        "requests_to_zyte_read_only_api": 3,
        "new_zyte_jobs": 0,
        "publisher_requests": 0,
        "approved_to_run": False,
        "source_permissions_verified": False,
        "remote_deployed_egg_independently_verified": False,
        "billing_and_spend_ceiling_independently_verified": False,
        "read_only_queue_observation_non_atomic": True,
        "queue_pages_complete": report["queue_list_single_pages_complete"],
        "pending_jobs_visible": report["pending_jobs_visible"],
        "running_jobs_visible": report["running_jobs_visible"],
        "pending_jobs_reported_total": report["pending_jobs_reported_total"],
        "running_jobs_reported_total": report["running_jobs_reported_total"],
        "periodic_schedule_page_complete": report["periodic_schedule_list_complete"],
        "periodic_schedules_reported_total": report["periodic_schedules_reported_total"],
        "enabled_periodic_schedules_visible": report["enabled_periodic_schedules_visible"],
        "disabled_periodic_schedules_visible": report["disabled_periodic_schedules_visible"],
        "no_future_jobs_guaranteed": False,
        "raw_job_ids_or_schedule_arguments_exported": False,
        "next_operator_action": (
            "Inspect all Zyte UI schedules and active jobs; verify installed "
            "deployed package version/bytes and actual account tier/units and "
            "spend ceiling; independently clear exact publisher access. "
            "No crawl is approved by this report."
        ),
    }
    result["report_sha256"] = digest(result)
    return result


def write_summary(summary, out_dir):
    if (not isinstance(summary, dict) or summary.get("kind") != KIND
            or summary.get("status") != "NO_GO_REAL_ACCOUNT_EVIDENCE_INCOMPLETE"
            or summary.get("approved_to_run") is not False
            or summary.get("raw_job_ids_or_schedule_arguments_exported") is not False
            or summary.get("new_zyte_jobs") != 0
            or summary.get("publisher_requests") != 0
            or summary.get("report_sha256") != digest({
                k: v for k, v in summary.items() if k != "report_sha256"
            })):
        raise ValueError("Refusing a non-redacted or authorizing G2 export")
    root = _private_new_directory(out_dir)
    try:
        _write_private(
            root / OUTPUT_FILE,
            (json.dumps(summary, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root / OUTPUT_FILE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-report", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input_report.read_text(encoding="utf-8"))
    summary = redact(source)
    target = write_summary(summary, args.out_dir)
    print(json.dumps({
        "status": summary["status"],
        "redacted_summary": str(target),
        "no_zyte_jobs_created": True,
        "publisher_requests": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
