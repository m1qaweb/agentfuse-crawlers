"""P22A1 cross-category frozen real-evidence accession; synthetic-only fixtures.

All HTML here is INVENTED for testing. No real publisher is contacted,
no publisher access is approved, and no human labels are created.
"""
import asyncio
import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from scripts.accession_cross_category_html import (
    VERSION, EXPECTED, _digest, _load, blank_ledger,
    frozen_plan, prepare, stage, stage_data, validate_plan,
)


NOW = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)
SYNTHETIC_NOTE = (
    "SYNTHETIC ONLY. This does NOT authorize a real page fetch. "
    "Before any acquisition, a real reviewer must independently check "
    "publisher ownership, the exact URL, access terms and robots, "
    "product scope and private HTML retention for the intended research."
)


def _date(delta):
    return (NOW + delta).isoformat(timespec="seconds")


def _review(source):
    from urllib.parse import urlsplit
    host = urlsplit(source["source_url"]).hostname
    return {
        "decision": "operator_attested_manual_permitted",
        "reviewer": "Synthetic Evidence Reviewer",
        "reviewed_at_utc": _date(timedelta(days=-2)),
        "expires_at_utc": _date(timedelta(days=4)),
        "ownership_url": source["source_url"],
        "terms_url": "https://" + host + "/terms",
        "robots_url": "https://" + host + "/robots.txt",
        "retention_reviewed": True,
        "note": SYNTHETIC_NOTE,
    }


def _synthetic_html(category):
    if category == "documentation":
        return ("<html><main><h1>Fictional Product API Docs</h1>"
                "<p>These mock features and endpoints are not actual product facts. "
                "</p>" * 2 + "<section><h2>Authentication</h2><p>" +
                "Fake documentation for synthetic regression only. " * 25 +
                "</p></section></main></html>")
    if category == "pricing":
        return ("<html><main><h1>Imaginary pricing table</h1>"
                "<table><tr><th>Model</th><th>Input price</th>"
                "<th>Output price</th></tr><tr><td>Mock Model</td>"
                "<td>$1.50 per million tokens</td>"
                "<td>$2.50 per million tokens</td></tr></table></main></html>")
    return ("<html><main><h1>Fictional release history</h1>"
            "<article><h2>November 1, 2026</h2>"
            "<p>Imaginary version release, only synthetic test text.</p>"
            "</article></main></html>")


def _capture(ledger, root, index=0, *, round_no=1, receipt=None):
    source = ledger["rows"][index]
    source["policy_review"] = _review(source)
    html = _synthetic_html(source["category"])
    raw = html.encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    rel = f"{source['source_id']}/round_{round_no}/{source['source_id']}-{sha[:20]}.html"
    file = root / rel
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(raw)
    source["rounds"][round_no-1] = {
        "round": round_no,
        "state": "captured",
        "snapshot": {
            "file": rel,
            "sha256": sha,
            "request_url": source["source_url"],
            "final_url": source["source_url"],
            "http_status": 200,
            "media_type": "text/html",
            "capture_method": "static_html",
            "captured_at_utc": _date(
                timedelta(days=-1, hours=round_no)
            ),
            "capture_origin_review_status": "operator_supplied_unverified",
        },
        "capture_receipt_id": receipt or (
            f"SYNTHETIC-REC-{source['source_id']}-{round_no:02}"
        ),
    }
    return file


def test_plan_is_exact_18_sources_36_rounds_not_permissions():
    plan = frozen_plan()
    assert plan["selected_source_count"] == 18
    assert plan["source_round_denominator"] == 36
    assert plan["category_counts"] == EXPECTED
    assert plan["expected_manifest_sha256"] == manifest_sha256()
    assert plan["expected_source_registry_sha256"] == registry_revision_sha256()
    assert plan["publisher_permissions_granted"] == 0
    assert plan["real_human_gold_cases"] == 0
    assert plan["approved_for_advisor"] is False
    assert _digest({
        k: v for k, v in plan.items() if k != "plan_sha256"
    }) == plan["plan_sha256"]
    assert len({r["source_id"] for r in plan["sources"]}) == 18
    assert len({r["provider_label_unverified"]
                for r in plan["sources"]}) == 18
    assert [r["wave"] for r in plan["sources"]] == [1]*9+[2]*9


