"""P22C2B part 1: genuine-human, BLIND, paginated original-table-row review.

No HTML fetching or Zyte. The P20A 18/36 cohort, P22A1 operator
policy/capture ledger and P22C1 original-row plan are revalidated on EVERY
invocation. Reviewers receive original row hashes, NOT parser predictions.
A per-row explicit status stops cherry-picked 'gold' from making fake recall.

This is restricted to recognized visible STATIC pricing tables; a completed
table review is not proof the vendor catalog, cards, JS tabs or source family
were exhaustively reviewed. Human identity attestations are not cryptographic
proof. All output is PRIVATE, not trusted AgentFuse data.
"""
import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentfuse_crawlers.model_labels import visible_cell_text
from agentfuse_crawlers.sources import load_sources
from scripts.accession_cross_category_html import stage_data
from scripts.adjudicate_cross_category_accuracy import (
    _pricing_gold_complete, _quoted_original_amount,
)
from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.p22c2_pilot_readiness import _round_census, _source_rows
from scripts.p22c_same_snapshot_replay import (
    _cell_sha, _main, _read, _rows, _tables, plan_source, sha,
)
from scripts.plan_documentation_children import _private_new_directory, _write_private
from scripts.reconcile_cross_category_reviews import (
    PRICE_FIELDS, REVIEWER, _bounded_note, _norm, _rate_scope, _timestamp,
)

VERSION = "p22c2b_paginated_price_review_v1"
BUNDLE_KIND = "blind_all_selected_static_table_rows_NOT_HUMAN_GOLD"
REVIEW_KIND = "independent_human_original_cell_paginated_review"
CONSENSUS_KIND = "two_human_original_table_row_consensus_NOT_ACCURACY"
MAX_PAGES = 160
MAX_REVIEW_ROWS = 24000
MAX_LABELS_PER_ROW = 8
MAX_LABELS_PER_SOURCE = 1600
MAX_PRIVATE_BYTES = 14_000_000
MAX_QUOTE = 450


def _utc_now(now):
    clock = datetime.now(timezone.utc) if now is None else now
    if (not isinstance(clock, datetime) or clock.tzinfo is None
            or clock.utcoffset() is None):
        raise ValueError("Independent review evaluation clock must be timezone aware")
    return clock.astimezone(timezone.utc)


def freeze_blind_bundle(plan, ledger, capture_root, *, source_id, round_no=1,
                        rows_per_window=64, now=None):
    """Read only a SOURCE-REVIEWED original HTML snapshot, not a Zyte Item."""
    allowed = {x["source_id"] for x in _source_rows(plan)}
    if (not isinstance(source_id, str) or source_id not in allowed
            or type(round_no) is not int or round_no not in (1, 2)):
        raise ValueError("Only fixed P20A pricing source ID / round 1 or 2")
    accession, cases, _ = stage_data(plan, ledger, capture_root, now=now)
    selected = next(
        x for x in cases if x["source_id"] == source_id and x["round"] == round_no
    )
    if selected["state"] != "captured":
        raise ValueError("Source capture HELD or missing; no inferred publisher access")
    item = next(x for x in ledger["rows"] if x["source_id"] == source_id)
    source = next(x for x in load_sources() if x["id"] == source_id)
    snap = item["rounds"][round_no - 1]["snapshot"]
    original = _snapshot_bytes(
        snap, capture_root, expected_url=source["url"], method="static_html",
    ).encode("utf-8")
    row_plan = plan_source(
        original, source_id=source_id,
        expected_sha256=selected["raw_html_sha256"],
        rows_per_window=rows_per_window,
    )
    inv = row_plan["inventory"]
    if (not row_plan["windows"] or inv["structural_hold_tables"]
            or len(row_plan["windows"]) > MAX_PAGES
            or inv["relevant_original_rows"] > MAX_REVIEW_ROWS
            or inv["all_visible_tables"] != inv["relevant_tables"]):
        raise ValueError(
            "Recognized visible pricing table inventory HELD: no tables, "
            "unrecognized tables, complex spans, or unsafe review limits"
        )
    table_map = {x["table_id"]: x for x in row_plan["tables"]}
    pages = []
    for window in row_plan["windows"]:
        t = table_map[window["table_id"]]
        if window["span_or_nested_table_hold"]:
            raise ValueError("Complex source table cannot be paginated safely")
        rows = [{
            "original_row_index": idx,
            "original_row_sha256": t["original_row_sha256"][idx],
        } for idx in range(window["row_start"], window["row_end"])]
        pages.append({
            "page_id": sha([row_plan["plan_sha256"],
                            source_id, round_no, window["window_id"]])[:28],
            "window_id": window["window_id"],
            "table_id": window["table_id"],
            "all_table_index": window["all_table_index"],
            "row_start": window["row_start"],
            "row_end": window["row_end"],
            "original_rows": rows,
        })
    if len({p["page_id"] for p in pages}) != len(pages):
        raise ValueError("Duplicate source-pinned reviewer page identity")
    bundle = {
        "schema_version": VERSION, "kind": BUNDLE_KIND,
        "frozen_p20a_plan_sha256": plan["plan_sha256"],
        "p22a1_accession_sha256": accession["accession_sha256"],
        "p22c1_original_row_plan_sha256": row_plan["plan_sha256"],
        "parser_package_sha256": row_plan["parser_package_sha256"],
        "source_id": source_id, "source_url": selected["source_url"],
        "round": round_no, "wave": selected["wave"],
        "original_html_sha256": selected["raw_html_sha256"],
        "captured_at_utc": selected["captured_at_utc"],
        "source_round_census": _round_census(cases),
        "pages": pages, "reviewed_original_data_rows": sum(
            len(x["original_rows"]) for x in pages
        ),
        "parser_predictions_in_blind_pages": False,
        "table_relevance_selection_from_parser_not_ground_truth": True,
        "source_wide_vendor_coverage_claimed": False,
        "publisher_origin_independently_authenticated": False,
        "source_policy_independently_verified": False,
        "new_publisher_requests": 0, "zyte_jobs_created": 0,
        "approved_for_advisor": False,
    }
    bundle["bundle_sha256"] = sha(bundle)
    if len(json.dumps(bundle).encode("utf-8")) > MAX_PRIVATE_BYTES:
        raise ValueError("Blind row review bundle exceeds private data size limit")
    return bundle, original, row_plan


