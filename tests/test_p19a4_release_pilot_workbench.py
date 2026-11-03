"""P19A4 fictional full-pilot workbench regressions.

No website requests, no Zyte jobs, no independent human gold. Invented
first-party-page-shaped HTML is used only to validate the operator workflow.
"""
import hashlib
import json
import os
import sys
from copy import deepcopy

import pytest

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.prepare_release_pilot import (
    make_plan, stage_captures, main as pilot_cli,
)

SELECTION = "synthetic-selection-seed-only-do-not-use-for-real-pilot"
HOLDOUT = "synthetic-holdout-split-seed-only-for-nonpublisher-pages"
CAPTURED = "2026-10-15T10:00:00Z"
POLICY = (
    "SYNTHETIC TEST ONLY. Fake publisher policy and robots review; "
    "the test never accesses a real publisher."
)
SOURCE = {x["id"]: x for x in load_sources()}


def _json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def html(sid):
    """Two explicitly fictional, independently owned release-shaped cards."""
    return (
        "<!doctype html><html><head><title>Fake synthetic updates</title></head>"
        "<body><main><h1>Imaginary official updates</h1>"
        '<article><h2 id="imaginary1">Imaginary technical release 2.1.0</h2>'
        '<time datetime="2026-10-14">2026-10-14</time><p>'
        "Synthetic imaginary fake product announcement for " + sid +
        " with deterministic invented API behavior, bounded reference "
        "details and fictitious model compatibility. No real publisher "
        "has announced any of this.</p></article>"
        '<article><h2 id="imaginary2">Imaginary technical release 2.0.0</h2>'
        '<time datetime="2026-10-10">2026-10-10</time><p>'
        "Synthetic older release to test release chronology, publisher "
        "location and repeatable original HTML byte hashing. No real "
        "announcement is made.</p></article></main></body></html>"
    )


def captures(root, plan):
    """Write a SYNTHETIC P19A1-shaped attested capture for each planned wave."""
    root.mkdir()
    for batch in plan["batches"]:
        directory = root / batch["batch_id"]
        directory.mkdir()
        snapshots, receipts = [], []
        for source in batch["sources"]:
            sid = source["source_id"]
            raw = html(sid).encode("utf-8")
            digest = hashlib.sha256(raw).hexdigest()
            filename = sid + "-" + digest[:20] + ".html"
            (directory / filename).write_bytes(raw)
            snapshots.append({
                "source_id": sid,
                "snapshot": {
                    "file": filename,
                    "sha256": digest,
                    "request_url": SOURCE[sid]["url"],
                    "final_url": SOURCE[sid]["url"],
                    "http_status": 200,
                    "media_type": "text/html",
                    "capture_method": "static_html",
                    "captured_at_utc": CAPTURED,
                    "capture_origin_review_status":
                        "operator_supplied_unverified",
                },
            })
            receipts.append({
                "source_id": sid,
                "official_source_url": SOURCE[sid]["url"],
                "raw_html_sha256": digest,
                "raw_html_bytes": len(raw),
                "robots_url": source["robots_url"],
                "robots_sha256": hashlib.sha256(
                    ("fake robots " + sid).encode()
                ).hexdigest(),
                "robots_allowed_for_agent": True,
                "robots_delay_seconds": 1.0,
                "http_date_unverified": "fake header",
                "last_modified_not_publication_date": "fake",
                "parser_capture_status": "captured",
                "parser_capture_reason": "synthetic",
                "publisher_origin_independently_authenticated": False,
                "published_release_facts_independently_verified": False,
                "approved_for_advisor": False,
            })
        manifest = {
            "schema_version": "1.0",
            "kind": "frozen_original_changelog_html_manifest",
            "expected_manifest_sha256": manifest_sha256(),
            "expected_source_registry_sha256": registry_revision_sha256(),
            "approved_for_advisor": False,
            "snapshots": snapshots,
        }
        audit = {
            "schema_version": "1.0",
            "kind": "p19a1_manual_original_changelog_capture_audit",
            "capture_count": len(snapshots),
            "source_ids": batch["source_ids"],
            "publisher_policy_review_operator_attested": True,
            "publisher_policy_independently_verified": False,
            "policy_review_note": POLICY,
            "robots_checks": len(snapshots),
            "network_requests_performed": 2 * len(snapshots),
            "receipts": receipts,
            "new_spider_sources": 0,
            "zyte_jobs_created": 0,
            "automatic_schedules_enabled": False,
            "new_release_alerts": 0,
            "advisor_approved_facts": 0,
            "approved_for_advisor": False,
        }
        _json(directory / "frozen_release_snapshots.json", manifest)
        _json(directory / "capture_audit.json", audit)


