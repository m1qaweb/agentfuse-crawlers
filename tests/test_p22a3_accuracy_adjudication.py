"""P22A3 conservative source-wide adjudication; ALL HTML is synthetic.

No publisher is contacted. Synthetic human files are deliberately forged
for regression tests only, never treated as real-world human gold.
"""
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import scripts.adjudicate_cross_category_accuracy as accuracy
from scripts.accession_cross_category_html import blank_ledger, frozen_plan
from scripts.reconcile_cross_category_reviews import (
    blank_reviewer, build_bundle,
)

NOW = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)
NOTE = (
    "Synthetic original page evidence only, used to test a conservative "
    "independent source-wide evaluation protocol without a real publisher."
)
PRICE_QUOTE = (
    "The example DeepSeek Model X inference input is USD 1.25 "
    "per million tokens for this demonstration."
)
DOC_QUOTE = (
    "The example Anthropic API authentication guide requires a "
    "bearer header on each fictional request."
)
RELEASE_QUOTE = (
    "This fictional Render release makes a new mock inference "
    "model endpoint available to demo testers."
)


def _at(days=0):
    return (NOW + timedelta(days=days)).isoformat()


def synthetic_html(category):
    if category == "pricing":
        return ("<html><main><h1>DeepSeek API Pricing</h1>"
                "<p>Private synthetic test input with mock, unverified pricing "
                "and no official model financial claim. " * 2 +
                "</p><table><tr><th>Model</th><th>Input price</th></tr>"
                "<tr><td>DeepSeek Model X</td><td>" + PRICE_QUOTE +
                "</td></tr></table></main></html>")
    if category == "documentation":
        return ("<html><main><h1>Anthropic API documentation</h1>"
                "<h2>Authentication</h2><p>" + DOC_QUOTE + " " +
                ("This illustrative authentication paragraph offers fictional "
                 "instructions about token creation and service usage. " * 12) +
                "</p></main></html>")
    return ("<html><main><h1>Render Changelog</h1>"
            "<article><h2 id='release-test-2026-11-01'>"
            "Mock Render Release 1.0</h2>"
            "<p>Published November 1, 2026</p>"
            "<p>" + RELEASE_QUOTE + "</p></article>"
            "</main></html>")


def make_captured(root, categories=("pricing", "documentation", "changelog")):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    known_names = {
        "pricing": "deepseek_pricing",
        "documentation": "anthropic_api_docs",
        "changelog": "render_changelog",
    }
    for category in categories:
        sid = known_names[category]
        source = next(x for x in ledger["rows"] if x["source_id"] == sid)
        from urllib.parse import urlsplit
        host = urlsplit(source["source_url"]).hostname
        source["policy_review"] = {
            "decision": "operator_attested_manual_permitted",
            "reviewer": "Synthetic Case Evidence Reviewer",
            "reviewed_at_utc": _at(days=-3),
            "expires_at_utc": _at(days=4),
            "ownership_url": source["source_url"],
            "terms_url": f"https://{host}/terms",
            "robots_url": f"https://{host}/robots.txt",
            "retention_reviewed": True,
            "note": NOTE + " Synthetic-only human policy review for unit tests.",
        }
        raw = synthetic_html(category).encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        relative = f"{category}/source_original_{sha[:15]}.html"
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        source["rounds"][0] = {
            "round": 1, "state": "captured",
            "capture_receipt_id": f"SYNTHETIC-TRUTH-ROUND-{category}-1",
            "snapshot": {
                "file": relative, "sha256": sha,
                "request_url": source["source_url"],
                "final_url": source["source_url"],
                "http_status": 200,
                "media_type": "text/html",
                "capture_method": "static_html",
                "captured_at_utc": _at(days=-1),
                "capture_origin_review_status": "operator_supplied_unverified",
            },
        }
    return plan, ledger