def blank_reviewer(bundle, letter):
    if letter not in ("A", "B"):
        raise ValueError("Reviewer must be independent person A or B")
    return {
        "schema_version": VERSION, "kind": REVIEW_KIND,
        "frozen_bundle_sha256": bundle["bundle_sha256"],
        "reviewer_letter": letter, "reviewer_id": None,
        "independent_blind_review_attested": False,
        "pages": [{
            "page_id": page["page_id"], "review_completed": False,
            "reviewed_at_utc": None, "review_note": "",
            "row_reviews": [{
                **row, "disposition": "not_reviewed", "labels": [],
            } for row in page["original_rows"]],
        } for page in bundle["pages"]],
        "parser_predictions_seen_before_review": False,
        "approved_for_advisor": False,
    }


def _read_human(reviewer, bundle, original, row_plan, letter, *, now=None):
    expected = blank_reviewer(bundle, letter)
    if (not isinstance(reviewer, dict) or set(reviewer) != set(expected)
            or reviewer.get("schema_version") != VERSION
            or reviewer.get("kind") != REVIEW_KIND
            or reviewer.get("reviewer_letter") != letter
            or reviewer.get("frozen_bundle_sha256") != bundle["bundle_sha256"]
            or reviewer.get("approved_for_advisor") is not False
            or reviewer.get("parser_predictions_seen_before_review") is not False
            or reviewer.get("independent_blind_review_attested") is not True
            or not isinstance(reviewer.get("reviewer_id"), str)
            or not REVIEWER.fullmatch(reviewer["reviewer_id"])
            or reviewer["reviewer_id"].strip().casefold().startswith("replace")
            or not isinstance(reviewer.get("pages"), list)
            or len(reviewer["pages"]) != len(expected["pages"])):
        raise ValueError("Invalid, forged or incomplete independent blind reviewer")
    clock = _utc_now(now)
    captured = _timestamp(bundle["captured_at_utc"])
    _, main = _main(original)
    tables = _tables(main)
    table_map = {t["table_id"]: t for t in row_plan["tables"]}
    labels_seen, result, dates = set(), [], []
    total_labels = 0
    for page, skeleton, identity in zip(
        reviewer["pages"], expected["pages"], bundle["pages"]
    ):
        if (not isinstance(page, dict) or set(page) != set(skeleton)
                or page.get("page_id") != skeleton["page_id"]
                or page.get("review_completed") is not True
                or not isinstance(page.get("row_reviews"), list)
                or len(page["row_reviews"]) != len(skeleton["row_reviews"])):
            raise ValueError("Missing, duplicate or reordered reviewed price page")
        _bounded_note(page.get("review_note"), "Complete source page row review")
        ts = _timestamp(page.get("reviewed_at_utc"))
        if ts < captured or ts > clock + timedelta(minutes=5):
            raise ValueError("Human review time predates original HTML or claims future")
        dates.append(ts)
        meta = table_map[identity["table_id"]]
        table = tables[meta["all_table_index"]]
        all_rows = _rows(table)
        reviewed = []
        for row, wanted in zip(page["row_reviews"], skeleton["row_reviews"]):
            if (not isinstance(row, dict) or set(row) != set(wanted)
                    or row["original_row_index"] != wanted["original_row_index"]
                    or row["original_row_sha256"] != wanted["original_row_sha256"]
                    or row["disposition"] not in (
                        "rates_labeled", "explicit_no_relevant_rate", "ambiguous"
                    )
                    or not isinstance(row["labels"], list)
                    or len(row["labels"]) > MAX_LABELS_PER_ROW):
                raise ValueError("Unreviewed/forged/duplicate original HTML row")
            idx = row["original_row_index"]
            if sha(__import__("lxml").html.tostring(
                all_rows[idx], encoding="utf-8", with_tail=False,
            )) != wanted["original_row_sha256"]:
                raise ValueError("Human row reference original HTML SHA-256 mismatch")
            if row["disposition"] == "rates_labeled" and not row["labels"]:
                raise ValueError("Labeled rate row missing human labels")
            if row["disposition"] != "rates_labeled" and row["labels"]:
                raise ValueError("Unlabeled or ambiguous row cannot smuggle human prices")
            original_cells = all_rows[idx].xpath("./th|./td")
            enriched = []
            for item in row["labels"]:
                if (not isinstance(item, dict)
                        or set(item) != {
                            "original_column_index", "original_cell_sha256",
                            "publisher_evidence_quote", "reviewed_value",
                            "review_note", "approved_for_advisor",
                        }
                        or item["approved_for_advisor"] is not False):
                    raise ValueError("Invalid human-reviewed original price label shape")
                col = item["original_column_index"]
                if type(col) is not int or not 0 <= col < len(original_cells):
                    raise ValueError("Cross-column or foreign original price cell")
                cell = original_cells[col]
                if item["original_cell_sha256"] != _cell_sha(cell):
                    raise ValueError("Original price cell SHA-256 mismatch")
                quote = item["publisher_evidence_quote"]
                material = visible_cell_text(cell)
                if (not isinstance(quote, str) or not 5 <= len(quote) <= MAX_QUOTE
                        or _norm(quote) not in _norm(material)):
                    raise ValueError("Human quote absent from selected original visible cell")
                _bounded_note(item["review_note"], "Original source price review")
                value = _rate_scope("pricing", item["reviewed_value"])
                if not _quoted_original_amount(quote, value["amount_decimal"]):
                    raise ValueError("Reviewed monetary amount absent from original cell quote")
                ref = {
                    "table_id": identity["table_id"],
                    "window_id": identity["window_id"],
                    "original_row_index": idx,
                    "original_column_index": col,
                    "original_row_sha256": wanted["original_row_sha256"],
                    "original_cell_sha256": item["original_cell_sha256"],
                    "publisher_evidence_quote": quote,
                    "reviewed_value": value,
                    "approved_for_advisor": False,
                }
                ref["reference_id"] = sha([
                    bundle["bundle_sha256"], identity["page_id"],
                    identity["table_id"], idx, col, _norm(quote), value,
                ])[:32]
                if ref["reference_id"] in labels_seen:
                    raise ValueError("Duplicate original source price label identity")
                labels_seen.add(ref["reference_id"])
                total_labels += 1
                if total_labels > MAX_LABELS_PER_SOURCE:
                    raise ValueError("Unbounded original pricing human labels")
                enriched.append(ref)
            reviewed.append({
                "original_row_index": idx,
                "disposition": row["disposition"],
                "labels": sorted(enriched, key=lambda x: x["reference_id"]),
            })
        result.append({
            "page_id": identity["page_id"], "table_id": identity["table_id"],
            "window_id": identity["window_id"], "rows": reviewed,
        })
    if sum(len(x["rows"]) for x in result) != bundle["reviewed_original_data_rows"]:
        raise ValueError("Missing original pricing data rows in page census")
    return {
        "reviewer_id": reviewer["reviewer_id"],
        "letter": letter, "pages": result,
        "latest_reviewed_at_utc": max(dates).isoformat(),
        "human_labels": total_labels,
        "operator_attested_independence_not_verified": True,
    }