def test_private_prepare_writes_unprivileged_blank_18_source_template(tmp_path):
    root = tmp_path / "p22a1-template"
    assert prepare(root) == root
    plan = json.loads((root / "frozen_p20a_18_source_plan.json").read_text())
    ledger = json.loads((root / "source_policy_and_capture_ledger_BLANK.json").read_text())
    assert validate_plan(plan) == plan
    assert blank_ledger(plan) == ledger
    assert len(ledger["rows"]) == 18
    assert all(len(row["rounds"]) == 2 for row in ledger["rows"])
    assert all(entry["state"] == "not_attempted"
               for row in ledger["rows"] for entry in row["rounds"])
    assert ledger["human_gold_supplied"] is False
    assert ledger["approved_for_advisor"] is False
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700
        assert all(f.stat().st_mode & 0o777 == 0o600
                   for f in root.iterdir())
    with pytest.raises(ValueError, match="NEW"):
        prepare(root)


def test_blank_source_denominator_never_becomes_parser_false_negative(tmp_path):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    metrics, cases, reviewers = stage_data(plan, ledger, tmp_path, now=NOW)
    assert len(cases) == 36 and not reviewers
    assert metrics["source_denominator"] == 18
    assert metrics["source_round_denominator"] == 36
    assert metrics["source_rounds_with_valid_byte_sha256"] == 0
    assert metrics["sources_without_original_html"] == 18
    assert metrics["round_state_counts"] == {"not_attempted": 36}
    assert metrics["held_sources_are_not_parser_false_negatives"] is True
    assert metrics["accuracy_measurable"] is False
    assert metrics["human_gold_label_count"] == 0
    assert metrics["network_requests_performed"] == 0
    assert metrics["advisor_fact_approvals"] == 0
    root = tmp_path / "stage-private"
    assert stage(plan, ledger, tmp_path, root, now=NOW) == root
    for reviewer in ("A", "B"):
        obj = json.loads((root / f"reviewer_{reviewer}_BLANK.json").read_text())
        assert obj["reviewer_id"] is None
        assert obj["human_reviews_performed"] == 0
        assert obj["tasks"] == []


def test_simulated_original_html_for_all_three_categories_can_be_replayed_offline(
        tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: pytest.fail("P22A1 must NEVER contact a publisher"),
    )
    monkeypatch.setattr(
        urllib.request, "build_opener",
        lambda *a, **kw: pytest.fail("P22A1 must NEVER initiate HTTP"),
    )
    plan, ledger = frozen_plan(), blank_ledger(frozen_plan())
    idx = {
        category: next(i for i, row in enumerate(ledger["rows"])
                       if row["category"] == category)
        for category in EXPECTED
    }
    for category, i in idx.items():
        _capture(ledger, tmp_path, i, round_no=1)
    metrics, cases, reviewers = stage_data(plan, ledger, tmp_path, now=NOW)
    assert len(cases) == 36 and len(reviewers) == 3
    assert metrics["sources_with_original_html"] == 3
    assert metrics["sources_without_original_html"] == 15
    assert metrics["source_rounds_with_valid_byte_sha256"] == 3
    assert metrics["human_gold_label_count"] == 0
    assert {x["category"] for x in reviewers} == set(EXPECTED)
    assert all("parser_capture_status_unverified" not in x for x in reviewers)
    assert all("parser_evidence_candidates_not_gold" not in x for x in reviewers)
    assert all(x["parser_predictions_hidden"] is True for x in reviewers)
    assert all(x["human_gold_established"] is False for x in reviewers)
    assert all("raw_html_sha256" in x for x in reviewers)
    captured = [x for x in cases if x["state"] == "captured"]
    assert len(captured) == 3
    assert all(x["publisher_fact_verified"] is False
               and x["publisher_origin_independently_authenticated"] is False
               for x in captured)
    root = tmp_path / "stage-output"
    assert stage(plan, ledger, tmp_path, root, now=NOW) == root
    a = json.loads((root / "reviewer_A_BLANK.json").read_text())
    b = json.loads((root / "reviewer_B_BLANK.json").read_text())
    assert a["tasks"] == b["tasks"]
    assert all(x["evidence_inventory"] == [] for x in a["tasks"])
    assert "Fake documentation" not in (root / "reviewer_A_BLANK.json").read_text()


