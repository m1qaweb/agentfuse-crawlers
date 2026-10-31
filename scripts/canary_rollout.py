"""Create read-only, explicit, policy-aware two-round Zyte canary plans.

The planner NEVER calls Zyte, triggers jobs, downloads HTML, changes source
lifecycle states, or approves publisher facts. Operator review is mandatory.
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256, source_lifecycle,
)
from agentfuse_crawlers.sources import load_sources

SPIDERS = {
    "documentation": "official_documentation",
    "changelog": "official_changelogs",
    "pricing": "official_pricing",
}
MAX_CANARY_SOURCES = 9
ROUNDS = 2


def build_canary_plan(source_ids):
    """Pin one source ID per explicit job; a plan is NOT crawl authorization."""
    if isinstance(source_ids, str):
        ids = [s.strip() for s in source_ids.split(",")]
    elif isinstance(source_ids, (tuple, list)):
        ids = list(source_ids)
    else:
        raise ValueError("Explicit comma-separated --source-ids required")
    if (not ids or any(not isinstance(x, str) or not x.strip() for x in ids)
            or len(ids) > MAX_CANARY_SOURCES or len(set(ids)) != len(ids)):
        raise ValueError("Canary requires 1-9 distinct nonblank source IDs")
    manifest = load_sources()
    by_id = {s["id"]: s for s in manifest}
    if any(sid not in by_id for sid in ids):
        raise ValueError("Unknown source ID is not permitted")
    selected = [by_id[sid] for sid in ids]
    for source in selected:
        allowed, reason = collection_decision(source, mode="validation")
        if not allowed:
            raise ValueError(
                f"Canary source {source['id']} rejected by source lifecycle: {reason}"
            )
    plan = {
        "schema_version": "1.0",
        "kind": "manual_validation_canary_plan",
        "execution_permitted": False,
        "network_requests_performed": 0,
        "approved_for_advisor": False,
        "manifest_sha256": manifest_sha256(manifest),
        "source_registry_sha256": registry_revision_sha256(),
        "repeats": ROUNDS,
        "source_ids": ids,
        "total_expected_jobs": len(ids) * ROUNDS,
        "source_count": len(ids),
        "sources": [],
        "jobs": [],
        "operator_preflight_required": [
            "Review publisher robots.txt/terms and access permissions per exact source",
            "Verify exact intended product and URL ownership",
            "Confirm configured Zyte schedules are not unintentionally modified",
            "Run only explicitly pinned source IDs and record job IDs",
            "Archive finished jobs and check accurate source/job provenance",
            "Never treat successful extraction as factual or monitoring approval",
        ],
    }
    for source in selected:
        lifecycle = source_lifecycle(source)
        plan["sources"].append({
            "source_id": source["id"],
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "lifecycle_state": lifecycle["state"],
            "publisher_policy_status": lifecycle["policy_status"],
            "collection_permission_review_required": (
                lifecycle["state"] != "validated_for_collection"
            ),
            "canary_scope": "manual_validation_only",
        })
    for round_index in range(1, ROUNDS + 1):
        for source in selected:
            args = {
                "cohort": "all",
                "source_ids": source["id"],
                "collection_mode": "validation",
                "expected_manifest_sha256": plan["manifest_sha256"],
                "expected_selection_ids_sha256": selection_ids_sha256([source]),
                "expected_source_registry_sha256": plan["source_registry_sha256"],
            }
            plan["jobs"].append({
                "round": round_index,
                "source_id": source["id"],
                "spider": SPIDERS[source["category"]],
                "category": source["category"],
                "source_url": source["url"],
                "spider_args": args,
                "zyte_job_id": None,
                "execution_status": "not_scheduled_requires_operator_authorization",
                "approved_for_advisor": False,
            })
    return plan


def write_canary_plan(plan, output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "canary_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    fields = ["round", "source_id", "spider", "category", "source_url",
              "cohort", "collection_mode", "expected_manifest_sha256",
              "expected_selection_ids_sha256", "expected_source_registry_sha256",
              "execution_status"]
    with (out / "manual_job_args.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for job in plan["jobs"]:
            writer.writerow({
                **{k: job.get(k, "") for k in fields},
                **job["spider_args"],
                "round": job["round"], "source_id": job["source_id"],
                "spider": job["spider"], "category": job["category"],
                "source_url": job["source_url"],
                "execution_status": job["execution_status"],
            })
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ids", required=True,
                        help="Explicit comma-separated manifest source IDs; max 9")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/canary-plan"))
    args = parser.parse_args()
    result = build_canary_plan(args.source_ids)
    write_canary_plan(result, args.out_dir)
    print(json.dumps({
        "status": "dry_run_only",
        "source_count": result["source_count"],
        "job_specs": result["total_expected_jobs"],
        "network_requests": 0,
        "approval": "requires_operator_policy_review",
    }, indent=2))


if __name__ == "__main__":
    main()
