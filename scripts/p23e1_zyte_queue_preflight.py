"""P23E1/P23E2: read-only Scrapy Cloud queue AND periodic schedule visibility.

Reads exactly THREE official Zyte GET endpoints: pending jobs, running jobs,
and the project periodic job list. The operator specifies the exact project. Does not create, schedule, approve, deploy,
stop, update, or monitor any job. Does not contact publisher URLs.
Returned queue and schedule data are NON-ATOMIC observations, not independent
proof of no future jobs, current deployed code, pricing or publisher rights.

Keep the API key in ZYTE_SCRAPY_CLOUD_API_KEY, never on the command line.
The private report always stays NO_GO; human operator checks are separate.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.run_context import package_fingerprint
from agentfuse_crawlers.validation_access import (
    digest, load_access_registry, load_run_plan_registry,
)
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)

SCHEMA = "1.1"
KIND = "p23e1_readonly_zyte_queue_snapshot_NOT_RUN_AUTHORIZATION"
PROJECT = re.compile(r"^[1-9][0-9]{0,10}$")
JOB = re.compile(r"^[0-9]+/[0-9]+/[0-9]+$")
HOST = "https://app.zyte.com"
STATES = ("pending", "running")
MAX_JOBS = 200
MAX_SCHEDULES = 200
MAX_BYTES = 1_000_000
API_KEY_VAR = "ZYTE_SCRAPY_CLOUD_API_KEY"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Zyte read-only API redirected; refusing credential forwarding")


def _project(value):
    value = str(value)
    if not PROJECT.fullmatch(value):
        raise ValueError("Zyte project ID must be a positive decimal integer")
    return value


def _url(project, state):
    project = _project(project)
    if state not in STATES:
        raise ValueError("Only pending and running Scrapy Cloud states are allowed")
    return (
        HOST + "/api/jobs/list.json?"
        + urllib.parse.urlencode(
            {"project": project, "state": state, "count": MAX_JOBS}
        )
    )


def _periodic_url(project):
    # No query or mutation endpoint; exact vendor-documented GET path.
    return HOST + "/api/projects/" + _project(project) + "/periodicjobs"


def _parse_periodic(raw, project):
    """Summarize one vendor schedule page, never serialize spider_args.

    Paginated/partial pages are explicitly incomplete. The vendor's next URL
    is NEVER followed by this tool, even if it points to app.zyte.com.
    """
    project = _project(project)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Invalid bounded periodic schedule response")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed official Zyte periodic schedule JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("Zyte periodic schedule response is not an object")
    count, next_url, prev_url, rows = (
        result.get("count"), result.get("next"),
        result.get("previous"), result.get("results"),
    )
    if (type(count) is not int or not 0 <= count <= 100000
            or not isinstance(rows, list)
            or len(rows) > MAX_SCHEDULES or len(rows) > count
            or any(v is not None and (not isinstance(v, str)
                       or not v or len(v) > 2048)
                   for v in (next_url, prev_url))):
        raise ValueError("Zyte periodic schedule pagination or totals invalid")

    schedules = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Zyte periodic schedule row must be an object")
        ident, owner = row.get("id"), row.get("project")
        if (type(ident) is not int or ident <= 0 or ident in seen
                or type(owner) not in (str, int) or str(owner) != project
                or type(row.get("disabled")) is not bool
                or row.get("type") not in ("spider", "script")):
            raise ValueError("Zyte periodic job ID, project, state or type invalid")
        seen.add(ident)
        tasks = row.get("tasks")
        if not isinstance(tasks, list) or not 0 < len(tasks) <= 32:
            raise ValueError("Missing or excessive Zyte periodic schedule tasks")
        names = []
        for task in tasks:
            if not isinstance(task, dict):
                raise ValueError("Malformed Zyte periodic schedule task")
            name = _short(task.get("name"), max_len=120)
            if not name:
                raise ValueError("Zyte periodic schedule task missing name")
            names.append(name)

        cron = _short(row.get("cron"), max_len=80)
        if not cron or len(cron.split()) != 5:
            raise ValueError("Malformed periodic schedule cadence")
        schedules.append({
            "id": ident,
            "disabled": row["disabled"],
            "type": row["type"],
            "cron_UNVERIFIED": cron,
            "task_names": names,
            "task_count": len(tasks),
            "task_arguments_REDACTED": True,
        })
    complete = count == len(rows) and next_url is None
    return {
        "reported_total": count,
        "returned_count": len(rows),
        "complete_single_page": complete,
        "has_next_page_NOT_FOLLOWED": next_url is not None,
        "schedules": schedules,
        "enabled_visible": sum(not row["disabled"] for row in schedules),
        "disabled_visible": sum(row["disabled"] for row in schedules),
        "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _read_only_get(url, key, limit=MAX_BYTES):
    """Bounded no-redirect GET for the only three allowlisted Zyte URLs."""
    if not isinstance(url, str):
        raise ValueError("Invalid official Scrapy Cloud list URL")
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qs(parts.query)
    queue_ok = (
        parts.scheme == "https" and parts.netloc == "app.zyte.com"
        and parts.path == "/api/jobs/list.json" and not parts.fragment
        and set(pairs) == {"project", "state", "count"}
        and all(len(v) == 1 for v in pairs.values())
        and url == _url(pairs["project"][0], pairs["state"][0])
    ) if set(pairs) == {"project", "state", "count"} else False
    # The periodic list endpoint has NO user-supplied pagination URL, query,
    # job id, or schedule id. The path must be canonical and exact.
    schedule_ok = False
    schedule_match = re.fullmatch(r"/api/projects/([1-9][0-9]{0,10})/periodicjobs",
                                  parts.path)
    if (parts.scheme == "https" and parts.netloc == "app.zyte.com"
            and not parts.query and not parts.fragment
            and schedule_match is not None):
        schedule_ok = url == _periodic_url(schedule_match.group(1))
    if not (queue_ok or schedule_ok):
        raise ValueError("Only exact read-only Zyte queue/schedule list GETs permitted")
    if not isinstance(key, str) or not key or any(c in key for c in "\r\n\x00"):
        raise ValueError("Private Scrapy Cloud key required")
    if type(limit) is not int or not 0 < limit <= MAX_BYTES:
        raise ValueError("Invalid bounded response size")
    auth = base64.b64encode((key + ":").encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={"Authorization": "Basic " + auth, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as resp:
        payload = resp.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Oversized official Zyte read-only response")
    return payload


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys in Zyte queue response")
        result[key] = value
    return result


def _short(value, *, max_len=128):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > max_len:
        raise ValueError("Malformed Zyte job metadata field")
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ValueError("Unsafe characters in Zyte job metadata")
    return value


def _parse_list(raw, project, state):
    """Strictly parse the complete returned page; never claim 0 from truncation."""
    _project(project)
    if state not in STATES or not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Invalid bounded Zyte queue response")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed official Zyte queue JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ValueError("Official Zyte queue API did not report status=ok")
    count, total, jobs = (
        payload.get("count"), payload.get("total"), payload.get("jobs")
    )
    if (type(count) is not int or type(total) is not int
            or not 0 <= count <= MAX_JOBS or total < count
            or not isinstance(jobs, list) or len(jobs) != count):
        raise ValueError("Zyte queue count, total or page size is inconsistent")
    clean = []
    seen = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("Zyte queue job is not a record")
        job_id = job.get("id")
        if (not isinstance(job_id, str) or not JOB.fullmatch(job_id)
                or job_id.split("/", 1)[0] != project
                or job_id in seen or job.get("state") != state):
            raise ValueError("Wrong-project, duplicate or wrong-state job")
        seen.add(job_id)
        spider = _short(job.get("spider"), max_len=120)
        if not spider:
            raise ValueError("Zyte queue row has no spider name")
        clean.append({
            "id": job_id,
            "state": state,
            "spider": spider,
            "version_UNVERIFIED_REMOTE_PACKAGE": _short(
                job.get("version"), max_len=120
            ),
            "started_time": _short(job.get("started_time"), max_len=45),
            "updated_time": _short(job.get("updated_time"), max_len=45),
        })
    return {
        "queried_state": state,
        "returned_count": count,
        "reported_total": total,
        "complete_single_page": count == total,
        "jobs": clean,
        "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def build_preflight(project, *, api_key=None, fetch=None, now=None):
    """Three bounded GETs; injected fake fetch exists ONLY for offline tests."""
    project = _project(project)
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise ValueError("Preflight requires timezone-aware UTC time")
    clock = clock.astimezone(timezone.utc)
    key = api_key if api_key is not None else os.environ.get(API_KEY_VAR)
    if fetch is None and (
            not isinstance(key, str) or not key
            or any(c in key for c in "\r\n\x00")):
        raise ValueError("Set private ZYTE_SCRAPY_CLOUD_API_KEY; no anonymous fallback")
    get = _read_only_get if fetch is None else fetch

    pages = {}
    for state in STATES:
        pages[state] = _parse_list(
            get(_url(project, state), key, MAX_BYTES), project, state,
        )
    # Request periodic schedules only AFTER both queue pages are validated.
    # Do not use vendor-controlled 'next' URLs for any follow-up requests.
    schedules = _parse_periodic(
        get(_periodic_url(project), key, MAX_BYTES), project,
    )
    job_ids = [j["id"] for state in STATES for j in pages[state]["jobs"]]
    if len(job_ids) != len(set(job_ids)):
        raise ValueError("Duplicate Zyte job ID across queue state snapshots")
    access = load_access_registry()
    plans = load_run_plan_registry()

    # An empty point-in-time queue is a useful observation, NOT a schedule,
    # deployment, budget, or publisher-authorization check.
    complete = all(p["complete_single_page"] for p in pages.values())
    no_visible_jobs = complete and not job_ids
    no_enabled_schedules = (
        schedules["complete_single_page"] and schedules["enabled_visible"] == 0
    )
    report = {
        "schema_version": SCHEMA,
        "kind": KIND,
        "status": "NO_GO_REQUIRES_PUBLISHER_CANARIES_DEPLOYMENT_AND_BUDGET",
        "snapshot_at_utc": clock.isoformat(timespec="seconds"),
        "project_id": project,
        "local_package_sha256_NOT_REMOTE_DEPLOYMENT_PROOF": package_fingerprint(),
        "active_queue_snapshot_non_atomic": True,
        "queue_list_single_pages_complete": complete,
        "no_pending_or_running_jobs_observed": no_visible_jobs,
        "pending_jobs_visible": len(pages["pending"]["jobs"]),
        "running_jobs_visible": len(pages["running"]["jobs"]),
        "pending_jobs_reported_total": pages["pending"]["reported_total"],
        "running_jobs_reported_total": pages["running"]["reported_total"],
        "job_list_pages": pages,
        "periodic_schedule_api_page": schedules,
        "periodic_schedule_list_complete": schedules["complete_single_page"],
        "periodic_schedules_reported_total": schedules["reported_total"],
        "enabled_periodic_schedules_visible": schedules["enabled_visible"],
        "disabled_periodic_schedules_visible": schedules["disabled_visible"],
        "no_enabled_periodic_schedules_observed": no_enabled_schedules,
        "local_access_review_records_NOT_INDEPENDENT_PERMISSION": len(
            access["reviews"]
        ),
        "local_reviewed_bulk_plan_records_NOT_OPERATOR_SIGNOFF": len(
            plans["plans"]
        ),
        "remote_current_deployed_egg_independently_verified": False,
        "current_zyte_billing_terms_independently_verified": False,
        "incremental_spend_ceiling_approved_by_operator": False,
        "periodic_schedules_independently_checked": False,
        "live_two_round_cross_category_gold_independently_verified": False,
        "p23e_bounded_plans_authorized_by_this_report": 0,
        "publisher_permissions_granted": 0,
        "new_jobs_created_or_modified": 0,
        "publisher_requests_performed": 0,
        "only_three_zyte_api_gets": True,
        "readiness_to_run": False,
        "source_status": "ALL_UNAPPROVED_SOURCES_REMAIN_HELD_UNLESS_REVIEWED_SEPARATELY",
        "next_operator_checks": [
            "Human independently reviews each exact publisher URL and retention rights",
            "Review actual current Zyte deployed egg and matching package fingerprint",
            "Recheck both queue states and all periodic schedule pages in Zyte UI",
            "Read actual account tier, unit availability, retention and any usage-based charges",
            "Independently document and approve a finite cost ceiling and stop thresholds",
            "Archive true distinct two-round canary evidence and blind human gold",
            "Review short-lived, approved P23E per-source run plan before P23F pilots",
        ],
    }
    report["report_sha256"] = digest(report)
    return report


def write_preflight(report, out_dir):
    if (not isinstance(report, dict) or report.get("kind") != KIND
            or not report.get("status", "").startswith("NO_GO")
            or report.get("readiness_to_run") is not False
            or report.get("new_jobs_created_or_modified") != 0
            or report.get("publisher_permissions_granted") != 0
            or report.get("publisher_requests_performed") != 0
            or report.get("remote_current_deployed_egg_independently_verified") is not False
            or report.get("incremental_spend_ceiling_approved_by_operator") is not False
            or report.get("report_sha256") != digest({
                k: v for k, v in report.items() if k != "report_sha256"
            })):
        raise ValueError("Refusing a privileged or unverified Zyte readiness report")
    root = _private_new_directory(out_dir)
    try:
        _write_private(
            root / "p23e1_zyte_readonly_queue_NO_GO.json",
            (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        _write_private(
            root / "OPERATOR_NEXT_STEPS_NOT_AUTHORIZED.txt",
            (
                "READ-ONLY ZYTE QUEUE SNAPSHOT; NOT AN APPROVAL\n"
                "Queue and periodic schedule lists are non-atomic snapshots.\n"
                "Paginated schedules need manual follow-up; future jobs may start.\n"
                "Inspect current deployed egg, account pricing, current scheduler,\n"
                "publisher rights and two-round canary evidence independently.\n"
                "Do not run, schedule or approve Zyte jobs from this artifact.\n"
            ).encode("utf-8"),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True, help="Known Scrapy Cloud project number")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="NEW private output path (never an existing directory)")
    args = parser.parse_args()
    report = build_preflight(args.project_id)
    path = write_preflight(report, args.out_dir)
    print(json.dumps({
        "status": report["status"],
        "private_report": str(path),
        "project_id": report["project_id"],
        "running_jobs_visible": report["running_jobs_visible"],
        "pending_jobs_visible": report["pending_jobs_visible"],
        "enabled_periodic_schedules_visible": report[
            "enabled_periodic_schedules_visible"
        ],
        "periodic_schedule_list_complete": report["periodic_schedule_list_complete"],
        "non_atomic_snapshot": True,
        "zyte_job_actions": 0,
        "publisher_requests": 0,
        "readiness_to_run": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
