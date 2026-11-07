"""P23C2: offline validation of Zyte Requests/Logs and original HTML evidence.

Reuses P23C1's frozen 18-source/36-round immutable Items verification
and P22A1's original-publisher HTML byte and policy accession. No HTTP calls,
no Zyte API calls, no permissions, no human reviews and no positive GO state.

Raw Requests/Logs use the documented Zyte JSON Lines object fields. These
operator-supplied files are NOT remotely authenticated or guaranteed complete
by their own SHA. Original HTML independently captured via P22A1 is NOT
asserted to be the exact body returned by the archived Zyte job.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.validation_access import _utc, digest
from scripts.accession_cross_category_html import frozen_plan, stage_data
from scripts.archive_jobs import load_archive
from scripts.p23c1_zyte_canary_archive_gate import (
    audit_receipts as audit_items, blank_receipts, _ensure_archive,
)
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)

VERSION = "1.0"
KIND = "p23c2_offline_zyte_raw_export_and_original_html_crosscheck_NOT_GO"
INDEX_KIND = "p23c2_private_raw_requests_logs_export_index_NOT_PERMISSION"
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_REQUESTS = 96
MAX_LOGS = 10000
MAX_REQUEST_BYTES = 1_500_000
MAX_LOG_BYTES = 6_000_000
MAX_LINE_BYTES = 65536
MAX_JOB_WINDOW = timedelta(hours=2)
LOG_LEVELS = {10, 20, 30, 40, 50}
DENIED_CODES = {401, 403, 407, 429}
SOURCE_FIELDS = frozenset({"source_id", "source_url", "category", "wave", "rounds"})
SLOT_FIELDS = frozenset({"round", "zyte_job_id", "requests", "logs"})
FILE_FIELDS = frozenset({"file", "sha256"})
INDEX_FIELDS = frozenset({
    "schema_version", "kind", "frozen_plan_sha256",
    "manifest_sha256", "source_registry_sha256", "package_sha256",
    "approved_for_advisor", "rows",
})
CSV_FIELDS = (
    "wave", "source_id", "category", "round", "zyte_job_id",
    "item_archive_status", "request_export_status", "log_export_status",
    "primary_get_count", "primary_status_matches_item",
    "unexpected_request_count", "log_error_count",
    "p22a1_original_html_status", "same_zyte_html_response_proven",
    "source_round_evidence_state", "issue_codes",
)


def _time(now=None):
    value = datetime.now(timezone.utc) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Time must be timezone-aware")
    return value.astimezone(timezone.utc)


def blank_export_index(plan=None):
    plan = frozen_plan() if plan is None else plan
    original = blank_receipts(plan)
    return {
        "schema_version": VERSION, "kind": INDEX_KIND,
        "frozen_plan_sha256": original["frozen_plan_sha256"],
        "manifest_sha256": original["manifest_sha256"],
        "source_registry_sha256": original["source_registry_sha256"],
        "package_sha256": original["expected_package_sha256"],
        "approved_for_advisor": False,
        "rows": [{
            "source_id": s["source_id"], "source_url": s["source_url"],
            "category": s["category"], "wave": s["wave"],
            "rounds": [{
                "round": n, "zyte_job_id": None,
                "requests": None, "logs": None,
            } for n in (1, 2)],
        } for s in original["rows"]],
    }


def _validate_index(index, item_receipts, plan, *, historical=False):
    expected = blank_export_index(plan)
    if (not isinstance(index, dict)
            or set(index) != INDEX_FIELDS
            or any(index[k] != expected[k] for k in
                   INDEX_FIELDS - ({"rows", "package_sha256"}
                                   if historical else {"rows"}))
            or (historical and index.get("package_sha256") !=
                item_receipts.get("expected_package_sha256"))
            or not isinstance(index["rows"], list)
            or len(index["rows"]) != 18):
        raise ValueError("Missing, privileged or stale P23C2 evidence index")
    if (not isinstance(item_receipts, dict)
            or not isinstance(item_receipts.get("rows"), list)
            or len(item_receipts["rows"]) != 18):
        raise ValueError("P23C1 source-round receipts not supplied")
    seen_files = set()
    for a, b, c in zip(index["rows"], expected["rows"], item_receipts["rows"]):
        if (not isinstance(a, dict) or set(a) != SOURCE_FIELDS
                or any(a[k] != b[k] for k in SOURCE_FIELDS - {"rounds"})
                or not isinstance(a["rounds"], list)
                or len(a["rounds"]) != 2):
            raise ValueError("Changed original P20A source or round count")
        for number, (slot, item_slot) in enumerate(zip(a["rounds"], c["rounds"]), 1):
            if (not isinstance(slot, dict) or set(slot) != SLOT_FIELDS
                    or type(slot["round"]) is not int or slot["round"] != number
                    or slot["zyte_job_id"] != item_slot["zyte_job_id"]):
                raise ValueError("Source round / Zyte job ID differs from P23C1")
            for kind in ("requests", "logs"):
                value = slot[kind]
                if value is None:
                    continue
                if slot["zyte_job_id"] is None:
                    raise ValueError("Raw export cannot exist without a job receipt")
                if (not isinstance(value, dict) or set(value) != FILE_FIELDS
                        or not isinstance(value["sha256"], str)
                        or not SHA.fullmatch(value["sha256"])
                        or not isinstance(value["file"], str)
                        or not 1 <= len(value["file"]) <= 240):
                    raise ValueError("Malformed private raw export receipt")
                name = value["file"]
                if (name.startswith("/") or "\\" in name or "\x00" in name
                        or "//" in name or name.endswith("/")
                        or any(x in {"", ".", ".."} for x in name.split("/"))
                        or name in seen_files):
                    raise ValueError("Unsafe or reused private raw export file")
                seen_files.add(name)
    return index


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object field in raw Zyte export")
        result[key] = value
    return result


def _read_raw_export(root, receipt, *, kind):
    """Read SHA-bound private JSONL, never strings from arbitrary web URLs."""
    path_root = Path(root)
    if (not path_root.is_dir() or path_root.is_symlink()
            or any(p.is_symlink() for p in path_root.parents)):
        raise ValueError("Expected non-symlink private export root")
    current = path_root
    for segment in receipt["file"].split("/"):
        current = current / segment
        if current.is_symlink():
            raise ValueError("Private raw export symlink denied")
    if (not current.is_file()
            or current.stat().st_size > (
                MAX_REQUEST_BYTES if kind == "requests" else MAX_LOG_BYTES
            )):
        raise ValueError("Missing or oversized raw Zyte " + kind + " JSONL")
    raw = current.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
        raise ValueError("Raw Zyte " + kind + " export SHA-256 mismatch")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Raw Zyte JSONL must be UTF-8") from exc
    # Empty JSONL is valid: a held job may have zero recorded HTTP requests.
    records = []
    maximum = MAX_REQUESTS if kind == "requests" else MAX_LOGS
    for raw_line in text.splitlines():
        if len(raw_line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ValueError("Oversized Zyte raw JSONL line")
        if not raw_line.strip():
            raise ValueError("Zyte raw export contains an empty JSONL record")
        try:
            row = json.loads(raw_line, object_pairs_hook=_pairs_no_duplicates)
        except json.JSONDecodeError as exc:
            raise ValueError("Zyte export must be genuine JSON Lines") from exc
        if not isinstance(row, dict):
            raise ValueError("Expected Zyte JSONL object, not JSON arrays")
        records.append(row)
        if len(records) > maximum:
            raise ValueError("Excessively large single-source Zyte export")
    return records


def _ms_to_time(value):
    if type(value) is not int or not 946684800000 <= value <= 4102444800000:
        raise ValueError("Invalid Zyte epoch milliseconds")
    return datetime.fromtimestamp(value / 1000, timezone.utc)


def _check_request_schema(row):
    if not isinstance(row, dict):
        raise ValueError("Zyte Request must be an object")
    for key in ("time", "method", "url", "status", "duration", "rs"):
        if key not in row:
            raise ValueError("Zyte Request missing documented required field")
    _ms_to_time(row["time"])
    if (not isinstance(row["method"], str) or not row["method"]
            or not isinstance(row["url"], str) or not row["url"]
            or type(row["status"]) is not int
            or not 0 <= row["status"] <= 599
            or type(row["duration"]) is not int or row["duration"] < 0
            or type(row["rs"]) is not int or row["rs"] < 0):
        raise ValueError("Invalid Zyte Request object field type")
    if "parent" in row and (type(row["parent"]) is not int or row["parent"] < 0):
        raise ValueError("Invalid Zyte request parent field")


def _check_log_schema(row):
    if (not isinstance(row, dict)
            or type(row.get("level")) is not int
            or row["level"] not in LOG_LEVELS
            or not isinstance(row.get("message"), str)
            or len(row["message"]) > 60000):
        raise ValueError("Invalid Zyte Log object")
    if "time" in row:
        _ms_to_time(row["time"])


def _window(start, finish_ms, record_ms):
    recorded = _ms_to_time(record_ms)
    end = start + MAX_JOB_WINDOW
    if type(finish_ms) is int:
        finished = _ms_to_time(finish_ms)
        if finished < start:
            return False
        end = min(end, finished + timedelta(minutes=5))
    return start - timedelta(minutes=5) <= recorded <= end


def _robots_url(url):
    parsed = urlsplit(url)
    return parsed._replace(path="/robots.txt", query="", fragment="").geturl()


def _request_diagnostics(rows, *, source, job, item):
    start = _utc(item["run_started_at_utc"])
    primary, robots, extra = [], [], []
    issues = set()
    robots_url = _robots_url(source["url"])
    for row in rows:
        _check_request_schema(row)
        if not _window(start, job.get("finished_time_ms"), row["time"]):
            issues.add("request_timestamp_outside_job_window")
        if row["method"] != "GET":
            issues.add("unexpected_non_get_method")
            extra.append(row)
        elif row["url"] == source["url"]:
            primary.append(row)
        elif row["url"] == robots_url:
            robots.append(row)
        else:
            issues.add("unexpected_url_or_redirect_request")
            extra.append(row)
        if row["status"] in DENIED_CODES:
            issues.add("publisher_access_denial_or_rate_limit_observed")
        if row["status"] == 0:
            issues.add("request_without_http_response_observed")
    if len(primary) != 1:
        issues.add("missing_or_duplicate_exact_primary_get")
    if len(robots) > 1:
        issues.add("duplicate_robots_requests")
    expected = job.get("stats", {}).get("downloader/request_count")
    if type(expected) is not int:
        issues.add("download_request_count_not_preserved_in_job_archive")
        count_matches = False
    elif expected != len(rows):
        issues.add("requests_export_count_differs_from_scrapy_stats")
        count_matches = False
    else:
        count_matches = True
    item_status = item.get("http_status")
    matches = (
        len(primary) == 1 and type(item_status) is int
        and item_status == primary[0]["status"]
    )
    if len(primary) == 1 and not matches:
        issues.add("primary_request_status_differs_from_source_item")
    return {
        "request_count": len(rows), "primary_get_count": len(primary),
        "robots_get_count": len(robots),
        "unexpected_request_count": len(extra),
        "recorded_request_count_matches_job_stats": count_matches,
        "primary_status_matches_item": matches,
        "primary_time_utc": (
            _ms_to_time(primary[0]["time"]) if len(primary) == 1 else None
        ),
        "issues": sorted(issues),
    }


def _log_diagnostics(rows, *, job, item):
    start = _utc(item["run_started_at_utc"])
    issues = set()
    errors = 0
    for row in rows:
        _check_log_schema(row)
        if "time" in row and not _window(
            start, job.get("finished_time_ms"), row["time"]
        ):
            issues.add("log_timestamp_outside_job_window")
        if row["level"] >= 40:
            errors += 1
    if errors:
        issues.add("job_error_or_critical_logs_present")
    # Log strings are deliberately NEVER copied into the audit artifact.
    return {"log_count": len(rows), "log_error_count": errors,
            "issues": sorted(issues)}


def audit_evidence(item_receipts, export_index, archive_root, export_root,
                   *, p22a1_ledger=None, html_root=None, access_registry=None,
                   now=None, historical_policy_root=None,
                   historical_egg_root=None):
    """Correlate archival evidence without converting it into permission/GO."""
    clock = _time(now)
    plan = frozen_plan()
    historical = (historical_policy_root is not None or
                  historical_egg_root is not None)
    _validate_index(export_index, item_receipts, plan, historical=historical)
    c1_report, c1_rows = audit_items(
        item_receipts, archive_root, now=clock, access_registry=access_registry,
        plan=plan,
        historical_policy_root=historical_policy_root,
        historical_egg_root=historical_egg_root,
    )
    if (c1_report["original_selected_sources"] != 18
            or c1_report["original_source_round_denominator"] != 36):
        raise ValueError("P23C1 source-round accounting drift")
    if (p22a1_ledger is None) != (html_root is None):
        raise ValueError("P22A1 ledger and private HTML root required together")
    if p22a1_ledger is None:
        html_cases = {}
        html_metrics = None
    else:
        html_metrics, cases, _ = stage_data(
            plan, p22a1_ledger, html_root, now=clock,
        )
        if len(cases) != 36 or html_metrics["source_round_denominator"] != 36:
            raise ValueError("P22A1 original HTML denominator changed")
        html_cases = {(r["source_id"], r["round"]): r for r in cases}
    from agentfuse_crawlers.sources import load_sources
    by_id = {s["id"]: s for s in load_sources()}
    rows, counts = [], Counter()
    for source_row, exp_row in zip(item_receipts["rows"], export_index["rows"]):
        source = by_id[source_row["source_id"]]
        for i, (slot, ex) in enumerate(
                zip(source_row["rounds"], exp_row["rounds"])):
            idx = len(rows)
            c1 = c1_rows[idx]
            if (c1["source_id"] != source["id"]
                    or c1["round"] != slot["round"]
                    or c1["zyte_job_id"] != slot["zyte_job_id"]):
                raise ValueError("P23C1 row/source/round mismatch")
            job_id = slot["zyte_job_id"]
            issues = set()
            request_status = "no_export_supplied"
            log_status = "no_export_supplied"
            requests = {"request_count": 0, "primary_get_count": 0,
                        "unexpected_request_count": 0,
                        "primary_status_matches_item": False,
                        "recorded_request_count_matches_job_stats": False,
                        "primary_time_utc": None, "issues": []}
            logs = {"log_count": 0, "log_error_count": 0, "issues": []}
            if job_id is not None:
                envelope, records = load_archive(
                    _ensure_archive(archive_root, job_id)
                )
                job, item = envelope["job"], records[0]
                if ex["requests"] is not None:
                    raw = _read_raw_export(
                        export_root, ex["requests"], kind="requests",
                    )
                    requests = _request_diagnostics(
                        raw, source=source, job=job, item=item,
                    )
                    request_status = "sha256_bound_jsonl_parsed_NOT_authenticated"
                    issues.update(requests["issues"])
                else:
                    issues.add("requests_export_missing")
                if ex["logs"] is not None:
                    raw = _read_raw_export(
                        export_root, ex["logs"], kind="logs",
                    )
                    logs = _log_diagnostics(raw, job=job, item=item)
                    log_status = "sha256_bound_jsonl_parsed_NOT_authenticated"
                    issues.update(logs["issues"])
                    if not raw:
                        issues.add("empty_logs_export_does_not_establish_full_job_trace")
                else:
                    issues.add("logs_export_missing")
            elif ex["requests"] is not None or ex["logs"] is not None:
                raise ValueError("Jobless source round has raw export")
            html = html_cases.get((source["id"], slot["round"]))
            html_status = "not_supplied"
            original_sha = None
            if html and html["state"] == "captured":
                original_sha = html["raw_html_sha256"]
                html_status = (
                    "independent_p22a1_original_html_sha256_verified"
                )
                if c1["slot_state"] != (
                        "http200_item_observed_NOT_ORIGINAL_HTML_VERIFIED"):
                    issues.add("html_capture_has_no_matching_http200_item")
                if requests["primary_time_utc"] is None:
                    issues.add("html_capture_unlinked_to_primary_request")
                else:
                    capture_at = _utc(html["captured_at_utc"])
                    if abs((capture_at - requests["primary_time_utc"]).total_seconds()
                           ) > 7200:
                        issues.add("separately_captured_html_outside_two_hour_window")
            elif html and html["state"] != "not_attempted":
                html_status = "p22a1_" + html["state"]
            if job_id is not None:
                if c1["slot_state"] != (
                        "http200_item_observed_NOT_ORIGINAL_HTML_VERIFIED"):
                    issues.add("source_item_not_usable_http200")
                elif not requests["primary_status_matches_item"]:
                    issues.add("http200_item_not_corroborated_by_request")
                if (job.get("close_reason") != "finished"
                        and c1["slot_state"] ==
                        "http200_item_observed_NOT_ORIGINAL_HTML_VERIFIED"):
                    issues.add("zyte_job_close_reason_not_finished")
            if job_id is None:
                state = c1["slot_state"]
            elif issues:
                state = "held_for_source_round_evidence_review"
            elif (html_status ==
                    "independent_p22a1_original_html_sha256_verified"):
                state = "all_local_exports_consistent_NOT_origin_verified"
            else:
                state = "requests_logs_consistent_HTML_NOT_SUPPLIED"
            row = {
                "wave": source_row["wave"],
                "source_id": source["id"], "category": source["category"],
                "round": slot["round"], "zyte_job_id": job_id,
                "item_archive_status": c1["slot_state"],
                "request_export_status": request_status,
                "log_export_status": log_status,
                "request_record_count": requests["request_count"],
                "primary_get_count": requests["primary_get_count"],
                "unexpected_request_count": requests["unexpected_request_count"],
                "request_count_matches_job_stats":
                    requests["recorded_request_count_matches_job_stats"],
                "primary_status_matches_item":
                    requests["primary_status_matches_item"],
                "log_record_count": logs["log_count"],
                "log_error_count": logs["log_error_count"],
                "p22a1_original_html_status": html_status,
                "original_html_sha256": original_sha,
                "same_zyte_html_response_proven": False,
                "source_round_evidence_state": state,
                "issue_codes": sorted(issues),
                "publisher_permission_independently_authenticated": False,
                "approved_for_advisor": False,
            }
            rows.append(row)
            counts[state] += 1
    if len(rows) != 36 or sum(counts.values()) != 36:
        raise ValueError("P23C2 lost a frozen source-round")
    report = {
        "schema_version": VERSION, "kind": KIND,
        "status": "NO_GO",
        "frozen_plan_sha256": plan["plan_sha256"],
        "source_manifest_sha256": manifest_sha256(),
        "source_lifecycle_sha256": registry_revision_sha256(),
        "p23c1_report_sha256": c1_report["report_sha256"],
        "historical_original_policy_and_egg_provenance_replay": historical,
        "historical_replay_grants_current_publisher_access": False,
        "p22a1_html_accession_sha256": (
            html_metrics["accession_sha256"] if html_metrics else None
        ),
        "original_selected_sources": 18,
        "original_source_round_denominator": 36,
        "source_rounds_with_items": c1_report[
            "source_rounds_with_immutable_item_archives"],
        "source_rounds_with_requests_export": sum(
            r["request_export_status"].startswith("sha256_bound")
            for r in rows),
        "source_rounds_with_logs_export": sum(
            r["log_export_status"].startswith("sha256_bound") for r in rows),
        "source_rounds_with_exact_primary_http_get": sum(
            r["primary_get_count"] == 1 for r in rows),
        "source_rounds_with_independent_original_html_sha": sum(
            r["original_html_sha256"] is not None for r in rows),
        "source_rounds_with_unexpected_requests": sum(
            r["unexpected_request_count"] > 0 for r in rows),
        "source_rounds_with_evidence_issues": sum(
            bool(r["issue_codes"]) for r in rows),
        "source_round_states": dict(sorted(counts.items())),
        "all_36_source_rounds": rows,
        "requests_export_origin_cryptographically_authenticated": False,
        "logs_export_origin_cryptographically_authenticated": False,
        "raw_original_html_response_from_same_zyte_job_proven": False,
        "remote_deployment_independently_authenticated": False,
        "access_permissions_or_human_gold_created": False,
        "full_460_source_diagnostic_approved": False,
        "approved_for_advisor": False,
        "new_network_requests": 0, "new_zyte_jobs": 0,
        "next_required_evidence": [
            "Genuine current Git-reviewed publisher access determinations",
            "Real operator-confirmed Zyte deployment and source-specific jobs",
            "Independent verification Requests/Logs exports are complete and official",
            "Original HTML provenance and same-job response-body binding",
            "Two independent whole-page human accuracy reviews",
        ],
    }
    report["report_sha256"] = digest(report)
    return report, rows


def _json_output(root, name, data):
    _write_private(
        root / name,
        (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def prepare(out_dir):
    root = _private_new_directory(out_dir)
    try:
        _json_output(root, "raw_requests_logs_receipt_index_BLANK.json",
                     blank_export_index())
        _write_private(root / "READ_ME_NO_CRAWL.txt", (
            "P23C2: exactly 18 original sources and 36 frozen rounds.\n"
            "All Requests/Logs export receipts start BLANK; no jobs created.\n"
            "Never fill a job unless the matching P23C1 receipt has a real job ID.\n"
            "A raw export descriptor has file and lowercase sha256 keys.\n"
            "Keep filled receipts, raw Requests/Logs, private source-review\n"
            "notes, and original publisher HTML off GitHub and public CI.\n"
            "The report always says NO_GO; SHA checks do not prove origin.\n"
        ).encode("utf-8"))
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def write_report(report, rows, out_dir):
    root = _private_new_directory(out_dir)
    try:
        _json_output(root, "zyte_original_evidence_36_rounds_NO_GO.json",
                     report)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: _safe_csv(
                    ",".join(row[key]) if key == "issue_codes" else row.get(key, "")
                ) for key in CSV_FIELDS
            })
        _write_private(root / "all_36_round_evidence.csv",
                       stream.getvalue().encode("utf-8-sig"))
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def _json_file(path):
    p = Path(path)
    if (not p.is_file() or p.is_symlink()
            or any(x.is_symlink() for x in p.parents)
            or not 2 <= p.stat().st_size <= 250000):
        raise ValueError("Missing, linked, or oversized private JSON evidence index")
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--audit", action="store_true")
    parser.add_argument("--p23c1-private-receipts", type=Path)
    parser.add_argument("--raw-export-index", type=Path)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--export-root", type=Path)
    parser.add_argument("--p22a1-private-ledger", type=Path)
    parser.add_argument("--html-root", type=Path)
    parser.add_argument("--historical-policy-root", type=Path)
    parser.add_argument("--historical-egg-root", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.prepare:
        if any((
            args.p23c1_private_receipts, args.raw_export_index,
            args.archive_root, args.export_root,
            args.p22a1_private_ledger, args.html_root,
            args.historical_policy_root, args.historical_egg_root,
        )):
            parser.error("--prepare must not accept real private evidence")
        out = prepare(args.out_dir)
        result = {"mode": "blank_only", "rounds": 36, "status": "NO_GO"}
    else:
        if not all((
            args.p23c1_private_receipts, args.raw_export_index,
            args.archive_root, args.export_root,
        )):
            parser.error("--audit requires the P23C1 receipt, export index and roots")
        report, rows = audit_evidence(
            _json_file(args.p23c1_private_receipts),
            _json_file(args.raw_export_index),
            args.archive_root, args.export_root,
            p22a1_ledger=(
                _json_file(args.p22a1_private_ledger)
                if args.p22a1_private_ledger else None
            ),
            html_root=args.html_root,
            historical_policy_root=args.historical_policy_root,
            historical_egg_root=args.historical_egg_root,
        )
        out = write_report(report, rows, args.out_dir)
        result = {
            "mode": "offline_evidence_corroboration", "status": "NO_GO",
            "rounds": len(rows), "full_crawl_approved": False,
        }
    print(json.dumps({**result, "out_dir": str(out)}, sort_keys=True))


if __name__ == "__main__":
    main()
