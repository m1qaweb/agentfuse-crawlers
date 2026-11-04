"""P19A6 synthetic tests: capture partial sources without sample attrition bias.

NO real HTML is fetched, legal access checked or human labels generated
outside these invented, strictly synthetic regression fixtures.
"""
import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from scripts.prepare_release_pilot import make_plan
from scripts.review_release_pilot_policy import (
    DECISION_ELIGIBLE, policy_template, require_batch_capture_review,
    validate_policy_ledger,
)
from scripts.stage_release_pilot_attrition import (
    score_partial_pilot, stage_partial_pilot, main as pilot_cli,
)

SELECT = "synthetic-p19a6-frozen-selection-key-not-production"
SPLIT = "synthetic-p19a6-gold-split-key-not-production"
NOTE = (
    "This is an entirely synthetic per-publisher access research and "
    "private retention note for testing. No actual terms or legal rights "
    "were reviewed. No real publisher has been accessed in this test."
)
CAPTURED = "2026-11-03T13:00:00Z"
REVIEWED = "2026-11-03T14:00:00Z"
DAY = "2026-11-02"
TITLE = "Imaginary test release v1.0.0"
BODY = (
    "This entirely fictional release announces synthetic developer "
    "API behavior, software configuration changes, migration details, "
    "reference model examples and improvements in system reliability. "
    "No actual vendor announced any of these fabricated release notes."
)
REVIEW_NOTE = (
    "I checked the sole fictional release owner anchor, its visible "
    "calendar date and the full publisher card directly in the synthetic HTML."
)
CENSUS_NOTE = (
    "This original HTML has one fictional release card and no other "
    "visible release owners or omitted releases; all content is fake."
)


def _html(sid):
    text = (TITLE + " " + DAY + " " + BODY + " " + sid)
    html = (
        "<!doctype html><html><head><title>Imaginary changelog page</title>"
        "</head><body><main><h1>Imaginary changelog</h1>"
        '<article><header><h2 id="r1">' + TITLE +
        '</h2><time datetime="' + DAY + 'T10:00:00Z">' + DAY +
        "</time></header><p>" + BODY + " " + sid +
        "</p></article></main></body></html>"
    )
    return html.encode("utf-8"), text


