"""P22C2B end-to-end synthetic 400-row human pagination and third adjudication.

All 'human' data here is FAKE, generated inside tests ONLY to validate
contract integrity. This is NOT real blind human work or publisher HTML.
"""
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from scripts.accession_cross_category_html import blank_ledger, frozen_plan
from scripts.p22c2b_paginated_pricing_review import (
    MAX_LABELS_PER_SOURCE, _read_human, blank_reviewer, freeze_blind_bundle,
    reconcile_pages, write_blind_templates,
)
from scripts.p22c2b_adjudicate_pricing_rows import (
    blank_third, build_packet, score_packet, write_third, write_score,
)
from scripts.p22c_same_snapshot_replay import (
    _cell_sha, _main, _rows, _tables,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
SID = "deepseek_pricing"
PRICE = "USD 0.50 / 1M tokens"
NOTE = (
    "SYNTHETIC ONLY: an imaginary test-case reviewer follows full "
    "source-original row, page, and typed evidence protocol. NO actual "
    "publisher permission, human assessment, source-origin proof, or gold."
)


def at(days=0, minutes=0):
    return (NOW + timedelta(days=days, minutes=minutes)).isoformat()


def fake_html(count):
    return (
        "<html><head><title>DeepSeek API Pricing</title></head><body><main>"
        "<h1>DeepSeek API Pricing</h1>"
        "<p>All prices are in USD.</p><p>Region: Global</p>"
        "<p>Tier: Standard</p><p>Prices per 1M tokens.</p>"
        "<table><caption>USD per 1M tokens</caption>"
        "<thead><tr><th>Model</th><th>Input price</th></tr></thead>"
        "<tbody>" +
        "".join(
            f"<tr><th>DeepSeek Mock Model {i:04}</th>"
            f"<td>{PRICE}</td></tr>"
            for i in range(count)
        ) +
        "</tbody></table></main></body></html>"
    ).encode("utf-8")


def synthetic_capture(root, count=400):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    selected = next(s for s in ledger["rows"] if s["source_id"] == SID)
    host = urlsplit(selected["source_url"]).hostname
    selected["policy_review"] = {
        "decision": "operator_attested_manual_permitted",
        "reviewer": "Synthetic Publisher Policy Reviewer",
        "reviewed_at_utc": at(-3), "expires_at_utc": at(4),
        "ownership_url": selected["source_url"],
        "terms_url": f"https://{host}/terms",
        "robots_url": f"https://{host}/robots.txt",
        "retention_reviewed": True,
        "note": NOTE * 2,
    }
    raw = fake_html(count)
    digest = hashlib.sha256(raw).hexdigest()
    file = root / SID / f"original-{digest[:20]}.html"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(raw)
    selected["rounds"][0] = {
        "round": 1, "state": "captured",
        "capture_receipt_id": "SYNTHETIC-P22C2B-FIRST-REVIEW",
        "snapshot": {
            "file": str(file.relative_to(root)),
            "sha256": digest,
            "request_url": selected["source_url"],
            "final_url": selected["source_url"],
            "http_status": 200,
            "media_type": "text/html",
            "capture_method": "static_html",
            "captured_at_utc": at(-1),
            "capture_origin_review_status": "operator_supplied_unverified",
        },
    }
    return plan, ledger, raw, file


def reviews(bundle, raw, *, status="rates_labeled", amount="0.50"):
    reviewers = [blank_reviewer(bundle, "A"), blank_reviewer(bundle, "B")]
    _, main = _main(raw)
    tables = _tables(main)
    all_rows = [_rows(table) for table in tables]
    for rv, name in zip(reviewers, ("Synthetic Reviewer Alpha",
                                   "Synthetic Reviewer Beta")):
        rv["reviewer_id"] = name
        rv["independent_blind_review_attested"] = True
        for p, source_page in zip(rv["pages"], bundle["pages"]):
            p["review_completed"] = True
            p["reviewed_at_utc"] = at()
            p["review_note"] = NOTE
            for row in p["row_reviews"]:
                idx = row["original_row_index"]
                row["disposition"] = status
                for cell_review in row["cell_reviews"]:
                    if status == "rates_labeled":
                        cell_review["disposition"] = (
                            "rates_labeled"
                            if cell_review["original_column_index"] == 1
                            else "explicit_no_relevant_rate"
                        )
                    elif status == "ambiguous":
                        cell_review["disposition"] = (
                            "ambiguous"
                            if cell_review["original_column_index"] == 1
                            else "explicit_no_relevant_rate"
                        )
                    else:
                        cell_review["disposition"] = "explicit_no_relevant_rate"
                if status == "rates_labeled":
                    cell = all_rows[source_page["all_table_index"]][idx].xpath(
                        "./th|./td"
                    )[1]
                    row["labels"] = [{
                        "original_column_index": 1,
                        "original_cell_sha256": _cell_sha(cell),
                        "publisher_evidence_quote": PRICE,
                        "reviewed_value": {
                            "amount_decimal": amount, "currency": "USD",
                            "billing_unit": "per_million_tokens",
                            "price_dimension": "input",
                            "model_or_service": (
                                f"DeepSeek Mock Model {idx-1:04}"
                            ),
                            "region": "Global",
                            "region_applicability": "explicit",
                            "tier_or_plan": "Standard",
                            "tier_applicability": "explicit",
                            "conditions": None,
                        },
                        "review_note": NOTE,
                        "approved_for_advisor": False,
                    }]
    return reviewers


def make_third(packet):
    form = blank_third(packet)
    form["adjudicator_id"] = "Synthetic Third Independent"
    form["independent_of_reviewers_a_and_b_attested"] = True
    form["review_completed"] = True
    form["adjudicated_at_utc"] = at(minutes=10)
    form["source_wide_selected_table_disposition_note"] = NOTE
    pred_by_cell = {}
    for p in packet["predictions"]:
        key = (
            p["table_id"], p["original_row_index"],
            p["original_column_index"], p["original_cell_sha256"],
        )
        pred_by_cell.setdefault(key, []).append(p["prediction_id"])
    matched = set()
    for ref in packet["references"]:
        key = (
            ref["table_id"], ref["original_row_index"],
            ref["original_column_index"], ref["original_cell_sha256"],
        )
        available = [
            x for x in pred_by_cell.get(key, []) if x not in matched
        ]
        if available:
            pid = available[0]
            matched.add(pid)
            form["matches"].append({
                "prediction_id": pid,
                "reference_id": ref["reference_id"],
                "same_original_cell_note": NOTE,
            })
        else:
            form["missed_reference_ids"].append(ref["reference_id"])
    form["unmatched_prediction_ids"] = [
        p["prediction_id"] for p in packet["predictions"]
        if p["prediction_id"] not in matched
    ]
    return form


def test_blank_paginated_original_cell_tasks_are_blind_and_complete(tmp_path):
    plan, ledger, _, _ = synthetic_capture(tmp_path, 400)
    bundle, raw, row_plan = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    assert bundle["source_id"] == SID
    assert bundle["original_html_sha256"] == hashlib.sha256(raw).hexdigest()
    assert bundle["reviewed_original_data_rows"] == 400
    assert len(bundle["pages"]) == 7
    assert bundle["source_round_census"]["all_original_source_rounds"] == 36
    assert bundle["source_round_census"]["pricing_original_source_rounds"] == 12
    assert bundle["parser_predictions_in_blind_pages"] is False
    assert bundle["table_relevance_selection_from_parser_not_ground_truth"] is True
    assert bundle["approved_for_advisor"] is False
    assert len({page["page_id"] for page in bundle["pages"]}) == 7
    assert sum(len(page["original_rows"]) for page in bundle["pages"]) == 400
    for letter in ("A", "B"):
        template = blank_reviewer(bundle, letter)
        assert template["independent_blind_review_attested"] is False
        assert template["parser_predictions_seen_before_review"] is False
        assert all(page["review_completed"] is False for page in template["pages"])
        assert all(
            row["disposition"] == "not_reviewed" and row["labels"] == []
            and all(cell["disposition"] == "not_reviewed"
                    for cell in row["cell_reviews"])
            for page in template["pages"] for row in page["row_reviews"]
        )
        assert not any("observed_value" in json.dumps(x)
                       for x in template["pages"])
    root = tmp_path / "private-blank"
    assert write_blind_templates(bundle, root) == root
    assert len(list(root.iterdir())) == 3
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir())
    with pytest.raises(ValueError, match="NEW"):
        write_blind_templates(bundle, root)


