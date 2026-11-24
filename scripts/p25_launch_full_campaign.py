"""P25: deliberately dispatch ONE of three full-category Zyte campaign jobs.

This is a real, opt-in Scrapy Cloud POST launcher, not a periodic scheduler.
It calls P21B's production authorization path for *all three categories*
before any POST. Separate, genuine per-URL access reviews and full-category
run plans must exist in the INSTALLED package. Absent reviews/plans = 0 POSTs.

A persisted attempt marker is written BEFORE the non-idempotent POST. If
the POST times out, retrying that category is forbidden until an operator
checks the Zyte account; an unknown response may still have created a job.
"""

import argparse
import base64
import json
import os
import stat
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.run_context import package_fingerprint
from scripts.p23e1_zyte_queue_preflight import (
    HOST, JOB, NoRedirect, _project, build_preflight, _unique_keys,
)
from scripts.p25_large_campaign import (
    ORDER, build_campaign, read_g3_review_csv, exact_pinned_args_shape,
)

POST_URL = HOST + "/api/run.json"
ACK_BUDGET = "ACCOUNT_BILLING_AND_JOB_RUNTIME_REVIEWED"
ACK_SOURCE = "ALL_CAMPAIGN_SOURCE_URL_RIGHTS_INDEPENDENTLY_REVIEWED"
MAX_RETURN = 4096


