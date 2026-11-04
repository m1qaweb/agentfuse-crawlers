"""P20A: no-network cross-category scope plan and full-source NO-GO census.

Every URL is an existing first-party manifest pin. These tests fabricate
neither publisher permission nor reviewed pricing/release/documentation gold.
"""
import csv
import json
import os
import sys
from collections import Counter

import pytest

from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.full_inventory_readiness import (
    EXPECTED, WAVES, build_preflight, write_preflight,
    _csv_bytes, CSV_SOURCE_FIELDS,
    main as preflight_cli,
)
from scripts.replay_release_snapshots import _digest


def test_460_source_census_is_complete_with_real_restrictions():
    report, rows, waves = build_preflight()
    assert len(load_sources()) == 460
    assert report["configured_sources"] == len(rows) == 460
    assert report["category_counts"] == {
        "documentation": 194, "pricing": 177, "changelog": 89,
    }
    assert report["source_manifest_sha256"] == manifest_sha256()
    assert report["source_registry_sha256"] == registry_revision_sha256()
    assert report["lifecycle_counts"] == {
        "needs_validation": 454, "degraded": 3, "quarantined": 3,
    }
    assert report["policy_status_counts"]["unresolved"] == 3
    assert report["unattended_collection_approved_count"] == 0
    assert report["technically_validation_allowed_by_local_guard_count"] == 457
    assert report["individually_reviewed_publisher_permission_count_verified_here"] == 0
    held_ids = {x["source_id"] for x in report["locally_blocked_sources"]}
    assert held_ids == {"v0_docs", "v0_pricing", "v0_changelog"}
    assert not report["preflight_checks"]["all_source_publisher_policy_review"]
    assert not report["preflight_checks"]["archived_two_round_real_zyte_canaries_supplied"]
    assert report["full_inventory_one_time_diagnostic_crawl"] == (
        "NO_GO_PENDING_EVIDENCE"
    )
    assert report["full_inventory_automatic_monitoring"] == (
        "NO_GO_PENDING_PER_SOURCE_APPROVAL"
    )
    assert report["real_accuracy_measured_by_this_preflight"] is False
    assert report["new_source_permissions"] == 0
    assert report["new_zyte_jobs"] == 0
    assert report["network_requests_performed"] == 0
    assert report["advisor_fact_approvals"] == 0
    assert report["deployment_authorized"] is False
    assert _digest({
        k: v for k, v in report.items() if k != "report_sha256"
    }) == report["report_sha256"]
    by_id = {x["source_id"]: x for x in rows}
    assert len(by_id) == 460
    assert set(by_id) == {s["id"] for s in load_sources()}
    assert by_id["kiro_docs"]["source_lifecycle_state"] == "degraded"
    assert by_id["v0_docs"]["validation_lifecycle_allows_request"] is False
    assert by_id["v0_docs"]["monitor_collection_approved"] is False
    assert len(waves) == 2


def test_frozen_pilot_is_18_distinct_provider_labels_three_spider_categories():
    report, rows, waves = build_preflight()
    src = {s["id"]: s for s in load_sources()}
    selected = []
    label_set = set()
    assert report["total_planned_manual_canary_jobs"] == 36
    assert len(report["risk_informed_canary_waves"]) == 2
    for n, wave in enumerate(waves, 1):
        plan = wave["canary_plan"]
        ids = plan["source_ids"]
        selected.extend(ids)
        assert wave["wave_id"] == "wave_" + str(n).zfill(2)
        assert len(ids) == 9
        assert len(set(ids)) == 9
        assert Counter(src[sid]["category"] for sid in ids) == {
            "documentation": 3, "pricing": 3, "changelog": 3
        }
        assert wave["manual_jobs"] == plan["total_expected_jobs"] == 18
        assert wave["network_requests_performed"] == 0
        assert plan["execution_permitted"] is False
        assert plan["approved_for_advisor"] is False
        assert plan["repeats"] == 2
        assert plan["manifest_sha256"] == manifest_sha256()
        assert plan["source_registry_sha256"] == registry_revision_sha256()
        assert len(plan["jobs"]) == 18
        assert all(x["zyte_job_id"] is None for x in plan["jobs"])
        assert all(x["execution_status"] ==
                   "not_scheduled_requires_operator_authorization"
                   for x in plan["jobs"])
        assert [x["source_id"] for x in plan["sources"]] == ids
        assert all(s["collection_permission_review_required"]
                   for s in plan["sources"])
        for sid in ids:
            label_set.add(src[sid]["provider"])
        for item in plan["jobs"]:
            args = item["spider_args"]
            assert item["source_url"] == src[item["source_id"]]["url"]
            assert item["spider"] in {
                "official_documentation", "official_pricing", "official_changelogs"
            }
            assert args["source_ids"] == item["source_id"]
            assert args["cohort"] == "all"
            assert args["collection_mode"] == "validation"
            assert "confirm_full_inventory" not in args
            assert args["expected_manifest_sha256"] == manifest_sha256()
            assert args["expected_source_registry_sha256"] == registry_revision_sha256()
            assert item["round"] in (1, 2)
    assert len(selected) == len(set(selected)) == 18
    assert len(label_set) == 18
    assert Counter(src[sid]["category"] for sid in selected) == {
        "documentation": 6, "pricing": 6, "changelog": 6
    }
    assert len(rows) == 460