def test_400_complete_original_rows_two_blind_humans_third_map_real_parser(
        tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: pytest.fail("No publisher HTTP in P22C2B"),
    )
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 400)
    bundle, original, row_plan = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw)
    agreement = reconcile_pages(bundle, original, row_plan, a, b, now=NOW)
    assert agreement["consensus_status"] == (
        "agreed_complete_selected_visible_table_row_census"
    )
    assert agreement["original_data_rows_accounted"] == 400
    assert agreement["pages_accounted"] == 7
    assert agreement["dual_agreed_human_rate_labels"] == 400
    assert agreement["human_independence_operator_attested_not_proven"] is True
    assert len(agreement["references"]) == 400
    assert len({x["reference_id"] for x in agreement["references"]}) == 400
    packet = build_packet(plan, ledger, tmp_path, bundle, a, b, now=NOW)
    assert len(packet["references"]) == 400
    assert packet["source_id"] == SID
    assert packet["parser_package_sha256"] == bundle["parser_package_sha256"]
    assert packet["source_round_census"]["all_original_source_rounds"] == 36
    assert packet["blind_review_preceded_parser_prediction_disclosure"] is True
    assert packet["vendor_catalog_completeness_verified"] is False
    assert packet["approved_for_advisor"] is False
    third = make_third(packet)
    # Every expected parser and every human rate has exactly one status.
    assert (len(third["matches"]) + len(third["unmatched_prediction_ids"])
            == len(packet["predictions"]))
    assert (len(third["matches"]) + len(third["missed_reference_ids"])
            == len(packet["references"]))
    report = score_packet(
        plan, ledger, tmp_path, bundle, a, b,
        packet, third, now=NOW + timedelta(minutes=20),
    )
    assert report["all_original_selected_data_rows_reviewed"] == 400
    assert report["blind_paginated_pages_reviewed"] == 7
    assert report["dual_human_agreed_references"] == 400
    assert report["tp"] + report["fn"] == 400
    assert report["strict_recall"] is not None
    assert report["production_accuracy_independently_verified"] is False
    assert report["source_sample_not_representative_177_or_460"] is True
    assert report["publisher_catalog_or_dynamic_cards_covered"] is False
    assert report["authorizes_live_zyte_or_bulk"] is False
    assert report["advisor_fact_approvals"] == 0
    assert report["new_zyte_jobs"] == report["new_publisher_requests"] == 0
    assert score_packet(
        plan, ledger, tmp_path, bundle, a, b,
        packet, third, now=NOW + timedelta(minutes=20),
    ) == report
    private = tmp_path / "third-prep"
    assert write_third(packet, private) == private
    assert len(list(private.iterdir())) == 2
    scored = tmp_path / "private-score"
    assert write_score(report, scored) == scored
    assert len(list(scored.iterdir())) == 1
    with pytest.raises(ValueError, match="NEW"):
        write_score(report, scored)


