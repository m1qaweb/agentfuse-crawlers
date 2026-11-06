"""P22C2A: publisher-policy + original-byte + independent-review readiness.

OFFLINE ONLY. Original P20A 18 sources / 36 rounds, including all 6 pricing
sources / 12 rounds. Compare legacy vs P22C1 parser-addressable PHYSICAL
cell positions from the exact same operator-supplied original HTML bytes.
These are candidate coverage diagnostics, NOT observed accuracy or truth.

Policy review is operator-attested, publisher origin is not independently
authenticated, and human reviewer identity/independence is not proven by
this script. No live Zyte spider opt-in, permission grants or advisor facts.
"""
import argparse
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.provider_profiles import identify_source_product
from agentfuse_crawlers.sources import load_sources
from scripts.accession_cross_category_html import frozen_plan, stage_data, validate_plan
from scripts.adjudicate_cross_category_accuracy import (
    _pricing_gold_complete, _quoted_original_amount,
)
from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.p22c_same_snapshot_replay import (
    _read as read_private, assemble as assemble_rows, plan_source, run_all,
    sha as original_sha,
)
from scripts.plan_documentation_children import _private_new_directory, _write_private
from scripts.reconcile_cross_category_reviews import (
    MAX_SOURCE_LABELS, reconcile,
)

VERSION = "p22c2a_source_owned_row_window_pilot_readiness_v1"
KIND = "offline_pricing_pilot_gate_NOT_AUTHORIZATION_OR_ACCURACY"
CHECKLIST_KIND = "p22c2a_blank_p20a_pricing_source_review_not_permission"
MAX_REPORT_SIZE = 6_000_000
MAX_DETAILS = 24


def _source_rows(plan):
    validate_plan(plan)
    subset = [row for row in plan["sources"] if row["category"] == "pricing"]
    if len(subset) != 6 or len({row["source_id"] for row in subset}) != 6:
        raise ValueError("P20A six fixed pricing source IDs were modified")
    return subset


def blank_pricing_checklist():
    plan = frozen_plan()
    pricing = _source_rows(plan)
    return {
        "schema_version": VERSION, "kind": CHECKLIST_KIND,
        "frozen_p20a_plan_sha256": plan["plan_sha256"],
        "source_denominator": 18, "source_round_denominator": 36,
        "pricing_source_denominator": 6, "pricing_round_denominator": 12,
        "source_replacement_allowed": False,
        "sources": [{
            "source_id": source["source_id"],
            "source_url": source["source_url"],
            "wave": source["wave"],
            "rounds": [{
                "round": number, "publisher_policy_status": "not_reviewed",
                "original_html_status": "not_supplied",
                "blind_reviewer_a": "not_supplied",
                "blind_reviewer_b": "not_supplied",
                "third_adjudicator": "not_supplied",
                "diagnostic_accuracy": None,
                "approved_for_advisor": False,
            } for number in (1, 2)],
        } for source in pricing],
        "publisher_permissions_granted": 0,
        "actual_publisher_html_captured": 0,
        "real_independent_human_labels": 0,
        "automatic_monitoring_authorized": False,
        "bulk_crawl_authorized": False,
        "no_original_page_or_reviewer_data_in_this_template": True,
        "approved_for_advisor": False,
    }


def _table_positions(observations, *, baseline):
    """Physical original table cell positions, NOT independently found rates."""
    found = set()
    for obs in observations:
        if not isinstance(obs, dict):
            raise ValueError("Malformed parser observation")
        if baseline:
            if not str(obs.get("evidence_kind", "")).startswith(
                "structured_table"
            ):
                continue
            table = obs.get("table_id")
            row, col = obs.get("row_index"), obs.get("column_index")
        else:
            table = obs.get("table_id")
            row = obs.get("original_row_index")
            col = obs.get("original_column_index")
        if (not isinstance(table, str) or not table.startswith("table-")
                or type(row) is not int or row < 0
                or type(col) is not int or col < 0):
            raise ValueError("Unsupported source-local parser cell coordinate")
        found.add((table, row, col))
    return found


