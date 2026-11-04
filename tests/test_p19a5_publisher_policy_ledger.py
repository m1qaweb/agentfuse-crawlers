"""P19A5 synthetic source-specific publisher policy ledger and hard gates.

All publisher URLs are data pins. No publisher network requests or legal
review performed by these tests; affirmative rows are FAKE operator records.
"""
import hashlib
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.capture_release_html import capture_changelog_html
from scripts.prepare_release_pilot import (
    make_plan, stage_captures,
)
from scripts.review_release_pilot_policy import (
    DECISION_ELIGIBLE, LEDGER_KIND, policy_template, require_batch_capture_review,
    validate_policy_ledger, main as policy_cli,
)

SELECTION = "p19a5-synthetic-private-selection-not-legal-review-2026"
HOLDOUT = "p19a5-synthetic-private-holdout-not-legal-review-2026"
NOTE = (
    "SYNTHETIC operator attestation only: independently inspected supposed "
    "publisher scope, ownership, robots path, access rules, and whether "
    "privately retained original page bytes are permitted for a bounded "
    "manual validation request; no real publisher was consulted."
)
KNOWN = {s["id"]: s for s in load_sources()}


def _reviewed(plan, *, blocked=None):
    block = set(blocked or [])
    ledger = policy_template(plan)
    for review in ledger["reviews"]:
        sid = review["source_id"]
        src = KNOWN[sid]
        prefix = "https://" + __import__(
            "urllib.parse", fromlist=["urlsplit"]
        ).urlsplit(src["url"]).netloc
        review.update({
            "reviewer_id": "Synthetic Policy Reviewer",
            "reviewed_at_utc": "2026-11-03T12:00:00Z",
            "ownership_evidence_url": src["url"],
            "access_policy_evidence_url": prefix + "/terms",
            "scope_and_retention_note": NOTE,
        })
        if sid in block:
            review["decision"] = "deferred_policy_unclear"
        else:
            review["decision"] = DECISION_ELIGIBLE
            review["robots_review_attested"] = True
            review["lawful_private_retention_attested"] = True
            review["publisher_scope_attested"] = True
    return ledger


def _fake_original(sid):
    return (
        "<!doctype html><html><head><title>Unverified example release "
        "history</title></head><body><main><h1>Invented changelog</h1>"
        '<article><h2 id="entry-1">Fictional Model 7.1.0 released</h2>'
        '<time datetime="2026-10-01">2026-10-01</time><p>'
        "Completely fictional release coverage test for source " + sid +
        ": invented developer model evaluation and documentation details, "
        "system administration behavior, migration notes, reference "
        "compatibility and safe service configuration.</p></article>"
        "</main></body></html>"
    ).encode("utf-8")