def reconcile_pages(bundle, original, row_plan, reviewer_a, reviewer_b, *,
                    now=None):
    left = _read_human(reviewer_a, bundle, original, row_plan, "A", now=now)
    right = _read_human(reviewer_b, bundle, original, row_plan, "B", now=now)
    if left["reviewer_id"].strip().casefold() == right[
        "reviewer_id"
    ].strip().casefold():
        raise ValueError("Two genuinely separate blind reviewer identities required")
    references, disputes, ambiguous = [], [], []
    for a, b in zip(left["pages"], right["pages"]):
        if a["page_id"] != b["page_id"]:
            raise ValueError("Different source page ordering in human review")
        for ra, rb in zip(a["rows"], b["rows"]):
            if ra["original_row_index"] != rb["original_row_index"]:
                raise ValueError("Human source row identity mismatch")
            if ra["disposition"] == "ambiguous" or rb["disposition"] == "ambiguous":
                ambiguous.append((a["page_id"], ra["original_row_index"]))
            elif (ra["disposition"] != rb["disposition"]
                  or ra["labels"] != rb["labels"]):
                disputes.append((a["page_id"], ra["original_row_index"]))
            elif ra["disposition"] == "rates_labeled":
                references.extend(ra["labels"])
    if any(not _pricing_gold_complete(x["reviewed_value"]) for x in references):
        ambiguous.append(("incomplete_human_rate_dimensions", -1))
    if len({x["reference_id"] for x in references}) != len(references):
        raise ValueError("Duplicated source-price gold identity in consensus")
    status = (
        "held_ambiguous_source_rows" if ambiguous else
        "held_two_independent_reviewers_disagree" if disputes else
        "agreed_complete_selected_visible_table_row_census"
    )
    value = {
        "schema_version": VERSION, "kind": CONSENSUS_KIND,
        "frozen_bundle_sha256": bundle["bundle_sha256"],
        "source_id": bundle["source_id"], "source_url": bundle["source_url"],
        "round": bundle["round"],
        "original_html_sha256": bundle["original_html_sha256"],
        "parser_package_sha256": bundle["parser_package_sha256"],
        "consensus_status": status,
        "original_data_rows_accounted": bundle["reviewed_original_data_rows"],
        "pages_accounted": len(bundle["pages"]),
        "disputed_rows": len(disputes), "ambiguous_rows": len(ambiguous),
        "dual_agreed_human_rate_labels": (
            len(references) if not (ambiguous or disputes) else None
        ),
        "references": references if not (ambiguous or disputes) else [],
        "reviewer_a_id": left["reviewer_id"],
        "reviewer_b_id": right["reviewer_id"],
        "latest_review_a_utc": left["latest_reviewed_at_utc"],
        "latest_review_b_utc": right["latest_reviewed_at_utc"],
        "original_study_source_denominator": 18,
        "original_study_source_round_denominator": 36,
        "original_study_pricing_source_denominator": 6,
        "original_study_pricing_round_denominator": 12,
        "original_table_selection_not_vendor_catalog_census": True,
        "human_independence_operator_attested_not_proven": True,
        "publisher_origin_independently_authenticated": False,
        "source_access_legality_verified_by_script": False,
        "parser_predictions_hidden_until_review_complete": True,
        "precision": None, "recall": None,
        "approved_for_advisor": False,
    }
    value["consensus_sha256"] = sha(value)
    return value