def fill_reviewers(plan, ledger, root):
    bundle, _, _ = build_bundle(plan, ledger, root, now=NOW)
    a, b = blank_reviewer(bundle, "A"), blank_reviewer(bundle, "B")
    for rv, name in ((a, "Synthetic Reviewer Alpha"), (b, "Synthetic Reviewer Beta")):
        rv["reviewer_id"] = name
        rv["independent_blind_review_attested"] = True
        for item in rv["source_reviews"]:
            category = item["category"]
            item["reviewed_at_utc"] = _at()
            item["page_scope"] = "sufficient_visible_static_page"
            item["whole_visible_page_review_complete"] = True
            item["exact_product_scope_reviewed"] = True
            item["no_relevant_evidence_observed"] = False
            item["review_note"] = NOTE
            if category == "pricing":
                value = {
                    "amount_decimal": "1.25", "currency": "USD",
                    "billing_unit": "per_million_tokens",
                    "price_dimension": "input",
                    "model_or_service": "DeepSeek Model X",
                    "region": None,
                    "region_applicability": "reviewed_not_applicable",
                    "tier_or_plan": None,
                    "tier_applicability": "reviewed_not_applicable",
                    "conditions": None,
                }
                quote = PRICE_QUOTE
            elif category == "documentation":
                value = {
                    "topic": "authentication", "support_state": "supported",
                    "capability_statement": (
                        "Synthetic Anthropic API authentication requires "
                        "a bearer header on each fictional request."),
                    "conditions": None,
                    "product_id": "Anthropic API",
                }
                quote = DOC_QUOTE
            else:
                value = {
                    "event_owner_url": item["source_url"] + "#release-test-2026-11-01",
                    "publisher_title": "Mock Render Release 1.0",
                    "version": "1.0", "date_status": "explicit_publication_day",
                    "published_at": "2026-11-01",
                    "date_evidence_text": "November 1, 2026",
                }
                quote = RELEASE_QUOTE
            item["evidence_inventory"] = [{
                "evidence_type": {
                    "pricing": "pricing_rate",
                    "documentation": "documentation_claim",
                    "changelog": "release_event",
                }[category],
                "publisher_evidence_quote": quote,
                "publisher_evidence_url": item["source_url"],
                "reviewed_value": value,
                "review_note": NOTE,
                "approved_for_advisor": False,
            }]
    return a, b


def fill_adjudicator(packet):
    form = accuracy.blank_adjudicator(packet)
    form["adjudicator_id"] = "Synthetic Independent Third"
    form["independent_of_a_and_b_attested"] = True
    cases = {x["case_id"]: x for x in packet["adjudication_cases"]}
    for item in form["cases"]:
        original = cases[item["case_id"]]
        item["review_completed"] = True
        item["adjudicated_at_utc"] = _at()
        item["adjudication_note"] = NOTE
        item["unmatched_prediction_ids"] = [
            x["prediction_id"] for x in original["predictions"]
        ]
        item["missed_reference_ids"] = [
            x["reference_id"] for x in original["references"]
        ]
    return form


def test_no_real_html_preserves_all_36_held_source_rounds(tmp_path):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    a, b = fill_reviewers(plan, ledger, tmp_path)
    packet = accuracy.build_packet(plan, ledger, tmp_path, a, b, now=NOW)
    assert len(packet["adjudication_cases"]) == 36
    assert packet["source_count_denominator"] == 18
    assert packet["source_round_denominator"] == 36
    assert all(x["score_status"] == "held" for x in packet["adjudication_cases"])
    assert accuracy.blank_adjudicator(packet)["cases"] == []
    adjudicator = fill_adjudicator(packet)
    report, scored, rounds = accuracy.score_packet(
        plan, ledger, tmp_path, a, b, packet, adjudicator, now=NOW,
    )
    assert not scored
    assert len(rounds) == 36
    assert report["overall"]["held_source_rounds"] == 36
    assert report["overall"]["adjudicated_source_rounds"] == 0
    assert report["overall"]["tp"] is report["overall"]["precision"] is None
    assert report["overall"]["recall"] is None
    assert report["representative_production_accuracy_verified"] is False
    assert report["network_requests_performed"] == 0
    assert report["advisor_fact_approvals"] == 0
    assert all(row["accuracy_state"] == "held_without_accuracy" for row in rounds)


