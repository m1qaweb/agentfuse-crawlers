"""P22A2 source-wide A/B human evidence consensus — synthetic-only tests.

No actual publisher rights or verified model prices/dates/claims exist here.
Exercise private original HTML, source IDs, quote uniqueness, release owners,
temporal review, disagreements, visible-page negatives and output safety.
"""
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.accession_cross_category_html import blank_ledger, frozen_plan
from scripts.reconcile_cross_category_reviews import (
    _documentation_scope, _rate_scope, _read_json,
    blank_reviewer, build_bundle, reconcile, write_consensus,
    write_templates,
)

NOW = datetime(2026, 11, 4, 22, 0, tzinfo=timezone.utc)
NOTE = (
    "Synthetic human evaluation of the entire visible static HTML source "
    "with explicitly scoped quote-backed evidence, no parser predictions "
    "and no publisher-origin or access-policy grant."
)
PRICE_QUOTE = (
    "A fictional MockModel inference input rate is USD 1.25 "
    "per million tokens for a test workload."
)
RELEASE_QUOTE = (
    "A mock first-party release adds a fictional model endpoint "
    "in this test document."
)
DOC_QUOTE = (
    "Synthetic authentication requires the example bearer token "
    "header on every request."
)


def _at(days=0, hours=0):
    return (NOW + timedelta(days=days, hours=hours)).isoformat()


def _html(category):
    if category == "pricing":
        return (
            "<html><main><h1>Fake pricing — test only</h1>"
            "<table><tr><th>Model</th><th>Input rate</th></tr>"
            "<tr><td>MockModel</td><td>" + PRICE_QUOTE +
            "</td></tr></table></main></html>"
        )
    if category == "changelog":
        return (
            "<html><main><h1>Fake changelog</h1>"
            "<article><h3 id='release-test-1'>Synthetic Release 1.0</h3>"
            "<p>Published 2026-11-01</p><p>" + RELEASE_QUOTE +
            "</p></article></main></html>"
        )
    return (
        "<html><main><h1>Fake documentation</h1>"
        "<section><h2>Authentication</h2><p>" + DOC_QUOTE +
        "</p></section></main></html>"
    )


def _policy(source):
    from urllib.parse import urlsplit
    host = urlsplit(source["source_url"]).hostname
    return {
        "decision": "operator_attested_manual_permitted",
        "reviewer": "Synthetic Reference Researcher",
        "reviewed_at_utc": _at(days=-3),
        "expires_at_utc": _at(days=3),
        "ownership_url": source["source_url"],
        "terms_url": f"https://{host}/terms",
        "robots_url": f"https://{host}/robots.txt",
        "retention_reviewed": True,
        "note": NOTE + " Operator-supplied only; no real publisher review was made.",
    }


def make_captured(plan, root, *, categories=("pricing", "changelog", "documentation")):
    ledger = blank_ledger(plan)
    for category in categories:
        row = next(r for r in ledger["rows"] if r["category"] == category)
        row["policy_review"] = _policy(row)
        content = _html(category).encode("utf-8")
        sha = hashlib.sha256(content).hexdigest()
        file = root / category / f"{row['source_id']}-{sha[:20]}.html"
        file.parent.mkdir(exist_ok=True, parents=True)
        file.write_bytes(content)
        row["rounds"][0] = {
            "round": 1, "state": "captured",
            "capture_receipt_id": f"SYNTHETIC-ORIGINAL-{category}-FIRST",
            "snapshot": {
                "file": str(file.relative_to(root)),
                "sha256": sha, "request_url": row["source_url"],
                "final_url": row["source_url"], "http_status": 200,
                "media_type": "text/html", "capture_method": "static_html",
                "captured_at_utc": _at(days=-1),
                "capture_origin_review_status": "operator_supplied_unverified",
            },
        }
    return ledger


def _rate_value(*, currency="USD"):
    return {
        "amount_decimal": "1.250", "currency": currency,
        "billing_unit": "per_million_tokens",
        "price_dimension": "input",
        "model_or_service": "MockModel",
        "region": None, "region_applicability": "unknown",
        "tier_or_plan": None, "tier_applicability": "unknown",
        "conditions": None,
    }


def _release_value(source_url):
    return {
        "event_owner_url": source_url + "#release-test-1",
        "publisher_title": "Synthetic Release 1.0",
        "version": "1.0",
        "date_status": "explicit_publication_day",
        "published_at": "2026-11-01",
        "date_evidence_text": "2026-11-01",
    }