def test_offline_selection_is_frozen_diverse_and_never_permission(monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *_a, **_kw: pytest.fail("P19A4 must never fetch a publisher"),
    )
    plan = make_plan(selection_key=SELECTION, size=20, batch_size=5)
    assert plan == make_plan(
        selection_key=SELECTION, size=20, batch_size=5,
    )
    assert len(SOURCE) == 460
    assert plan["changelog_source_count"] == 89
    assert plan["source_count"] == 20
    assert plan["batch_count"] == 4
    assert plan["selected_provisional_provider_groups"] == 20
    assert plan["selection_frozen_before_capture"] is True
    assert plan["publisher_policy_review_completed"] is False
    assert plan["captured_snapshots"] == 0
    assert plan["network_requests_performed"] == 0
    assert plan["advisor_approved_facts"] == 0
    assert plan["approved_for_advisor"] is False
    assert plan["selection_key_commitment_sha256"] != SELECTION
    source_ids = [
        source["source_id"] for batch in plan["batches"]
        for source in batch["sources"]
    ]
    groups = [
        source["provisional_provider_group"] for batch in plan["batches"]
        for source in batch["sources"]
    ]
    assert len(set(source_ids)) == len(source_ids) == 20
    assert len(set(groups)) == 20
    assert all(SOURCE[sid]["category"] == "changelog" for sid in source_ids)
    assert all(batch["network_requests_performed"] == 0 for batch in plan["batches"])
    assert all(batch["operator_policy_review_required_for_each_source"]
               for batch in plan["batches"])
    assert all("--capture" not in batch["read_only_capture_plan_command"]
               for batch in plan["batches"])
    assert all(source["publisher_policy_reviewed"] is False
               for batch in plan["batches"] for source in batch["sources"])


@pytest.mark.parametrize(("size", "batch_size"), [(15, 5), (16, 4), (25, 5)])
def test_diverse_planning_bounds_and_batch_count(size, batch_size):
    plan = make_plan(
        selection_key=SELECTION, size=size, batch_size=batch_size,
    )
    assert plan["source_count"] == size
    assert plan["batch_count"] == (size + batch_size - 1) // batch_size
    assert len(set(
        x["provisional_provider_group"]
        for batch in plan["batches"] for x in batch["sources"]
    )) == size


@pytest.mark.parametrize(("size", "batch_size", "holdout"), [
    (14, 5, 25), (26, 5, 25), (20, 0, 25), (20, 6, 25),
    (20, 5, 0), (20, 5, 100), (True, 5, 25),
])
def test_invalid_size_or_batch_or_holdout_rejected(size, batch_size, holdout):
    with pytest.raises(ValueError):
        make_plan(
            selection_key=SELECTION, size=size,
            batch_size=batch_size, holdout_percent=holdout,
        )


def test_plan_change_or_secret_rotation_cannot_stagE_a_new_cohort(tmp_path):
    plan = make_plan(selection_key=SELECTION, size=15)
    captures(tmp_path / "captures", plan)
    for change in (
        lambda x: x["batches"][0]["source_ids"].reverse(),
        lambda x: x["batches"][0]["sources"][0].update(
            raw_html_capture_permission_granted=True
        ),
        lambda x: x.update(source_registry_sha256="f" * 64),
        lambda x: x.update(captured_snapshots=15),
    ):
        modified = deepcopy(plan)
        change(modified)
        with pytest.raises(ValueError, match="Frozen pilot plan"):
            stage_captures(
                modified, tmp_path / "captures", tmp_path / "unused",
                selection_key=SELECTION, split_key=HOLDOUT,
            )
    with pytest.raises(ValueError, match="Frozen pilot plan"):
        stage_captures(
            plan, tmp_path / "captures", tmp_path / "unused",
            selection_key="this-other-operator-selection-secret-is-incorrect",
            split_key=HOLDOUT,
        )
    assert not (tmp_path / "unused").exists()


