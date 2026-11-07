"""P23C3A: download existing approved single-source Zyte job evidence, read-only.

Only reads already-completed jobs named in a P23C1 receipt ledger. No
publisher HTTP requests, Zyte scheduling, deploys, publisher permissions,
trust promotion, human review, or original-HTML response capture.

Official Zyte Scrapy Cloud storage: GET jobs, requests, requests/stats, logs.
Uses the repository's Basic-auth, no-redirect, storage.zyte.com-only client.
Keep filled receipts, credentials and downloaded raw Logs off public CI.
"""
import argparse
import hashlib
import json
import os
import shutil
import urllib.parse
from pathlib import Path

from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.validation_access import digest
from scripts.archive_jobs import (
    _job_details, _request, JOB_ID, load_archive,
)
from scripts.p23c1_zyte_canary_archive_gate import (
    _ensure_archive, _read_json, audit_receipts,
)
from scripts.p23c2_zyte_requests_logs_html_gate import (
    MAX_LOGS, MAX_LOG_BYTES, MAX_REQUESTS, MAX_REQUEST_BYTES,
    MAX_LINE_BYTES, _check_request_schema, _check_log_schema,
    _pairs_no_duplicates, blank_export_index,
)
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)

SCHEMA = "1.0"
KIND = "p23c3a_existing_zyte_job_readonly_export_NOT_PUBLISHER_PERMISSION"
MAX_JOBS = 2
PAGE_SIZE = {"requests": 32, "logs": 40}
PAGE_BYTES = 3_000_000
META_BYTES = 2_000_000
STATS_BYTES = 200_000
HOST = "https://storage.zyte.com"
PREFLIGHT = "READ_ONLY_PRECHECK_NOT_CRAWL_AUTHORIZATION"


def _url(kind, job_id, offset, count):
    if kind not in {"requests", "logs"} or not JOB_ID.fullmatch(job_id):
        raise ValueError("Only a configured, valid job Requests/Logs endpoint is supported")
    params = urllib.parse.urlencode({
        "format": "jl", "meta": "_key",
        "count": count, "start": f"{job_id}/{offset}",
    })
    return f"{HOST}/{kind}/{job_id}?{params}"


def _parse_page(raw, kind, job_id, offset, max_page):
    if not isinstance(raw, bytes) or len(raw) > PAGE_BYTES:
        raise ValueError("Invalid or oversized official Zyte raw evidence page")
    try:
        contents = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Non-UTF8 Zyte JSONL page") from exc
    lines = contents.splitlines()
    if len(lines) > max_page:
        raise ValueError("Zyte page exceeded count parameter")
    parsed = []
    for i, line in enumerate(lines):
        if not line.strip() or len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError("Invalid or oversized Zyte evidence JSONL line")
        try:
            item = json.loads(line, object_pairs_hook=_pairs_no_duplicates)
        except json.JSONDecodeError as exc:
            raise ValueError("Zyte page contains invalid JSONL") from exc
        if not isinstance(item, dict):
            raise ValueError("Zyte evidence record must be an object")
        # Ordinal verification is mandatory. Never silently accept truncated
        # or overlapping storage pagination and call that a complete export.
        expected_key = f"{job_id}/{offset + i}"
        if item.get("_key") != expected_key:
            raise ValueError("Missing/duplicated/out-of-order official Zyte _key")
        if kind == "requests":
            _check_request_schema(item)
        else:
            _check_log_schema(item)
        parsed.append(item)
    return parsed


def _serialise(rows, byte_limit):
    lines = []
    total = 0
    for row in rows:
        raw = (json.dumps(
            row, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ) + "\n").encode("utf-8")
        total += len(raw)
        if total > byte_limit:
            raise ValueError("Zyte exported evidence exceeds private retention budget")
        lines.append(raw)
    return b"".join(lines)


def _download_paged(job_id, kind, api_key, fetch):
    if not JOB_ID.fullmatch(job_id) or kind not in {"requests", "logs"}:
        raise ValueError("Unrecognized exact Zyte job/kind")
    maximum = MAX_REQUESTS if kind == "requests" else MAX_LOGS
    byte_limit = MAX_REQUEST_BYTES if kind == "requests" else MAX_LOG_BYTES
    received = []
    while True:
        offset = len(received)
        if offset > maximum:
            raise ValueError("Zyte export exceeded max single-source row count")
        count = min(PAGE_SIZE[kind], maximum - offset + 1)
        url = _url(kind, job_id, offset, count)
        raw = fetch(url, api_key, PAGE_BYTES)
        page = _parse_page(raw, kind, job_id, offset, count)
        received.extend(page)
        if len(received) > maximum:
            raise ValueError("Zyte evidence export exceeds bounded rows")
        if len(page) < count:
            break
    return _serialise(received, byte_limit), len(received)