def _docs_value():
    return {
        "topic": "authentication", "support_state": "supported",
        "capability_statement":
            "Mock authentication uses a fictional bearer token header.",
        "conditions": None, "product_id": "synthetic_docs_product",
    }


def evidence(task):
    category = task["category"]
    quote = {
        "pricing": PRICE_QUOTE, "changelog": RELEASE_QUOTE,
        "documentation": DOC_QUOTE,
    }[category]
    value = {
        "pricing": _rate_value(),
        "changelog": _release_value(task["source_url"]),
        "documentation": _docs_value(),
    }[category]
    label_type = {
        "pricing": "pricing_rate", "changelog": "release_event",
        "documentation": "documentation_claim",
    }[category]
    return {
        "evidence_type": label_type,
        "publisher_evidence_quote": quote,
        "publisher_evidence_url": task["source_url"],
        "reviewed_value": value,
        "review_note": NOTE,
        "approved_for_advisor": False,
    }


def completed_pair(plan, ledger, root, *, categories=None):
    bundle, _, _ = build_bundle(plan, ledger, root, now=NOW)
    a = blank_reviewer(bundle, "A")
    b = blank_reviewer(bundle, "B")
    for reviewer, name in ((a, "Independent Human A"), (b, "Independent Human B")):
        reviewer["reviewer_id"] = name
        reviewer["independent_blind_review_attested"] = True
        for task in reviewer["source_reviews"]:
            if categories is not None and task["category"] not in categories:
                continue
            task["reviewed_at_utc"] = _at()
            task["page_scope"] = "sufficient_visible_static_page"
            task["whole_visible_page_review_complete"] = True
            task["exact_product_scope_reviewed"] = True
            task["no_relevant_evidence_observed"] = False
            task["review_note"] = NOTE
            task["evidence_inventory"] = [evidence(task)]
    return bundle, a, b


def test_no_html_keeps_36_frozen_denominator_and_zero_accuracy(tmp_path):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    bundle, metrics, sources = build_bundle(plan, ledger, tmp_path, now=NOW)
    assert len(sources) == 36
    assert bundle["source_round_denominator"] == 36
    assert bundle["human_review_tasks"] == []
    assert bundle["parser_predictions_in_reviewer_tasks"] is False
    assert metrics["sources_without_original_html"] == 18
    a, b = blank_reviewer(bundle, "A"), blank_reviewer(bundle, "B")
    a["reviewer_id"] = "Independent First Reviewer"
    b["reviewer_id"] = "Independent Second Reviewer"
    a["independent_blind_review_attested"] = True
    b["independent_blind_review_attested"] = True
    report, statuses, consensus = reconcile(plan, ledger, tmp_path, a, b, now=NOW)
    assert len(statuses) == 36 and consensus == []
    assert report["original_html_rounds"] == 0
    assert report["agreed_visible_page_census_rounds"] == 0
    assert report["human_agreed_quote_bound_evidence_labels"] == 0
    assert report["precision"] is None and report["recall"] is None
    assert report["false_negatives"] is None
    assert not report["accuracy_measurable"]
    assert report["new_network_requests"] == report["new_zyte_jobs"] == 0
    assert report["advisor_fact_approvals"] == 0