def _write_json(root, name, obj):
    payload = (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()
    if len(payload) > MAX_PRIVATE_BYTES:
        raise ValueError("Private paginated human review exceeds file size budget")
    _write_private(root / name, payload)


def write_blind_templates(bundle, output):
    root = _private_new_directory(output)
    try:
        _write_json(root, "source_original_table_blind_task_bundle_PRIVATE.json", bundle)
        for letter in ("A", "B"):
            _write_json(
                root, f"source_independent_human_{letter}_BLANK.json",
                blank_reviewer(bundle, letter),
            )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def _load_json(path):
    return _read(path, MAX_PRIVATE_BYTES, json_input=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepare-blind", action="store_true", required=True)
    p.add_argument("--frozen-plan", type=Path, required=True)
    p.add_argument("--private-ledger", type=Path, required=True)
    p.add_argument("--capture-root", type=Path, required=True)
    p.add_argument("--source-id", required=True)
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--rows-per-window", type=int, default=64)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    bundle, _, _ = freeze_blind_bundle(
        _load_json(args.frozen_plan), _load_json(args.private_ledger),
        args.capture_root, source_id=args.source_id, round_no=args.round,
        rows_per_window=args.rows_per_window,
    )
    root = write_blind_templates(bundle, args.out_dir)
    print(json.dumps({
        "private_blank_blind_tasks": str(root),
        "original_rows_to_review": bundle["reviewed_original_data_rows"],
        "source_pages": len(bundle["pages"]),
        "published_prices": 0, "publisher_requests": 0, "zyte_jobs": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