def test_two_snapshot_rounds_must_have_unique_receipts_and_increasing_time(tmp_path):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    _capture(ledger, tmp_path, 1, round_no=1)
    _capture(ledger, tmp_path, 1, round_no=2)
    metrics, cases, tasks = stage_data(plan, ledger, tmp_path, now=NOW)
    assert metrics["source_rounds_with_valid_byte_sha256"] == 2
    assert metrics["sources_with_original_html"] == 1
    assert len(tasks) == 2
    forged = deepcopy(ledger)
    forged["rows"][1]["rounds"][1]["capture_receipt_id"] = (
        forged["rows"][1]["rounds"][0]["capture_receipt_id"]
    )
    with pytest.raises(ValueError, match="unique"):
        stage_data(plan, forged, tmp_path, now=NOW)
    forged = deepcopy(ledger)
    forged["rows"][1]["rounds"][1]["snapshot"]["captured_at_utc"] = (
        forged["rows"][1]["rounds"][0]["snapshot"]["captured_at_utc"]
    )
    with pytest.raises(ValueError, match="later"):
        stage_data(plan, forged, tmp_path, now=NOW)


@pytest.mark.parametrize("tamper,expected", [
    ("missing_source", "18-source"),
    ("duplicate_id", "reordered"),
    ("swap_rows", "reordered"),
    ("source_url", "reordered"),
    ("wrong_round", "round"),
    ("missing_round", "reordered"),
    ("fake_gold", "18-source"),
    ("wrong_plan_sha", "18-source"),
    ("status_without_html", "smuggle"),
    ("receipt_without_html", "smuggle"),
    ("html_without_policy", "unreviewed"),
    ("denied_policy", "unreviewed"),
    ("no_retention", "retention"),
    ("future_policy", "future"),
    ("expired_policy", "expired"),
    ("tamper_original_bytes", "SHA-256"),
    ("wrong_snapshot_url", "URL"),
    ("wrong_method", "method"),
    ("wrong_capture_origin", "method"),
    ("unauthorized_approved_status", "method"),
    ("fake_source_permissions", "18-source"),
    ("traversal", "path"),
])
def test_invalid_or_forged_original_evidence_fails_closed(tmp_path, tamper, expected):
    plan = frozen_plan()
    ledger = blank_ledger(plan)
    file = _capture(ledger, tmp_path, index=1)
    row = ledger["rows"][1]
    a = row["rounds"][0]
    p = row["policy_review"]
    if tamper == "missing_source":
        ledger["rows"].pop()
    elif tamper == "duplicate_id":
        ledger["rows"][1]["source_id"] = ledger["rows"][0]["source_id"]
    elif tamper == "swap_rows":
        ledger["rows"][0], ledger["rows"][1] = ledger["rows"][1], ledger["rows"][0]
    elif tamper == "source_url":
        row["source_url"] = "https://attacker.invalid/source"
    elif tamper == "wrong_round":
        a["round"] = 2
    elif tamper == "missing_round":
        row["rounds"].pop()
    elif tamper == "fake_gold":
        ledger["human_gold_supplied"] = True
    elif tamper == "wrong_plan_sha":
        ledger["frozen_plan_sha256"] = "a"*64
    elif tamper == "status_without_html":
        a["state"] = "capture_failed"
    elif tamper == "receipt_without_html":
        a["state"] = "not_attempted"
    elif tamper == "html_without_policy":
        p["decision"] = "pending_review"
        for x in list(p):
            if x != "decision":
                p[x] = False if x == "retention_reviewed" else None
    elif tamper == "denied_policy":
        p["decision"] = "denied_by_terms"
    elif tamper == "no_retention":
        p["retention_reviewed"] = False
    elif tamper == "future_policy":
        p["reviewed_at_utc"] = _date(timedelta(days=15))
        p["expires_at_utc"] = _date(timedelta(days=20))
    elif tamper == "expired_policy":
        p["reviewed_at_utc"] = _date(timedelta(days=-8))
        p["expires_at_utc"] = _date(timedelta(days=-2))
    elif tamper == "tamper_original_bytes":
        file.write_text("not the original page", encoding="utf-8")
    elif tamper == "wrong_snapshot_url":
        a["snapshot"]["request_url"] = "https://hostile.invalid/pricing"
    elif tamper == "wrong_method":
        a["snapshot"]["capture_method"] = "headless_browser"
    elif tamper == "wrong_capture_origin":
        a["snapshot"]["capture_origin_review_status"] = "authenticated"
    elif tamper == "unauthorized_approved_status":
        a["snapshot"]["capture_origin_review_status"] = "verified_publisher"
    elif tamper == "fake_source_permissions":
        ledger["approved_for_advisor"] = True
    elif tamper == "traversal":
        a["snapshot"]["file"] = "../outside.html"
    with pytest.raises(ValueError, match=expected):
        stage_data(plan, ledger, tmp_path, now=NOW)


