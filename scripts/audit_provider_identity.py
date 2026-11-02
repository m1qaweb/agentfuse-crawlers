"""P16A offline audit of exact 460-source ownership/family hypotheses.

Accepts only the previously pinned three-category Items from the same
manifest, selection and crawler package. Never fetches a new URL, promotes
a title/brand association to verified ownership, or schedules adapters.

CSV/JSON are local/private review queues, not published provider facts.
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.provider_profiles import (
    identify_source_product, load_provider_profiles,
)
from agentfuse_crawlers.sources import load_sources
from scripts.build_failure_matrix import (
    CATEGORIES, _read_json_array, _safe_csv, build_failure_matrix,
)

FIELDS = (
    "source_id", "category", "manifest_provider", "expected_provider_id",
    "expected_product_id", "profile_review_status", "source_status",
    "http_status", "original_source_title", "title_alias_signal",
    "observed_positive_alias", "observed_contradictory_alias",
    "title_conflict", "observed_page_family", "structural_evidence",
    "proposed_adapter_family", "adapter_activated", "review_action",
)


def audit_source_product_ownership(by_category):
    baseline = build_failure_matrix(by_category)
    known = {s["id"]: s for s in load_sources()}
    report_rows = []
    signals, families = Counter(), Counter()
    conflicts = []
    for category in CATEGORIES:
        for item in by_category[category]:
            source = known[item["source_id"]]
            evidence = identify_source_product(source, item)
            signal = evidence["source_title_alias_evidence_status"]
            family = evidence["source_page_family_candidate"]
            signals[signal] += 1
            families[family] += 1
            if evidence["source_product_title_conflict"]:
                conflicts.append(source["id"])
            action = (
                "review_product_identity_conflict" if
                evidence["source_product_title_conflict"]
                else "review_official_title_and_product_owner" if
                evidence["source_expected_product_id"]
                else "not_profiled_use_generic_unverified_extractor"
            )
            report_rows.append({
                "source_id": source["id"],
                "category": category,
                "manifest_provider": source["provider"],
                "expected_provider_id": evidence["source_expected_provider_id"],
                "expected_product_id": evidence["source_expected_product_id"],
                "profile_review_status": evidence["source_product_profile_status"],
                "source_status": item.get("status"),
                "http_status": item.get("http_status"),
                "original_source_title": str(item.get("title") or "")[:240],
                "title_alias_signal": signal,
                "observed_positive_alias": evidence["source_title_alias_observed"],
                "observed_contradictory_alias":
                    evidence["source_title_conflicting_alias_observed"],
                "title_conflict": evidence["source_product_title_conflict"],
                "observed_page_family": family,
                "structural_evidence": ",".join(
                    evidence["source_page_family_evidence"]
                ),
                "proposed_adapter_family": evidence["source_adapter_candidate"],
                "adapter_activated": evidence["source_specific_adapter_authorized"],
                "review_action": action,
            })
    if len(report_rows) != 460:
        raise ValueError("P16A audit requires exactly 460 unique source observations")
    report_rows.sort(key=lambda x: (
        not x["title_conflict"],
        not bool(x["expected_product_id"]),
        CATEGORIES.index(x["category"]),
        x["source_id"],
    ))
    result = {
        "schema_version": "2.0",
        "report_kind": "unverified_owner_and_markup_family_review_not_product_truth",
        "source_item_count": 460,
        "manifest_sha256": baseline["summary"]["manifest_sha256"],
        "source_registry_sha256": baseline["summary"]["source_registry_sha256"],
        "deployed_package_sha256": baseline["summary"]["deployed_package_sha256"],
        "profiles_present": len(load_provider_profiles()),
        "profiled_source_records": sum(
            bool(x["expected_product_id"]) for x in report_rows
        ),
        "unprofiled_source_records": sum(
            not x["expected_product_id"] for x in report_rows
        ),
        "observed_title_signals": dict(sorted(signals.items())),
        "observed_markup_families": dict(sorted(families.items())),
        "title_conflict_review_source_ids": sorted(conflicts),
        "all_aliases_unreviewed": True,
        "automatically_selected_specific_adapters": 0,
        "verified_product_ownership_claims": 0,
        "approved_advisor_facts": 0,
        "new_crawl_requests": 0,
        "deployment_authorized": False,
    }
    return {"summary": result, "sources": report_rows}


def write_ownership_audit(report, out_dir):
    out = Path(out_dir)
    if out.is_symlink():
        raise ValueError("Refusing symlink review output")
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (out / "source_product_ownership_summary.json").write_text(
        json.dumps(report["summary"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (out / "source_product_review_queue.csv").open(
        "w", newline="", encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in report["sources"]:
            writer.writerow({key: _safe_csv(row.get(key, ""))
                             for key in FIELDS})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pricing-items", type=Path, required=True)
    parser.add_argument("--documentation-items", type=Path, required=True)
    parser.add_argument("--changelog-items", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/private/p16a"))
    args = parser.parse_args()
    items = {
        "pricing": _read_json_array(args.pricing_items),
        "documentation": _read_json_array(args.documentation_items),
        "changelog": _read_json_array(args.changelog_items),
    }
    report = audit_source_product_ownership(items)
    target = write_ownership_audit(report, args.out_dir)
    print(json.dumps({
        "source_items": report["summary"]["source_item_count"],
        "profiled": report["summary"]["profiled_source_records"],
        "title_conflicts": len(report["summary"]["title_conflict_review_source_ids"]),
        "verified_owner_claims": 0,
        "adapter_activations": 0,
        "output": str(target),
    }, indent=2))


if __name__ == "__main__":
    main()