def test_actual_synthetic_byte_snapshots_and_two_independent_reviewers_agree(
        tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: pytest.fail("Publisher network access forbidden in P22A2"),
    )
    monkeypatch.setattr(
        urllib.request, "build_opener",
        lambda *a, **kw: pytest.fail("No publisher opener may be constructed"),
    )
    plan = frozen_plan()
    ledger = make_captured(plan, tmp_path)
    bundle, a, b = completed_pair(plan, ledger, tmp_path)
    assert len(bundle["human_review_tasks"]) == 3
    assert all("parser_capture_status_unverified" not in t
               for t in bundle["human_review_tasks"])
    assert all("observed_price" not in t and "predicted_release" not in t
               for t in bundle["human_review_tasks"])
    report, statuses, consensus = reconcile(plan, ledger, tmp_path, a, b, now=NOW)
    assert len(statuses) == 36
    assert len(consensus) == 3
    assert report["source_denominator"] == 18
    assert report["source_round_denominator"] == 36
    assert report["original_html_rounds"] == 3
    assert report["agreed_visible_page_census_rounds"] == 3
    assert report["human_agreed_quote_bound_evidence_labels"] == 3
    assert report["disputed_visible_page_census_rounds"] == 0
    assert report["precision"] is report["recall"] is None
    assert not report["accuracy_measurable"]
    assert report["publisher_origin_independently_authenticated"] is False
    assert all(record["approved_for_advisor"] is False for record in consensus)
    assert {x["category"] for x in consensus} == {
        "pricing", "changelog", "documentation",
    }
    assert next(x for x in consensus if x["category"] == "pricing")[
        "evidence"
    ][0]["reviewed_value"]["amount_decimal"] == "1.25"
    private = tmp_path / "private-consensus"
    assert write_consensus((report, statuses, consensus), private) == private
    assert len(list(private.iterdir())) == 3
    assert "verified_publisher_facts" in (
        private / "agreed_quote_grounded_evidence_PRIVATE.json"
    ).read_text()
    with pytest.raises(ValueError, match="NEW"):
        write_consensus((report, statuses, consensus), private)


def test_prepare_templates_safe_and_distinct_without_leaking_parser_candidates(tmp_path):
    plan = frozen_plan()
    ledger = make_captured(plan, tmp_path, categories=("pricing",))
    bundle, _, _ = build_bundle(plan, ledger, tmp_path, now=NOW)
    root = tmp_path / "blinded"
    assert write_templates(bundle, root) == root
    a = _read_json(root / "independent_reviewer_A_BLANK.json")
    b = _read_json(root / "independent_reviewer_B_BLANK.json")
    assert len(a["source_reviews"]) == len(b["source_reviews"]) == 1
    assert a["reviewer_id"] is b["reviewer_id"] is None
    assert not a["independent_blind_review_attested"]
    assert all(not x["whole_visible_page_review_complete"]
               and x["evidence_inventory"] == []
               and x["parser_predictions_hidden"] is True
               for x in a["source_reviews"])
    assert "parser_evidence_candidates_not_gold" not in json.dumps(a)
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700
        assert all(f.stat().st_mode & 0o777 == 0o600 for f in root.iterdir())


def test_agreed_whole_visible_page_with_zero_evidence_not_global_no_price(tmp_path):
    plan, ledger = frozen_plan(), blank_ledger(frozen_plan())
    # No HTML means there can be no valid negative.
    _, a, b = completed_pair(plan, ledger, tmp_path)
    report, _, consensus = reconcile(plan, ledger, tmp_path, a, b, now=NOW)
    assert report["agreed_visible_page_census_rounds"] == 0
    assert consensus == []
    ledger = make_captured(plan, tmp_path, categories=("pricing",))
    _, a, b = completed_pair(plan, ledger, tmp_path)
    for reviewer in (a, b):
        row = reviewer["source_reviews"][0]
        row["evidence_inventory"] = []
        row["no_relevant_evidence_observed"] = True
    report, _, consensus = reconcile(plan, ledger, tmp_path, a, b, now=NOW)
    assert report["agreed_visible_page_census_rounds"] == 1
    assert report["human_agreed_quote_bound_evidence_labels"] == 0
    assert consensus[0]["visible_page_no_relevant_evidence"] is True
    assert report["false_negatives"] is None


def test_disagreements_hold_quote_grounded_reference_not_zero_accuracy(tmp_path):
    plan = frozen_plan()
    ledger = make_captured(plan, tmp_path, categories=("pricing",))
    _, a, b = completed_pair(plan, ledger, tmp_path)
    b["source_reviews"][0]["evidence_inventory"][0]["reviewed_value"][
        "currency"
    ] = None
    report, statuses, consensus = reconcile(plan, ledger, tmp_path, a, b, now=NOW)
    assert consensus == []
    assert report["disputed_visible_page_census_rounds"] == 1
    assert report["agreed_visible_page_census_rounds"] == 0
    assert report["human_agreed_quote_bound_evidence_labels"] == 0
    assert report["accuracy_measurable"] is False
    assert next(x for x in statuses if x["state"] == "captured")[
        "dual_review_status"
    ] == "held_two_reviewers_disagree_on_page_evidence"


