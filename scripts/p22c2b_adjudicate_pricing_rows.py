"""P22C2B part 2: independent THIRD human pricing rate identity adjudication.

The A/B paginated row census must be COMPLETE before we reveal any P22C1
parser candidates. Every qualified prediction/reference must then be matched,
unmatched or missed. Source CELL identity and original SHA are mandatory;
a matched wrong typed rate is FP+FN, not TP.

Diagnostics apply ONLY to recognized visible static pricing table cells on
one frozen P20A source/round, NOT real-world vendor catalog accuracy.
Human identity independence and publisher origin are not cryptographic proof.
No browser fetches, Zyte, bulk grants, advisor approvals, or production DB.
"""
import argparse
import json
import shutil
from collections import Counter
from datetime import timedelta
from pathlib import Path

from scripts.adjudicate_cross_category_accuracy import _price_field_exact
from scripts.p22c2b_paginated_pricing_review import (
    VERSION, _load_json, _utc_now, freeze_blind_bundle, reconcile_pages,
    MAX_PRIVATE_BYTES,
)
from scripts.p22c_same_snapshot_replay import (
    assemble as assemble_rows, run_all, sha,
)
from scripts.plan_documentation_children import _private_new_directory, _write_private
from scripts.reconcile_cross_category_reviews import (
    REVIEWER, _bounded_note, _timestamp,
)

PACKET_KIND = "after_blind_review_original_rate_match_packet"
THIRD_KIND = "independent_third_source_cell_rate_adjudication"
SCORE_KIND = "pilot_scored_selected_static_table_rows_NOT_VENDOR_ACCURACY"
MAX_PAIRS = 2000


def build_packet(plan, ledger, capture_root, frozen_bundle,
                 reviewer_a, reviewer_b, *, now=None):
    if not isinstance(frozen_bundle, dict):
        raise ValueError("Missing frozen original source row review bundle")
    bundle, raw, row_plan = freeze_blind_bundle(
        plan, ledger, capture_root,
        source_id=frozen_bundle.get("source_id"),
        round_no=frozen_bundle.get("round"),
        rows_per_window=frozen_bundle.get("rows_per_window"),
        now=now,
    )
    if bundle != frozen_bundle:
        raise ValueError("BLIND source review bundle changed vs original bytes/plan")
    consensus = reconcile_pages(
        bundle, raw, row_plan, reviewer_a, reviewer_b, now=now,
    )
    if consensus["consensus_status"] != (
        "agreed_complete_selected_visible_table_row_census"
    ):
        raise ValueError(
            "Independent blind human review incomplete, disputed or ambiguous; "
            "held source must NOT become a parser accuracy score"
        )
    replay = assemble_rows(raw, row_plan, run_all(raw, row_plan))
    if (not replay["report"]["recognized_row_window_coverage_complete"]
            or replay["report"]["holds"]
            or replay["report"]["validated_windows"] != len(row_plan["windows"])):
        raise ValueError("P22C1 row replay held or incomplete: no third-person score")
    rows = replay["unverified_observations"]
    predictions = []
    for row in rows:
        if not row["comparable_candidate_unverified"]:
            continue
        if (row["source_id"] != bundle["source_id"]
                or row["source_url"] != bundle["source_url"]):
            raise ValueError("Cross-source price prediction in original row replay")
        predictions.append({
            "prediction_id": row["observation_id"],
            "table_id": row["table_id"],
            "original_row_index": row["original_row_index"],
            "original_column_index": row["original_column_index"],
            "original_cell_sha256": row["original_cell_sha256"],
            "observed_value": {
                "normalized_amount_decimal": row["normalized_amount_decimal"],
                "currency": row["currency"],
                "billing_unit": row["billing_unit"],
                "price_dimension": row["price_dimension"],
                "model_or_service": row["model_or_service"],
                "region": row["region"], "tier_or_plan": row["tier_or_plan"],
            },
            "approved_for_advisor": False,
        })
    if (len(predictions) > MAX_PAIRS
            or len({x["prediction_id"] for x in predictions}) != len(predictions)):
        raise ValueError("Duplicate or unbounded original rate predictions")
    references = consensus["references"]
    if (len(references) > MAX_PAIRS
            or len({x["reference_id"] for x in references}) != len(references)):
        raise ValueError("Duplicate or unbounded independently labeled price gold")
    packet = {
        "schema_version": VERSION, "kind": PACKET_KIND,
        "frozen_bundle_sha256": bundle["bundle_sha256"],
        "consensus_sha256": consensus["consensus_sha256"],
        "p22c1_row_assembly_sha256": replay["report"]["report_sha256"],
        "original_html_sha256": bundle["original_html_sha256"],
        "source_id": bundle["source_id"], "source_url": bundle["source_url"],
        "round": bundle["round"], "wave": bundle["wave"],
        "parser_package_sha256": bundle["parser_package_sha256"],
        "source_round_census": bundle["source_round_census"],
        "reviewer_a_id": consensus["reviewer_a_id"],
        "reviewer_b_id": consensus["reviewer_b_id"],
        "latest_review_a_utc": consensus["latest_review_a_utc"],
        "latest_review_b_utc": consensus["latest_review_b_utc"],
        "pages_accounted": consensus["pages_accounted"],
        "original_rows_accounted": consensus["original_data_rows_accounted"],
        "predictions": predictions, "references": references,
        "unqualified_parser_observations_review_only":
            len(rows) - len(predictions),
        "blind_review_preceded_parser_prediction_disclosure": True,
        "source_representative_population_accuracy": False,
        "vendor_catalog_completeness_verified": False,
        "publisher_origin_authenticated": False,
        "human_independence_verified": False,
        "live_zyte_crawl_authorized": False,
        "approved_for_advisor": False,
    }
    packet["packet_sha256"] = sha(packet)
    if len(json.dumps(packet, ensure_ascii=False).encode()) > MAX_PRIVATE_BYTES:
        raise ValueError("Independent adjudication packet exceeds safe private cap")
    return packet


