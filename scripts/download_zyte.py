#!/usr/bin/env python3
"""Read-only, verified Zyte Scrapy Cloud job downloader.

Legacy operator entrypoint retained, but now writes an immutable job archive
instead of a single unpaginated JSONL download. API keys are passed ONLY
through the Authorization header, not the URL or exported metadata.

ZYTE_SCRAPY_CLOUD_API_KEY=... python -m scripts.download_zyte \
  --job-id 883514/1/9 --out-dir output/archive

To verify the stored archive without any key/network:
  python -m scripts.download_zyte --job-id 883514/1/9 \
  --out-dir output/archive --verify-only
"""

import argparse
import json
from pathlib import Path

from scripts.archive_jobs import archive_job, archive_path, load_archive


def download_job(job_id, out_dir, api_key=None):
    """Compatibility API: return (compressed archive path, official item count)."""
    target, envelope, _ = archive_job(job_id, out_dir, api_key=api_key)
    return target / "items.jsonl.gz", envelope["source_summary_count"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("output/archive"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        root = archive_path(args.out_dir, args.job_id)
        metadata, rows = load_archive(root)
        summary = {"status": "verified_offline", "path": str(root),
                   "job_id": args.job_id, "items": len(rows)}
    else:
        path, count = download_job(args.job_id, args.out_dir)
        summary = {"status": "archived_or_verified", "path": str(path.parent),
                   "job_id": args.job_id, "items": count}
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
