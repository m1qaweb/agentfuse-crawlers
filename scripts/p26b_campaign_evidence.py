"""P26B: export and replay evidence from ONE completed P25 category job.

Only authenticated, read-only Zyte storage GETs, or entirely offline replay.
Requires the as-run checkout, G3 ranking, P25 launch ledger and Items archive.
A stopped or incomplete job is useful diagnostic evidence, not a successful run.
Never grants access, schedules a job, captures publisher HTML or approves facts.
"""
import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers import validation_access as policy
from agentfuse_crawlers.run_context import selection_ids_sha256
from agentfuse_crawlers.sources import select_sources
from scripts.archive_jobs import JOB_ID, _job_details, _request, load_archive
from scripts.p23c2_zyte_requests_logs_html_gate import (
    _check_log_schema, _check_request_schema, _ms_to_time, _pairs_no_duplicates,
)
from scripts.p23c3a_download_completed_zyte_evidence import (
    HOST, META_BYTES, PAGE_BYTES, PAGE_SIZE, STATS_BYTES, _parse_page,
    _serialise, _url,
)
from scripts.p25_audit_campaign_items import EXPECTED_ARGS, HELD_STATUSES
from scripts.p25_large_campaign import ORDER, build_campaign, read_g3_review_csv
from scripts.plan_documentation_children import _private_new_directory, _write_private

KIND = "p26b_completed_p25_category_evidence_NOT_ACCURACY"
MAX_ROWS = {"requests": 4096, "logs": 20000}
MAX_BYTES = {"requests": 16_000_000, "logs": 32_000_000}
JSON_LIMIT = 2_000_000
ALLOWED_HTTP_BARRIERS = {401, 403, 407, 429}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_file(path, limit):
    path = Path(path)
    if (not path.is_file() or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)):
        raise ValueError("Expected a private regular evidence file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Evidence exceeds bounded private storage limit")
    return raw


def _object(raw):
    value = json.loads(raw, object_pairs_hook=_pairs_no_duplicates)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       indent=2, allow_nan=False) + "\n").encode("utf-8")


def _in_window(record, timestamp):
    return (policy._utc(record["reviewed_at_utc"]) <= timestamp
            < policy._utc(record["expires_at_utc"]))


