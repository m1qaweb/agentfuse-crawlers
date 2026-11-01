"""Read-only audit of unverified Zyte pricing Items, before/after a parser fix.

No network calls, no provider facts approved, no inferred missing data.
A larger comparable count is a DIAGNOSTIC, never proof of price correctness.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.sources import load_sources

DIMENSIONS = (
    "currency", "billing_unit", "price_dimension", "model_or_service",
    "region", "tier_or_plan",
)
ROWS_FIELDS = (
    "source_id", "provider", "status", "reason", "http_status",
    "observations", "comparable_candidates", "scoped_observations",
    "explicit_scope_declarations", "missing_currency", "missing_billing_unit",
    "missing_price_dimension", "missing_region", "missing_tier_or_plan",
    "parser_revision", "detected_price_entries", "card_count",
    "card_price_entries", "card_observations", "card_omitted",
    "card_oversized", "card_duplicates", "rate_identity_collisions",
    "inventory_complete", "text_available", "approved_for_advisor",
)


def inspect(items, *, expect_all=False):
    if not isinstance(items, list):
        raise ValueError("Expected Zyte JSON Item array")
    known = {s["id"]: s for s in load_sources()
             if s["category"] == "pricing"}
    seen = set()
    statuses = Counter()
    blockers = Counter()
    dimensions = Counter()
    parser_revisions = Counter()
    source_rows = []
    observed = total = comparable = anomalies = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Zyte Item must be an object")
        sid = item.get("source_id")
        if sid not in known or sid in seen:
            raise ValueError("Unknown/duplicate pricing source in Zyte Items")
        seen.add(sid)
        if (item.get("category") != "pricing"
                or item.get("source_url") != known[sid]["url"]):
            raise ValueError("Provider/category/source URL provenance mismatch")
        if item.get("approved_for_advisor") is not False:
            anomalies += 1
        statuses[item.get("status", "unknown")] += 1
        parser_revisions[item.get("pricing_parser_revision") or "legacy_unversioned"] += 1
        records = item.get("pricing_observations") or []
        if not isinstance(records, list):
            raise ValueError("pricing_observations must be an array")
        counts = Counter()
        for observation in records:
            if not isinstance(observation, dict):
                raise ValueError("Invalid pricing observation")
            if (observation.get("source_id") != sid
                    or observation.get("source_url") != known[sid]["url"]):
                raise ValueError("Pricing observation source attribution mismatch")
            total += 1
            observed += 1
            for name in DIMENSIONS:
                if observation.get(name):
                    dimensions[name] += 1
                else:
                    counts["missing_" + name] += 1
            for issue in observation.get("normalization_blockers") or []:
                blockers[issue] += 1
            if observation.get("scope_declarations"):
                counts["scoped_observations"] += 1
                counts["explicit_scope_declarations"] += len(
                    observation["scope_declarations"]
                )
            if observation.get("comparable_candidate") is True:
                comparable += 1
                counts["comparable_candidates"] += 1
                if (any(not observation.get(d) for d in DIMENSIONS)
                        or observation.get("normalization_blockers")
                        or observation.get("approved_for_advisor") is not False
                        or not observation.get("normalized_amount_decimal")):
                    anomalies += 1
        source_rows.append({
            "source_id": sid, "provider": known[sid]["provider"],
            "status": item.get("status", "unknown"),
            "reason": item.get("error", ""),
            "http_status": item.get("http_status"),
            "observations": len(records),
            "comparable_candidates": counts["comparable_candidates"],
            "scoped_observations": counts["scoped_observations"],
            "explicit_scope_declarations": counts["explicit_scope_declarations"],
            "missing_currency": counts["missing_currency"],
            "missing_billing_unit": counts["missing_billing_unit"],
            "missing_price_dimension": counts["missing_price_dimension"],
            "missing_region": counts["missing_region"],
            "missing_tier_or_plan": counts["missing_tier_or_plan"],
            "parser_revision": item.get("pricing_parser_revision"),
            "detected_price_entries": item.get(
                "pricing_observation_total_detected", len(records)
            ),
            "card_count": item.get("pricing_card_total", 0),
            "card_price_entries": item.get("pricing_card_price_entries_examined", 0),
            "card_observations": item.get("pricing_card_observation_count", 0),
            "card_omitted": item.get("pricing_card_omitted", 0),
            "card_oversized": item.get("pricing_card_oversized_count", 0),
            "card_duplicates": item.get("pricing_card_duplicate_rate_count", 0),
            "rate_identity_collisions": item.get(
                "pricing_rate_identity_collision_count", 0
            ),
            "inventory_complete": item.get("pricing_inventory_complete"),
            "text_available": bool(item.get("text") or item.get("text_sample")),
            "approved_for_advisor": item.get("approved_for_advisor"),
        })
    if expect_all and seen != set(known):
        raise ValueError("Not a complete 177-source pricing inventory")
    return {
        "schema_version": "1.0",
        "report_kind": "read_only_pricing_item_diagnostics",
        "review_status": "unverified",
        "approved_for_advisor": False,
        "source_count": len(source_rows),
        "expected_full_inventory_sources": len(known),
        "source_accounting_complete": seen == set(known),
        "observed_price_rows": observed,
        "comparable_candidates": comparable,
        "sources_with_rate_candidates": sum(
            r["comparable_candidates"] > 0 for r in source_rows
        ),
        "status_counts": dict(sorted(statuses.items())),
        "parser_revisions": dict(sorted(parser_revisions.items())),
        "card_summaries": {
            "structured_cards_detected": sum(r["card_count"] for r in source_rows),
            "price_card_entries_examined": sum(
                r["card_price_entries"] for r in source_rows
            ),
            "card_observations_retained": sum(
                r["card_observations"] for r in source_rows
            ),
            "cards_omitted_or_oversized": sum(
                r["card_omitted"] for r in source_rows
            ),
            "duplicate_comparable_rates_deduplicated": sum(
                r["card_duplicates"] for r in source_rows
            ),
            "price_identity_collisions": sum(
                r["rate_identity_collisions"] for r in source_rows
            ),
        },
        "dimension_coverage": {
            dim: {"known": dimensions[dim], "total": total}
            for dim in DIMENSIONS
        },
        "normalization_blockers": dict(blockers.most_common()),
        "provenance_or_approval_anomalies": anomalies,
        "sources": source_rows,
        "notice": (
            "Rows are unverified; numeric candidate yield is not accuracy. "
            "Compare source-level behavior and review real official evidence "
            "before any publication or source-approval action."
        ),
    }


def save(report, out_dir):
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pricing_run_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (folder / "pricing_sources.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=ROWS_FIELDS)
        writer.writeheader()
        writer.writerows(report["sources"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/pricing-evidence-audit"))
    parser.add_argument("--expect-all", action="store_true",
                        help="Require every configured pricing source ID")
    args = parser.parse_args()
    data = json.loads(args.items.read_text(encoding="utf-8"))
    report = inspect(data, expect_all=args.expect_all)
    save(report, args.out_dir)
    print(json.dumps({
        k: report[k] for k in (
            "source_count", "observed_price_rows", "comparable_candidates",
            "sources_with_rate_candidates", "provenance_or_approval_anomalies",
        )
    }, indent=2))


if __name__ == "__main__":
    main()
