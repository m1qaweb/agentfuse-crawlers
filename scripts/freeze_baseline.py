"""P15A: freeze three Zyte Dashboard Items/Requests/Logs triplets offline.

Creates reproducible hashes + a 460-source multi-axis issue matrix; never
confuses exported Items with official P07 job archives or original HTML.
Only stores byte hashes and aggregate HTTP codes from Requests/Logs; their
potentially sensitive raw contents remain in the original private files.

Optional plaintext copies require an explicit opt-in AND an operator-managed
encrypted private filesystem. No outbound requests or production DB writes.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
from collections import Counter
from pathlib import Path

from scripts.build_failure_matrix import (
    CATEGORIES, EXPECTED, JOB, SPIDERS, _fingerprint,
    _read_json_array, build_failure_matrix, write_failure_matrix,
)

KIND_PREFIX = {
    "items": "items_official_",
    "requests": "requests_official_",
    "log": "log_official_",
}
CATEGORY_SUFFIX = {
    "documentation": "documentation",
    "pricing": "pricing",
    "changelog": "changelogs",
}
MAX_INPUT_SIZE = 400_000_000
MAX_REQUESTS = 3500
MAX_LOGS = 600
SCHEMA_VERSION = "1.0"


def _file_sha(path):
    sha = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            if size > MAX_INPUT_SIZE:
                raise ValueError("Unreasonably large unreviewed Zyte export")
            sha.update(chunk)
    return sha.hexdigest(), size


def _validate_export_label(path, category, kind):
    name = Path(path).name
    suffix = CATEGORY_SUFFIX[category]
    # Exact naming ties each input to the intended existing spider without
    # trusting its contents or a user-supplied, arbitrary file label.
    pattern = rf"^{KIND_PREFIX[kind]}{suffix}_[0-9]+\.json$"
    if not re.fullmatch(pattern, name):
        raise ValueError("Wrong Zyte export kind/category filename: " + name)


def _load_triplet(category, paths):
    data, evidence = {}, {}
    for kind in ("items", "requests", "log"):
        path = Path(paths[kind])
        _validate_export_label(path, category, kind)
        sha, size = _file_sha(path)
        value = _read_json_array(path)
        limit = EXPECTED[category] if kind == "items" else (
            MAX_REQUESTS if kind == "requests" else MAX_LOGS
        )
        if len(value) > limit:
            raise ValueError("Zyte export has unexpected record count: " + kind)
        evidence[kind] = {
            "filename": path.name,
            "sha256": sha,
            "size_bytes": size,
            "record_count": len(value),
        }
        data[kind] = value
    rows, reqs, logs = data["items"], data["requests"], data["log"]
    if len(rows) != EXPECTED[category]:
        raise ValueError("Full category source Item count mismatch")
    job_set = {x.get("zyte_job_id") for x in rows}
    if len(job_set) != 1 or not isinstance(next(iter(job_set)), str):
        raise ValueError("Mixed/missing Zyte job IDs in category")
    job_id = next(iter(job_set))
    if not JOB.fullmatch(job_id):
        raise ValueError("Invalid Zyte Job ID")
    if (not any(job_id in str(x.get("message", ""))
                and f"[{SPIDERS[category]}] Starting" in str(x.get("message", ""))
                for x in logs)
            or not any(
                f"[{SPIDERS[category]}] Job accounted for {EXPECTED[category]}/{EXPECTED[category]} sources"
                in str(x.get("message", ""))
                for x in logs)
            or not any("closing spider (finished)" in
                       str(x.get("message", "")).lower() for x in logs)):
        raise ValueError("Log export lacks matching job identity, accounting, or finish marker")
    requested_urls = set()
    response_codes = Counter()
    for entry in reqs:
        if not isinstance(entry.get("url"), str) or not isinstance(entry.get("status"), int):
            raise ValueError("Malformed Requests export")
        requested_urls.add(entry["url"])
        response_codes[str(entry["status"])] += 1
    missing_request = [
        row["source_id"] for row in rows
        if row.get("http_status") is not None
        and row["source_url"] not in requested_urls
    ]
    if missing_request:
        raise ValueError(
            "Source-summary HTTP response missing original URL from Requests: "
            + ",".join(missing_request[:3])
        )
    evidence["job_id"] = job_id
    evidence["source_initial_request_urls_accounted"] = sum(
        row.get("http_status") is not None for row in rows
    )
    evidence["requests_http_status_counts"] = dict(sorted(response_codes.items()))
    evidence["scrapy_finish_log_observed"] = True
    evidence["original_http_body_bytes_present"] = False
    return rows, evidence


def _lock_key(manifest):
    """Only the dated, stable expected baseline is pinned in Git, never data."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source_item_count": manifest["source_item_count"],
        "manifest_sha256": manifest["manifest_sha256"],
        "source_registry_sha256": manifest["source_registry_sha256"],
        "deployed_package_sha256": manifest["deployed_package_sha256"],
        "job_ids": manifest["job_ids"],
        "input_export_files": {
            category: {
                kind: {
                    "sha256": manifest["files"][category][kind]["sha256"],
                    "size_bytes": manifest["files"][category][kind]["size_bytes"],
                    "record_count": manifest["files"][category][kind]["record_count"],
                }
                for kind in ("items", "requests", "log")
            }
            for category in CATEGORIES
        },
    }