def load_context(g3_rows, target, campaign_sha, category, ledger_dir, archive_dir,
                 *, access=None, plans=None, loader=load_archive):
    """Bind one job to its actual launch attempt, exact package and scope.

    Deliberately reconstruct at the recorded dispatch time, never today's
    expiry. The as-run package must be installed; no hash override in the CLI.
    No historical input is used by the live authorization path.
    """
    if (not isinstance(campaign_sha, str) or not policy.SHA256.fullmatch(campaign_sha)
            or category not in ORDER):
        raise ValueError("Invalid campaign digest/category")
    label = campaign_sha + "." + category
    ledger = Path(ledger_dir)
    attempt_raw = _read_file(ledger / (label + ".ATTEMPTED_NO_BLIND_RETRY.json"), JSON_LIMIT)
    accepted_raw = _read_file(ledger / (label + ".SCHEDULED.json"), JSON_LIMIT)
    attempt, accepted = _object(attempt_raw), _object(accepted_raw)
    if (attempt.get("status") != "DISPATCH_ATTEMPTED_UNKNOWN_UNTIL_ZYTE_RESPONSE"
            or accepted.get("status") != "SCHEDULED_NOT_FINISHED_NOT_AUDITED"
            or any(r.get("campaign_sha256") != campaign_sha or
                   r.get("category") != category for r in (attempt, accepted))):
        raise ValueError("Dispatch receipts do not identify the same campaign/category")
    job_id = accepted.get("job_id")
    if (not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id)
            or job_id.split("/")[0] != attempt.get("project")):
        raise ValueError("Invalid dispatch job/project identity")
    at = policy._utc(attempt.get("attempted_at_utc"))
    access = policy.load_access_registry() if access is None else access
    plans = policy.load_run_plan_registry() if plans is None else plans
    campaign = build_campaign(g3_rows, target, access=access, plans=plans, now=at)
    if (campaign["campaign_sha256"] != campaign_sha
            or not campaign["local_policy_and_three_plan_scope_complete"]
            or campaign["missing_current_source_access_reviews"]
            or attempt.get("remote_package_digest_OPERATOR_ATTESTATION_NOT_API_VERIFIED")
            != campaign["local_package_sha256_NOT_REMOTE_PROOF"]):
        raise ValueError("As-run ranking/package/policy does not match dispatch receipts")
    selected = next(j for j in campaign["jobs"] if j["category"] == category)
    ids = selected["target_source_ids_manifest_order"]
    plan_id = selected["matching_plan_id_NOT_REMOTE_PROOF"]
    plan = plans["plans"][plan_id]
    # The production gate allows a small review clock tolerance. Historical
    # evidence requires a genuinely already reviewed scope at dispatch.
    if (not _in_window(plan, at) or
            any(not _in_window(access["reviews"][sid], at) for sid in ids)):
        raise ValueError("Category review/plan not valid at recorded dispatch")
    if (any(r.get("target_primary_urls") != len(ids) for r in (attempt, accepted))
            or accepted.get("requested_manifest_items") != selected["requested_manifest_items"]):
        raise ValueError("Dispatch receipts have changed category counts")
    root = Path(archive_dir)
    envelope_raw = _read_file(root / "envelope.json", JSON_LIMIT)
    envelope, rows = loader(root)
    job = envelope.get("job", {})
    if (job.get("job_id") != job_id or job.get("category") != category
            or job.get("spider") != selected["spider"] or job.get("state") != "finished"
            or job.get("spider_args") != EXPECTED_ARGS or job.get("unrecorded_argument_names")
            or job.get("expected_item_count") != len(rows)):
        raise ValueError("Archive does not match the scheduled P25 category")
    whole = select_sources(category, "all")
    sources = {s["id"]: s for s in whole}
    seen = set()
    target_ids = set(ids)
    for row in rows:
        sid = row.get("source_id")
        source = sources.get(sid)
        if (source is None or sid in seen
                or row.get("source_url") != source["url"]
                or row.get("provider") != source["provider"]
                or row.get("category") != category
                or row.get("spider_name") != selected["spider"]
                or row.get("zyte_job_id") != job_id
                or row.get("requested_cohort") != "all"
                or row.get("collection_mode") != "validation"
                or row.get("approved_for_advisor") is not False
                or row.get("manifest_sha256") != campaign["manifest_sha256"]
                or row.get("source_registry_sha256") != campaign["source_registry_sha256"]
                or row.get("selection_ids_sha256") != selection_ids_sha256(whole)
                or row.get("selection_source_count") != len(whole)
                or row.get("deployment_revision") != campaign["local_package_sha256_NOT_REMOTE_PROOF"]
                or row.get("bulk_access_registry_sha256") != campaign["access_registry_sha256"]
                or row.get("bulk_run_plan_registry_sha256") != campaign["bulk_run_registry_sha256"]
                or row.get("bulk_run_plan_id") != plan_id
                or row.get("bulk_run_plan_sha256") != policy.digest(plan)
                or row.get("bulk_source_authorized_by_reviewed_plan") is not (sid in target_ids)):
            raise ValueError("Items contain inconsistent as-run identity or authorization provenance")
        seen.add(sid)
        if sid not in target_ids and (
                row.get("status") not in HELD_STATUSES or row.get("http_status") is not None
                or not str(row.get("policy_observation", "")).startswith("not_fetched_by_")):
            raise ValueError("Non-target Item suggests an unauthorized fetch")
    return {
        "campaign": campaign, "category": category, "job": job, "items": rows,
        "sources": sources, "target_ids": target_ids, "plan": plan,
        "reviews": access["reviews"], "attempted_at": at,
        "bindings": {"campaign_sha256": campaign_sha, "category": category,
                     "job_id": job_id, "attempt_receipt_sha256": sha(attempt_raw),
                     "scheduled_receipt_sha256": sha(accepted_raw),
                     "items_envelope_sha256": sha(envelope_raw)},
    }


