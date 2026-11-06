"""P22C2A: all page bytes, permissions and human identities are SYNTHETIC.

This exercises exact source/round binding and candidate-COVERAGE diagnostics.
It does not grant publisher permission or simulate genuine human research.
"""
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from scripts.accession_cross_category_html import blank_ledger, frozen_plan
from scripts.p22c2_pilot_readiness import (
    _table_positions, blank_pricing_checklist, evaluate, write_blank,
    write_report,
)
from scripts.reconcile_cross_category_reviews import blank_reviewer, build_bundle

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
PRICE = "USD 0.50 / 1M tokens"
SYNTHETIC_NOTE = (
    "SYNTHETIC EVALUATION ONLY. This example records no genuine publisher "
    "permissions, original website captures, independent expert labels, "
    "commercially valid rates or operator requests."
)
SID = "deepseek_pricing"


def at(days=0):
    return (NOW + timedelta(days=days)).isoformat()


def html_rows(count):
    return (
        "<html><head><title>DeepSeek API Pricing</title></head>"
        "<body><main><h1>DeepSeek API Pricing</h1>"
        "<p>All prices are in USD.</p><p>Region: Global</p>"
        "<p>Tier: Standard</p><p>Prices per 1M tokens.</p>"
        "<table><caption>USD per 1M tokens</caption>"
        "<thead><tr><th>Model</th><th>Input price</th></tr></thead>"
        "<tbody>" +
        "".join(
            f"<tr><th>DeepSeek Mock Model {i:04}</th><td>{PRICE}</td></tr>"
            for i in range(count)
        ) +
        "</tbody></table></main></body></html>"
    ).encode("utf-8")


def captured(root, count=8, *, source_id=SID, round_no=1):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    row = next(x for x in ledger["rows"] if x["source_id"] == source_id)
    host = urlsplit(row["source_url"]).hostname
    row["policy_review"] = {
        "decision": "operator_attested_manual_permitted",
        "reviewer": "Synthetic Publisher Policy Operator",
        "reviewed_at_utc": at(-3),
        "expires_at_utc": at(4),
        "ownership_url": row["source_url"],
        "terms_url": f"https://{host}/terms",
        "robots_url": f"https://{host}/robots.txt",
        "retention_reviewed": True, "note": SYNTHETIC_NOTE * 2,
    }
    raw = html_rows(count)
    digest = hashlib.sha256(raw).hexdigest()
    file = root / source_id / f"original-r{round_no}-{digest[:24]}.html"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(raw)
    row["rounds"][round_no-1] = {
        "round": round_no, "state": "captured",
        "capture_receipt_id": f"SYNTHETIC-P22C2-{source_id}-{round_no:02}",
        "snapshot": {
            "file": str(file.relative_to(root)),
            "sha256": digest, "request_url": row["source_url"],
            "final_url": row["source_url"],
            "http_status": 200, "media_type": "text/html",
            "capture_method": "static_html",
            "captured_at_utc": at(-1),
            "capture_origin_review_status": "operator_supplied_unverified",
        },
    }
    return plan, ledger, raw, file


def human_pair(plan, ledger, root, n, *, disagreement=False):
    bundle, _, _ = build_bundle(plan, ledger, root, now=NOW)
    a = blank_reviewer(bundle, "A")
    b = blank_reviewer(bundle, "B")
    for rv, name in ((a, "Synthetic Independent Alpha"),
                     (b, "Synthetic Independent Beta")):
        rv["reviewer_id"] = name
        rv["independent_blind_review_attested"] = True
        for task in rv["source_reviews"]:
            task.update({
                "reviewed_at_utc": at(),
                "page_scope": "sufficient_visible_static_page",
                "whole_visible_page_review_complete": True,
                "exact_product_scope_reviewed": True,
                "no_relevant_evidence_observed": False,
                "review_note": SYNTHETIC_NOTE,
            })
            task["evidence_inventory"] = [
                {
                    "evidence_type": "pricing_rate",
                    "publisher_evidence_quote": (
                        f"DeepSeek Mock Model {i:04} {PRICE}"
                    ),
                    "publisher_evidence_url": task["source_url"],
                    "reviewed_value": {
                        "amount_decimal": (
                            "1.25" if disagreement and
                            rv["reviewer_letter"] == "B" and i == 0
                            else "0.50"
                        ),
                        "currency": "USD",
                        "billing_unit": "per_1m_tokens",
                        "price_dimension": "input",
                        "model_or_service": f"DeepSeek Mock Model {i:04}",
                        "region": "Global", "region_applicability": "explicit",
                        "tier_or_plan": "Standard",
                        "tier_applicability": "explicit",
                        "conditions": None,
                    },
                    "review_note": SYNTHETIC_NOTE,
                    "approved_for_advisor": False,
                } for i in range(n)
            ]
    return a, b