def _verify_current_job(job_id, archived, api_key, fetch):
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid completed Zyte job ID")
    raw = fetch(f"{HOST}/jobs/{job_id}", api_key, META_BYTES)
    if not isinstance(raw, bytes) or len(raw) > META_BYTES:
        raise ValueError("Invalid response from official Zyte Job metadata API")
    try:
        remote = json.loads(raw, object_pairs_hook=_pairs_no_duplicates)
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed official Zyte Job metadata JSON") from exc
    if not isinstance(remote, dict):
        raise ValueError("Zyte Job metadata must be an object")
    verified = _job_details(job_id, remote)
    # The archive must match fresh completed official Job metadata, including
    # exact spider scope/args, version, job state and item count. This is
    # still an API observation, NOT independent publisher authentication.
    for name in (
        "job_id", "spider", "category", "state", "close_reason",
        "deploy_id", "deployment_version", "expected_item_count",
        "spider_args", "unrecorded_argument_names",
    ):
        if verified.get(name) != archived.get(name):
            raise ValueError("Official Zyte job metadata differs from local immutable archive")
    if verified["state"] != "finished" or len(verified["spider_args"]) < 6:
        raise ValueError("Only pinned, finished source-scoped jobs can be exported")
    return hashlib.sha256(raw).hexdigest()


def _verify_requests_stats(job_id, observed, api_key, fetch):
    raw = fetch(f"{HOST}/requests/{job_id}/stats", api_key, STATS_BYTES)
    if not isinstance(raw, bytes) or len(raw) > STATS_BYTES:
        raise ValueError("Invalid official Zyte Requests stats response")
    try:
        stats = json.loads(raw, object_pairs_hook=_pairs_no_duplicates)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid official Zyte Requests stats JSON") from exc
    if not isinstance(stats, dict) or not isinstance(stats.get("totals"), dict):
        raise ValueError("Official Zyte Requests stats totals are missing")
    count = stats["totals"].get("input_values")
    if type(count) is not int or count != observed:
        raise ValueError("Paginated Requests export count != official Zyte Requests stats")
    return hashlib.sha256(raw).hexdigest()


def _preflight(receipts, archive_root, source_id, *, access_registry=None,
               now=None):
    """Enforce exact P23C1 source/round/policy checks before any API call."""
    if not isinstance(source_id, str) or source_id not in {
        s["id"] for s in load_sources()
    }:
        raise ValueError("Unknown source ID")
    report, all_rows = audit_receipts(
        receipts, archive_root, access_registry=access_registry, now=now,
    )
    source_rows = [row for row in all_rows if row["source_id"] == source_id]
    if len(source_rows) != 2:
        raise ValueError("Source not in original frozen P20A canary cohort")
    jobs = [row["zyte_job_id"] for row in source_rows
            if row["zyte_job_id"] is not None]
    if not 1 <= len(jobs) <= MAX_JOBS:
        raise ValueError("Need one or two genuinely archived original single-source jobs")
    for row in source_rows:
        if row["zyte_job_id"] is not None and (
                row["policy_access_status"] !=
                "local_review_attestation_present_NOT_permission"
                or not row["archive_item_integrity_checked"]):
            raise ValueError("Source/job scope or access review is not current")
    return report, jobs


def _require_new_output(directory):
    target = Path(directory)
    if target.exists() or target.is_symlink() or any(
        part.is_symlink() for part in target.parents
    ):
        raise ValueError("Use a NEW private export directory; never overwrite")
    return target


