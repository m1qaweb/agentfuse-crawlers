"""P20B offline Zyte UI instructions, never publisher or Zyte requests."""
import csv
import json
import os
import sys
from collections import Counter

import pytest

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources, select_sources
from scripts.prepare_zyte_ui_args import (
    KIND, build_full_diagnostic_ui_guide,
    write_zyte_ui_guide, main as ui_main,
)
from scripts.replay_release_snapshots import _digest


def test_exact_safely_pinned_460_source_3_spider_zyte_ui_jobs():
    result = build_full_diagnostic_ui_guide()
    assert result["kind"] == KIND
    assert result["source_ids_accounted_for"] == 460
    assert result["manual_spider_jobs"] == 3
    assert result["source_manifest_sha256"] == manifest_sha256()
    assert result["source_registry_sha256"] == registry_revision_sha256()
    assert result["expected_package_sha256_NOT_REMOTE_PROOF"] == package_fingerprint()
    assert result["locally_eligible_primary_source_count"] == 0
    expected = [
        ("official_changelogs", "changelog", 89),
        ("official_pricing", "pricing", 177),
        ("official_documentation", "documentation", 194),
    ]
    assert [(x["spider"], x["category"], x["configured_source_count"])
            for x in result["jobs"]] == expected
    for row in result["jobs"]:
        args = row["arguments"]
        selected = select_sources(row["category"], cohort="all")
        assert args == {
            "cohort": "all",
            "confirm_full_inventory": "yes",
            "collection_mode": "validation",
        }
        assert row["scope_fingerprints_reference_only"] == {
            "expected_manifest_sha256": manifest_sha256(),
            "expected_selection_ids_sha256": selection_ids_sha256(selected),
            "expected_source_registry_sha256": registry_revision_sha256(),
        }
        assert "source_ids" not in args
        assert "limit" not in args and "offset" not in args
        assert row["job_units"] == 1
        assert row["priority"] == "Normal"
        assert row["tags"] == []
        assert row["explicitly_no_source_ids_argument"] is True
        assert row["operator_review_status"].startswith("NOT_AUTHORIZED")
        gate = row["local_bulk_plan_preflight"]
        assert gate["status"] == "no_matching_reviewed_plan"
        assert gate["locally_eligible_source_count"] == gate["max_primary_requests"] == 0
        assert gate["run_authorized_by_guide"] is gate["remote_deployment_verified"] is False
        assert row["scheduled_jobs"] == 0
        assert row["advisor_fact_approvals"] == 0
    assert result["jobs"][0]["source_ids_locally_policy_blocked"] == (
        ["v0_changelog"]
    )
    assert result["jobs"][1]["source_ids_locally_policy_blocked"] == (
        ["v0_pricing"]
    )
    assert result["jobs"][2]["source_ids_locally_policy_blocked"] == (
        ["v0_docs"]
    )
    assert result["full_diagnostic_approved_to_run"] is False
    assert result["recurrent_monitoring_approved"] is False
    assert result["all_source_publisher_permissions_verified_here"] is False
    assert result["publisher_terms_and_robots_independently_verified"] is False
    assert result["live_canary_evidence_supplied_to_this_command"] is False
    assert result["network_requests_performed"] == 0
    assert result["zyte_jobs_created"] == 0
    assert result["deployment_authorized"] is False
    assert result["advisor_fact_approvals"] == 0
    assert _digest({
        key: value for key, value in result.items()
        if key != "report_sha256"
    }) == result["report_sha256"]