def _download(job_id, kind, key, fetch):
    """Bound every page and total; require an explicit empty terminal page.

    A short nonempty page does not terminate pagination. This matters for
    storage APIs returning fewer rows than requested. Ordinals are checked
    by the existing P23C3A parser. No hidden extra publisher requests.
    """
    rows, total = [], 0
    while True:
        offset = len(rows)
        count = min(PAGE_SIZE[kind], MAX_ROWS[kind] - offset + 1)
        if count < 1:
            raise ValueError("Campaign export exceeds row bound")
        raw = fetch(_url(kind, job_id, offset, count), key, PAGE_BYTES)
        page = _parse_page(raw, kind, job_id, offset, count)
        if not page:
            break
        rows.extend(page)
        total += len(raw)
        if len(rows) > MAX_ROWS[kind] or total > MAX_BYTES[kind]:
            raise ValueError("Campaign export exceeds private retention bound")
    return _serialise(rows, MAX_BYTES[kind]), rows


def _remote_metadata(context, key, fetch):
    job = context["job"]
    raw = fetch(f'{HOST}/jobs/{job["job_id"]}', key, META_BYTES)
    remote = _object(raw)
    actual = _job_details(job["job_id"], remote)
    for field in ("job_id", "spider", "category", "state", "close_reason",
                  "deploy_id", "deployment_version", "expected_item_count",
                  "spider_args", "unrecorded_argument_names", "finished_time_ms"):
        if actual.get(field) != job.get(field):
            raise ValueError("Official job metadata differs from immutable Items archive")
    start = _ms_to_time(remote.get("running_time"))
    end = _ms_to_time(actual.get("finished_time_ms"))
    if end < start or start < context["attempted_at"]:
        raise ValueError("Official job time does not match recorded dispatch")
    return {
        "running_time_ms": remote["running_time"],
        "finished_time_ms": actual["finished_time_ms"],
        "deploy_id": actual["deploy_id"], "deployment_version": actual["deployment_version"],
        "job_metadata_response_sha256": sha(raw),
        "scrapy_downloader_request_count": actual["stats"].get("downloader/request_count"),
    }


def _rows_from_bytes(raw, kind, job_id):
    if len(raw) > MAX_BYTES[kind]:
        raise ValueError("Oversized offline export")
    rows = []
    check = _check_request_schema if kind == "requests" else _check_log_schema
    for index, line in enumerate(raw.splitlines()):
        if index >= MAX_ROWS[kind] or len(line) > 65536:
            raise ValueError("Offline evidence exceeds line or row limit")
        row = _object(line)
        if row.get("_key") != f"{job_id}/{index}":
            raise ValueError("Offline export missing, duplicated or reordered ordinal")
        check(row)
        rows.append(row)
    return rows