def test_missing_page_and_row_cannot_be_reconciled(tmp_path):
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 90)
    bundle, original, row_plan = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw)
    b["pages"].pop()
    with pytest.raises(ValueError, match="independent blind reviewer"):
        reconcile_pages(bundle, original, row_plan, a, b, now=NOW)
    a, b = reviews(bundle, raw)
    a["pages"][0]["row_reviews"].pop(3)
    with pytest.raises(ValueError, match="price page"):
        reconcile_pages(bundle, original, row_plan, a, b, now=NOW)


def test_each_original_cell_must_be_disposed_even_when_row_is_marked_done(tmp_path):
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 3)
    bundle, original, row_plan = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw)
    a["pages"][0]["row_reviews"][0]["cell_reviews"][0][
        "disposition"
    ] = "not_reviewed"
    with pytest.raises(ValueError, match="Every ORIGINAL cell"):
        reconcile_pages(bundle, original, row_plan, a, b, now=NOW)
    a, b = reviews(bundle, raw)
    a["pages"][0]["row_reviews"][0]["cell_reviews"][1][
        "disposition"
    ] = "explicit_no_relevant_rate"
    with pytest.raises(ValueError, match="Row and full original-cell"):
        reconcile_pages(bundle, original, row_plan, a, b, now=NOW)


