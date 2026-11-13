"""P23E1: read-only Scrapy Cloud pending/running queue visibility.

Reads exactly TWO official Zyte jobs/list.json GET endpoints for the
operator-specified project. Does not create, schedule, approve, deploy,
stop, update, or monitor any job. Does not contact publisher URLs.
Returned queue data is a NON-ATOMIC observation, not proof of empty
schedules, current deployed code, account pricing or publisher rights.

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

SCHEMA = "1.0"
KIND = "p23e1_readonly_zyte_queue_snapshot_NOT_RUN_AUTHORIZATION"
PROJECT = re.compile(r"^[1-9][0-9]{0,10}$")
JOB = re.compile(r"^[0-9]+/[0-9]+/[0-9]+$")
HOST = "https://app.zyte.com"
STATES = ("pending", "running")
MAX_JOBS = 200
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


def _read_only_get(url, key, limit=MAX_BYTES):
    """Bounded, no-redirect GET of exactly the allowed two API endpoints."""
    if not isinstance(url, str):
        raise ValueError("Invalid official Scrapy Cloud list URL")
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qs(parts.query)
    if (parts.scheme != "https" or parts.netloc != "app.zyte.com"
            or parts.path != "/api/jobs/list.json"
            or parts.fragment or set(pairs) != {"project", "state", "count"}
            or any(len(v) != 1 for v in pairs.values())
            or url != _url(pairs["project"][0], pairs["state"][0])):
        raise ValueError("Only exact read-only pending/running list GETs permitted")
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
        raise ValueError("Oversized official Zyte queue response")
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
    """Two bounded GETs; injected fake fetch exists ONLY for offline tests."""
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
    job_ids = [j["id"] for state in STATES for j in pages[state]["jobs"]]
    if len(job_ids) != len(set(job_ids)):
        raise ValueError("Duplicate Zyte job ID across queue state snapshots")
    access = load_access_registry()
    plans = load_run_plan_registry()

    # An empty point-in-time queue is a useful observation, NOT a schedule,
    # deployment, budget, or publisher-authorization check.
    complete = all(p["complete_single_page"] for p in pages.values())
    no_visible_jobs = complete and not job_ids
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
        "only_two_zyte_api_gets": True,
        "readiness_to_run": False,
        "source_status": "ALL_UNAPPROVED_SOURCES_REMAIN_HELD_UNLESS_REVIEWED_SEPARATELY",
        "next_operator_checks": [
            "Human independently reviews each exact publisher URL and retention rights",
            "Review actual current Zyte deployed egg and matching package fingerprint",
            "Verify pending/running queues again, and inspect periodic schedules in dashboard",
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
                "Job lists are non-atomic; scheduled and future jobs are not checked.\n"
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
        "non_atomic_snapshot": True,
        "zyte_job_actions": 0,
        "publisher_requests": 0,
        "readiness_to_run": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