def test_manual_output_is_new_only_private_and_has_460_no_executable_full_job(tmp_path):
    report, rows, waves = build_preflight()
    root = tmp_path / "operator-private"
    location = write_preflight(report, rows, waves, root)
    assert location == root
    p = root / "full_inventory_readiness.json"
    saved = json.loads(p.read_text())
    assert saved == report
    csv_path = root / "all_460_source_review_queue.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        entries = list(csv.DictReader(stream))
    assert len(entries) == 460
    assert len({x["source_id"] for x in entries}) == 460
    assert all(
        x["monitor_collection_approved"] == "False" for x in entries
    )
    for wave in ("wave_01", "wave_02"):
        sub = root / wave
        manual = json.loads(
            (sub / "manual_canary_plan.json").read_text()
        )
        assert manual["source_count"] == 9
        assert manual["execution_permitted"] is False
        with (sub / "manual_canary_job_args.csv").open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            jobs = list(csv.DictReader(stream))
        assert len(jobs) == 18
        assert all(x["spider_source_ids"] == x["source_id"] for x in jobs)
        assert all(x["execution_status"] ==
                   "not_scheduled_requires_operator_authorization"
                   for x in jobs)
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700
        assert p.stat().st_mode & 0o777 == 0o600
        assert csv_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="NEW"):
        write_preflight(report, rows, waves, root)
    assert json.loads(p.read_text()) == saved


def test_manual_output_does_not_leak_shell_formula_execution():
    fields = ("source_id", "provider")
    raw = _csv_bytes(fields, [
        {"source_id": "=1+1", "provider": "@terminal!A1"},
        {"source_id": "good", "provider": "+7"},
    ]).decode("utf-8-sig")
    assert "'=1+1" in raw
    assert "'@terminal!A1" in raw
    assert "'+7" in raw


def test_zero_network_cli_and_no_existing_crawl_tasks(monkeypatch, tmp_path,
                                                        capsys):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: pytest.fail("Readiness must never contact publishers"),
    )
    monkeypatch.setattr(
        urllib.request, "build_opener",
        lambda *a, **kw: pytest.fail("Readiness must never fetch robots.txt"),
    )
    monkeypatch.setattr(sys, "argv", [
        "full_inventory_readiness",
        "--out-dir", str(tmp_path / "report"),
    ])
    preflight_cli()
    output = json.loads(capsys.readouterr().out)
    assert output["full_inventory_diagnostic"] == "NO_GO_PENDING_EVIDENCE"
    assert output["unattended_monitoring"] == "NO_GO_PENDING_PER_SOURCE_APPROVAL"
    assert output["preplanned_cross_category_sources"] == 18
    assert output["preplanned_live_manual_canary_jobs"] == 36
    assert output["new_zyte_jobs"] == 0
    assert output["network_requests_performed"] == 0
    assert output["advisor_fact_approvals"] == 0


def test_source_inventory_or_category_change_fails_closed(monkeypatch):
    import scripts.full_inventory_readiness as module
    sources = load_sources()
    monkeypatch.setattr(module, "load_sources", lambda: sources[:-1])
    with pytest.raises(ValueError, match="460"):
        build_preflight()
    tampered = [dict(s) for s in sources]
    tampered[0]["category"] = "unrelated"
    monkeypatch.setattr(module, "load_sources", lambda: tampered)
    with pytest.raises(ValueError, match="mix"):
        build_preflight()


def test_newly_policy_blocked_canary_source_cannot_be_auto_replaced(monkeypatch):
    import scripts.full_inventory_readiness as module
    actual = module.collection_decision
    source_id = WAVES[0][0][0]
    def fake_review(source, mode="validation"):
        if source["id"] == source_id and mode == "validation":
            return False, "policy_unresolved_or_quarantined"
        return actual(source, mode)
    monkeypatch.setattr(module, "collection_decision", fake_review)
    with pytest.raises(ValueError, match="policy-blocked"):
        build_preflight()


def test_symlinked_output_is_rejected(tmp_path):
    report, rows, waves = build_preflight()
    dest = tmp_path / "already_here"
    dest.mkdir()
    link = tmp_path / "linked_output"
    try:
        link.symlink_to(dest, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unsupported")
    with pytest.raises(ValueError, match="NEW"):
        write_preflight(report, rows, waves, link)


def test_full_inventory_cannot_auto_authorize_from_monitor_approvals(monkeypatch):
    """Even hypothetical 460 permissions are NOT a completed live gold study."""
    import scripts.full_inventory_readiness as module
    actual = module.collection_decision
    def fake_review(source, mode="validation"):
        if mode == "monitor":
            return True, "hypothetically_approved"
        return actual(source, mode)
    monkeypatch.setattr(module, "collection_decision", fake_review)
    # The untouched source_lifecycle is still incomplete. A hypothetical
    # monitoring count cannot turn into a real-evidence assertion.
    out, _, _ = build_preflight()
    assert out["unattended_collection_approved_count"] == 460
    assert out["full_inventory_one_time_diagnostic_crawl"] == "NO_GO_PENDING_EVIDENCE"
    assert out["real_accuracy_measured_by_this_preflight"] is False
    assert out["new_zyte_jobs"] == 0