def test_operator_can_download_full_copy_paste_args_without_local_checkout(
        tmp_path):
    guide = build_full_diagnostic_ui_guide()
    folder = tmp_path / "p20b-zyte-no-local"
    assert write_zyte_ui_guide(guide, folder) == folder
    saved = json.loads(
        (folder / "zyte_full_3_spiders_NOT_AUTHORIZED.json").read_text()
    )
    assert saved == guide
    with (folder / "zyte_full_3_spiders_NOT_AUTHORIZED.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert {x["spider"] for x in rows} == {
        "official_changelogs", "official_pricing",
        "official_documentation",
    }
    assert all(row["cohort"] == "all" for row in rows)
    assert all(row["confirm_full_inventory"] == "yes" for row in rows)
    assert all(row["collection_mode"] == "validation" for row in rows)
    assert all("source_ids" not in row for row in rows)
    assert all(row["expected_manifest_sha256"] == manifest_sha256()
               for row in rows)
    assert all(row["expected_source_registry_sha256"] ==
               registry_revision_sha256() for row in rows)
    assert all(row["expected_selection_ids_sha256"] ==
               selection_ids_sha256(select_sources(row["category"], cohort="all"))
               for row in rows)
    assert all(row["expected_bulk_plan_sha256"] == "" for row in rows
               if "expected_bulk_plan_sha256" in row)
    assert all(row["human_authorization_status"].startswith("NOT_AUTHORIZED")
               for row in rows)
    assert all(row["local_plan_primary_request_cap"] == "0"
               and row["local_plan_status"] == "no_matching_reviewed_plan"
               and row["expected_package_sha256"] == package_fingerprint() for row in rows)
    txt = (folder / "READ_ME_ZYTE_UI_SETTINGS_NOT_AUTHORIZED.txt").read_text()
    for x in ("SPIDER: official_changelogs", "SPIDER: official_pricing",
              "SPIDER: official_documentation", "LOCAL PRIMARY REQUEST CAP: 0",
              "DO NOT RUN: arguments withheld", "EXPECTED PACKAGE SHA-256",
              "the spider locates ONE exact current reviewed plan",
              "DO NOT add source_ids", "NOT AUTHORIZED"):
        assert x in txt
    assert "confirm_full_inventory = yes" not in txt
    assert "cohort = all" not in txt
    assert "collection_mode = validation" not in txt
    if os.name == "posix":
        assert folder.stat().st_mode & 0o777 == 0o700
        for file in folder.iterdir():
            assert file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="NEW"):
        write_zyte_ui_guide(guide, folder)
    assert saved == json.loads(
        (folder / "zyte_full_3_spiders_NOT_AUTHORIZED.json").read_text()
    )


def test_no_network_cli_preflight(monkeypatch, tmp_path, capsys):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *_a, **_kw: pytest.fail(
            "P20B may not fetch any Zyte or publisher URL"
        ),
    )
    monkeypatch.setattr(
        urllib.request, "build_opener",
        lambda *_a, **_kw: pytest.fail(
            "P20B may not fetch any robots or publisher URL"
        ),
    )
    monkeypatch.setattr(
        sys, "argv", [
            "prepare_zyte_ui_args", "--out-dir", str(tmp_path / "out")
        ],
    )
    ui_main()
    out = json.loads(capsys.readouterr().out)
    assert out["source_ids_accounted_for"] == 460
    assert out["full_diagnostic_approved_to_run"] is False
    assert out["new_publisher_permissions_granted"] == 0
    assert out["zyte_jobs_created"] == 0
    assert out["network_requests_performed"] == 0
    assert len(out["spiders"]) == 3


def test_manifest_change_does_not_generate_stale_full_scope(monkeypatch):
    import scripts.prepare_zyte_ui_args as module
    manifest = load_sources()
    monkeypatch.setattr(module, "load_sources", lambda: manifest[:-1])
    with pytest.raises(ValueError, match="194/177/89"):
        module.build_full_diagnostic_ui_guide()
    altered = [dict(x) for x in manifest]
    altered[0]["category"] = "unknown"
    monkeypatch.setattr(module, "load_sources", lambda: altered)
    with pytest.raises(ValueError, match="194/177/89"):
        module.build_full_diagnostic_ui_guide()


def test_source_selection_tamper_fails_closed(monkeypatch):
    import scripts.prepare_zyte_ui_args as module
    original = module.select_sources
    def wrong(category, cohort="all"):
        xs = original(category, cohort=cohort)
        return xs[:-1] if category == "pricing" else xs
    monkeypatch.setattr(module, "select_sources", wrong)
    with pytest.raises(ValueError, match="unexpectedly differs"):
        module.build_full_diagnostic_ui_guide()


def test_operator_output_never_implicitly_approves_real_scrapes():
    result = build_full_diagnostic_ui_guide()
    for key in ("full_diagnostic_approved_to_run",
                "recurrent_monitoring_approved",
                "all_source_publisher_permissions_verified_here",
                "publisher_terms_and_robots_independently_verified",
                "live_canary_evidence_supplied_to_this_command",
                "deployment_authorized"):
        assert result[key] is False
    for row in result["jobs"]:
        assert not row["scheduled_jobs"]
        assert row["source_ids_locally_policy_blocked"]
        assert "approval" not in row["arguments"]