def _round_census(cases):
    if len(cases) != 36:
        raise ValueError("All 36 preselected source-rounds must be retained")
    count = Counter((x["category"], x["state"]) for x in cases)
    return {
        "all_original_source_rounds": 36,
        "pricing_original_source_rounds": 12,
        "all_round_capture_states": dict(sorted(
            Counter(x["state"] for x in cases).items()
        )),
        "pricing_round_capture_states": dict(sorted(
            (state, n) for (category, state), n in count.items()
            if category == "pricing"
        )),
    }


def _review_consensus(plan, ledger, capture_root, selected,
                      reviewer_a, reviewer_b, *, now=None):
    if (reviewer_a is None) != (reviewer_b is None):
        raise ValueError("Both independent A and B reviewers are required together")
    if reviewer_a is None:
        return {
            "status": "not_supplied",
            "original_source_gold_labels": None,
            "fully_scoped_gold_rates": None,
            "dual_human_agreement_operator_attested": False,
        }
    report, rounds, evidence = reconcile(
        plan, ledger, capture_root, reviewer_a, reviewer_b, now=now,
    )
    match = [x for x in rounds
             if x["source_id"] == selected["source_id"]
             and x["round"] == selected["round"]]
    if len(match) != 1:
        raise ValueError("Selected source-round absent from human review census")
    status = match[0]["dual_review_status"]
    agreed = [x for x in evidence
              if x["source_id"] == selected["source_id"]
              and x["round"] == selected["round"]]
    if status != "agreed_two_reviewers_visible_page_inventory":
        if agreed:
            raise ValueError("Disputed source has unexpected agreed gold evidence")
        return {
            "status": status, "original_source_gold_labels": None,
            "fully_scoped_gold_rates": None,
            "dual_human_agreement_operator_attested": False,
        }
    if len(agreed) != 1 or agreed[0]["raw_html_sha256"] != selected[
        "raw_html_sha256"
    ] or agreed[0]["source_url"] != selected["source_url"]:
        raise ValueError("Publisher evidence did not bind to exact original source round")
    human = agreed[0]["evidence"]
    for item in human:
        if item.get("evidence_type") != "pricing_rate":
            raise ValueError("Nonpricing human evidence in pricing round")
        if not _quoted_original_amount(
            item["publisher_evidence_quote"],
            item["reviewed_value"]["amount_decimal"],
        ):
            raise ValueError("Human rate amount missing from original quote")
    return {
        "status": status, "original_source_gold_labels": len(human),
        "fully_scoped_gold_rates": sum(
            _pricing_gold_complete(x["reviewed_value"]) for x in human
        ),
        "dual_human_agreement_operator_attested": True,
    }


