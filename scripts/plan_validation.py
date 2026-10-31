"""Offline rollout planner for the three approved Zyte spiders.

Never crawls websites, creates periodic jobs, changes proven status, or promotes
candidate data to AgentFuse recommendations.
"""

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.sources import load_proven_source_ids, load_sources, select_sources
from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256

SPIDERS = {
    "changelog": "official_changelogs",
    "documentation": "official_documentation",
    "pricing": "official_pricing",
}
YEAR_BOUND = re.compile(r"/20[0-9]{2}(?:/|$)")


def static_warnings(source):
    """Routing hints only; never represent a live HTTP validation."""
    url = urlsplit(source["url"])
    path = url.path.rstrip("/").lower()
    flags = []
    if source["category"] == "changelog":
        if YEAR_BOUND.search(url.path):
            flags.append("year_pinned_changelog_requires_rollover_review")
        if path.endswith("/blog"):
            flags.append("generic_blog_not_dedicated_release_notes")
        if url.hostname == "github.com" and path.endswith("/releases"):
            flags.append("github_html_releases_needs_live_date_validation")
    if source["category"] == "documentation" and path in {"", "/docs", "/documentation"}:
        flags.append("docs_landing_page_not_entire_documentation_tree")
    return flags


def plan_validation(cohort="candidate", batch_size=15):
    """Stable, complete, nonoverlapping jobs using the source selector itself."""
    if cohort not in {"candidate", "proven"}:
        raise ValueError("Only proven/candidate scoped validation is supported")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be an integer from 1 through 100")
    manifest = load_sources()
    all_ids = {entry["id"] for entry in manifest}
    proven = load_proven_source_ids()
    manifest_fingerprint = manifest_sha256(manifest)
    batches = []
    expected_ids = set()
    seen = set()
    warnings = []
    for category, spider_name in SPIDERS.items():
        selected = select_sources(category, cohort=cohort)
        expected_ids.update(row["id"] for row in selected)
        for offset in range(0, len(selected), batch_size):
            batch = select_sources(category, cohort=cohort, offset=offset, limit=batch_size)
            ids = [row["id"] for row in batch]
            if any(sid in seen for sid in ids):
                raise ValueError("Duplicate validation selection")
            seen.update(ids)
            batches.append({
                "spider": spider_name,
                "category": category,
                "cohort": cohort,
                "offset": offset,
                "limit": batch_size,
                "requested_count": len(batch),
                "source_ids": ids,
                # Stable over promotions: explicitly select these IDs under
                # cohort=all, with expected manifest+selection fingerprints.
                "pinned_cohort": "all",
                "source_ids_csv": ",".join(ids),
                "expected_manifest_sha256": manifest_fingerprint,
                "expected_selection_ids_sha256": selection_ids_sha256(batch),
                "first_source_id": ids[0],
                "last_source_id": ids[-1],
            })
        for source in selected:
            for warning in static_warnings(source):
                warnings.append({
                    "source_id": source["id"],
                    "provider": source["provider"],
                    "category": category,
                    "source_url": source["url"],
                    "warning": warning,
                    "review_status": "needs_live_validation",
                })
    if seen != expected_ids or not expected_ids <= all_ids:
        raise ValueError("Validation plan did not cover expected manifest IDs")
    return {
        "schema_version": 2,
        "manifest_sha256": manifest_fingerprint,
        "cohort": cohort,
        "batch_size": batch_size,
        "manifest_sources": len(manifest),
        "proven_sources": len(proven),
        "candidate_sources": len(manifest) - len(proven),
        "planned_sources": len(expected_ids),
        "planned_jobs": len(batches),
        "category_counts": dict(sorted(Counter(
            row["category"] for row in manifest if
            (row["id"] in proven) == (cohort == "proven")
        ).items())),
        "batches": batches,
        "static_warnings": warnings,
        "approved_for_advisor": False,
        "note": "Plan and flags are static; all source URLs still require live Zyte validation.",
    }


def write_plan(plan, out_dir):
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation_batches.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output / "validation_batches.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "spider", "category", "cohort", "offset", "limit", "requested_count",
            "first_source_id", "last_source_id", "pinned_cohort",
            "source_ids_csv", "expected_manifest_sha256",
            "expected_selection_ids_sha256",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: item.get(k, "") for k in fields}
                         for item in plan["batches"])
    with (output / "static_review_flags.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "source_id", "provider", "category", "source_url", "warning", "review_status",
        ])
        writer.writeheader()
        writer.writerows(plan["static_warnings"])
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=("candidate", "proven"), default="candidate")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--out-dir", type=Path, default=Path("output/validation-plan"))
    args = parser.parse_args()
    result = plan_validation(args.cohort, args.batch_size)
    out = write_plan(result, args.out_dir)
    print(json.dumps({
        "cohort": result["cohort"],
        "planned_sources": result["planned_sources"],
        "planned_jobs": result["planned_jobs"],
        "static_warning_count": len(result["static_warnings"]),
        "output_dir": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