def blank_third(packet):
    return {
        "schema_version": VERSION, "kind": THIRD_KIND,
        "frozen_packet_sha256": packet["packet_sha256"],
        "adjudicator_id": None,
        "independent_of_reviewers_a_and_b_attested": False,
        "review_completed": False, "adjudicated_at_utc": None,
        "source_wide_selected_table_disposition_note": "",
        "matches": [],
        "unmatched_prediction_ids": [],
        "missed_reference_ids": [],
        "approved_for_advisor": False,
    }


def _source_cell(ref):
    return (
        ref["table_id"], ref["original_row_index"],
        ref["original_column_index"], ref["original_cell_sha256"],
    )


def score_packet(plan, ledger, capture_root, frozen_bundle,
                 reviewer_a, reviewer_b, frozen_packet, third, *, now=None):
    packet = build_packet(
        plan, ledger, capture_root, frozen_bundle,
        reviewer_a, reviewer_b, now=now,
    )
    if not isinstance(frozen_packet, dict) or frozen_packet != packet:
        raise ValueError("Third-human packet differs from CURRENT source/HTML/labels/parser")
    template = blank_third(packet)
    if (not isinstance(third, dict) or set(third) != set(template)
            or any(third[key] != template[key] for key in (
                "schema_version", "kind", "frozen_packet_sha256",
                "approved_for_advisor",
            ))
            or not isinstance(third.get("adjudicator_id"), str)
            or not REVIEWER.fullmatch(third["adjudicator_id"])
            or third["adjudicator_id"].strip().casefold() in {
                packet["reviewer_a_id"].strip().casefold(),
                packet["reviewer_b_id"].strip().casefold(),
            }
            or third.get("independent_of_reviewers_a_and_b_attested") is not True
            or third.get("review_completed") is not True):
        raise ValueError("A separate third HUMAN adjudicator with frozen packet required")
    stamp = _timestamp(third["adjudicated_at_utc"])
    if (stamp < max(
            _timestamp(packet["latest_review_a_utc"]),
            _timestamp(packet["latest_review_b_utc"]),
        )
            or stamp > _utc_now(now) + timedelta(minutes=5)):
        raise ValueError("Third review time must follow BOTH A/B reviews and not be future")
    _bounded_note(
        third["source_wide_selected_table_disposition_note"],
        "Complete selected-table third-person disposition",
    )
    for key in ("matches", "unmatched_prediction_ids", "missed_reference_ids"):
        if not isinstance(third.get(key), list):
            raise ValueError("Missing complete third-review prediction/reference dispositions")
    pred = {x["prediction_id"]: x for x in packet["predictions"]}
    refs = {x["reference_id"]: x for x in packet["references"]}
    used_p, used_r, field_total, field_correct = set(), set(), Counter(), Counter()
    tp, wrong_typed = 0, 0
    for match in third["matches"]:
        if (not isinstance(match, dict)
                or set(match) != {
                    "prediction_id", "reference_id", "same_original_cell_note",
                }
                or not isinstance(match["prediction_id"], str)
                or not isinstance(match["reference_id"], str)
                or match["prediction_id"] not in pred
                or match["reference_id"] not in refs):
            raise ValueError("Cross-source or unknown human/parser price identity")
        pid, rid = match["prediction_id"], match["reference_id"]
        if pid in used_p or rid in used_r:
            raise ValueError("Duplicate parser or human rate used twice")
        a, b = pred[pid], refs[rid]
        if _source_cell(a) != _source_cell(b):
            raise ValueError("Price match REQUIRES exact original table/row/column/cell hash")
        _bounded_note(match["same_original_cell_note"], "Original source-cell match")
        used_p.add(pid)
        used_r.add(rid)
        checks = _price_field_exact(a["observed_value"], b["reviewed_value"])
        for k, ok in checks.items():
            field_total[k] += 1
            field_correct[k] += int(ok)
        if all(checks.values()):
            tp += 1
        else:
            wrong_typed += 1
    unmatched = third["unmatched_prediction_ids"]
    missed = third["missed_reference_ids"]
    if (any(not isinstance(x, str) for x in unmatched + missed)
            or len(unmatched) != len(set(unmatched))
            or len(missed) != len(set(missed))
            or used_p & set(unmatched) or used_r & set(missed)
            or used_p | set(unmatched) != set(pred)
            or used_r | set(missed) != set(refs)):
        raise ValueError("INCOMPLETE identity disposition of all original price predictions/gold")
    fp = len(unmatched) + wrong_typed
    fn = len(missed) + wrong_typed
    report = {
        "schema_version": VERSION, "kind": SCORE_KIND,
        "source_id": packet["source_id"], "source_url": packet["source_url"],
        "round": packet["round"],
        "source_round_census": packet["source_round_census"],
        "original_html_sha256": packet["original_html_sha256"],
        "frozen_packet_sha256": packet["packet_sha256"],
        "parser_package_sha256": packet["parser_package_sha256"],
        "all_original_selected_data_rows_reviewed": packet["original_rows_accounted"],
        "blind_paginated_pages_reviewed": packet["pages_accounted"],
        "predicted_fully_comparable_rates": len(pred),
        "dual_human_agreed_references": len(refs),
        "unqualified_parser_observations_review_only":
            packet["unqualified_parser_observations_review_only"],
        "tp": tp, "fp": fp, "fn": fn,
        "wrong_typed_matched_rates_fp_and_fn": wrong_typed,
        "strict_precision": tp / (tp + fp) if tp + fp else None,
        "strict_recall": tp / (tp + fn) if tp + fn else None,
        "field_compared": dict(field_total),
        "field_exact": dict(field_correct),
        "field_exact_fraction": {
            k: field_correct[k] / field_total[k] for k in field_total
        },
        "metric_scope":
            "reviewer_attested_preselected_recognized_visible_static_pricing_table_rows_ONLY",
        "human_attestation_not_cryptographic_independence": True,
        "source_sample_not_representative_177_or_460": True,
        "publisher_origin_independently_authenticated": False,
        "publisher_catalog_or_dynamic_cards_covered": False,
        "production_accuracy_independently_verified": False,
        "authorizes_live_zyte_or_bulk": False,
        "new_publisher_requests": 0, "new_zyte_jobs": 0,
        "advisor_fact_approvals": 0, "approved_for_advisor": False,
    }
    report["report_sha256"] = sha(report)
    return report