def test_real_offline_extraction_using_synthetic_bytes_three_categories(
        tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *x, **kw: pytest.fail("P22A3 must never contact a publisher"),
    )
    plan, ledger = make_captured(tmp_path)
    a, b = fill_reviewers(plan, ledger, tmp_path)
    packet = accuracy.build_packet(plan, ledger, tmp_path, a, b, now=NOW)
    assert len(packet["adjudication_cases"]) == 36
    assert all(x["approved_for_advisor"] is False
               for x in packet["adjudication_cases"])
    assert packet["publisher_origin_independently_authenticated"] is False
    assert packet["parser_predictions_not_shown_to_blinded_reviewers"] is True
    for row in packet["adjudication_cases"]:
        if row["score_status"] == "requires_independent_adjudication":
            assert row["raw_html_sha256"] and row["references"]
            assert row["source_url"].startswith("https://")
            assert all(x["approved_for_advisor"] is False
                       for x in row["references"] + row["predictions"])
    form = fill_adjudicator(packet)
    assert len(form["cases"]) >= 1, (
        "At least one actual source-scoped synthetic replay must reach "
        "third-review adjudication, not just exercise held paths"
    )
    report, scored, rounds = accuracy.score_packet(
        plan, ledger, tmp_path, a, b, packet, form, now=NOW,
    )
    assert len(rounds) == 36
    assert len(scored) == len(form["cases"])
    assert report["overall"]["adjudicated_source_rounds"] == len(scored)
    assert report["overall"]["held_source_rounds"] == 36 - len(scored)
    assert report["documentation_feature_support_accuracy"] is None
    assert report["documentation_corpus_coverage_accuracy"] is None
    assert report["publisher_origin_independently_authenticated"] is False
    assert not report["representative_production_accuracy_verified"]
    assert report["advisor_fact_approvals"] == 0
    # Every review packet is stateless and unchanged if original bytes agree.
    assert packet == accuracy.build_packet(plan, ledger, tmp_path, a, b, now=NOW)
    saved = tmp_path / "private-adjudicator"
    assert accuracy.write_packet(packet, saved) == saved
    assert len(list(saved.iterdir())) == 2
    with pytest.raises(ValueError, match="NEW"):
        accuracy.write_packet(packet, saved)
    score_path = tmp_path / "private-results"
    assert accuracy.write_score((report, scored, rounds), score_path) == score_path
    assert len(list(score_path.iterdir())) == 3
    with pytest.raises(ValueError, match="NEW"):
        accuracy.write_score((report, scored, rounds), score_path)