def diagnose(context, metadata, requests, logs):
    """Report actual operational evidence; no source facts or approval."""
    start = _ms_to_time(metadata["running_time_ms"])
    end = _ms_to_time(metadata["finished_time_ms"])
    if (start < context["attempted_at"] or end < start
            or metadata["finished_time_ms"] != context["job"].get("finished_time_ms")
            or metadata["deploy_id"] != context["job"].get("deploy_id")
            or metadata["deployment_version"] != context["job"].get("deployment_version")):
        raise ValueError("Evidence times/deployment do not match archive")
    sources = context["sources"]
    allowed = context["target_ids"]
    target_urls = {sources[sid]["url"]: sid for sid in allowed}
    robots_urls = {
        urlsplit(url)._replace(path="/robots.txt", query="", fragment="").geturl()
        for url in target_urls
    }
    requests_by_source = Counter()
    statuses = {}
    issues = Counter()
    robots_count = 0
    for row in requests:
        t = _ms_to_time(row["time"])
        if not start <= t <= end:
            issues["request_outside_official_job_window"] += 1
        if row["method"] != "GET":
            issues["unexpected_non_get_request"] += 1
        elif row["url"] in target_urls:
            sid = target_urls[row["url"]]
            requests_by_source[sid] += 1
            statuses[sid] = row["status"]
            if not _in_window(context["plan"], t) or not _in_window(context["reviews"][sid], t):
                issues["primary_request_timestamp_outside_review_window"] += 1
        elif row["url"] in robots_urls:
            robots_count += 1
        else:
            # No broad redirect allowance: flag even possibly legitimate
            # robots redirects for independent review rather than pass them.
            issues["unreconciled_or_out_of_scope_url"] += 1
        if row["status"] in ALLOWED_HTTP_BARRIERS:
            issues["http_access_barrier"] += 1
    for count in requests_by_source.values():
        if count > 1:
            issues["duplicate_primary_request"] += count - 1
    item_statuses = Counter()
    seen = set()
    for row in context["items"]:
        sid = row["source_id"]
        seen.add(sid)
        item_statuses[str(row.get("status"))] += 1
        if sid not in allowed:
            continue
        status = row.get("http_status")
        if type(status) is int and (requests_by_source[sid] != 1 or statuses.get(sid) != status):
            issues["item_http_status_not_reconciled"] += 1
        if row.get("status") in HELD_STATUSES:
            issues["selected_source_held"] += 1
            if requests_by_source[sid]:
                issues["held_source_has_primary_request"] += 1
        if (row.get("status") in {"robots_or_policy_denied", "rejected_redirect",
                                  "redirect_needs_review", "source_access_limited"}
                or (row.get("status") == "blocked" and
                    row.get("error") == "access_or_login_challenge")):
            issues["item_access_barrier"] += 1
    expected = metadata.get("scrapy_downloader_request_count")
    if type(expected) is not int or expected != len(requests):
        issues["requests_count_not_reconciled_with_scrapy_stats"] += 1
    missing = sorted(set(sources) - seen)
    unattempted = sorted(allowed - set(requests_by_source))
    if missing:
        issues["missing_manifest_items"] = len(missing)
    if unattempted:
        issues["target_without_recorded_primary_get"] = len(unattempted)
    if context["job"].get("close_reason") != "finished":
        issues["job_not_normally_closed"] += 1
    return {
        "kind": KIND, "status": "NO_GO_DIAGNOSTIC_ONLY",
        **context["bindings"], "target_primary_urls": len(allowed),
        "manifest_slots": len(sources), "items_observed": len(seen),
        "missing_manifest_ids": missing, "target_without_primary_get_ids": unattempted,
        "target_primary_urls_observed": len(requests_by_source),
        "recorded_primary_gets": sum(requests_by_source.values()),
        "robots_gets": robots_count, "request_records": len(requests),
        "log_records": len(logs), "log_error_or_critical_records": sum(r["level"] >= 40 for r in logs),
        "item_statuses": dict(sorted(item_statuses.items())),
        "issues": dict(sorted(issues.items())),
        "remote_package_independently_authenticated": False,
        "logs_independently_count_verified": False,
        "same_response_html_retained_or_verified": False,
        "publisher_accuracy_independently_verified": False,
        "approved_for_advisor": False, "new_jobs": 0, "publisher_requests_performed_now": 0,
    }