def _write_json(root, name, value):
    blob = (json.dumps(value, ensure_ascii=False, indent=2)+"\n").encode()
    if len(blob) > MAX_PRIVATE_BYTES:
        raise ValueError("Oversized private adjudication output")
    _write_private(root / name, blob)


def write_third(packet, out_dir):
    root = _private_new_directory(out_dir)
    try:
        _write_json(root, "p22c2b_parser_vs_human_ADJUDICATION_PACKET_PRIVATE.json", packet)
        _write_json(root, "p22c2b_third_human_ADJUDICATOR_BLANK.json",
                    blank_third(packet))
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def write_score(report, out_dir):
    root = _private_new_directory(out_dir)
    try:
        _write_json(root, "p22c2b_original_table_row_accuracy_NOT_VENDOR_TRUTH.json",
                    report)
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare-third", action="store_true")
    g.add_argument("--score", action="store_true")
    p.add_argument("--frozen-plan", type=Path, required=True)
    p.add_argument("--private-ledger", type=Path, required=True)
    p.add_argument("--capture-root", type=Path, required=True)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--reviewer-a", type=Path, required=True)
    p.add_argument("--reviewer-b", type=Path, required=True)
    p.add_argument("--packet", type=Path)
    p.add_argument("--third-human", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    plan, ledger = _load_json(args.frozen_plan), _load_json(args.private_ledger)
    bundle = _load_json(args.bundle)
    a, b = _load_json(args.reviewer_a), _load_json(args.reviewer_b)
    if args.prepare_third:
        if args.packet or args.third_human:
            p.error("Third-person blank preparation cannot accept filled review")
        packet = build_packet(plan, ledger, args.capture_root, bundle, a, b)
        root = write_third(packet, args.out_dir)
    else:
        if not args.packet or not args.third_human:
            p.error("Scoring requires exact frozen packet and completed third reviewer")
        report = score_packet(
            plan, ledger, args.capture_root, bundle, a, b,
            _load_json(args.packet), _load_json(args.third_human),
        )
        root = write_score(report, args.out_dir)
    print(json.dumps({
        "private_result": str(root),
        "publisher_http_requests": 0, "zyte_jobs": 0,
        "production_fact_approvals": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