def evaluate(plan, ledger, capture_root, *, source_id, round_no=1,
             rows_per_window=64, reviewer_a=None, reviewer_b=None, now=None):
    """Construct one source/round private evidence triage, never run a crawl."""
    pricing = _source_rows(plan)
    if (not isinstance(source_id, str)
            or source_id not in {row["source_id"] for row in pricing}
            or type(round_no) is not int or round_no not in (1, 2)):
        raise ValueError("Select one frozen P20A pricing source ID and round 1/2")
    if (reviewer_a is None) != (reviewer_b is None):
        raise ValueError("A and B human review inputs must be supplied together")
    # Even an unobserved source is still a 36-round study member.
    accession, cases, _ = stage_data(plan, ledger, capture_root, now=now)
    selected = next(
        x for x in cases
        if x["source_id"] == source_id and x["round"] == round_no
    )
    census = _round_census(cases)
    holds = []
    if selected["state"] != "captured":
        holds.append("original_source_round_not_captured_or_policy_held")
    report = {
        "schema_version": VERSION, "kind": KIND,
        "frozen_p20a_plan_sha256": plan["plan_sha256"],
        "p22a1_accession_sha256": accession["accession_sha256"],
        "source_id": source_id, "source_url": selected["source_url"],
        "round": round_no, "wave": selected["wave"],
        "source_category": "pricing",
        "original_capture_state": selected["state"],
        "operator_policy_decision": selected["operator_policy_decision"],
        "source_policy_independently_verified": False,
        "publisher_origin_authenticated": False,
        "original_html_sha256": selected.get("raw_html_sha256"),
        "original_source_bytes_verified": selected["state"] == "captured",
        "source_round_census": census,
        "legacy_vs_row_window_coverage_NOT_ACCURACY": None,
        "blind_review": {
            "status": "not_supplied", "original_source_gold_labels": None,
            "fully_scoped_gold_rates": None,
            "dual_human_agreement_operator_attested": False,
        },
        "readiness_for_third_identity_adjudicator": False,
        "live_zyte_row_window_crawl_authorized": False,
        "full_460_source_crawl_authorized": False,
        "human_truth_independently_authenticated": False,
        "precision": None, "recall": None,
        "false_positives": None, "false_negatives": None,
        "price_accuracy_measured": False,
        "new_publisher_http_requests": 0, "new_zyte_jobs": 0,
        "advisor_fact_approvals": 0, "approved_for_advisor": False,
    }
    if selected["state"] == "captured":
        row = next(x for x in ledger["rows"] if x["source_id"] == source_id)
        snap = row["rounds"][round_no - 1]["snapshot"]
        source = next(s for s in load_sources() if s["id"] == source_id)
        text = _snapshot_bytes(
            snap, capture_root, expected_url=source["url"],
            method="static_html",
        )
        raw = text.encode("utf-8")
        row_plan = plan_source(
            raw, source_id=source_id,
            expected_sha256=selected["raw_html_sha256"],
            rows_per_window=rows_per_window,
        )
        row_data = assemble_rows(raw, row_plan, run_all(raw, row_plan))
        row_output = row_data["report"]
        baseline = extract_evidence(
            raw, source["url"], category="pricing", source_id=source_id,
        )
        identity = identify_source_product(source, baseline)
        old_positions = _table_positions(
            baseline.get("pricing_observations") or [], baseline=True,
        )
        new_positions = _table_positions(
            row_data["unverified_observations"], baseline=False,
        )
        gained = sorted(new_positions - old_positions)
        lost = sorted(old_positions - new_positions)
        report["legacy_vs_row_window_coverage_NOT_ACCURACY"] = {
            "same_original_html_sha256": row_plan["original_html_sha256"],
            "same_deployed_parser_package_sha256":
                row_plan["parser_package_sha256"],
            "row_plan_sha256": row_plan["plan_sha256"],
            "row_assembly_report_sha256": row_output["report_sha256"],
            "baseline_parser_revision": baseline["pricing_parser_revision"],
            "baseline_rows_examined": baseline["pricing_rows_examined"],
            "baseline_table_rows_incomplete":
                baseline["pricing_table_rows_incomplete"],
            "baseline_observation_limit_reached":
                baseline["pricing_observation_limit_reached"],
            "baseline_parser_table_physical_cell_positions": len(old_positions),
            "bounded_row_parser_table_physical_cell_positions": len(new_positions),
            "additional_parser_addressable_cell_positions": len(gained),
            "positions_previously_seen_but_missing_in_row_replay": len(lost),
            "additional_cell_locator_sample": [
                {"table_id": t, "original_row_index": i,
                 "original_column_index": j} for t, i, j in gained[:MAX_DETAILS]
            ],
            "missing_cell_locator_sample": [
                {"table_id": t, "original_row_index": i,
                 "original_column_index": j} for t, i, j in lost[:MAX_DETAILS]
            ],
            "row_windows_planned": row_plan["inventory"]["row_windows"],
            "row_windows_validated": row_output["validated_windows"],
            "row_assembly_hold_reasons": row_output["holds"],
            "recognized_visible_static_rows_only": True,
            "unverified_parser_candidate_coverage_not_rate_recall": True,
            "vendor_catalog_completeness_verified": False,
        }
        holds.extend(row_output["holds"])
        if not row_output["recognized_row_window_coverage_complete"]:
            holds.append("recognized_row_window_source_incomplete")
        if lost:
            holds.append("legacy_physical_rate_cells_lost_during_row_window_replay")
        if identity.get("source_product_title_conflict"):
            holds.append("source_product_identity_conflict")
        if len(new_positions) > MAX_SOURCE_LABELS:
            holds.append("source_exceeds_p22a2_200_gold_labels_per_source_capacity")
        if not new_positions:
            holds.append("no_scored_original_price_cells_observed_not_vendor_negative")
        report["blind_review"] = _review_consensus(
            plan, ledger, capture_root, selected,
            reviewer_a, reviewer_b, now=now,
        )
        if report["blind_review"]["status"] != (
            "agreed_two_reviewers_visible_page_inventory"
        ):
            holds.append("two_independent_complete_blind_reviews_not_agreed")
        else:
            human = report["blind_review"]
            if human["original_source_gold_labels"] == 0 and new_positions:
                holds.append("no_human_labeled_prices_despite_parser_rate_cells")
            if human["fully_scoped_gold_rates"] != human[
                "original_source_gold_labels"
            ]:
                holds.append("human_reference_prices_have_unresolved_dimensions")
    elif reviewer_a is not None:
        # Full A/B packets cannot falsely change this held source to captured.
        report["blind_review"] = _review_consensus(
            plan, ledger, capture_root, selected,
            reviewer_a, reviewer_b, now=now,
        )
        holds.append("original_source_html_missing_even_if_reviewers_attested")
    report["hold_reasons"] = sorted(set(holds))
    report["readiness_for_third_identity_adjudicator"] = not bool(holds)
    report["next_operator_step"] = (
        "third_person_row_window_identity_review_required"
        if not holds else
        "resolve_source_access_or_evidence_holds_before_scoring"
    )
    # An approved data fact requires more than one A/B agreement or even
    # a third reviewer: publisher source origin and allowed reuse remain
    # independently unverified by this offline engineering script.
    report["report_sha256"] = original_sha(report)
    return report