def test_synthetic_html_tamper_changes_packet_or_fails_sha(tmp_path):
    plan, ledger = make_captured(tmp_path, categories=("documentation",))
    a, b = fill_reviewers(plan, ledger, tmp_path)
    packet = accuracy.build_packet(plan, ledger, tmp_path, a, b, now=NOW)
    mutated = copy.deepcopy(packet)
    mutated["packet_sha256"] = "0"*64
    with pytest.raises(ValueError, match="CURRENT"):
        accuracy.score_packet(
            plan, ledger, tmp_path, a, b, mutated, fill_adjudicator(packet), now=NOW,
        )
    raw_path = next((tmp_path / "documentation").iterdir())
    raw_path.write_text("altered original bytes", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        accuracy.build_packet(plan, ledger, tmp_path, a, b, now=NOW)


def test_zero_and_incomplete_price_predictions_never_auto_match_truth():
    gold = {
        "amount_decimal": "1.25", "currency": "USD",
        "billing_unit": "per_million_tokens", "price_dimension": "input",
        "model_or_service": "ExampleX", "region": None,
        "region_applicability": "reviewed_not_applicable",
        "tier_or_plan": None, "tier_applicability": "reviewed_not_applicable",
    }
    assert accuracy._pricing_gold_complete(gold)
    assert not accuracy._pricing_gold_complete({
        **gold, "region_applicability": "unknown"
    })
    fields = accuracy._price_field_exact({
        "normalized_amount_decimal": "1.2500", "currency": "USD",
        "billing_unit": "per_million_tokens", "price_dimension": "input",
        "model_or_service": "ExampleX", "region": None, "tier_or_plan": None,
    }, gold)
    assert all(fields.values())
    fields = accuracy._price_field_exact({
        "normalized_amount_decimal": "1.75", "currency": "USD",
        "billing_unit": "per_million_tokens", "price_dimension": "input",
        "model_or_service": "ExampleX", "region": None, "tier_or_plan": None,
    }, gold)
    assert fields["amount_decimal"] is False


def synthetic_packet():
    rows = []
    base = {
        "source_id": "deepseek_pricing",
        "source_url": "https://example.invalid/fake-pricing",
        "category": "pricing", "wave": 2, "round": 1,
        "original_capture_state": "captured",
        "raw_html_sha256": "a"*64,
        "captured_at_utc": _at(days=-1),
        "review_status": "agreed_two_reviewers_visible_page_inventory",
        "case_id": "case0001",
        "score_status": "requires_independent_adjudication",
        "hold_reasons": [],
        "unqualified_rate_observations": 0,
        "parser_package_sha256": "a"*64,
        "approved_for_advisor": False,
    }
    base["predictions"] = [{
        "prediction_id": "prediction-1", "category": "pricing",
        "prediction_identity": "model-cell-price",
        "physical_cell_hint": {
            "raw_parent_cell_text": PRICE_QUOTE, "table_id": "table-1",
            "row_index": 2, "column_index": 1,
        },
        "observed_value": {
            "normalized_amount_decimal": "1.25", "currency": "USD",
            "billing_unit": "per_million_tokens", "price_dimension": "input",
            "model_or_service": "DeepSeek Model X", "region": None,
            "tier_or_plan": None,
        },
        "approved_for_advisor": False,
    }]
    base["references"] = [{
        "reference_id": "reference-1",
        "category": "pricing", "evidence_ids": ["evidence-1"],
        "reviewed_value": {
            "amount_decimal": "1.25", "currency": "USD",
            "billing_unit": "per_million_tokens", "price_dimension": "input",
            "model_or_service": "DeepSeek Model X", "region": None,
            "region_applicability": "reviewed_not_applicable",
            "tier_or_plan": None, "tier_applicability": "reviewed_not_applicable",
            "conditions": None,
        },
        "publisher_evidence_quotes": [PRICE_QUOTE],
        "approved_for_advisor": False,
    }]
    rows.append(base)
    for i in range(35):
        category = ("pricing", "changelog", "documentation")[i % 3]
        rows.append({
            **{k: v for k, v in base.items()
               if k not in ("predictions", "references")},
            "source_id": f"held_{category}_{i}",
            "category": category,
            "case_id": f"held-{i}",
            "score_status": "held",
            "hold_reasons": ["no_original_html"],
            "predictions": [], "references": [],
            "original_capture_state": "not_attempted",
        })
    packet = {
        "schema_version": "1.0", "kind": accuracy.PACKET_KIND,
        "frozen_plan_sha256": "a"*64,
        "source_round_denominator": 36, "source_count_denominator": 18,
        "p22a2_review_report_sha256": "b"*64,
        "p22a2_task_bundle_sha256": "c"*64,
        "parser_package_sha256": "d"*64,
        "adjudication_cases": rows,
        "publisher_origin_independently_authenticated": False,
        "independent_review_real_world_truth_verified": False,
        "parser_predictions_not_shown_to_blinded_reviewers": True,
        "advisor_fact_approvals": 0, "approved_for_advisor": False,
    }
    packet["packet_sha256"] = accuracy._digest(packet)
    return packet


def score_fake_packet(monkeypatch, *, wrong_price=False):
    expected = synthetic_packet()
    if wrong_price:
        expected["adjudication_cases"][0]["predictions"][0][
            "observed_value"
        ]["normalized_amount_decimal"] = "2.50"
        expected["packet_sha256"] = accuracy._digest({
            k: v for k, v in expected.items() if k != "packet_sha256"
        })
    packet = copy.deepcopy(expected)
    # Isolate deterministic accounting and tamper handling; do not turn
    # the fixture mutable packet into the independently recomputed source.
    monkeypatch.setattr(accuracy, "build_packet",
                        lambda *args, **kwargs: copy.deepcopy(expected))
    plan = {"plan_sha256": packet["frozen_plan_sha256"]}
    a, b = (
        {"reviewer_id": "Synthetic First Reviewer",
         "source_reviews": [{"source_id": "deepseek_pricing", "round": 1,
                              "reviewed_at_utc": _at(days=-1)}]},
        {"reviewer_id": "Synthetic Second Reviewer",
         "source_reviews": [{"source_id": "deepseek_pricing", "round": 1,
                              "reviewed_at_utc": _at(days=-1)}]},
    )
    form = fill_adjudicator(packet)
    task = form["cases"][0]
    task["unmatched_prediction_ids"] = []
    task["missed_reference_ids"] = []
    task["matches"] = [{
        "prediction_id": "prediction-1", "reference_id": "reference-1",
        "same_visible_evidence_note": NOTE,
    }]
    return packet, form, lambda: accuracy.score_packet(
        plan, {}, None, a, b, packet, form, now=NOW,
    )


def test_valid_manual_cell_match_reports_one_strict_typed_rate_tp(monkeypatch):
    _, _, score = score_fake_packet(monkeypatch)
    report, cases, rounds = score()
    assert len(rounds) == 36
    assert report["overall"]["held_source_rounds"] == 35
    assert report["overall"]["adjudicated_source_rounds"] == 1
    assert report["by_category"]["pricing"]["tp"] == 1
    assert report["by_category"]["pricing"]["fp"] == 0
    assert report["by_category"]["pricing"]["fn"] == 0
    assert report["by_category"]["pricing"]["precision"] == 1
    assert report["by_category"]["pricing"]["recall"] == 1
    assert report["representative_production_accuracy_verified"] is False


def test_wrong_monetary_amount_is_fp_and_fn_not_a_tp(monkeypatch):
    packet, form, score = score_fake_packet(monkeypatch, wrong_price=True)
    report, _, _ = score()
    assert report["by_category"]["pricing"]["tp"] == 0
    assert report["by_category"]["pricing"]["fp"] == 1
    assert report["by_category"]["pricing"]["fn"] == 1
    assert report["by_category"]["pricing"]["precision"] == 0
    assert report["by_category"]["pricing"]["recall"] == 0
    assert report["by_category"]["pricing"]["field_exact_rate"][
        "amount_decimal"
    ] == 0


@pytest.mark.parametrize("attack,expected", [
    ("same_third_as_a", "Separate"),
    ("no_attestation", "Separate"),
    ("wrong_packet_hash", "Separate"),
    ("not_completed", "complete"),
    ("missing_case", "Missing"),
    ("wrong_case_id", "complete"),
    ("duplicate_match", "Duplicate"),
    ("missing_prediction_disposition", "INCOMPLETE"),
    ("missing_reference_disposition", "INCOMPLETE"),
    ("foreign_prediction_id", "Cross-source"),
    ("foreign_reference_id", "Cross-source"),
    ("invented_quote", "CURRENT"),
    ("future_clock", "future"),
    ("no_note", "Substantive"),
    ("tampered_frozen_packet", "CURRENT"),
])
def test_adjudicator_must_cover_every_genuine_identity(
        monkeypatch, attack, expected):
    packet, form, score = score_fake_packet(monkeypatch)
    task = form["cases"][0]
    if attack == "same_third_as_a":
        form["adjudicator_id"] = "Synthetic First Reviewer"
    elif attack == "no_attestation":
        form["independent_of_a_and_b_attested"] = False
    elif attack == "wrong_packet_hash":
        form["frozen_packet_sha256"] = "f"*64
    elif attack == "not_completed":
        task["review_completed"] = False
    elif attack == "missing_case":
        form["cases"].pop()
    elif attack == "wrong_case_id":
        task["case_id"] = "other-case-id"
    elif attack == "duplicate_match":
        task["matches"].append(copy.deepcopy(task["matches"][0]))
    elif attack == "missing_prediction_disposition":
        task["matches"] = []
    elif attack == "missing_reference_disposition":
        task["matches"] = []
        task["unmatched_prediction_ids"] = ["prediction-1"]
    elif attack == "foreign_prediction_id":
        task["matches"][0]["prediction_id"] = "foreign-id"
    elif attack == "foreign_reference_id":
        task["matches"][0]["reference_id"] = "foreign-id"
    elif attack == "invented_quote":
        packet["adjudication_cases"][0]["predictions"][0][
            "physical_cell_hint"
        ]["raw_parent_cell_text"] = "Never seen original rate number"
        packet["packet_sha256"] = accuracy._digest({
            k: v for k,v in packet.items() if k != "packet_sha256"
        })
        form["frozen_packet_sha256"] = packet["packet_sha256"]
    elif attack == "future_clock":
        task["adjudicated_at_utc"] = _at(days=10)
    elif attack == "no_note":
        task["adjudication_note"] = ""
    elif attack == "tampered_frozen_packet":
        packet["packet_sha256"] = "f"*64
    with pytest.raises(ValueError, match=expected):
        score()


def test_category_specific_match_guards():
    release = {
        "category": "changelog"
    }
    with pytest.raises(ValueError, match="EXACT"):
        accuracy._match_valid(
            release,
            {"observed_value": {
                "event_owner_url": "https://example.invalid/release#a"
            }},
            {"reviewed_value": {
                "event_owner_url": "https://example.invalid/release#b"
            }},
            NOTE,
        )
    docs = {"category": "documentation"}
    with pytest.raises(ValueError, match="topic"):
        accuracy._match_valid(
            docs, {"observed_value": {"topic": "authentication"}},
            {"reviewed_value": {"topic": "rate_limits"}}, NOTE,
        )
    quote = {"category": "pricing"}
    with pytest.raises(ValueError, match="bound"):
        accuracy._match_valid(
            quote, {"physical_cell_hint": {
                "raw_parent_cell_text": "Different mock rate row"
            }},
            {"publisher_evidence_quotes": [PRICE_QUOTE]}, NOTE,
        )


def test_docs_multiple_human_claims_same_topic_is_one_topic_reference():
    task = {"task_id": "test-1", "category": "documentation"}
    reference = {
        "evidence": [
            {"evidence_id": "a", "reviewed_value": {"topic": "authentication"},
             "publisher_evidence_quote": "First unique mock authentication quote"},
            {"evidence_id": "b", "reviewed_value": {"topic": "authentication"},
             "publisher_evidence_quote": "Second unique mock authentication quote"},
        ]
    }
    refs = accuracy._references(task, reference)
    assert len(refs) == 1
    assert len(refs[0]["evidence_ids"]) == 2



def test_human_pricing_rate_must_exist_as_number_in_original_quote():
    assert accuracy._quoted_original_amount(
        "Input price is USD 1.2500 per million tokens on this mock page.",
        "1.25",
    )
    assert accuracy._quoted_original_amount(
        "A fictional USD 1,250.50 rate per billing period.",
        "1250.5",
    )
    assert not accuracy._quoted_original_amount(
        "A fictional price is USD 125 per million tokens.",
        "1.25",
    )
    assert not accuracy._quoted_original_amount(
        "A fictional offer is free in this mock example.",
        "0",
    )
    assert not accuracy._quoted_original_amount(
        "Locale-specific amount is 1,25 EUR in this synthetic card.",
        "1.25",
    )
    with pytest.raises(ValueError, match="absent"):
        accuracy._references({
            "task_id": "mock-source-round-1", "category": "pricing",
        }, {"evidence": [{
            "evidence_id": "mock-case-1",
            "publisher_evidence_quote": (
                "Mock price is USD 7.25, not the claimed USD 1.25."
            ).replace("USD 1.25", "1.50 dollars"),
            "reviewed_value": {"amount_decimal": "1.25"},
        }]})


def test_adjudicator_timestamp_must_follow_both_blind_reviews(monkeypatch):
    packet, form, score = score_fake_packet(monkeypatch)
    form["cases"][0]["adjudicated_at_utc"] = _at(days=-2)
    with pytest.raises(ValueError, match="follow BOTH"):
        score()


def test_loader_rejects_oversized_original_review_json_and_symlink(tmp_path):
    huge = tmp_path / "too-big.json"
    huge.write_bytes(b"[" + b" " * 6_000_020 + b"]")
    with pytest.raises(ValueError, match="oversized"):
        accuracy._load(huge)
    other = tmp_path / "actual.json"
    other.write_text("{}")
    link = tmp_path / "fake-review.json"
    try:
        link.symlink_to(other)
    except OSError:
        pytest.skip("Symlink unavailable")
    with pytest.raises(ValueError, match="unsafe"):
        accuracy._load(link)
