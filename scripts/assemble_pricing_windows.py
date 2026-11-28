"""Combine bounded pricing-table window Items into offline *review-only* evidence.

Refuse overlapping, missing, changed-page, clipped or incompatible windows.
This is not a production source summary, verified full vendor inventory,
price-change baseline, alert signal, or advisor approval. No network or DB IO.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.pricing_perplexity import (
    DEFAULT_PRICING_PARSER_REVISION as REVISION, pricing_parser_revision,
)
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SAFE_NAME = re.compile(r"^[a-z0-9_]{1,90}$")
IDENTITY_FIELDS = (
    "source_id", "source_url", "provider", "category", "content_sha256",
    "manifest_sha256", "source_registry_sha256", "deployment_revision",
    "pricing_evidence_schema", "pricing_parser_revision",
    "pricing_table_total", "pricing_table_relevant", "pricing_table_scanned",
)


def _verify_row(row, source):
    if not isinstance(row, dict):
        raise ValueError("Pricing window must be a dictionary")
    if any(row.get(k) != source[k] for k in ("source_id", "source_url", "category")):
        raise ValueError("Window ID/category/URL disagrees with pinned source manifest")
    if row.get("approved_for_advisor") is not False:
        raise ValueError("Crawler window must explicitly refuse advisor approval")
    if row.get("pricing_evidence_schema") != "1.0" or row.get(
        "pricing_parser_revision"
    ) != pricing_parser_revision(source["source_id"], source["source_url"]):
        raise ValueError("Window requires exact P11B pricing parser revision")
    if row.get("http_status") != 200 or row.get("status") not in {
        "partial_capture", "captured",
    }:
        raise ValueError("Unsuccessful or review-needed source page cannot be assembled")
    for key in ("content_sha256", "manifest_sha256", "source_registry_sha256",
                "deployment_revision"):
        if not isinstance(row.get(key), str) or not SHA256.fullmatch(row[key]):
            raise ValueError("Missing or invalid immutable window identity: " + key)
    if not isinstance(row.get("zyte_job_id"), str) or not re.fullmatch(
        r"\d+/\d+/\d+", row["zyte_job_id"]
    ):
        raise ValueError("A distinct real Zyte job ID is required per table window")
    for key in ("pricing_table_total", "pricing_table_scanned",
                "pricing_table_relevant", "pricing_table_window_start",
                "pricing_table_window_limit", "pricing_table_window_end",
                "pricing_observation_total_detected", "pricing_observation_count"):
        if type(row.get(key)) is not int or row[key] < 0:
            raise ValueError("Noninteger or negative pricing window counter: " + key)
    start = row["pricing_table_window_start"]
    end = row["pricing_table_window_end"]
    limit = row["pricing_table_window_limit"]
    relevant = row["pricing_table_relevant"]
    if not (0 <= start <= end <= relevant <= row["pricing_table_scanned"]
            <= row["pricing_table_total"] and 1 <= limit <= 64
            and end - start <= limit):
        raise ValueError("Pricing window range or source table inventory is inconsistent")
    if row.get("pricing_table_scan_truncated"):
        raise ValueError("Relevant tables may exist beyond bounded scan")
    if any(row.get(flag) for flag in (
        "pricing_observation_limit_reached",
        "pricing_table_rows_incomplete",
        "pricing_card_scan_truncated",
        "pricing_card_rate_identity_conflict",
        "pricing_rate_identity_collision_count",
        "pricing_evidence_lost_to_item_budget",
        "pricing_product_scope_unresolved",
    )):
        raise ValueError("A source window omitted, clipped, or confused price evidence")
    observations = row.get("pricing_observations")
    table_evidence = row.get("pricing_table_evidence")
    indices = row.get("pricing_table_window_selected_indices")
    if not isinstance(observations, list) or len(observations) != row[
        "pricing_observation_count"
    ] or row["pricing_observation_total_detected"] != len(observations):
        raise ValueError("Window price-observation count/inventory mismatch")
    if not isinstance(indices, list) or not isinstance(table_evidence, list):
        raise ValueError("Selected table metadata is required for replay")
    if not (len(indices) == len(table_evidence) == end - start):
        raise ValueError("Selected table index count differs from window range")
    if (any(type(i) is not int or i < 0 for i in indices)
            or indices != sorted(set(indices))):
        raise ValueError("Source HTML table indexes must be unique and increasing")
    if any(info.get("table_index") != i for i, info in zip(indices, table_evidence)):
        raise ValueError("Table provenance index differs from inventory")
    for item in observations:
        if (not isinstance(item, dict)
                or item.get("source_id") != source["source_id"]
                or item.get("source_url") != source["source_url"]
                or item.get("approved_for_advisor") is not False):
            raise ValueError("Unapproved and exact source-linked observations required")
        table_id = item.get("table_id")
        if item.get("evidence_kind") in {
            "structured_table", "structured_table_labeled_inline_component",
        }:
            if table_id not in {x.get("table_id") for x in table_evidence}:
                raise ValueError("Rate references a table outside this window")
            if item["evidence_kind"] == "structured_table_labeled_inline_component":
                if (type(item.get("inline_component_index")) is not int
                        or type(item.get("inline_component_count")) is not int
                        or not 2 <= item["inline_component_count"] <= 4
                        or not 0 <= item["inline_component_index"] <
                            item["inline_component_count"]
                        or not isinstance(item.get("inline_component_evidence_sha256"), str)
                        or not SHA256.fullmatch(
                            item["inline_component_evidence_sha256"]
                        )
                        or not isinstance(item.get("raw_parent_cell_text"), str)
                        or not item["raw_parent_cell_text"]
                        or item.get("comparable_candidate") is not False
                        or item.get("review_quote_candidate") is not False
                        or item.get("normalized_amount_decimal") is not None):
                    raise ValueError("Unsafe or unbound inline rate review component")
        elif item.get("evidence_kind") == "structured_card":
            if start != 0:
                raise ValueError("Card evidence must appear only in first table window")
        else:
            raise ValueError("Unknown pricing evidence kind")
    if row.get("pricing_table_window_cards_included") is not (start == 0):
        raise ValueError("Card-window ownership metadata does not match offset")


def assemble_source_windows(rows):
    """Return one review-only union; strict failure is preferable to false coverage."""
    if not rows:
        raise ValueError("No pricing window Items for source")
    manifest = {s["id"]: {
        "source_id": s["id"], "source_url": s["url"], "category": s["category"],
    } for s in load_sources() if s["category"] == "pricing"}
    sid = rows[0].get("source_id") if isinstance(rows[0], dict) else None
    source = manifest.get(sid)
    if source is None or any(row.get("source_id") != sid for row in rows):
        raise ValueError("Mixed or unknown pricing source IDs")
    for row in rows:
        _verify_row(row, source)
    first = rows[0]
    for row in rows[1:]:
        if any(row.get(field) != first.get(field) for field in IDENTITY_FIELDS):
            raise ValueError("Pricing source, parser, package, or HTML changed between windows")
    ordered = sorted(rows, key=lambda item: item["pricing_table_window_start"])
    relevant = first["pricing_table_relevant"]
    cursor = 0
    last_index = -1
    jobs = set()
    observation_ids = set()
    observations = []
    table_ids = set()
    review_quotes = 0
    comparable = 0
    for row in ordered:
        start = row["pricing_table_window_start"]
        if start != cursor or row["pricing_table_window_end"] <= start:
            raise ValueError("Missing, overlapping or empty pricing table window")
        cursor = row["pricing_table_window_end"]
        if row["zyte_job_id"] in jobs:
            raise ValueError("Pricing windows require independent Zyte job IDs")
        jobs.add(row["zyte_job_id"])
        for index, table in zip(
            row["pricing_table_window_selected_indices"],
            row["pricing_table_evidence"],
        ):
            if index <= last_index or table.get("table_id") in table_ids:
                raise ValueError("Table indexes/identities overlap across windows")
            last_index = index
            table_ids.add(table["table_id"])
        for obs in row["pricing_observations"]:
            oid = obs.get("observation_id")
            if not isinstance(oid, str) or not oid or oid in observation_ids:
                raise ValueError("Pricing window contains ambiguous/duplicate rate identity")
            observation_ids.add(oid)
            observations.append(obs)
            review_quotes += bool(obs.get("review_quote_candidate"))
            comparable += bool(obs.get("comparable_candidate"))
    if cursor != relevant or relevant == 0:
        raise ValueError("Not all recognized relevant source tables were included")
    return {
        "assembly_schema": "1.0",
        "kind": "offline_pricing_table_window_union_unverified",
        "source_id": sid,
        "source_url": first["source_url"],
        "provider": first["provider"],
        "manifest_sha256": first["manifest_sha256"],
        "source_registry_sha256": first["source_registry_sha256"],
        "deployment_revision": first["deployment_revision"],
        "content_sha256": first["content_sha256"],
        "pricing_parser_revision": first["pricing_parser_revision"],
        "covered_recognized_relevant_tables": cursor,
        "recognized_relevant_tables": relevant,
        "separate_job_count": len(jobs),
        "source_job_ids": sorted(jobs),
        "price_observations": observations,
        "price_observation_count": len(observations),
        "review_quote_candidate_count": review_quotes,
        "fully_scoped_unverified_candidate_count": comparable,
        "recognized_table_window_coverage_complete": True,
        "publisher_catalog_completeness_verified": False,
        "rate_comparison_eligible": False,
        "approved_for_advisor": False,
        "review_status": "pending_human_verification",
        "notice": (
            "Complete union of recognized HTML pricing tables on ONE unchanged "
            "source page; NOT global publisher pricing completeness, price "
            "accuracy, authorization, or suitability for automatic comparisons."
        ),
    }


def assemble_items(items):
    if not isinstance(items, list) or not items:
        raise ValueError("At least one pricing window Item is required")
    groups = defaultdict(list)
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("source_id"), str):
            raise ValueError("Invalid pricing source Item in assembly")
        groups[item["source_id"]].append(item)
    return [assemble_source_windows(group) for _, group in sorted(groups.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", nargs="+", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/pricing-window-review"))
    args = parser.parse_args()
    rows = []
    for file in args.items:
        blob = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(blob, dict):
            rows.append(blob)
        elif isinstance(blob, list):
            rows.extend(blob)
        else:
            raise ValueError("Expected pricing Item or array of Items")
    results = assemble_items(rows)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifests = []
    for result in results:
        sid = result["source_id"]
        if not SAFE_NAME.fullmatch(sid):
            raise ValueError("Unsafe source ID filename")
        destination = args.out_dir / (sid + "_review_inventory.json")
        destination.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        manifests.append({
            "source_id": sid,
            "recognized_tables": result["recognized_relevant_tables"],
            "price_observations": result["price_observation_count"],
            "jobs": result["source_job_ids"],
            "review_file": destination.name,
            "approved_for_advisor": False,
        })
    (args.out_dir / "assembly_manifest.json").write_text(
        json.dumps(manifests, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({
        "assembled_sources": len(results),
        "source_tables": sum(x["recognized_relevant_tables"] for x in results),
        "price_observations": sum(x["price_observation_count"] for x in results),
        "approved_for_advisor": False,
        "deployment_authorized": False,
    }, indent=2))


if __name__ == "__main__":
    main()