def test_duplicate_label_and_cross_cell_sha_fail_closed(tmp_path):
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 4)
    bundle, original, row_plan = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw)
    a["pages"][0]["row_reviews"][0]["labels"].append(copy.deepcopy(
        a["pages"][0]["row_reviews"][0]["labels"][0]
    ))
    with pytest.raises(ValueError, match="Duplicate"):
        reconcile_pages(bundle, original, row_plan, a, b, now=NOW)
    a, b = reviews(bundle, raw)
    a["pages"][0]["row_reviews"][0]["labels"][0][
        "original_cell_sha256"
    ] = "0"*64
    with pytest.raises(ValueError, match="SHA-256"):
        reconcile_pages(bundle, original, row_plan, a, b, now=NOW)


@pytest.mark.parametrize("attack,part", [
    ("unknown_amount", "amount absent"),
    ("foreign_quote", "quote absent"),
    ("false_source", "independent blind reviewer"),
    ("bad_unit", "unit"),
    ("future_review", "future"),
    ("third_sees_predictions", "blind reviewer"),
])
def test_human_input_quote_scope_timing_and_blinding_fail_closed(
        tmp_path, attack, part):
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 3)
    bundle, original, row_plan = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw)
    label = a["pages"][0]["row_reviews"][0]["labels"][0]
    if attack == "unknown_amount":
        label["reviewed_value"]["amount_decimal"] = "9.99"
    elif attack == "foreign_quote":
        label["publisher_evidence_quote"] = "Never in this original cell 0.50"
    elif attack == "false_source":
        a["frozen_bundle_sha256"] = "0"*64
    elif attack == "bad_unit":
        label["reviewed_value"]["billing_unit"] = "per_unknown_units"
    elif attack == "future_review":
        a["pages"][0]["reviewed_at_utc"] = at(days=5)
    elif attack == "third_sees_predictions":
        a["parser_predictions_seen_before_review"] = True
    with pytest.raises(ValueError, match=part):
        reconcile_pages(bundle, original, row_plan, a, b, now=NOW)


def test_no_rate_row_and_ambiguous_row_are_handled_without_fake_gold(tmp_path):
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 3)
    bundle, original, row_plan = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw, status="explicit_no_relevant_rate")
    agreement = reconcile_pages(bundle, original, row_plan, a, b, now=NOW)
    assert agreement["dual_agreed_human_rate_labels"] == 0
    assert agreement["consensus_status"] == (
        "agreed_complete_selected_visible_table_row_census"
    )
    a, b = reviews(bundle, raw, status="ambiguous")
    outcome = reconcile_pages(bundle, original, row_plan, a, b, now=NOW)
    assert outcome["consensus_status"] == "held_ambiguous_source_rows"
    assert outcome["references"] == []
    with pytest.raises(ValueError, match="HELD|incomplete|ambiguous"):
        build_packet(plan, ledger, tmp_path, bundle, a, b, now=NOW)


def test_one_wrong_typed_rate_is_fp_and_fn_even_in_same_physical_cell(tmp_path):
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 1)
    bundle, _, _ = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    # Both reviewers independently assert an incorrect but canonical 1k unit
    # in this test; the physical original rate states 1M, and a third-person
    # same-cell match MUST not transform this into a correct rate.
    a, b = reviews(bundle, raw)
    for rv in (a, b):
        rv["pages"][0]["row_reviews"][0]["labels"][0][
            "reviewed_value"
        ]["billing_unit"] = "per_1k_tokens"
    packet = build_packet(plan, ledger, tmp_path, bundle, a, b, now=NOW)
    third = make_third(packet)
    assert len(third["matches"]) == 1
    score = score_packet(
        plan, ledger, tmp_path, bundle, a, b, packet, third,
        now=NOW + timedelta(minutes=20),
    )
    assert score["tp"] == 0
    assert score["fp"] == score["fn"] == 1
    assert score["wrong_typed_matched_rates_fp_and_fn"] == 1
    assert score["field_exact_fraction"]["billing_unit"] == 0