@pytest.mark.parametrize("attack,expected", [
    ("same_reviewer", "distinct"),
    ("no_attestation", "attested"),
    ("wrong_bundle_sha", "attested"),
    ("wrong_plan_sha", "attested"),
    ("wrong_category", "Forged"),
    ("wrong_snapshot_sha", "Forged"),
    ("swap_review_letters", "attested"),
    ("missing_task", "attested"),
    ("inject_parser_prediction", "Forged"),
    ("approved_fact", "Forged"),
    ("missing_quote", "absent"),
    ("duplicate_quote_labels", "repeated"),
    ("wrong_source_url", "cross-owned"),
    ("bad_rate_amount", "decimal"),
    ("invented_region", "cannot invent"),
    ("currency_lowercase", "ISO"),
    ("expired_capture", "review predates"),
    ("claim_future_review", "future"),
    ("no_census_full_page", "Complete source review"),
    ("pretend_no_evidence", "Empty-page"),
    ("unknown_topic", "topic"),
    ("unknown_support", "topic"),
    ("fake_release_owner", "release owner"),
    ("wrong_release_date", "Day"),
    ("no_release_year", "Day"),
])
def test_untrusted_publisher_claims_and_blind_reviewer_tampering_fail_closed(
        tmp_path, attack, expected):
    plan = frozen_plan()
    ledger = make_captured(plan, tmp_path)
    _, a, b = completed_pair(plan, ledger, tmp_path)
    target = next(
        x for x in a["source_reviews"] if x["category"] == "pricing"
    )
    if attack == "same_reviewer":
        b["reviewer_id"] = a["reviewer_id"]
    elif attack == "no_attestation":
        a["independent_blind_review_attested"] = False
    elif attack == "wrong_bundle_sha":
        a["task_bundle_sha256"] = "0"*64
    elif attack == "wrong_plan_sha":
        a["frozen_plan_sha256"] = "a"*64
    elif attack == "wrong_category":
        target["category"] = "changelog"
    elif attack == "wrong_snapshot_sha":
        target["raw_html_sha256"] = "b"*64
    elif attack == "swap_review_letters":
        a["reviewer_letter"] = "B"
    elif attack == "missing_task":
        a["source_reviews"].pop()
    elif attack == "inject_parser_prediction":
        target["parser_prediction"] = {"price": 3}
    elif attack == "approved_fact":
        target["approved_for_advisor"] = True
    elif attack == "missing_quote":
        target["evidence_inventory"][0]["publisher_evidence_quote"] = (
            "Nonexistent unique publisher text with no source HTML matching"
        )
    elif attack == "duplicate_quote_labels":
        target["evidence_inventory"].append(
            copy.deepcopy(target["evidence_inventory"][0])
        )
    elif attack == "wrong_source_url":
        target["evidence_inventory"][0]["publisher_evidence_url"] = (
            "https://other.invalid/pricing"
        )
    elif attack == "bad_rate_amount":
        target["evidence_inventory"][0]["reviewed_value"][
            "amount_decimal"
        ] = "NaN"
    elif attack == "invented_region":
        target["evidence_inventory"][0]["reviewed_value"][
            "region"
        ] = "Global"
    elif attack == "currency_lowercase":
        target["evidence_inventory"][0]["reviewed_value"][
            "currency"
        ] = "usd"
    elif attack == "expired_capture":
        target["reviewed_at_utc"] = _at(days=-2)
    elif attack == "claim_future_review":
        target["reviewed_at_utc"] = _at(days=20)
    elif attack == "no_census_full_page":
        target["whole_visible_page_review_complete"] = False
    elif attack == "pretend_no_evidence":
        target["no_relevant_evidence_observed"] = True
    elif attack in {"unknown_topic", "unknown_support"}:
        docs = next(x for x in a["source_reviews"]
                    if x["category"] == "documentation")
        value = docs["evidence_inventory"][0]["reviewed_value"]
        value["topic" if attack == "unknown_topic" else "support_state"] = "fake"
    elif attack in {"fake_release_owner", "wrong_release_date", "no_release_year"}:
        release = next(x for x in a["source_reviews"]
                       if x["category"] == "changelog")
        value = release["evidence_inventory"][0]["reviewed_value"]
        if attack == "fake_release_owner":
            value["event_owner_url"] = release["source_url"] + "#nonexistent"
        if attack == "wrong_release_date":
            value["published_at"] = "2026-11-02"
        if attack == "no_release_year":
            value["date_evidence_text"] = "November 1"
    with pytest.raises(ValueError, match=expected):
        reconcile(plan, ledger, tmp_path, a, b, now=NOW)


