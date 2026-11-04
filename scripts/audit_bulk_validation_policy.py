"""P21B read-only public-package scope audit; no permits, Zyte or publisher GET.

Read Git-reviewed installed source access and run plan registries and emit
all 460 source IDs with an explicit bulk authorization status. A source's
technical validation eligibility is NOT publisher permission. No CLI text
field can approve a bulk request; only a separately reviewed, current
source+run-plan pair in the deployed package can do so.
"""
import argparse
import csv
import io
import json
import shutil
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.run_context import manifest_sha256, package_fingerprint
from agentfuse_crawlers.validation_access import (
    load_access_registry, load_run_plan_registry,
    validation_access_decision, validation_access_revision_sha256,
    bulk_plan_revision_sha256,
)
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)

COLUMNS = (
    "source_id", "provider", "category", "source_url",
    "technical_validation_eligible", "technical_validation_reason",
    "reviewed_for_bulk_validation", "bulk_validation_review_reason",
    "can_be_fetched_without_exact_run_plan",
    "advisor_fact_approval",
)


def build_policy_readiness():
    sources = load_sources()
    reviews = load_access_registry()
    plans = load_run_plan_registry()
    counts = Counter()
    rows = []
    for source in sources:
        possible, reason = collection_decision(source, "validation")
        reviewed, review_reason = validation_access_decision(
            source, scope="bulk_validation", registry=reviews,
        )
        counts["configured_source_ids"] += 1
        counts["technically_validatable"] += bool(possible)
        counts["reviewed_permitted_for_bulk"] += bool(reviewed)
        counts["missing_review_or_denied"] += not reviewed
        counts["source_requires_exact_run_plan"] += 1
        rows.append({
            "source_id": source["id"],
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "technical_validation_eligible": possible,
            "technical_validation_reason": reason,
            "reviewed_for_bulk_validation": reviewed,
            "bulk_validation_review_reason": review_reason,
            "can_be_fetched_without_exact_run_plan": False,
            "advisor_fact_approval": False,
        })
    if len(sources) != 460 or len(rows) != 460:
        raise ValueError("P21B reviewed bulk policy inventory requires full manifest")
    by_category = Counter(x["category"] for x in sources)
    if by_category != {
        "documentation": 194, "pricing": 177, "changelog": 89,
    }:
        raise ValueError("P21B bulk review inventory category mismatch")
    report = {
        "schema_version": "1.0",
        "kind": "p21b_offline_bulk_review_readiness_not_authorization",
        "source_manifest_sha256": manifest_sha256(sources),
        "lifecycle_registry_sha256": registry_revision_sha256(),
        "access_review_registry_sha256": validation_access_revision_sha256(reviews),
        "bulk_plan_registry_sha256": bulk_plan_revision_sha256(plans),
        "running_package_fingerprint": package_fingerprint(),
        "category_counts": dict(sorted(by_category.items())),
        "counts": dict(sorted(counts.items())),
        "approved_run_plans_in_deployed_package": len(plans["plans"]),
        "active_run_plan_selected": False,
        "publisher_permissions_independently_verified_by_this_tool": False,
        "publisher_policy_review_attestation_is_not_a_legal_grant": True,
        "no_bulk_request_can_use_only_confirm_full_inventory": True,
        "bulk_run_authorized_by_this_audit": False,
        "full_inventory_run_recommended": False,
        "advisor_fact_approvals": 0,
        "new_zyte_jobs": 0,
        "network_requests_performed": 0,
        "new_access_permissions": 0,
    }
    return report, rows


def _csv(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({
            key: _csv_safe(row.get(key)) for key in COLUMNS
        })
    return stream.getvalue().encode("utf-8-sig")


def _csv_safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def write_policy_readiness(report, rows, out_dir):
    root = _private_new_directory(out_dir)
    try:
        _write_private(
            root / "bulk_validation_readiness.json",
            (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        _write_private(
            root / "all_460_source_bulk_review_queue.csv",
            _csv(rows),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    report, rows = build_policy_readiness()
    root = write_policy_readiness(report, rows, args.out_dir)
    print(json.dumps({
        "report": str(root / "bulk_validation_readiness.json"),
        "full_manifest_accounted": report["counts"]["configured_source_ids"],
        "technically_validatable": report["counts"]["technically_validatable"],
        "source_reviewed_for_bulk": report["counts"]["reviewed_permitted_for_bulk"],
        "approved_bulk_run_plans": report["approved_run_plans_in_deployed_package"],
        "full_crawl_authorized": False,
        "network_requests_performed": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