@pytest.mark.parametrize("attack,part", [
    ("duplicate_match", "Duplicate"),
    ("cross_cell", "exact original"),
    ("missing_prediction", "INCOMPLETE"),
    ("missing_reference", "INCOMPLETE"),
    ("different_third_packet", "CURRENT"),
    ("same_reviewer", "separate third"),
    ("no_attestation", "separate third"),
    ("third_precedes_a_b", "must follow"),
    ("future_third", "must follow"),
])
def test_third_human_requires_exact_full_disposition_and_identity(
        tmp_path, attack, part):
    plan, ledger, raw, _ = synthetic_capture(tmp_path, 2)
    bundle, _, _ = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw)
    packet = build_packet(plan, ledger, tmp_path, bundle, a, b, now=NOW)
    form = make_third(packet)
    if attack == "duplicate_match":
        form["matches"].append(copy.deepcopy(form["matches"][0]))
    elif attack == "cross_cell":
        form["matches"][0]["reference_id"] = form["matches"][1]["reference_id"]
    elif attack == "missing_prediction":
        form["matches"].pop()
    elif attack == "missing_reference":
        form["matches"].pop()
        form["unmatched_prediction_ids"].append(
            packet["predictions"][0]["prediction_id"]
        )
    elif attack == "different_third_packet":
        form["frozen_packet_sha256"] = "0"*64
    elif attack == "same_reviewer":
        form["adjudicator_id"] = a["reviewer_id"]
    elif attack == "no_attestation":
        form["independent_of_reviewers_a_and_b_attested"] = False
    elif attack == "third_precedes_a_b":
        form["adjudicated_at_utc"] = at(minutes=-10)
    elif attack == "future_third":
        form["adjudicated_at_utc"] = at(days=8)
    with pytest.raises(ValueError, match=part):
        score_packet(
            plan, ledger, tmp_path, bundle, a, b,
            packet, form, now=NOW + timedelta(minutes=20),
        )


def test_original_html_or_human_review_change_invalidates_packet(tmp_path):
    plan, ledger, raw, file = synthetic_capture(tmp_path, 2)
    bundle, _, _ = freeze_blind_bundle(
        plan, ledger, tmp_path, source_id=SID, now=NOW
    )
    a, b = reviews(bundle, raw)
    packet = build_packet(plan, ledger, tmp_path, bundle, a, b, now=NOW)
    third = make_third(packet)
    modified = copy.deepcopy(packet)
    modified["predictions"][0]["observed_value"]["normalized_amount_decimal"] = "999"
    with pytest.raises(ValueError, match="CURRENT"):
        score_packet(
            plan, ledger, tmp_path, bundle, a, b, modified, third,
            now=NOW + timedelta(minutes=20),
        )
    a["pages"][0]["review_note"] = NOTE + " altered after third saw packet"
    with pytest.raises(ValueError, match="CURRENT"):
        score_packet(
            plan, ledger, tmp_path, bundle, a, b, packet, third,
            now=NOW + timedelta(minutes=20),
        )
    file.write_bytes(file.read_bytes().replace(b"0.50", b"0.51", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        build_packet(plan, ledger, tmp_path, bundle, a, b, now=NOW)


def test_no_substitutions_and_no_unapproved_capture(tmp_path):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    with pytest.raises(ValueError, match="HELD"):
        freeze_blind_bundle(
            plan, ledger, tmp_path, source_id=SID, now=NOW,
        )
    with pytest.raises(ValueError, match="fixed P20A"):
        freeze_blind_bundle(
            plan, ledger, tmp_path, source_id="openai_api_pricing", now=NOW,
        )
    with pytest.raises(ValueError, match="round 1 or 2"):
        freeze_blind_bundle(
            plan, ledger, tmp_path, source_id=SID, round_no=3, now=NOW,
        )


def test_large_ratelabel_budget_cannot_be_bypassed():
    assert MAX_LABELS_PER_SOURCE >= 400
    assert MAX_LABELS_PER_SOURCE < 10000