def test_quote_in_hidden_script_does_not_qualify_original_visible_page(tmp_path):
    plan = frozen_plan()
    ledger = make_captured(plan, tmp_path, categories=("pricing",))
    snapshot = ledger["rows"][
        next(i for i, row in enumerate(ledger["rows"]) if row["category"] == "pricing")
    ]["rounds"][0]["snapshot"]
    file = tmp_path / snapshot["file"]
    page = (
        "<html><main><h1>Fake site</h1><p>No prices displayed.</p></main>"
        "<script>" + PRICE_QUOTE + "</script></html>"
    )
    file.write_text(page, encoding="utf-8")
    snapshot["sha256"] = hashlib.sha256(page.encode()).hexdigest()
    _, a, b = completed_pair(plan, ledger, tmp_path)
    with pytest.raises(ValueError, match="absent"):
        reconcile(plan, ledger, tmp_path, a, b, now=NOW)


def test_incomplete_js_shell_review_cannot_be_reclassified_as_no_price(tmp_path):
    plan = frozen_plan()
    ledger = make_captured(plan, tmp_path, categories=("pricing",))
    _, a, b = completed_pair(plan, ledger, tmp_path)
    for reviewer in (a, b):
        task = reviewer["source_reviews"][0]
        task["page_scope"] = "insufficient_js_or_challenge"
        task["whole_visible_page_review_complete"] = False
        task["exact_product_scope_reviewed"] = False
        task["no_relevant_evidence_observed"] = None
        task["evidence_inventory"] = []
    report, statuses, consensus = reconcile(plan, ledger, tmp_path, a, b, now=NOW)
    assert not consensus
    assert report["not_reviewed_or_insufficient_page_rounds"] == 1
    assert report["false_negatives"] is None
    assert next(x for x in statuses if x["state"] == "captured")[
        "dual_review_status"
    ] == "held_incomplete_blind_page_review"


def test_rate_scope_unknown_never_becomes_global_default():
    v = _rate_value(currency=None)
    reviewed = _rate_scope("pricing", v)
    assert reviewed["currency"] is None
    assert reviewed["region_applicability"] == "unknown"
    assert reviewed["tier_applicability"] == "unknown"
    assert reviewed["region"] is reviewed["tier_or_plan"] is None
    with pytest.raises(ValueError, match="Explicit"):
        reviewed = copy.deepcopy(v)
        reviewed["region_applicability"] = "explicit"
        _rate_scope("pricing", reviewed)
    with pytest.raises(ValueError, match="Conditional"):
        reviewed = copy.deepcopy(v)
        reviewed["tier_applicability"] = "conditional"
        _rate_scope("pricing", reviewed)


def test_docs_conditional_and_unknown_status_are_not_facts():
    source = _docs_value()
    source["support_state"] = "conditional"
    source["conditions"] = "Provider explicitly requires conditional access."
    assert _documentation_scope(source)["support_state"] == "conditional"
    source["conditions"] = None
    with pytest.raises(ValueError, match="Conditional"):
        _documentation_scope(source)
    source = _docs_value()
    source["support_state"] = "unknown"
    assert _documentation_scope(source)["support_state"] == "unknown"


def test_changed_original_html_sha_and_missing_frozen_source_are_rejected(tmp_path):
    plan = frozen_plan()
    ledger = make_captured(plan, tmp_path, categories=("pricing",))
    _, a, b = completed_pair(plan, ledger, tmp_path)
    file = next((tmp_path / "pricing").iterdir())
    file.write_text("An entirely different document", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        reconcile(plan, ledger, tmp_path, a, b, now=NOW)
    copy_plan = copy.deepcopy(plan)
    copy_plan["sources"].pop()
    with pytest.raises(ValueError, match="edited or stale"):
        build_bundle(copy_plan, ledger, tmp_path, now=NOW)


def test_real_reviewer_file_loader_enforces_private_bounds(tmp_path):
    bad = tmp_path / "reviewed.json"
    bad.write_bytes(b"{" + b" " * 6_001_000 + b"}")
    with pytest.raises(ValueError, match="oversized"):
        _read_json(bad)
    with pytest.raises(ValueError):
        _read_json(tmp_path / "missing.json")