def test_full_offline_staging_emits_p19a3_inputs_and_blank_review_only(tmp_path,
                                                                        monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *_a, **_kw: pytest.fail("Staging must not access publisher web"),
    )
    plan = make_plan(selection_key=SELECTION, size=15, batch_size=5)
    capture = tmp_path / "capture"
    captures(capture, plan)
    output = tmp_path / "staged"
    result = stage_captures(
        plan, capture, output, selection_key=SELECTION, split_key=HOLDOUT,
    )
    assert result["verified_capture_hashes"] == 15
    assert result["selected_source_count"] == 15
    assert result["blank_reviewer_templates"] == 6
    assert result["missing_filled_reviewer_files"] == 6
    assert result["human_review_completed"] is False
    assert result["ready_for_p19a3_scoring"] is False
    assert result["advisor_fact_approvals"] == 0
    assert result["network_requests_performed"] == 0
    assert result["deployment_authorized"] is False
    actual_cohort = json.loads((output / "cohort.json").read_text())
    assert len(actual_cohort["batches"]) == 3
    assert actual_cohort["approved_for_advisor"] is False
    audit = json.loads((output / "pilot_staging_audit.json").read_text())
    assert audit["source_count"] == 15
    assert audit["replays_computed_offline"] == 3
    assert audit["independent_census_reviewers_completed"] == 0
    assert audit["publisher_policy_independently_verified"] is False
    assert audit["original_html_copied_bytes"] > 0
    for batch in actual_cohort["batches"]:
        name = batch["batch_id"]
        raw = output / name / "capture"
        frozen = json.loads(
            (raw / "frozen_release_snapshots.json").read_text()
        )
        assert len(frozen["snapshots"]) == 5
        for entry in frozen["snapshots"]:
            f = raw / entry["snapshot"]["file"]
            assert f.is_file()
            assert hashlib.sha256(f.read_bytes()).hexdigest() == (
                entry["snapshot"]["sha256"]
            )
            if os.name == "posix":
                assert f.stat().st_mode & 0o777 == 0o600
        replay = json.loads((output / batch["replay"]).read_text())
        packet = json.loads((output / batch["blind_packet"]).read_text())
        assert replay["source_count"] == 5
        assert len(packet["tasks"]) == 5
        assert all(t["predicted_titles_prefilled"] is False for t in packet["tasks"])
        for label in ("a", "b"):
            reference = json.loads(
                (output / name / "census" / (
                    "reviewer_" + label + "_template.json"
                )).read_text()
            )
            assert reference["independent_blind_review_attested"] is False
            assert all(r["events"] == [] for r in reference["source_reviews"])
            assert not (output / name / "census" / (
                "reviewer_" + label + "_filled.json"
            )).exists()
    if os.name == "posix":
        assert output.stat().st_mode & 0o777 == 0o700
        assert (output / "cohort.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="NEW"):
        stage_captures(
            plan, capture, output,
            selection_key=SELECTION, split_key=HOLDOUT,
        )


@pytest.mark.parametrize("corruption", [
    "changed_html", "tamper_audit", "no_policy_review", "false_robots",
    "missing_source", "future_snapshot", "wrong_receipt", "missing_wave",
])
def test_all_capture_batches_are_checked_before_staging(tmp_path, corruption):
    plan = make_plan(selection_key=SELECTION, size=15, batch_size=5)
    capture = tmp_path / "capture"
    captures(capture, plan)
    first = capture / "wave_01"
    audit_file = first / "capture_audit.json"
    manifest_file = first / "frozen_release_snapshots.json"
    manifest = json.loads(manifest_file.read_text())
    audit = json.loads(audit_file.read_text())
    if corruption == "changed_html":
        (first / manifest["snapshots"][0]["snapshot"]["file"]).write_text(
            "<html><h1>Fake HTML mutated after original SHA capture</h1></html>"
        )
    elif corruption == "tamper_audit":
        audit["capture_count"] = 999
    elif corruption == "no_policy_review":
        audit["publisher_policy_review_operator_attested"] = False
    elif corruption == "false_robots":
        audit["receipts"][0]["robots_allowed_for_agent"] = False
    elif corruption == "missing_source":
        manifest["snapshots"].pop()
    elif corruption == "future_snapshot":
        manifest["snapshots"][0]["snapshot"][
            "captured_at_utc"] = "2099-01-01T12:00:00Z"
    elif corruption == "wrong_receipt":
        audit["receipts"][0]["raw_html_sha256"] = "a" * 64
    elif corruption == "missing_wave":
        (capture / "wave_03" / "capture_audit.json").unlink()
    _json(audit_file, audit)
    _json(manifest_file, manifest)
    result = tmp_path / "must_not_exist"
    with pytest.raises((ValueError, FileNotFoundError)):
        stage_captures(
            plan, capture, result,
            selection_key=SELECTION, split_key=HOLDOUT,
        )
    assert not result.exists()


def test_symlinked_original_capture_file_is_rejected(tmp_path):
    plan = make_plan(selection_key=SELECTION, size=15, batch_size=5)
    cap = tmp_path / "capture"
    captures(cap, plan)
    first = cap / "wave_01"
    manifest = json.loads(
        (first / "frozen_release_snapshots.json").read_text()
    )
    target = first / manifest["snapshots"][0]["snapshot"]["file"]
    replacement = first / "new-original.html"
    target.rename(replacement)
    try:
        target.symlink_to(replacement)
    except OSError:
        pytest.skip("No symlink support")
    with pytest.raises(ValueError, match="symlink"):
        stage_captures(
            plan, cap, tmp_path / "unused",
            selection_key=SELECTION, split_key=HOLDOUT,
        )


def test_plan_cli_writes_private_zero_network_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY", SELECTION)
    monkeypatch.setattr(sys, "argv", [
        "prepare_release_pilot", "--plan",
        "--size", "20", "--batch-size", "5",
        "--out-dir", str(tmp_path / "selection"),
    ])
    pilot_cli()
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["selected_sources"] == 20
    assert stdout["publisher_policy_review_completed"] is False
    assert stdout["network_requests_performed"] == 0
    assert stdout["zyte_jobs_created"] == 0
    document = json.loads(
        (tmp_path / "selection" / "pilot_selection_plan.json").read_text()
    )
    assert document["source_count"] == 20
    assert document["plan_sha256"]
    assert SELECTION not in json.dumps(document)
    with pytest.raises(ValueError, match="NEW"):
        pilot_cli()