def test_blank_checklist_exact_six_sources_twelve_rounds_no_permissions(tmp_path):
    x = blank_pricing_checklist()
    assert x["source_denominator"] == 18
    assert x["source_round_denominator"] == 36
    assert x["pricing_source_denominator"] == 6
    assert x["pricing_round_denominator"] == 12
    assert x["frozen_p20a_plan_sha256"] == frozen_plan()["plan_sha256"]
    assert len(x["sources"]) == 6
    assert {i["source_id"] for i in x["sources"]} == {
        "gemini_api_pricing", "aws_bedrock_pricing",
        "oracle_oci_generative_ai_pricing",
        "deepseek_pricing", "mistral_pricing", "together_ai_pricing",
    }
    assert all(len(s["rounds"]) == 2 for s in x["sources"])
    assert all(i["publisher_policy_status"] == "not_reviewed"
               for s in x["sources"] for i in s["rounds"])
    assert x["actual_publisher_html_captured"] == 0
    assert x["real_independent_human_labels"] == 0
    assert x["bulk_crawl_authorized"] is False
    root = tmp_path / "private"
    assert write_blank(root) == root
    assert json.loads(
        (root / "p22c2a_six_pricing_sources_BLANK.json").read_text()
    ) == x
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700
        assert all(f.stat().st_mode & 0o777 == 0o600 for f in root.iterdir())
    with pytest.raises(ValueError, match="NEW"):
        write_blank(root)


def test_without_permitted_original_html_all_36_denominators_remain_visible(tmp_path):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    result = evaluate(plan, ledger, tmp_path, source_id=SID, now=NOW)
    assert result["original_capture_state"] == "not_attempted"
    assert result["original_source_bytes_verified"] is False
    assert result["original_html_sha256"] is None
    assert result["source_round_census"]["all_original_source_rounds"] == 36
    assert result["source_round_census"]["pricing_original_source_rounds"] == 12
    assert result["source_round_census"][
        "pricing_round_capture_states"
    ] == {"not_attempted": 12}
    assert result["legacy_vs_row_window_coverage_NOT_ACCURACY"] is None
    assert "original_source_round_not_captured_or_policy_held" in result[
        "hold_reasons"
    ]
    assert result["price_accuracy_measured"] is False
    assert result["precision"] is result["recall"] is None
    assert result["live_zyte_row_window_crawl_authorized"] is False
    assert result["full_460_source_crawl_authorized"] is False
    assert result["advisor_fact_approvals"] == 0
    assert write_report(result, tmp_path / "output")
    with pytest.raises(ValueError, match="NEW"):
        write_report(result, tmp_path / "output")


def test_true_400_row_candidate_coverage_is_not_real_precision_or_recall(
        tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *args, **kw: pytest.fail("P22C2 must not contact publishers"),
    )
    plan, ledger, raw, _ = captured(tmp_path, count=400)
    report = evaluate(plan, ledger, tmp_path, source_id=SID, now=NOW)
    metrics = report["legacy_vs_row_window_coverage_NOT_ACCURACY"]
    assert metrics["same_original_html_sha256"] == hashlib.sha256(raw).hexdigest()
    assert metrics["baseline_table_rows_incomplete"] is True
    assert metrics["baseline_rows_examined"] == 249
    assert metrics["row_windows_planned"] == metrics["row_windows_validated"] == 7
    assert metrics["baseline_parser_table_physical_cell_positions"] == 249
    assert metrics["bounded_row_parser_table_physical_cell_positions"] == 400
    assert metrics["additional_parser_addressable_cell_positions"] == 151
    assert metrics["positions_previously_seen_but_missing_in_row_replay"] == 0
    assert metrics["unverified_parser_candidate_coverage_not_rate_recall"] is True
    assert "source_exceeds_p22a2_200_gold_labels_per_source_capacity" in (
        report["hold_reasons"]
    )
    assert report["readiness_for_third_identity_adjudicator"] is False
    assert report["blind_review"]["status"] == "not_supplied"
    assert report["publisher_origin_authenticated"] is False
    assert report["source_policy_independently_verified"] is False
    assert report["human_truth_independently_authenticated"] is False
    assert report["precision"] is report["recall"] is None
    assert report["price_accuracy_measured"] is False


def test_small_source_with_genuine_shaped_blind_packets_can_reach_adjudicator_gate(
        tmp_path):
    plan, ledger, _, _ = captured(tmp_path, count=6)
    a, b = human_pair(plan, ledger, tmp_path, 6)
    output = evaluate(
        plan, ledger, tmp_path, source_id=SID, reviewer_a=a,
        reviewer_b=b, now=NOW,
    )
    assert output["blind_review"]["status"] == (
        "agreed_two_reviewers_visible_page_inventory"
    )
    assert output["blind_review"]["original_source_gold_labels"] == 6
    assert output["blind_review"]["fully_scoped_gold_rates"] == 6
    assert output["legacy_vs_row_window_coverage_NOT_ACCURACY"][
        "bounded_row_parser_table_physical_cell_positions"
    ] == 6
    assert not output["hold_reasons"], output["hold_reasons"]
    assert output["readiness_for_third_identity_adjudicator"] is True
    assert output["next_operator_step"] == (
        "third_person_row_window_identity_review_required"
    )
    assert output["price_accuracy_measured"] is False
    assert output["advisor_fact_approvals"] == 0