def _post_run(project, job, key, timeout):
    """Exactly one basic-auth POST to the official Scrapy Cloud run endpoint."""
    if (not isinstance(key, str) or not key
            or any(c in key for c in "\r\n\x00")):
        raise ValueError("Private Scrapy Cloud API key is required")
    if not exact_pinned_args_shape(job.get("spider_args")):
        raise ValueError("P25 dispatch requires exact plan and deployed-package pins")
    if type(timeout) is not int or not 600 <= timeout <= 3300:
        raise ValueError("Campaign job must have a bounded 600-3300 second timeout")
    form = {
        "project": _project(project),
        "spider": job["spider"],
        "priority": "2",
        "units": "1",
        # Scrapy job-side runtime ceiling (not a Zyte monetary ceiling).
        "job_settings": json.dumps(
            {"CLOSESPIDER_TIMEOUT": timeout}, separators=(",", ":"),
        ),
        **job["spider_args"],
    }
    auth = base64.b64encode((key + ":").encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        POST_URL,
        data=urllib.parse.urlencode(form).encode("ascii"),
        headers={
            "Authorization": "Basic " + auth,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as resp:
        result = resp.read(MAX_RETURN + 1)
    if len(result) > MAX_RETURN:
        raise ValueError("Zyte job dispatch response too large")
    return result


def _response_job_id(raw, project):
    if not isinstance(raw, bytes) or not 5 <= len(raw) <= MAX_RETURN:
        raise ValueError("Malformed Scrapy Cloud run response")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Malformed Scrapy Cloud run response JSON") from exc
    job_id = value.get("jobid") if isinstance(value, dict) else None
    if (not isinstance(value, dict) or value.get("status") != "ok"
            or not isinstance(job_id, str) or not JOB.fullmatch(job_id)
            or job_id.split("/", 1)[0] != _project(project)):
        raise ValueError("Scrapy Cloud did not acknowledge a valid project job ID")
    return job_id


def _private_ledger_dir(root):
    root = Path(root)
    # The ledger is a local, private, persistent operator directory, not a
    # per-run temporary artifact. Shared/missing storage cannot ensure
    # cross-machine deduplication. Never put it in public GitHub artifacts.
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError("Refusing a symlinked campaign ledger path")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("Campaign ledger must be a directory")
    mode = stat.S_IMODE(root.stat().st_mode)
    if mode & 0o077:
        raise ValueError("Campaign ledger must be owner-only (chmod 700)")
    return root


def _exclusive_json(path, payload):
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
           + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # Do not remove marker after an unknown POST result.
        raise
    return path


def dispatch_one(*, g3_rows, target, category, project, campaign_sha256,
                 observed_remote_package_sha256, ledger_dir,
                 ack_account_billing, ack_source_rights,
                 timeout_seconds=3300, key=None,
                 account_preflight=None, post=None,
                 access=None, plans=None, now=None,
                 package_sha=None):
    """A single non-idempotent POST, after every full-campaign source/plan gate."""
    if category not in ORDER:
        raise ValueError("Only three full-category campaign jobs are supported")
    project = _project(project)
    report = build_campaign(g3_rows, target, access=access, plans=plans,
                            now=now, package_sha=package_sha)
    if (not report["local_policy_and_three_plan_scope_complete"]
            or report["missing_current_source_access_reviews"] != 0
            or report["target_primary_urls"] != target
            or len(report["jobs"]) != 3):
        raise ValueError("NO-GO: 200-300 source rights and three exact plans are incomplete")
    if (campaign_sha256 != report["campaign_sha256"]
            or observed_remote_package_sha256 !=
            report["local_package_sha256_NOT_REMOTE_PROOF"]):
        raise ValueError("Campaign/package fingerprint changed or remote deployment unverified")
    if ack_account_billing != ACK_BUDGET or ack_source_rights != ACK_SOURCE:
        raise ValueError("Owner must explicitly attest billing and reviewed source rights")
    if type(timeout_seconds) is not int or not 600 <= timeout_seconds <= 3300:
        raise ValueError("Bounded job runtime required, 600-3300 seconds")
    api_key = key if key is not None else os.environ.get(
        "ZYTE_SCRAPY_CLOUD_API_KEY",
    )
    if (not isinstance(api_key, str) or not api_key
            or any(c in api_key for c in "\r\n\x00")):
        raise ValueError("Private ZYTE_SCRAPY_CLOUD_API_KEY is required")

    # A conservative 3-GET snapshot; not atomic and not a publisher permit.
    inspect = (account_preflight if account_preflight is not None
               else lambda proj, api: build_preflight(proj, api_key=api))
    account = inspect(project, api_key)
    if (not isinstance(account, dict)
            or account.get("project_id") != project
            or account.get("only_three_zyte_api_gets") is not True
            or account.get("queue_list_single_pages_complete") is not True
            or account.get("periodic_schedule_list_complete") is not True
            or account.get("no_pending_or_running_jobs_observed") is not True
            or account.get("no_enabled_periodic_schedules_observed") is not True
            or account.get("readiness_to_run") is not False
            or account.get("new_jobs_created_or_modified") != 0):
        raise ValueError("NO-GO: account queue/schedule snapshot incomplete, active or untrusted")
    job = next(j for j in report["jobs"] if j["category"] == category)
    if (job["reviewed_plan_authorization_status"] != "exact_approved_subset"
            or job["reviewed_bulk_access_count"] !=
            job["target_authorized_primary_urls"]):
        raise ValueError("NO-GO: category source plan lacks exact reviewed scope")
    # The spider constructor refuses mismatched explicit pins before
    # scheduling publisher requests. Compact args remain for legacy audits.
    job = {**job, "spider_args": job["pinned_spider_args"]}
    if not exact_pinned_args_shape(job["spider_args"]):
        raise ValueError("Missing exact runtime plan/package pins")
    ledger = _private_ledger_dir(ledger_dir)
    label = report["campaign_sha256"] + "." + category
    attempted = ledger / (label + ".ATTEMPTED_NO_BLIND_RETRY.json")
    accepted = ledger / (label + ".SCHEDULED.json")
    # Atomically reserve before the network POST; concurrent local invocations
    # cannot schedule a second job for this same campaign/category.
    _exclusive_json(attempted, {
        "status": "DISPATCH_ATTEMPTED_UNKNOWN_UNTIL_ZYTE_RESPONSE",
        "campaign_sha256": report["campaign_sha256"],
        "category": category, "project": project,
        "target_primary_urls": job["target_authorized_primary_urls"],
        "remote_package_digest_OPERATOR_ATTESTATION_NOT_API_VERIFIED":
            observed_remote_package_sha256,
        "runtime_seconds_job_setting": timeout_seconds,
        "spider_args": job["spider_args"],
        "budget_checked_EXTERNALLY_NOT_DOLLAR_CAP": True,
        "operator_must_check_Zyte_before_retry": True,
        "attempted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    # Once marker exists, NEVER silently retry a timeout/connection drop.
    submit = _post_run if post is None else post
    job_id = _response_job_id(
        submit(project, job, api_key, timeout_seconds), project,
    )
    _exclusive_json(accepted, {
        "status": "SCHEDULED_NOT_FINISHED_NOT_AUDITED",
        "campaign_sha256": report["campaign_sha256"],
        "category": category, "job_id": job_id,
        "requested_manifest_items": job["requested_manifest_items"],
        "target_primary_urls": job["target_authorized_primary_urls"],
        "spider_args": job["spider_args"],
        "publisher_accuracy_independently_verified": False,
        "completion_verified": False,
    })
    return {"status": "SCHEDULED_NOT_FINISHED_NOT_AUDITED",
            "job_id": job_id, "category": category,
            "target_primary_urls": job["target_authorized_primary_urls"],
            "scheduled": 1, "remaining_categories_NOT_AUTOSCHEDULED": 2}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    ranking = parser.add_mutually_exclusive_group(required=True)
    ranking.add_argument("--g3-top300", type=Path)
    ranking.add_argument("--g3-all460", type=Path)
    parser.add_argument("--target", type=int, default=300)
    parser.add_argument("--dispatch-category", choices=ORDER, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--campaign-sha256", required=True,
                        help="Exact SHA from the current private P25 campaign report")
    parser.add_argument("--remote-package-sha256", required=True,
                        help="Independently verify the installed Zyte egg before entry")
    parser.add_argument("--ack-account-billing", required=True,
                        help="Type ACCOUNT_BILLING_AND_JOB_RUNTIME_REVIEWED")
    parser.add_argument("--ack-source-rights", required=True,
                        help="Type ALL_CAMPAIGN_SOURCE_URL_RIGHTS_INDEPENDENTLY_REVIEWED")
    parser.add_argument("--timeout-seconds", type=int, default=3300)
    parser.add_argument("--ledger-dir", type=Path, required=True,
                        help="Persistent owner-private local directory across all three launches")
    args = parser.parse_args()
    result = dispatch_one(
        g3_rows=read_g3_review_csv(args.g3_all460 or args.g3_top300),
        target=args.target, category=args.dispatch_category,
        project=args.project_id, campaign_sha256=args.campaign_sha256,
        observed_remote_package_sha256=args.remote_package_sha256,
        ledger_dir=args.ledger_dir, ack_account_billing=args.ack_account_billing,
        ack_source_rights=args.ack_source_rights,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
