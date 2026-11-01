"""P14B: deterministic ALL-source Zyte validation plan; never schedules crawls.

Two equivalent coverage strategies:
- sharded (default): small, recoverable jobs whose union is every source ID.
- full: three explicit full-category jobs, with confirm_full_inventory=yes.

Plan source IDs are pinned to the exact manifest, selection and lifecycle
registry. Planning does not establish publisher permissions, approve facts,
change the Zyte schedule or infer a valid price or dated release.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256, source_lifecycle,
)
from agentfuse_crawlers.sources import load_sources, select_sources
from scripts.plan_validation import static_warnings

CATEGORIES = ("documentation", "pricing", "changelog")
SPIDERS = {
    "documentation": "official_documentation",
    "pricing": "official_pricing",
    "changelog": "official_changelogs",
}
EXPECTED_BY_CATEGORY = {
    "documentation": 194, "pricing": 177, "changelog": 89,
}
MAX_SHARD_SIZE = 100
DEFAULT_SHARD_SIZE = 25
FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
PLAN_VERSION = "1.0"
PLAN_FIELDS = (
    "job_key", "spider", "category", "strategy", "requested_count",
    "expected_fetchable_sources", "expected_policy_skips",
    "source_ids_csv", "spider_args_json",
    "publisher_access_review_required",
)


def _canonical_digest(obj):
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def build_full_inventory_plan(*, strategy="sharded", shard_size=25,
                              expected_package_sha256=None):
    """Plan all manifest source IDs exactly once; all arguments are static."""
    if strategy not in {"sharded", "full"}:
        raise ValueError("strategy must be sharded or full")
    if (isinstance(shard_size, bool) or not isinstance(shard_size, int)
            or not 1 <= shard_size <= MAX_SHARD_SIZE):
        raise ValueError("shard_size must be an integer from 1 to 100")
    if (expected_package_sha256 is not None
            and (not isinstance(expected_package_sha256, str)
                 or not FINGERPRINT.fullmatch(expected_package_sha256))):
        raise ValueError("expected_package_sha256 must be a 64-character lowercase SHA-256")

    manifest = load_sources()
    by_category = Counter(s["category"] for s in manifest)
    if dict(by_category) != EXPECTED_BY_CATEGORY or len(manifest) != 460:
        raise ValueError("460-source manifest changed; re-review inventory baseline before crawling")
    registry_sha = registry_revision_sha256()
    manifest_sha = manifest_sha256(manifest)
    jobs, warnings = [], []
    all_ids = set()
    per_category = {}
    quarantine = []
    requested_unreviewed = []
    for category in CATEGORIES:
        whole = select_sources(category, "all")
        expected_ids = [x["id"] for x in whole]
        chunks = (
            [whole] if strategy == "full"
            else [
                whole[i:i + shard_size]
                for i in range(0, len(whole), shard_size)
            ]
        )
        if len(expected_ids) != len(set(expected_ids)):
            raise ValueError("Duplicate configured IDs within a category")
        per_category[category] = {
            "manifest_count": len(whole),
            "planned_jobs": len(chunks),
            "expected_policy_skipped": [],
            "expected_primary_source_fetches": 0,
        }
        for index, chunk in enumerate(chunks, 1):
            ids = [row["id"] for row in chunk]
            if set(ids) & all_ids:
                raise ValueError("Inventory plan overlaps source IDs")
            all_ids.update(ids)
            # Use the same code path the Scrapy spider uses, and confirm
            # selected order rather than trusting a caller's CSV ordering.
            selected = select_sources(category, "all", source_ids=ids)
            if [s["id"] for s in selected] != ids:
                raise ValueError("Sharded selection differs from source manifest ordering")
            eligible = [s for s in chunk if collection_decision(s, "validation")[0]]
            skipped = [s["id"] for s in chunk if s not in eligible]
            args = {
                "cohort": "all",
                "collection_mode": "validation",
                "expected_manifest_sha256": manifest_sha,
                "expected_selection_ids_sha256": selection_ids_sha256(selected),
                "expected_source_registry_sha256": registry_sha,
            }
            if strategy == "full":
                args["confirm_full_inventory"] = "yes"
            else:
                args["source_ids"] = ",".join(ids)
            job = {
                "job_key": f"{category}-{index:03d}",
                "spider": SPIDERS[category],
                "category": category,
                "strategy": strategy,
                "source_ids": ids,
                "source_ids_csv": ",".join(ids),
                "requested_count": len(ids),
                "expected_primary_source_fetches": len(eligible),
                "expected_policy_skipped_source_ids": skipped,
                "expected_policy_skips": len(skipped),
                "spider_args": args,
                "expected_selection_ids_sha256": args["expected_selection_ids_sha256"],
                "publisher_access_review_required": True,
                "automatic_execution_authorized": False,
            }
            jobs.append(job)
            per_category[category]["expected_policy_skipped"].extend(skipped)
            per_category[category]["expected_primary_source_fetches"] += len(eligible)
        for entry in whole:
            state = source_lifecycle(entry)
            if not collection_decision(entry, "validation")[0]:
                quarantine.append(entry["id"])
            if state["policy_status"] != "allowed_reviewed":
                requested_unreviewed.append(entry["id"])
            for reason in static_warnings(entry):
                warnings.append({
                    "source_id": entry["id"],
                    "source_url": entry["url"],
                    "category": category,
                    "reason": reason,
                    "review_status": "requires_operator_review",
                })

    known_ids = {x["id"] for x in manifest}
    if all_ids != known_ids or sum(j["requested_count"] for j in jobs) != 460:
        raise ValueError("Full-inventory planner did not cover exactly 460 configured IDs")
    if len({x["job_key"] for x in jobs}) != len(jobs):
        raise ValueError("Nonunique planned job key")
    for job in jobs:
        chosen = select_sources(job["category"], "all",
                                source_ids=job["source_ids"]
                                if strategy == "sharded" else None)
        if selection_ids_sha256(chosen) != job["expected_selection_ids_sha256"]:
            raise ValueError("Full-inventory selection fingerprint drift")

    base = {
        "schema_version": PLAN_VERSION,
        "kind": "unapproved_offline_full_inventory_validation_plan",
        "strategy": strategy,
        "shard_size": shard_size if strategy == "sharded" else None,
        "manifest_sha256": manifest_sha,
        "source_registry_sha256": registry_sha,
        "expected_package_sha256": expected_package_sha256,
        "total_manifest_sources": 460,
        "categories": per_category,
        "planned_jobs": len(jobs),
        "source_ids": [s["id"] for s in manifest],
        "expected_policy_skipped_source_ids": sorted(quarantine),
        "expected_primary_source_fetches": 460 - len(quarantine),
        "publisher_access_review_required_source_count": len(requested_unreviewed),
        "publisher_access_review_not_automatically_authorized": True,
        "static_warnings": warnings,
        "jobs": jobs,
        "manual_execution_only": True,
        "network_requests_performed": 0,
        "approved_for_advisor": False,
        "deployment_authorized": False,
    }
    base["plan_sha256"] = _canonical_digest(base)
    return base


def validate_full_inventory_plan(plan):
    """Do not trust imported plan JSON from a file before archiving/auditing."""
    if not isinstance(plan, dict):
        raise ValueError("Invalid full-inventory plan")
    recreated = build_full_inventory_plan(
        strategy=plan.get("strategy"),
        shard_size=plan.get("shard_size") if plan.get("strategy") == "sharded" else 25,
        expected_package_sha256=plan.get("expected_package_sha256"),
    )
    if _canonical_digest(plan) != _canonical_digest(recreated) or plan != recreated:
        raise ValueError("Full-inventory plan was edited or is stale for this manifest")
    return recreated


def write_full_inventory_plan(plan, out_dir):
    validate_full_inventory_plan(plan)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "full_inventory_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "manual_zyte_jobs.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAN_FIELDS)
        writer.writeheader()
        for job in plan["jobs"]:
            writer.writerow({
                **{key: job.get(key, "") for key in PLAN_FIELDS},
                "spider_args_json": json.dumps(
                    job["spider_args"], ensure_ascii=False, sort_keys=True,
                ),
            })
    with (out_dir / "publisher_review_flags.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("source_id", "source_url", "category",
                                "reason", "review_status"),
        )
        writer.writeheader()
        writer.writerows(plan["static_warnings"])
    return out_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=("sharded", "full"),
                        default="sharded")
    parser.add_argument("--shard-size", type=int, default=DEFAULT_SHARD_SIZE)
    parser.add_argument("--expected-package-sha256")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/p14b-full-inventory"))
    args = parser.parse_args()
    plan = build_full_inventory_plan(
        strategy=args.strategy, shard_size=args.shard_size,
        expected_package_sha256=args.expected_package_sha256,
    )
    write_full_inventory_plan(plan, args.out_dir)
    print(json.dumps({
        "strategy": plan["strategy"],
        "sources_accounted_for": plan["total_manifest_sources"],
        "planned_jobs": plan["planned_jobs"],
        "expected_primary_source_fetches": plan["expected_primary_source_fetches"],
        "policy_skips": plan["expected_policy_skipped_source_ids"],
        "publisher_access_review_required": True,
        "run_automatically": False,
        "out_dir": str(args.out_dir),
    }, indent=2))


if __name__ == "__main__":
    main()