def test_disputed_human_rate_remains_held_and_no_gold_metrics(tmp_path):
    plan, ledger, _, _ = captured(tmp_path, count=4)
    a, b = human_pair(plan, ledger, tmp_path, 4, disagreement=True)
    output = evaluate(
        plan, ledger, tmp_path, source_id=SID, reviewer_a=a,
        reviewer_b=b, now=NOW,
    )
    assert output["blind_review"]["status"] == (
        "held_two_reviewers_disagree_on_page_evidence"
    )
    assert "two_independent_complete_blind_reviews_not_agreed" in output[
        "hold_reasons"
    ]
    assert output["blind_review"]["original_source_gold_labels"] is None
    assert output["readiness_for_third_identity_adjudicator"] is False


def test_two_reviewer_files_are_required_together(tmp_path):
    plan, ledger, _, _ = captured(tmp_path, count=3)
    a, _ = human_pair(plan, ledger, tmp_path, 3)
    with pytest.raises(ValueError, match="A and B"):
        evaluate(
            plan, ledger, tmp_path, source_id=SID, reviewer_a=a,
            reviewer_b=None, now=NOW,
        )


def test_fake_human_amount_not_in_original_quote_is_rejected(tmp_path):
    plan, ledger, _, _ = captured(tmp_path, count=2)
    a, b = human_pair(plan, ledger, tmp_path, 2)
    for reviewer in (a, b):
        reviewer["source_reviews"][0]["evidence_inventory"][0][
            "reviewed_value"
        ]["amount_decimal"] = "9.99"
    with pytest.raises(ValueError, match="amount missing"):
        evaluate(
            plan, ledger, tmp_path, source_id=SID, reviewer_a=a,
            reviewer_b=b, now=NOW,
        )


@pytest.mark.parametrize("attack,match", [
    ("original_bytes_changed", "SHA-256"),
    ("source_url_changed", "reordered|altered|source"),
    ("original_snapshot_wrong_url", "URL"),
    ("policy_review_expired", "expired"),
    ("frozen_plan_reordered", "edited or stale"),
])
def test_captured_source_policy_and_byte_tampering_fail_closed(
        tmp_path, attack, match):
    plan, ledger, _, file = captured(tmp_path, count=2)
    if attack == "original_bytes_changed":
        file.write_bytes(b"altered" + file.read_bytes())
    elif attack == "source_url_changed":
        ledger["rows"][next(i for i,r in enumerate(ledger["rows"])
                           if r["source_id"] == SID)]["source_url"] = (
            "https://wrong.invalid/pricing"
        )
    elif attack == "original_snapshot_wrong_url":
        row = next(x for x in ledger["rows"] if x["source_id"] == SID)
        row["rounds"][0]["snapshot"]["final_url"] = (
            "https://wrong.invalid/pricing"
        )
    elif attack == "policy_review_expired":
        row = next(x for x in ledger["rows"] if x["source_id"] == SID)
        row["policy_review"]["expires_at_utc"] = at(-1)
    elif attack == "frozen_plan_reordered":
        plan["sources"].reverse()
    with pytest.raises(ValueError, match=match):
        evaluate(plan, ledger, tmp_path, source_id=SID, now=NOW)


@pytest.mark.parametrize("bad", [
    "not_in_original_source_study", "openai_api_pricing", "kiro_docs",
])
def test_source_cannot_be_replaced_with_unsampled_or_nonpricing_id(tmp_path, bad):
    plan, ledger, _, _ = captured(tmp_path, count=2)
    with pytest.raises(ValueError, match="frozen P20A pricing"):
        evaluate(plan, ledger, tmp_path, source_id=bad, now=NOW)


@pytest.mark.parametrize("bad", [0, 3, "1", True])
def test_round_must_be_exact_selected_frozen_one_or_two(tmp_path, bad):
    plan = frozen_plan()
    with pytest.raises(ValueError, match="round 1/2"):
        evaluate(
            plan, blank_ledger(plan), tmp_path, source_id=SID,
            round_no=bad, now=NOW,
        )


def test_physical_parser_cell_position_validator_is_strict():
    with pytest.raises(ValueError, match="cell coordinate"):
        _table_positions([{
            "evidence_kind": "structured_table",
            "table_id": "table-1", "row_index": True, "column_index": 2,
        }], baseline=True)
    with pytest.raises(ValueError, match="cell coordinate"):
        _table_positions([{
            "evidence_kind": "structured_table",
            "table_id": "table-1", "row_index": -1, "column_index": 2,
        }], baseline=True)


def test_second_round_capture_can_be_individually_evaluated(tmp_path):
    plan, ledger, raw, _ = captured(tmp_path, count=2, round_no=2)
    out = evaluate(plan, ledger, tmp_path, source_id=SID, round_no=2, now=NOW)
    assert out["round"] == 2
    assert out["original_html_sha256"] == hashlib.sha256(raw).hexdigest()
    assert out["source_round_census"]["pricing_round_capture_states"] == {
        "captured": 1, "not_attempted": 11,
    }
    assert out["price_accuracy_measured"] is False
