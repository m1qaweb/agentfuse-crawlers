#!/usr/bin/env python3
"""Combine Scrapy exports and identify changed pages without claiming fact changes.

Example:
    python scripts/compare_exports.py --current output/*.jsonl --out-dir output/review
    python scripts/compare_exports.py --current output/today/*.jsonl \
        --previous output/yesterday/*.jsonl --out-dir output/review
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.sources import load_sources

STATUS_FIELDS = [
    "source_id", "provider", "category", "status", "http_status",
    "fetched_at_utc", "source_url", "final_url", "word_count",
    "content_sha256", "review_status", "error",
]
CHANGE_FIELDS = [
    "source_id", "provider", "category", "change_type", "previous_hash",
    "current_hash", "fetched_at_utc", "source_url", "review_status",
]


def read_jsonl(paths):
    """Choose the most recent item for a source_id across exported runs."""
    rows = {}
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Bad JSON in {path}:{line_no}: {exc}") from exc
                source_id = item.get("source_id")
                if not source_id:
                    raise ValueError(f"Missing source_id in {path}:{line_no}")
                if (
                    source_id not in rows or
                    item.get("fetched_at_utc", "") >= rows[source_id].get("fetched_at_utc", "")
                ):
                    rows[source_id] = item
    return rows


def compare(current, previous):
    changes = []
    for source_id, item in sorted(current.items()):
        old = previous.get(source_id)
        new_hash = item.get("content_sha256", "")
        old_hash = old.get("content_sha256", "") if old else ""
        if item.get("status") != "captured" or not new_hash:
            kind = "not_captured"
        elif not old or old.get("status") != "captured" or not old_hash:
            kind = "new_baseline"
        elif old_hash != new_hash:
            kind = "page_text_changed"
        else:
            kind = "unchanged"
        changes.append({
            "source_id": source_id,
            "provider": item.get("provider", ""),
            "category": item.get("category", ""),
            "change_type": kind,
            "previous_hash": old_hash,
            "current_hash": new_hash,
            "fetched_at_utc": item.get("fetched_at_utc", ""),
            "source_url": item.get("source_url", ""),
            "review_status": item.get("review_status", "unverified"),
        })
    return changes


def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", nargs="+", required=True, type=Path)
    parser.add_argument("--previous", nargs="*", default=[], type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    current = read_jsonl(args.current)
    previous = read_jsonl(args.previous)
    for source in load_sources():
        if source["id"] not in current:
            current[source["id"]] = {
                "source_id": source["id"],
                "provider": source["provider"],
                "category": source["category"],
                "source_url": source["url"],
                "status": "not_in_export",
                "error": "No record in supplied export files; verify job and robots access",
                "review_status": "unverified",
            }
    changes = compare(current, previous)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    write_csv(args.out_dir / "status.csv", [current[key] for key in sorted(current)], STATUS_FIELDS)
    write_csv(args.out_dir / "changes.csv", changes, CHANGE_FIELDS)
    with open(args.out_dir / "snapshots.jsonl", "w", encoding="utf-8") as handle:
        for key in sorted(current):
            handle.write(json.dumps(current[key], ensure_ascii=False) + "\n")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources_expected": len(current),
        "sources_captured": sum(v.get("status") == "captured" for v in current.values()),
        "counts": {kind: sum(c["change_type"] == kind for c in changes)
                   for kind in ("new_baseline", "page_text_changed", "unchanged", "not_captured")},
        "note": "Page text changes are not verified pricing, model, or feature changes.",
    }
    with open(args.out_dir / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