def freeze_dashboard_exports(paths_by_category, *, baseline_lock=None):
    if (not isinstance(paths_by_category, dict)
            or set(paths_by_category) != set(CATEGORIES)):
        raise ValueError("Exactly three named Zyte category export triplets required")
    rows_by_cat, files = {}, {}
    for category in CATEGORIES:
        mapping = paths_by_category[category]
        if not isinstance(mapping, dict) or set(mapping) != {
            "items", "requests", "log",
        }:
            raise ValueError("Require Items, Requests and Logs for " + category)
        rows_by_cat[category], files[category] = _load_triplet(category, mapping)
    quality = build_failure_matrix(rows_by_cat)
    baseline = quality["summary"]
    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": "frozen_dashboard_exports_not_original_html_or_verified_job_archive",
        "source_item_count": baseline["source_item_count"],
        "manifest_sha256": baseline["manifest_sha256"],
        "source_registry_sha256": baseline["source_registry_sha256"],
        "deployed_package_sha256": baseline["deployed_package_sha256"],
        "job_ids": baseline["job_ids"],
        "files": files,
        "quality_counts_sha256": _fingerprint({
            "category_metrics": baseline["category_metrics"],
            "observed_counters": baseline["observed_counters"],
            "concurrent_source_flags": baseline["concurrent_source_flags"],
        }),
        "failure_matrix_sha256": _fingerprint(quality["sources"]),
        "scope": "full_460_configured_source_summaries",
        "raw_publisher_http_html_available": False,
        "source_html_can_be_reparsed_from_exports": False,
        "external_zyte_archive_integrity_verified": False,
        "input_bytes_are_sha256_frozen_from_local_dashboard_exports": True,
        "same_inputs_yield_same_offline_issue_vector": True,
        "publisher_truth_independently_verified": False,
        "source_policy_approval_changed": False,
        "advisor_fact_approvals": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }
    result["freeze_manifest_sha256"] = _fingerprint(result)
    if baseline_lock is not None:
        locked = json.loads(Path(baseline_lock).read_text(encoding="utf-8"))
        expected = {key: locked.get(key) for key in _lock_key(result)}
        if _lock_key(result) != expected:
            raise ValueError("Nov 2 frozen baseline lock mismatch: inputs, job or deployment drifted")
        metric_expectations = locked.get("expected_observed_counters", {})
        if (not isinstance(metric_expectations, dict)
                or not metric_expectations
                or any(
                    quality["summary"]["observed_counters"].get(key) != value
                    for key, value in metric_expectations.items()
                )):
            raise ValueError("Nov 2 frozen baseline metric expectation mismatch")
    return result, quality


def _private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing symlink evidence output destination")
    os.chmod(path, 0o700)
    return path


def _private_file(path):
    if Path(path).is_symlink():
        raise ValueError("Refusing symlink evidence file")
    os.chmod(path, 0o600)


def write_freeze(result, quality, out_dir, *, paths_by_category=None,
                 copy_unencrypted_exports=False,
                 acknowledge_plaintext_private_storage=False):
    if copy_unencrypted_exports and (
        not acknowledge_plaintext_private_storage
        or paths_by_category is None
    ):
        raise ValueError(
            "Explicitly acknowledge private PLAINTEXT copies; "
            "use an encrypted, operator-controlled storage location"
        )
    out = _private_dir(out_dir)
    matrix = write_failure_matrix(quality, out)
    _private_file(matrix / "source_failure_matrix.csv")
    _private_file(matrix / "source_failure_matrix.jsonl")
    _private_file(matrix / "quality_baseline.json")
    filename = out / "freeze_manifest.json"
    filename.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _private_file(filename)
    if copy_unencrypted_exports:
        private = _private_dir(out / "source_exports_PRIVATE_UNENCRYPTED")
        for cat in CATEGORIES:
            for kind in ("items", "requests", "log"):
                origin = Path(paths_by_category[cat][kind])
                target = private / origin.name
                if target.is_symlink():
                    raise ValueError("Refusing symlink private export target")
                if target.exists():
                    if _file_sha(target) != _file_sha(origin):
                        raise ValueError("Existing private evidence file differs: " + origin.name)
                else:
                    with origin.open("rb") as src, target.open("xb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                _private_file(target)
                if _file_sha(target)[0] != result["files"][cat][kind]["sha256"]:
                    raise ValueError("Private export copy integrity mismatch")
    return out


def _arguments(args):
    return {
        category: {
            kind: getattr(args, f"{category}_{kind}")
            for kind in ("items", "requests", "log")
        } for category in CATEGORIES
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for cat in CATEGORIES:
        for kind in ("items", "requests", "log"):
            parser.add_argument(
                f"--{cat}-{kind}", required=True, type=Path,
            )
    parser.add_argument("--baseline-lock", type=Path,
                        help="Versioned expected original export/quality hashes")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/private/p15a-evidence"))
    parser.add_argument("--copy-private-exports", action="store_true",
                        help="Copies raw exports in PLAINTEXT: operator encrypted volume only")
    parser.add_argument("--acknowledge-plaintext-private-storage",
                        action="store_true",
                        help="Required with --copy-private-exports")
    args = parser.parse_args()
    mapping = _arguments(args)
    result, matrix = freeze_dashboard_exports(
        mapping, baseline_lock=args.baseline_lock,
    )
    out = write_freeze(
        result, matrix, args.out_dir, paths_by_category=mapping,
        copy_unencrypted_exports=args.copy_private_exports,
        acknowledge_plaintext_private_storage=args.acknowledge_plaintext_private_storage,
    )
    print(json.dumps({
        "sources": result["source_item_count"],
        "fingerprint": result["deployed_package_sha256"],
        "frozen_input_files": 9,
        "full_original_html_replay_available": False,
        "external_job_archive_verified": False,
        "advisor_fact_approvals": 0,
        "directory": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