def write_blank(out_dir):
    root = _private_new_directory(out_dir)
    try:
        value = blank_pricing_checklist()
        _write_private(root / "p22c2a_six_pricing_sources_BLANK.json", (
            json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        ).encode())
        _write_private(root / "README_PRIVATE.txt", (
            "P22C2A original P20A SIX pricing sources / 12 rounds.\n"
            "NOT source access permission. NO real HTML captured, NO human labels.\n"
            "Use P22A1 private reviewed capture and P22A2 A/B original-page review.\n"
            "Never upload filled human reviews or raw publisher HTML to GitHub.\n"
        ).encode())
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def write_report(report, out_dir):
    root = _private_new_directory(out_dir)
    try:
        payload = (json.dumps(report, indent=2, ensure_ascii=False)+"\n").encode()
        if len(payload) > MAX_REPORT_SIZE:
            raise ValueError("Private source readiness report exceeds size cap")
        _write_private(root / "p22c2a_single_source_pilot_READINESS_NOT_ACCURACY.json",
                       payload)
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--evaluate", action="store_true")
    p.add_argument("--frozen-plan", type=Path)
    p.add_argument("--private-ledger", type=Path)
    p.add_argument("--capture-root", type=Path)
    p.add_argument("--source-id")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--rows-per-window", type=int, default=64)
    p.add_argument("--reviewer-a", type=Path)
    p.add_argument("--reviewer-b", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    if args.prepare:
        if any((args.frozen_plan, args.private_ledger, args.capture_root,
                args.source_id, args.reviewer_a, args.reviewer_b)):
            p.error("Blank preparation must not consume private data")
        result = {"blank_private_template": str(write_blank(args.out_dir))}
    else:
        if not all((args.frozen_plan, args.private_ledger,
                    args.capture_root, args.source_id)):
            p.error("Source evaluation requires original private accession files")
        if bool(args.reviewer_a) != bool(args.reviewer_b):
            p.error("Independent A/B reviewer files must be supplied together")
        data = evaluate(
            read_private(args.frozen_plan, 200_000, json_input=True),
            read_private(args.private_ledger, 200_000, json_input=True),
            args.capture_root, source_id=args.source_id,
            round_no=args.round, rows_per_window=args.rows_per_window,
            reviewer_a=(
                read_private(args.reviewer_a, 6_000_000, json_input=True)
                if args.reviewer_a else None
            ),
            reviewer_b=(
                read_private(args.reviewer_b, 6_000_000, json_input=True)
                if args.reviewer_b else None
            ),
        )
        result = {
            "private_evidence_gate_report": str(write_report(data, args.out_dir)),
            "source_hold_count": len(data["hold_reasons"]),
            "third_adjudication_ready": data[
                "readiness_for_third_identity_adjudicator"
            ],
        }
    print(json.dumps({**result, "publisher_fetches": 0, "zyte_jobs": 0,
                      "trusted_prices_published": 0}, indent=2))


if __name__ == "__main__":
    main()