def test_policy_hold_is_recorded_without_changing_original_sample(tmp_path):
    plan, ledger = frozen_plan(), blank_ledger(frozen_plan())
    row = ledger["rows"][0]
    row["policy_review"] = _review(row)
    row["policy_review"]["decision"] = "denied_by_robots"
    row["rounds"][0]["state"] = "held_by_robots"
    row["rounds"][1]["state"] = "held_by_robots"
    report, cases, tasks = stage_data(plan, ledger, tmp_path, now=NOW)
    assert report["source_denominator"] == 18
    assert report["source_round_denominator"] == 36
    assert report["round_state_counts"]["held_by_robots"] == 2
    assert len(tasks) == 0
    assert any(x["source_id"] == row["source_id"] and x["state"] == "held_by_robots"
               for x in cases)
    assert report["accuracy_measurable"] is False


def test_file_symlinks_and_changed_manifests_are_refused(tmp_path):
    plan = frozen_plan()
    changed = deepcopy(plan)
    changed["sources"][0]["source_url"] = "https://different.invalid/"
    with pytest.raises(ValueError, match="edited or stale"):
        validate_plan(changed)
    ledger = blank_ledger(plan)
    file = _capture(ledger, tmp_path, 0)
    link = tmp_path / "link.html"
    try:
        link.symlink_to(file)
    except OSError:
        pytest.skip("Symlinks not supported on this runner")
    ledger["rows"][0]["rounds"][0]["snapshot"]["file"] = "link.html"
    with pytest.raises(ValueError, match="symlink"):
        stage_data(plan, ledger, tmp_path, now=NOW)


def test_stage_never_overwrites_a_private_ledger_or_outputs(tmp_path):
    plan, ledger = frozen_plan(), blank_ledger(frozen_plan())
    output = tmp_path / "replayed-output"
    stage(plan, ledger, tmp_path, output, now=NOW)
    assert len(list(output.iterdir())) == 4
    assert json.loads((output / "attrition_and_parser_diagnostics_NOT_GOLD.json").read_text())[
        "accuracy_measurable"
    ] is False
    with pytest.raises(ValueError, match="new private"):
        stage(plan, ledger, tmp_path, output, now=NOW)


def test_inputs_are_bounded_and_private_not_arbitrary_url(tmp_path):
    x = tmp_path / "oversize.json"
    x.write_bytes(b"[" + b" " * 201_000 + b"]")
    with pytest.raises(ValueError, match="oversized"):
        _load(x)
    with pytest.raises(ValueError):
        _load(tmp_path / "does_not_exist.json")