def export_evidence(context, out_dir, *, key=None, fetch=_request):
    """Download once per completed category; store private SHA-bound evidence."""
    root = _private_new_directory(out_dir)
    try:
        key = key if key is not None else os.environ.get("ZYTE_SCRAPY_CLOUD_API_KEY")
        if not key:
            raise ValueError("Set ZYTE_SCRAPY_CLOUD_API_KEY privately")
        metadata = _remote_metadata(context, key, fetch)
        job_id = context["bindings"]["job_id"]
        request_raw, requests = _download(job_id, "requests", key, fetch)
        stats_raw = fetch(f"{HOST}/requests/{job_id}/stats", key, STATS_BYTES)
        stats = _object(stats_raw)
        count = stats.get("totals", {}).get("input_values")
        if type(count) is not int or count != len(requests):
            raise ValueError("Paginated Requests count differs from official storage stats")
        log_raw, logs = _download(job_id, "logs", key, fetch)
        receipt = {
            "kind": KIND, **context["bindings"], "metadata": metadata,
            "requests_stats_response_sha256": sha(stats_raw),
            "requests": {"sha256": sha(request_raw), "count": len(requests)},
            "logs": {"sha256": sha(log_raw), "count": len(logs)},
            "terminal_empty_page_observed_for_both": True,
            "approved_for_advisor": False,
        }
        receipt["receipt_sha256"] = policy.digest(receipt)
        report = diagnose(context, metadata, requests, logs)
        _write_private(root / "requests.jl", request_raw)
        _write_private(root / "logs.jl", log_raw)
        _write_private(root / "receipt.json", _json_bytes(receipt))
        _write_private(root / "diagnostics.json", _json_bytes(report))
        return report
    except BaseException:
        shutil.rmtree(root)
        raise


def replay_evidence(context, export_dir):
    """Offline replay uses exact as-run receipts; never checks today's expiry."""
    root = Path(export_dir)
    receipt = _object(_read_file(root / "receipt.json", JSON_LIMIT))
    if (receipt.get("kind") != KIND or receipt.get("approved_for_advisor") is not False
            or receipt.get("terminal_empty_page_observed_for_both") is not True
            or any(receipt.get(k) != v for k, v in context["bindings"].items())
            or receipt.get("receipt_sha256") != policy.digest({
                k: v for k, v in receipt.items() if k != "receipt_sha256"
            })):
        raise ValueError("Evidence receipt does not bind this as-run job")
    parsed = {}
    for kind in ("requests", "logs"):
        raw = _read_file(root / (kind + ".jl"), MAX_BYTES[kind])
        rows = _rows_from_bytes(raw, kind, context["bindings"]["job_id"])
        if receipt.get(kind) != {"sha256": sha(raw), "count": len(rows)}:
            raise ValueError("Offline evidence checksum/count mismatch")
        parsed[kind] = rows
    return diagnose(context, receipt["metadata"], parsed["requests"], parsed["logs"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    ranking = parser.add_mutually_exclusive_group(required=True)
    ranking.add_argument("--g3-all460", type=Path)
    ranking.add_argument("--g3-top300", type=Path)
    parser.add_argument("--target", type=int, default=300)
    parser.add_argument("--campaign-sha256", required=True)
    parser.add_argument("--category", required=True, choices=ORDER)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--out-dir", type=Path, help="Export evidence via read-only Zyte GETs")
    mode.add_argument("--replay-dir", type=Path, help="Replay an existing export offline")
    args = parser.parse_args()
    context = load_context(
        read_g3_review_csv(args.g3_all460 or args.g3_top300), args.target,
        args.campaign_sha256, args.category, args.ledger_dir, args.archive_dir,
    )
    if args.replay_dir:
        report = replay_evidence(context, args.replay_dir)
    else:
        report = export_evidence(context, args.out_dir)
    # Keep full source IDs and raw data in private operator storage.
    print(json.dumps({k: v for k, v in report.items()
                      if k not in {"missing_manifest_ids", "target_without_primary_get_ids"}},
                     sort_keys=True))


if __name__ == "__main__":
    main()