def _write(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _prepare(tmp_path, *, blocked=(), missing=(), size=15):
    plan = make_plan(selection_key=SELECT, size=size, batch_size=5)
    ledger = policy_template(plan)
    blocked = set(blocked)
    for review in ledger["reviews"]:
        sid = review["source_id"]
        domain = urlsplit(review["source_url"]).netloc
        review.update({
            "reviewer_id": "Synthetic Policy Reviewer",
            "reviewed_at_utc": "2026-11-03T12:00:00Z",
            "ownership_evidence_url": review["source_url"],
            "access_policy_evidence_url": "https://" + domain + "/terms",
            "scope_and_retention_note": NOTE,
        })
        if sid in blocked:
            review["decision"] = "deferred_policy_unclear"
        else:
            review["decision"] = DECISION_ELIGIBLE
            review["robots_review_attested"] = True
            review["lawful_private_retention_attested"] = True
            review["publisher_scope_attested"] = True
    receipt = validate_policy_ledger(plan, ledger, selection_key=SELECT)
    root = tmp_path / "capture"
    root.mkdir()
    for wave in plan["batches"]:
        folder = root / wave["batch_id"]
        folder.mkdir()
        for source in wave["sources"]:
            sid = source["source_id"]
            if sid in blocked or sid in missing:
                continue
            publisher = folder / sid
            publisher.mkdir()
            raw, _ = _html(sid)
            sha = hashlib.sha256(raw).hexdigest()
            name = sid + "-" + sha[:20] + ".html"
            (publisher / name).write_bytes(raw)
            _write(publisher / "frozen_release_snapshots.json", {
                "schema_version": "1.0",
                "kind": "frozen_original_changelog_html_manifest",
                "expected_manifest_sha256": manifest_sha256(),
                "expected_source_registry_sha256": registry_revision_sha256(),
                "approved_for_advisor": False,
                "snapshots": [{
                    "source_id": sid,
                    "snapshot": {
                        "file": name,
                        "sha256": sha,
                        "request_url": source["source_url"],
                        "final_url": source["source_url"],
                        "http_status": 200, "media_type": "text/html",
                        "capture_method": "static_html",
                        "captured_at_utc": CAPTURED,
                        "capture_origin_review_status":
                            "operator_supplied_unverified",
                    },
                }],
            })
            _write(publisher / "capture_audit.json", {
                "schema_version": "1.0",
                "kind": "p19a1_manual_original_changelog_capture_audit",
                "capture_count": 1,
                "source_ids": [sid],
                "publisher_policy_review_operator_attested": True,
                "publisher_policy_independently_verified": False,
                "policy_review_note": NOTE,
                "source_specific_policy_review_receipt_sha256":
                    receipt["receipt_sha256"],
                "source_specific_policy_review_completed": True,
                "robots_checks": 1,
                "network_requests_performed": 2,
                "receipts": [{
                    "source_id": sid,
                    "official_source_url": source["source_url"],
                    "raw_html_sha256": sha,
                    "raw_html_bytes": len(raw),
                    "robots_url": source["robots_url"],
                    "robots_sha256": hashlib.sha256(
                        ("invented robots: " + sid).encode()
                    ).hexdigest(),
                    "robots_allowed_for_agent": True,
                    "publisher_origin_independently_authenticated": False,
                    "published_release_facts_independently_verified": False,
                    "approved_for_advisor": False,
                }],
                "new_spider_sources": 0,
                "zyte_jobs_created": 0,
                "automatic_schedules_enabled": False,
                "new_release_alerts": 0,
                "advisor_approved_facts": 0,
                "approved_for_advisor": False,
            })
    return plan, ledger, root


def _stage(plan, ledger, captures, dest):
    return stage_partial_pilot(
        plan, ledger, captures, dest,
        selection_key=SELECT, split_key=SPLIT,
    )


def _fill_reviews(staged):
    cohort = json.loads((staged / "captured_subset_review_cohort.json").read_text())
    for batch in cohort["batches"]:
        packet = json.loads((staged / batch["blind_packet"]).read_text())
        for label in ("a", "b"):
            path = staged / batch["batch_id"] / "census" / (
                "reviewer_" + label + "_template.json"
            )
            template = json.loads(path.read_text())
            template["reviewer_id"] = "Fictional Reviewer " + label.upper()
            template["independent_blind_review_attested"] = True
            for rev, task in zip(template["source_reviews"], packet["tasks"]):
                sid = task["source_id"]
                rev.update({
                    "reviewed_full_visible_html": True,
                    "event_list_complete": True,
                    "unattributed_release_count": 0,
                    "release_count_observed": 1,
                    "census_note": CENSUS_NOTE,
                    "reviewed_at_utc": REVIEWED,
                    "events": [{
                        "owner_url": task["source_url"] + "#r1",
                        "publisher_title": TITLE,
                        "version": "1.0.0",
                        "date_status": "explicit_publication_day",
                        "published_at": DAY,
                        "date_evidence_text": DAY,
                        "publisher_evidence_quote": (
                            TITLE + " " + DAY + " " + BODY
                        ),
                        "review_note": REVIEW_NOTE,
                        "approved_for_advisor": False,
                    }],
                })
            _write(staged / batch["batch_id"] / "census" / (
                "reviewer_" + label + "_filled.json"
            ), template)


def test_capture_subset_permission_only_for_ordered_eligible_ids():
    plan = make_plan(selection_key=SELECT, size=15)
    ledger = policy_template(plan)
    sid = plan["batches"][0]["source_ids"][0]
    # Pending reviews never permit a real GET, even for one publisher.
    with pytest.raises(ValueError, match="held"):
        require_batch_capture_review(
            plan, ledger, source_ids=[sid], selection_key=SELECT,
        )
    with pytest.raises(ValueError, match="ordered"):
        require_batch_capture_review(
            plan, ledger, source_ids=[
                plan["batches"][0]["source_ids"][1],
                plan["batches"][1]["source_ids"][0],
            ], selection_key=SELECT,
        )


def test_partial_staging_does_not_hide_policy_denials_or_missing_html(tmp_path):
    base = make_plan(selection_key=SELECT, size=15)
    blocked = base["batches"][0]["source_ids"][0]
    missing = base["batches"][1]["source_ids"][1]
    plan, ledger, root = _prepare(
        tmp_path, blocked={blocked}, missing={missing},
    )
    report = _stage(plan, ledger, root, tmp_path / "staged")
    assert report["frozen_selected_sources"] == 15
    assert report["original_html_captured"] == 13
    assert report["source_policy_held"] == 1
    assert report["eligible_original_html_missing"] == 1
    assert report["blank_independent_reviewer_templates"] == 6
    assert report["ready_to_score_human_gold"] is False
    assert report["network_requests_performed"] == 0
    assert report["advisor_fact_approvals"] == 0
    out = tmp_path / "staged"
    account = json.loads(
        (out / "full_frozen_selection_accounting.json").read_text()
    )
    assert account["frozen_source_count"] == 15
    assert len(account["original_selected_sources"]) == 15
    assert account["policy_held_count"] == 1
    assert account["eligible_uncaptured_count"] == 1
    assert account["captured_source_count"] == 13
    assert account["status_counts"]["publisher_policy_held"] == 1
    assert account["status_counts"][
        "eligible_but_original_html_not_supplied"
    ] == 1
    entries = {x["source_id"]: x for x in account["original_selected_sources"]}
    assert entries[blocked]["capture_status"] == "publisher_policy_held"
    assert entries[missing]["capture_status"] == (
        "eligible_but_original_html_not_supplied"
    )
    assert entries[blocked]["raw_snapshot_sha256"] is None
    assert entries[missing]["raw_snapshot_sha256"] is None
    subset = json.loads((out / "captured_subset_review_cohort.json").read_text())
    for batch in subset["batches"]:
        manuscript = json.loads(
            (out / batch["capture_manifest"]).read_text()
        )
        assert all(
            x["source_id"] not in {blocked, missing}
            for x in manuscript["snapshots"]
        )
        for sid in (x["source_id"] for x in manuscript["snapshots"]):
            assert (out / batch["batch_id"] / "capture_audits" /
                    (sid + ".json")).is_file()
        for who in ("a", "b"):
            folder = out / batch["batch_id"] / "census"
            template = json.loads(
                (folder / ("reviewer_" + who + "_template.json")).read_text()
            )
            assert template["independent_blind_review_attested"] is False
            assert all(x["events"] == [] for x in template["source_reviews"])
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o700


def test_scoring_preserves_original_denominator_and_only_scored_metrics(tmp_path):
    base = make_plan(selection_key=SELECT, size=15)
    blocked = base["batches"][0]["source_ids"][0]
    missing = base["batches"][1]["source_ids"][1]
    plan, ledger, root = _prepare(tmp_path, blocked={blocked}, missing={missing})
    staged = tmp_path / "staged"
    _stage(plan, ledger, root, staged)
    with pytest.raises(ValueError):
        score_partial_pilot(
            plan, ledger, staged, selection_key=SELECT, split_key=SPLIT,
        )
    _fill_reviews(staged)
    result = score_partial_pilot(
        plan, ledger, staged, selection_key=SELECT, split_key=SPLIT,
    )
    assert result["source_count_in_original_preregistered_selection"] == 15
    assert result["captured_original_html_source_count"] == 13
    assert result["selection_capture_coverage"] == pytest.approx(13/15)
    assert result["scored_source_count"] <= 13
    assert result["missing_policy_capture_or_review_source_count"] >= 2
    assert result["pilot_sample_coverage_diagnostic_ready"] is False
    assert result["full_selected_population_accuracy_established"] is False
    assert result["publisher_origin_independently_authenticated"] is False
    assert result["advisor_fact_approvals"] == 0
    assert result["network_requests_performed"] == 0
    rows = {x["source_id"]: x for x in result["frozen_selected_sources"]}
    assert rows[blocked]["diagnostic_only_metrics"] is None
    assert rows[missing]["diagnostic_only_metrics"] is None
    assert rows[blocked]["hold_reason"] == "deferred_policy_unclear"
    assert rows[missing]["hold_reason"] == "eligible_original_html_missing"
    assert result["subset_scored_only_diagnostics"][
        "generalizable_release_accuracy_established"] is False


@pytest.mark.parametrize("attack", [
    "bad_receipt", "changed_original_bytes", "unauthorized_capture",
    "symlink_source", "orphan_capture", "malformed_audit",
])
def test_invalid_partial_capture_fails_before_staging(tmp_path, attack):
    plan, ledger, root = _prepare(tmp_path)
    first_wave = plan["batches"][0]
    first_sid = first_wave["source_ids"][0]
    folder = root / first_wave["batch_id"] / first_sid
    if attack == "bad_receipt":
        path = folder / "capture_audit.json"
        audit = json.loads(path.read_text())
        audit["source_specific_policy_review_receipt_sha256"] = "a"*64
        _write(path, audit)
    elif attack == "changed_original_bytes":
        filename = next(folder.glob("*.html"))
        filename.write_text("CHANGED fake HTML after hash")
    elif attack == "unauthorized_capture":
        sid = first_sid
        for review in ledger["reviews"]:
            if review["source_id"] == sid:
                review.update({
                    "decision": "deferred_policy_unclear",
                    "robots_review_attested": False,
                    "lawful_private_retention_attested": False,
                    "publisher_scope_attested": False,
                })
        # Existing capture has old receipt; source is now held.
    elif attack == "symlink_source":
        target = folder / "source_link.html"
        target.symlink_to(next(folder.glob("*.html")))
    elif attack == "orphan_capture":
        (root / "wave_unknown").mkdir()
    elif attack == "malformed_audit":
        path = folder / "capture_audit.json"
        audit = json.loads(path.read_text())
        audit["capture_count"] = 2
        _write(path, audit)
    with pytest.raises((ValueError, OSError, FileNotFoundError)):
        _stage(plan, ledger, root, tmp_path / "staged")
    assert not (tmp_path / "staged").exists()


def test_fake_policy_denial_never_counts_as_parser_false_negative(tmp_path):
    base = make_plan(selection_key=SELECT, size=15)
    blocked = set(x["source_id"] for w in base["batches"] for x in w["sources"])
    plan, ledger, root = _prepare(tmp_path, blocked=blocked)
    result = _stage(plan, ledger, root, tmp_path / "no_access")
    assert result["source_policy_held"] == 15
    assert result["original_html_captured"] == 0
    assert result["blank_independent_reviewer_templates"] == 0
    scored = score_partial_pilot(
        plan, ledger, tmp_path / "no_access",
        selection_key=SELECT, split_key=SPLIT,
    )
    assert scored["captured_original_html_source_count"] == 0
    assert scored["scored_source_count"] == 0
    assert scored["missing_policy_capture_or_review_source_count"] == 15
    assert scored["subset_scored_only_diagnostics"] is None
    assert scored["pilot_sample_coverage_diagnostic_ready"] is False
    assert scored["full_selected_population_accuracy_established"] is False
    assert all(x["diagnostic_only_metrics"] is None for x in
               scored["frozen_selected_sources"])


def test_tampered_selection_denominator_even_resigned_hash_is_rejected(tmp_path):
    plan, ledger, root = _prepare(tmp_path)
    staged = tmp_path / "stage"
    _stage(plan, ledger, root, staged)
    file = staged / "full_frozen_selection_accounting.json"
    state = json.loads(file.read_text())
    state["original_selected_sources"].pop()
    from scripts.replay_release_snapshots import _digest
    state["ledger_sha256"] = _digest({
        k: v for k, v in state.items() if k != "ledger_sha256"
    })
    _write(file, state)
    with pytest.raises(ValueError, match="incomplete or replaced"):
        score_partial_pilot(
            plan, ledger, staged, selection_key=SELECT, split_key=SPLIT,
        )


def test_policy_partial_capture_failure_does_not_delete_other_provider(tmp_path):
    # The frozen selection never resamples, even if the policy-eligible
    # publisher failed its manual exact-path original HTML GET.
    base = make_plan(selection_key=SELECT, size=15)
    missing = base["batches"][0]["source_ids"][0]
    plan, ledger, root = _prepare(tmp_path, missing={missing})
    staged = tmp_path / "staged"
    report = _stage(plan, ledger, root, staged)
    assert report["original_html_captured"] == 14
    assert report["eligible_original_html_missing"] == 1
    assert report["frozen_selected_sources"] == 15
