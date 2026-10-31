"""Immutable, checksum-verified, read-only Zyte Scrapy Cloud job archive.

Only official storage.zyte.com Jobs Metadata and paginated Items API are used.
No job scheduling, crawler changes, publisher fetches, or advisor approvals.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.sources import load_sources

JOB_ID = re.compile(r"^[0-9]+/[0-9]+/[0-9]+$")
SPIDERS = {
    "official_documentation": "documentation",
    "official_pricing": "pricing",
    "official_changelogs": "changelog",
}
MAX_ITEMS = 500
PAGE_SIZE = 20
MAX_PAGE_BYTES = 24_000_000
MAX_ITEM_BYTES = 950_000
MAX_TOTAL_BYTES = 400_000_000
ENVELOPE_SCHEMA = "1.0"
ALLOWED_ARGS = (
    "cohort", "source_ids", "limit", "offset", "confirm_full_inventory",
    "expected_manifest_sha256", "expected_selection_ids_sha256",
    "expected_source_registry_sha256", "collection_mode",
)
STATS_KEYS = (
    "item_scraped_count", "elapsed_time_seconds", "finish_reason",
    "downloader/request_count", "downloader/response_count",
    "robotstxt/request_count", "agentfuse/coverage/expected_sources",
    "agentfuse/coverage/reported_sources", "agentfuse/coverage/missing_sources",
    "agentfuse/coverage/duplicate_sources", "agentfuse/run/quality_outcome",
)


def canonical_bytes(item):
    return (json.dumps(item, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Unexpected Zyte API redirect; refusing to forward credentials")


def _request(url, api_key, limit):
    """Credentials appear in Authorization header ONLY, never URLs or logs."""
    if not url.startswith("https://storage.zyte.com/"):
        raise ValueError("Only the official Zyte storage API can be accessed")
    if not api_key or any(c in api_key for c in ("\r", "\n", "\x00")):
        raise ValueError("Invalid or missing ZYTE_SCRAPY_CLOUD_API_KEY")
    basic = base64.b64encode((api_key + ":").encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url, headers={
            "Authorization": "Basic " + basic,
            "Accept": "application/x-jsonlines,application/json",
        },
    )
    with urllib.request.build_opener(RefuseRedirect()).open(request, timeout=90) as response:
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Zyte response exceeds bounded download limit")
    return payload


def _metadata(job_id, key):
    data = json.loads(_request("https://storage.zyte.com/jobs/" + job_id,
                               key, 2_000_000))
    if not isinstance(data, dict):
        raise ValueError("Invalid Zyte job metadata")
    return data


def _items_page(job_id, key, offset, count):
    params = urllib.parse.urlencode({
        "format": "jl", "meta": "_key", "count": count,
        "start": f"{job_id}/{offset}",
    })
    url = "https://storage.zyte.com/items/" + job_id + "?" + params
    payload = _request(url, key, MAX_PAGE_BYTES)
    rows = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed paginated Zyte JSONL") from exc
        if not isinstance(row, dict):
            raise ValueError("Zyte Item is not an object")
        rows.append(row)
    return rows


def _job_details(job_id, meta):
    if meta.get("state") != "finished":
        raise ValueError("Zyte job has not finished; cannot archive unstable Items")
    spider = meta.get("spider")
    if spider not in SPIDERS:
        raise ValueError("Unrecognized spider; only three AgentFuse spiders supported")
    stats = meta.get("scrapystats")
    if not isinstance(stats, dict):
        raise ValueError("Zyte job metadata lacks scrapystats")
    count = stats.get("item_scraped_count")
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_ITEMS:
        raise ValueError("Invalid/missing item_scraped_count in official Zyte metadata")
    arguments = meta.get("spider_args") or {}
    if not isinstance(arguments, dict):
        raise ValueError("Malformed spider_args metadata")
    # An arbitrary spider arg could contain a private value. Archive ONLY
    # expected scope arguments; never serialize credentials or unknown args.
    safe_args = {key: arguments[key] for key in ALLOWED_ARGS
                 if key in arguments and isinstance(arguments[key], (str, int))}
    return {
        "job_id": job_id, "spider": spider, "category": SPIDERS[spider],
        "state": meta["state"], "close_reason": str(meta.get("close_reason") or ""),
        "deploy_id": str(meta.get("deploy_id") or ""),
        "deployment_version": str(meta.get("version") or "")[:120],
        "finished_time_ms": meta.get("finished_time"),
        "expected_item_count": count,
        "spider_args": safe_args,
        "unrecorded_argument_names": sorted(set(arguments) - set(ALLOWED_ARGS)),
        "stats": {k: stats[k] for k in STATS_KEYS if k in stats
                  and isinstance(stats[k], (str, int, float))},
    }


def _collect_items(job_id, key, expected, category, page_fetch):
    manifest = {s["id"]: s for s in load_sources()}
    items, entries = [], []
    total_size = 0
    seen_source = set()
    for offset in range(0, expected, PAGE_SIZE):
        count = min(PAGE_SIZE, expected - offset)
        page = page_fetch(job_id, key, offset, count)
        if len(page) != count:
            raise ValueError("Items page count differs from official job metadata")
        for position, row in enumerate(page, start=offset):
            if row.get("_key") != f"{job_id}/{position}":
                raise ValueError("Missing, duplicated or out-of-order Zyte _key")
            sid = row.get("source_id")
            src = manifest.get(sid) if isinstance(sid, str) else None
            if not src or src["category"] != category or row.get("category") != category:
                raise ValueError("Unknown or mismatched source ID/category in Zyte Items")
            if sid in seen_source:
                raise ValueError("Duplicate source summary in single Zyte job: " + sid)
            seen_source.add(sid)
            if row.get("zyte_job_id") not in (None, "", job_id):
                raise ValueError("Scraped Item job ID differs from requested job")
            raw = canonical_bytes(row)
            if len(raw) > MAX_ITEM_BYTES:
                raise ValueError("Zyte Item exceeds expected 950 KB budget")
            total_size += len(raw)
            if total_size > MAX_TOTAL_BYTES:
                raise ValueError("Job export exceeds bounded archive storage budget")
            items.append(raw)
            entries.append({
                "index": position,
                "zyte_item_key": row["_key"],
                "source_id": sid,
                "item_sha256": digest(raw),
                "bytes": len(raw),
                "identity_matches_current_manifest": bool(
                    src["provider"] == row.get("provider")
                    and src["url"] == row.get("source_url")
                ),
                "status": str(row.get("status", "unknown"))[:80],
            })
    return items, entries


def _scope(items, entries):
    common = (
        "manifest_sha256", "selection_ids_sha256", "selection_source_count",
        "requested_cohort", "run_started_at_utc",
        "source_registry_sha256", "collection_mode", "spider_name",
    )
    first = json.loads(items[0]) if items else {}
    consistent = True
    for raw in items[1:]:
        row = json.loads(raw)
        if any(row.get(k) != first.get(k) for k in common):
            consistent = False
            break
    expected = first.get("selection_source_count")
    count_ok = isinstance(expected, int) and expected == len(entries)
    hashes_recorded = bool(
        isinstance(first.get("manifest_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", first["manifest_sha256"])
        and isinstance(first.get("selection_ids_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", first["selection_ids_sha256"])
    )
    return {
        "metadata_consistent": consistent,
        "scope_count_matches_items": count_ok,
        "provenance_hashes_recorded": hashes_recorded,
        "run_start_recorded": bool(first.get("run_started_at_utc")),
        "spider_name_from_items": first.get("spider_name"),
        "source_identity_mismatches": sum(
            not entry["identity_matches_current_manifest"] for entry in entries
        ),
        "requested_cohort": first.get("requested_cohort"),
        "manifest_sha256": first.get("manifest_sha256"),
        "selection_ids_sha256": first.get("selection_ids_sha256"),
        "selection_source_count": expected,
        "source_registry_sha256": first.get("source_registry_sha256"),
        "collection_mode": first.get("collection_mode"),
        "source_status_counts": dict(sorted(Counter(x["status"] for x in entries).items())),
    }


def _gzip_bytes(items):
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer,
                       compresslevel=6, mtime=0) as compressed:
        for item in items:
            compressed.write(item)
    return buffer.getvalue()


def archive_path(root, job_id):
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("job-id must look like 883514/1/9")
    return Path(root) / "jobs" / job_id.replace("/", "_")


def archive_job(job_id, root, *, api_key=None, fetch_metadata=None, fetch_page=None):
    """Archive one finished job or validate/return existing byte-identical archive.

    Inject official metadata/page readers in offline tests; never require an API
    key to replay or verify an already stored job.
    """
    target = archive_path(root, job_id)
    if target.exists():
        report, _ = load_archive(target)
        if report["job"]["job_id"] != job_id:
            raise ValueError("Existing immutable archive has wrong job ID")
        return target, report, "already_archived"
    key = api_key if api_key is not None else os.environ.get("ZYTE_SCRAPY_CLOUD_API_KEY")
    if not key:
        raise ValueError("Set ZYTE_SCRAPY_CLOUD_API_KEY before downloading")
    job = _job_details(job_id, (fetch_metadata or _metadata)(job_id, key))
    records, entries = _collect_items(
        job_id, key, job["expected_item_count"], job["category"],
        fetch_page or _items_page,
    )
    scope = _scope(records, entries)
    scope["job_spider_matches_items"] = (
        scope["spider_name_from_items"] == job["spider"]
    )
    scope["safe_for_semantic_diff"] = bool(
        scope["metadata_consistent"]
        and scope["scope_count_matches_items"]
        and scope["provenance_hashes_recorded"]
        and scope["run_start_recorded"]
        and scope["job_spider_matches_items"]
        and not scope["source_identity_mismatches"]
        and job["close_reason"] == "finished"
    )
    envelope = {
        "archive_schema": ENVELOPE_SCHEMA,
        "job": job,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_scope": scope,
        "source_summary_count": len(entries),
        "source_evidence_is_unverified": True,
        "approved_for_advisor": False,
    }
    compact = _gzip_bytes(records)
    index_bytes = canonical_bytes({"items": entries, "item_count": len(entries)})
    envelope["integrity"] = {
        "gzip_sha256": digest(compact),
        "uncompressed_sha256": digest(b"".join(records)),
        "index_sha256": digest(index_bytes),
    }
    envelope_bytes = canonical_bytes(envelope)
    finaldir = target.parent
    finaldir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".archive-pending-", dir=finaldir))
    try:
        (stage / "items.jsonl.gz").write_bytes(compact)
        (stage / "index.json").write_bytes(index_bytes)
        (stage / "envelope.json").write_bytes(envelope_bytes)
        load_archive(stage)
        if target.exists():
            raise FileExistsError("Another process archived the same job; re-verify")
        stage.rename(target)  # atomic directory rename on same filesystem
        return target, envelope, "archived"
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def load_archive(path):
    """Check every stored Item, page ordinal, index and whole-file checksum."""
    root = Path(path)
    envelope = json.loads((root / "envelope.json").read_bytes())
    if envelope.get("archive_schema") != ENVELOPE_SCHEMA:
        raise ValueError("Unknown immutable archive schema")
    job = envelope.get("job") or {}
    job_id = job.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid archived Zyte job ID")
    index_raw = (root / "index.json").read_bytes()
    compressed = (root / "items.jsonl.gz").read_bytes()
    integrity = envelope.get("integrity") or {}
    if digest(index_raw) != integrity.get("index_sha256"):
        raise ValueError("Archive index checksum mismatch")
    if digest(compressed) != integrity.get("gzip_sha256"):
        raise ValueError("Archive gzip checksum mismatch")
    index = json.loads(index_raw)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(MAX_TOTAL_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise ValueError("Corrupt archive gzip") from exc
    if len(raw) > MAX_TOTAL_BYTES or digest(raw) != integrity.get("uncompressed_sha256"):
        raise ValueError("Archive uncompressed checksum/size mismatch")
    lines = raw.splitlines(keepends=True)
    entries = index.get("items") or []
    if len(lines) != len(entries) or len(lines) != job.get("expected_item_count"):
        raise ValueError("Archive item count differs from job metadata")
    parsed = []
    seen = set()
    for i, (line, entry) in enumerate(zip(lines, entries)):
        if (entry["index"] != i or entry["zyte_item_key"] != f"{job_id}/{i}"
                or digest(line) != entry["item_sha256"]
                or len(line) != entry["bytes"]):
            raise ValueError("Archive per-item checksum/order mismatch")
        row = json.loads(line)
        if row.get("_key") != entry["zyte_item_key"] or row.get("source_id") != entry["source_id"]:
            raise ValueError("Archived source/ordinal mismatch")
        if row["source_id"] in seen:
            raise ValueError("Duplicate source during archive replay")
        seen.add(row["source_id"])
        parsed.append(row)
    return envelope, parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("output/archive"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        target = archive_path(args.out_dir, args.job_id)
        report, records = load_archive(target)
        result = {"mode": "verified_offline", "job_id": args.job_id,
                  "item_count": len(records), "path": str(target)}
    else:
        target, report, status = archive_job(args.job_id, args.out_dir)
        result = {"mode": status, "job_id": args.job_id,
                  "item_count": report["source_summary_count"], "path": str(target)}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