def _write(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _fake_capture_waves(directory, plan, receipt):
    """Write original-HTML-shaped *synthetic* P19A1 receipts, never web GET."""
    directory.mkdir()
    for wave in plan["batches"]:
        folder = directory / wave["batch_id"]
        folder.mkdir()
        manifest_rows, audit_rows = [], []
        for source in wave["sources"]:
            sid = source["source_id"]
            raw = _fake_original(sid)
            digest = hashlib.sha256(raw).hexdigest()
            name = sid + "-" + digest[:20] + ".html"
            (folder / name).write_bytes(raw)
            manifest_rows.append({
                "source_id": sid,
                "snapshot": {
                    "file": name, "sha256": digest,
                    "request_url": source["source_url"],
                    "final_url": source["source_url"],
                    "http_status": 200, "media_type": "text/html",
                    "capture_method": "static_html",
                    "captured_at_utc": "2026-11-03T13:00:00Z",
                    "capture_origin_review_status":
                        "operator_supplied_unverified",
                },
            })
            audit_rows.append({
                "source_id": sid,
                "official_source_url": source["source_url"],
                "raw_html_sha256": digest,
                "raw_html_bytes": len(raw),
                "robots_url": source["robots_url"],
                "robots_sha256": hashlib.sha256(
                    ("synthetic-robots:" + sid).encode()
                ).hexdigest(),
                "robots_allowed_for_agent": True,
                "publisher_origin_independently_authenticated": False,
                "published_release_facts_independently_verified": False,
                "approved_for_advisor": False,
            })
        _write(folder / "frozen_release_snapshots.json", {
            "schema_version": "1.0",
            "kind": "frozen_original_changelog_html_manifest",
            "expected_manifest_sha256": manifest_sha256(),
            "expected_source_registry_sha256": registry_revision_sha256(),
            "approved_for_advisor": False,
            "snapshots": manifest_rows,
        })
        _write(folder / "capture_audit.json", {
            "schema_version": "1.0",
            "kind": "p19a1_manual_original_changelog_capture_audit",
            "capture_count": len(manifest_rows),
            "source_ids": wave["source_ids"],
            "publisher_policy_review_operator_attested": True,
            "publisher_policy_independently_verified": False,
            "policy_review_note": NOTE,
            "source_specific_policy_review_receipt_sha256":
                receipt["receipt_sha256"],
            "source_specific_policy_review_completed": True,
            "robots_checks": len(manifest_rows),
            "network_requests_performed": len(manifest_rows) * 2,
            "receipts": audit_rows,
            "new_spider_sources": 0,
            "zyte_jobs_created": 0,
            "automatic_schedules_enabled": False,
            "new_release_alerts": 0,
            "advisor_approved_facts": 0,
            "approved_for_advisor": False,
        })


def test_new_policy_ledger_is_unfilled_no_permission(tmp_path):
    plan = make_plan(selection_key=SELECTION, size=20)
    ledger = policy_template(plan)
    assert ledger["kind"] == LEDGER_KIND
    assert ledger["pilot_plan_sha256"] == plan["plan_sha256"]
    assert len(ledger["reviews"]) == 20
    assert len(set(x["source_id"] for x in ledger["reviews"])) == 20
    assert all(x["decision"] == "pending_review" for x in ledger["reviews"])
    assert all(x["reviewer_id"] is None for x in ledger["reviews"])
    report = validate_policy_ledger(plan, ledger, selection_key=SELECTION)
    assert report["source_count"] == 20
    assert report["operator_attested_attempt_eligible_count"] == 0
    assert report["held_or_pending_source_count"] == 20
    assert report["decision_counts"]["pending_review"] == 20
    assert report["all_frozen_sources_operator_attested_eligible"] is False
    assert not report["publisher_terms_and_robots_independently_verified"]
    assert report["network_requests_performed"] == 0
    assert report["new_source_permissions"] == 0
    assert report["approved_for_advisor"] is False
    assert SELECTION not in json.dumps(report)


def test_reviews_exact_wave_capture_ready_only_when_all_sources_have_own_evidence():
    plan = make_plan(selection_key=SELECTION, size=15)
    reviewed = _reviewed(plan)
    report = validate_policy_ledger(plan, reviewed, selection_key=SELECTION)
    assert report["operator_attested_attempt_eligible_count"] == 15
    assert report["held_or_pending_source_count"] == 0
    assert report["all_frozen_sources_operator_attested_eligible"] is True
    assert all(row["all_batch_sources_operator_attested_eligible"]
               for row in report["batches"])
    wave = plan["batches"][0]["source_ids"]
    attempt = require_batch_capture_review(
        plan, reviewed, source_ids=wave, selection_key=SELECTION,
    )
    assert attempt["receipt_sha256"] == report["receipt_sha256"]
    # Partial captures remain constrained to this one original wave
    # and never grant permission to an unreviewed or blocked source.
    subset_receipt = require_batch_capture_review(
        plan, reviewed, source_ids=wave[:-1], selection_key=SELECTION,
    )
    assert subset_receipt["receipt_sha256"] == report["receipt_sha256"]
    with pytest.raises(ValueError, match="exactly match"):
        require_batch_capture_review(
            plan, reviewed, source_ids=list(reversed(wave)),
            selection_key=SELECTION,
        )


def test_a_blocked_publisher_is_not_ever_swapped_or_dropped():
    plan = make_plan(selection_key=SELECTION, size=20)
    blocked = plan["batches"][0]["source_ids"][1]
    ledger = _reviewed(plan, blocked={blocked})
    result = validate_policy_ledger(plan, ledger, selection_key=SELECTION)
    assert result["source_count"] == 20
    assert result["held_or_pending_source_count"] == 1
    assert result["operator_attested_attempt_eligible_count"] == 19
    assert result["decision_counts"]["deferred_policy_unclear"] == 1
    wave = result["batches"][0]
    assert blocked in wave["held_source_ids"]
    assert wave["all_batch_sources_operator_attested_eligible"] is False
    assert len(wave["planned_source_ids"]) == 5
    assert set(wave["operator_attested_capture_eligible_source_ids"]).isdisjoint(
        wave["held_source_ids"]
    )
    with pytest.raises(ValueError, match="held"):
        require_batch_capture_review(
            plan, ledger, source_ids=plan["batches"][0]["source_ids"],
            selection_key=SELECTION,
        )


@pytest.mark.parametrize("mutate", [
    lambda x: x["reviews"][0].update(approved_for_advisor=True),
    lambda x: x.update(approved_for_advisor=True),
    lambda x: x.update(new_source_permissions=1),
    lambda x: x.update(pilot_plan_sha256="0" * 64),
    lambda x: x["reviews"][0].update(
        source_url="https://hijacked.example/changelog"
    ),
    lambda x: x["reviews"][0].update(
        robots_url="https://hijacked.example/robots.txt"
    ),
    lambda x: x["reviews"][0].update(ownership_evidence_url="http://unsafe.example"),
    lambda x: x["reviews"][0].update(
        ownership_evidence_url="https://attacker.example/legal"
    ),
    lambda x: x["reviews"][0].update(
        access_policy_evidence_url="https://site.example/terms?token=secret"
    ),
    lambda x: x["reviews"][0].update(
        reviewer_id="REPLACE_THIS_REVIEWER"
    ),
    lambda x: x["reviews"][0].update(
        reviewed_at_utc="2099-01-01T10:00:00Z"
    ),
    lambda x: x["reviews"][0].update(
        publisher_scope_attested=False
    ),
    lambda x: x["reviews"][0].update(
        lawful_private_retention_attested=False
    ),
    lambda x: x["reviews"][0].update(
        robots_review_attested=False
    ),
    lambda x: x["reviews"][0].update(
        scope_and_retention_note="does not count"
    ),
    lambda x: x["reviews"][0].update(
        reviewed_at_utc="2026-11-03"
    ),
])
def test_forged_or_incomplete_per_source_attestation_fails_closed(mutate):
    plan = make_plan(selection_key=SELECTION, size=15)
    ledger = _reviewed(plan)
    mutate(ledger)
    with pytest.raises(ValueError):
        validate_policy_ledger(plan, ledger, selection_key=SELECTION)


def test_duplicate_unknown_or_stale_review_rows_are_rejected():
    plan = make_plan(selection_key=SELECTION, size=15)
    ledger = _reviewed(plan)
    for change in (
        lambda x: x["reviews"].append(deepcopy(x["reviews"][0])),
        lambda x: x["reviews"][0].update(source_id="nonexistent_changelog"),
        lambda x: x["reviews"].pop(),
        lambda x: x["reviews"][0].update(unknown_field="ignore"),
    ):
        altered = deepcopy(ledger)
        change(altered)
        with pytest.raises(ValueError):
            validate_policy_ledger(plan, altered, selection_key=SELECTION)
    with pytest.raises(ValueError, match="Frozen pilot plan"):
        validate_policy_ledger(
            plan, ledger, selection_key="wrong-selection-key-for-this-frozen-plan-and-provider",
        )


def test_pending_may_not_have_implicit_permissions_or_labels():
    plan = make_plan(selection_key=SELECTION, size=15)
    ledger = policy_template(plan)
    ledger["reviews"][0]["robots_review_attested"] = True
    with pytest.raises(ValueError, match="Unreviewed source"):
        validate_policy_ledger(plan, ledger, selection_key=SELECTION)
    ledger = policy_template(plan)
    ledger["reviews"][0]["scope_and_retention_note"] = NOTE
    with pytest.raises(ValueError, match="Unreviewed source"):
        validate_policy_ledger(plan, ledger, selection_key=SELECTION)


def test_blocked_review_does_not_keep_partially_affirmative_permission():
    plan = make_plan(selection_key=SELECTION, size=15)
    sid = plan["batches"][0]["source_ids"][0]
    ledger = _reviewed(plan, blocked={sid})
    ledger["reviews"][0]["robots_review_attested"] = True
    with pytest.raises(ValueError, match="Blocked/deferred"):
        validate_policy_ledger(plan, ledger, selection_key=SELECTION)


def test_real_capture_api_rejects_missing_policy_before_network(tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "build_opener",
        lambda *_a: pytest.fail("No robots or publisher GET before per-source policy"),
    )
    sid = "openai_api_changelog"
    with pytest.raises(ValueError, match="requires source-specific policy"):
        capture_changelog_html(
            [sid], tmp_path / "capture",
            policy_review_note=NOTE,
        )
    assert not (tmp_path / "capture").exists()


def test_offline_pilot_staging_binds_exact_policy_receipt_sha(tmp_path):
    plan = make_plan(selection_key=SELECTION, size=15)
    ledger = _reviewed(plan)
    receipt = validate_policy_ledger(plan, ledger, selection_key=SELECTION)
    captures_root = tmp_path / "captures"
    _fake_capture_waves(captures_root, plan, receipt)
    out = tmp_path / "review_stage"
    report = stage_captures(
        plan, captures_root, out, selection_key=SELECTION,
        split_key=HOLDOUT, source_policy_preflight=receipt,
    )
    assert report["selected_source_count"] == 15
    assert report["missing_filled_reviewer_files"] == 6
    assert report["human_review_completed"] is False
    assert report["advisor_fact_approvals"] == 0
    assert report["network_requests_performed"] == 0
    staged_audit = json.loads((out / "pilot_staging_audit.json").read_text())
    assert staged_audit["source_specific_policy_review_receipt_sha256"] == (
        receipt["receipt_sha256"]
    )


def test_staging_refuses_mixed_or_stale_policy_receipts(tmp_path):
    plan = make_plan(selection_key=SELECTION, size=15)
    receipt = validate_policy_ledger(
        plan, _reviewed(plan), selection_key=SELECTION,
    )
    root = tmp_path / "captures"
    _fake_capture_waves(root, plan, receipt)
    audit_path = root / "wave_02" / "capture_audit.json"
    audit = json.loads(audit_path.read_text())
    audit["source_specific_policy_review_receipt_sha256"] = "b" * 64
    _write(audit_path, audit)
    with pytest.raises(ValueError, match="exact pilot policy"):
        stage_captures(
            plan, root, tmp_path / "blocked",
            selection_key=SELECTION, split_key=HOLDOUT,
            source_policy_preflight=receipt,
        )
    assert not (tmp_path / "blocked").exists()


def test_staging_blocks_if_any_selected_publisher_policy_is_held(tmp_path):
    plan = make_plan(selection_key=SELECTION, size=15)
    one = plan["batches"][-1]["source_ids"][0]
    receipt = validate_policy_ledger(
        plan, _reviewed(plan, blocked={one}), selection_key=SELECTION,
    )
    root = tmp_path / "captures"
    _fake_capture_waves(root, plan, receipt)
    with pytest.raises(ValueError, match="full source-policy preflight"):
        stage_captures(
            plan, root, tmp_path / "blocked",
            selection_key=SELECTION, split_key=HOLDOUT,
            source_policy_preflight=receipt,
        )


def test_offline_policy_cli_creates_unfilled_private_packet(tmp_path,
                                                            monkeypatch, capsys):
    plan = make_plan(selection_key=SELECTION, size=15)
    source = tmp_path / "plan.json"
    _write(source, plan)
    monkeypatch.setenv("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY", SELECTION)
    monkeypatch.setattr(sys, "argv", [
        "review_release_pilot_policy",
        "--prepare", "--pilot-plan", str(source),
        "--out-dir", str(tmp_path / "preflight"),
    ])
    policy_cli()
    summary = json.loads(capsys.readouterr().out)
    assert summary["network_requests_performed"] == 0
    assert summary["operator_attested_attempt_eligible_count"] == 0
    saved = json.loads(
        (tmp_path / "preflight" / "source_policy_review_template.json"
        ).read_text()
    )
    assert len(saved["reviews"]) == 15
    assert all(x["decision"] == "pending_review" for x in saved["reviews"])
    if os.name == "posix":
        assert (tmp_path / "preflight").stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match="NEW"):
        policy_cli()