def download_existing_job_evidence(receipts, archive_root, out_dir, source_id,
                                   *, api_key=None, fetch=None,
                                   access_registry=None, now=None):
    """Download one reviewed source's existing completed jobs, NO new jobs.

    The caller provides the real operator's private receipt file and archived
    Items, reviewed source policy, and Scrapy Cloud key. Synthetic fetch
    injection is for offline unit tests only.
    """
    target = _require_new_output(out_dir)
    c1, job_ids = _preflight(
        receipts, archive_root, source_id,
        access_registry=access_registry, now=now,
    )
    key = api_key if api_key is not None else os.environ.get(
        "ZYTE_SCRAPY_CLOUD_API_KEY"
    )
    if not isinstance(key, str) or not key or any(
        x in key for x in ("\r", "\n", "\x00")
    ):
        raise ValueError("Set Scrapy Cloud API key privately for READ-ONLY storage")
    fetcher = fetch if fetch is not None else _request

    # Download every selected job and validate the full pagination/stats in
    # memory first. Do not write a misleading partial receipt on API errors.
    snapshots = []
    for job_id in job_ids:
        envelope, records = load_archive(_ensure_archive(archive_root, job_id))
        if len(records) != 1 or records[0]["source_id"] != source_id:
            raise ValueError("Local archived Items scope changed before download")
        metadata_sha = _verify_current_job(
            job_id, envelope["job"], key, fetcher,
        )
        requests_bytes, request_count = _download_paged(
            job_id, "requests", key, fetcher,
        )
        requests_stats_sha = _verify_requests_stats(
            job_id, request_count, key, fetcher,
        )
        logs_bytes, log_count = _download_paged(
            job_id, "logs", key, fetcher,
        )
        snapshots.append({
            "job_id": job_id, "requests": requests_bytes,
            "logs": logs_bytes, "request_count": request_count,
            "log_count": log_count,
            "remote_metadata_sha256": metadata_sha,
            "remote_request_stats_sha256": requests_stats_sha,
        })

    index = blank_export_index()
    for record, item in zip(index["rows"], receipts["rows"]):
        for slot, previous in zip(record["rounds"], item["rounds"]):
            slot["zyte_job_id"] = previous["zyte_job_id"]
    selected = next(x for x in index["rows"] if x["source_id"] == source_id)
    slots = {s["zyte_job_id"]: s for s in selected["rounds"]}
    report = {
        "schema_version": SCHEMA, "kind": KIND,
        "source_id": source_id,
        "source_rounds_downloaded": len(snapshots),
        "frozen_original_source_denominator": 18,
        "frozen_original_round_denominator": 36,
        "p23c1_report_sha256": c1["report_sha256"],
        "completed_jobs": [],
        "read_only_zyte_storage_gets_only": True,
        "new_publisher_requests": 0,
        "new_zyte_jobs": 0,
        "publisher_permissions_granted": 0,
        "raw_logs_are_sensitive_private_data": True,
        "operator_must_verify_actual_remote_zyte_deployment": True,
        "publisher_response_html_proven": False,
        "human_gold_accuracy_measured": False,
        "full_inventory_go": False,
        "approved_for_advisor": False,
    }
    out = _private_new_directory(target)
    try:
        for snap in snapshots:
            job_id = snap["job_id"]
            dirname = job_id.replace("/", "_")
            folder = out / dirname
            folder.mkdir(mode=0o700)
            for kind in ("requests", "logs"):
                path = folder / (kind + ".jl")
                _write_private(path, snap[kind])
                slots[job_id][kind] = {
                    "file": dirname + "/" + kind + ".jl",
                    "sha256": hashlib.sha256(snap[kind]).hexdigest(),
                }
            report["completed_jobs"].append({
                "zyte_job_id": job_id,
                "requests_exported": snap["request_count"],
                "logs_exported": snap["log_count"],
                "current_job_metadata_sha256_NOT_remote_deploy_proof":
                    snap["remote_metadata_sha256"],
                "current_requests_stats_sha256": snap["remote_request_stats_sha256"],
            })
        _write_private(
            out / "raw_requests_logs_receipt_index_FILLED.json",
            (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        report["report_sha256"] = digest(report)
        _write_private(
            out / "read_only_completed_job_export_receipt_NOT_GO.json",
            (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
    except Exception:
        shutil.rmtree(out)
        raise
    return out, report, index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight", action="store_true")
    modes.add_argument("--download-existing", action="store_true")
    parser.add_argument("--source-id", required=True,
                        help="One original P20A configured source ID")
    parser.add_argument("--p23c1-private-receipts", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path,
                        help="New private directory (download only)")
    args = parser.parse_args()
    receipts = _read_json(args.p23c1_private_receipts)
    if args.preflight:
        if args.out_dir is not None:
            parser.error("--preflight does not write evidence")
        _report, jobs = _preflight(
            receipts, args.archive_root, args.source_id,
        )
        answer = {
            "status": PREFLIGHT, "source_id": args.source_id,
            "existing_finished_jobs": jobs, "zyte_requests": 0,
            "publisher_requests": 0, "canary_go": False,
        }
    else:
        if args.out_dir is None:
            parser.error("--download-existing needs --out-dir")
        path, report, _ = download_existing_job_evidence(
            receipts, args.archive_root, args.out_dir, args.source_id,
        )
        answer = {
            "status": "EXPORTED_READ_ONLY_NOT_CANARY_GO",
            "output_dir": str(path),
            "source_id": report["source_id"],
            "finished_jobs_read": report["source_rounds_downloaded"],
            "new_publisher_requests": 0, "new_zyte_jobs": 0,
        }
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
