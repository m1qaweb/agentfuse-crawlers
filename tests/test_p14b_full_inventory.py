"""P14B: entire 460-source plan and read-only immutable archive audits.

Synthetic job bytes are used to test accounting logic, not provider truth.
No test makes a network call, creates an actual Zyte run or approves facts.
"""

from copy import deepcopy
import json

import pytest

from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.source_lifecycle import collection_decision
from scripts.archive_jobs import archive_job
from scripts.audit_full_inventory import (
    audit_full_inventory, write_full_inventory_audit,
)
from scripts.full_inventory_plan import (
    build_full_inventory_plan, validate_full_inventory_plan,
    write_full_inventory_plan,
)

KNOWN = {s["id"]: s for s in load_sources()}
PACKAGE_SHA = "9" * 64


def fake_job_archive(tmp_path, job, *, job_num, package_sha=PACKAGE_SHA,
                     missing_id=None, args_override=None, close_reason="finished",
                     policy_fetch_violation=False):
    jobid = f"883514/1/{job_num + 100}"
    source_rows = []
    for n, sid in enumerate(job["source_ids"]):
        if sid == missing_id:
            continue
        src = KNOWN[sid]
        eligible = collection_decision(src, "validation")[0]
        skipped = not eligible
        row = {
            "_key": f"{jobid}/{len(source_rows)}",
            "source_id": sid,
            "source_url": src["url"],
            "provider": src["provider"],
            "category": src["category"],
            "spider_name": job["spider"],
            "status": "source_quarantined" if skipped else "captured",
            "error": "policy_unresolved_or_quarantined" if skipped else "",
            "http_status": 200 if (eligible or policy_fetch_violation) else None,
            "final_url": src["url"] if eligible else "",
            "policy_observation": (
                "not_fetched_by_lifecycle_guard" if skipped else "fetched"
            ),
            "source_policy_status": (
                "unresolved" if skipped else "not_reviewed"
            ),
            "source_lifecycle_state": (
                "quarantined" if skipped else "needs_validation"
            ),
            "content_sha256": "a" * 64 if eligible else "",
            "schema_version": "2.1",
            "approved_for_advisor": False,
            "review_status": "unverified",
            "requested_cohort": "all",
            "run_scope_explicit": True,
            "collection_mode": "validation",
            "manifest_sha256": job["spider_args"]["expected_manifest_sha256"],
            "source_registry_sha256": job["spider_args"][
                "expected_source_registry_sha256"
            ],
            "selection_ids_sha256": job["expected_selection_ids_sha256"],
            "selection_source_count": job["requested_count"],
            "run_started_at_utc": "2026-11-01T18:00:00+00:00",
            "fetched_at_utc": "2026-11-01T18:10:00+00:00",
            "zyte_job_id": jobid,
            "deployment_revision_kind": "package_py_json_sha256_v1",
            "deployment_revision": package_sha,
            "pricing_evidence_schema": "1.0" if src["category"] == "pricing" else None,
            "pricing_inventory_complete": False if src["category"] == "pricing" else None,
            "pricing_comparable_candidate_count": 0,
            "documentation_scope_status": (
                "overview_only" if src["category"] == "documentation" else None
            ),
            "release_window_complete": (
                False if src["category"] == "changelog" else None
            ),
            "release_dated_event_count": 0,
        }
        source_rows.append(row)
    meta = {
        "state": "finished",
        "spider": job["spider"],
        "close_reason": close_reason,
        "version": "fake-revision",
        "deploy_id": 30,
        "finished_time": 1793560000000 + job_num * 120000,
        "spider_args": args_override or job["spider_args"],
        "scrapystats": {
            "item_scraped_count": len(source_rows),
            "memusage/max": 140000000,
        },
    }
    path, _, state = archive_job(
        jobid, tmp_path, api_key="SYNTHETIC-NO-NETWORK",
        fetch_metadata=lambda *_: meta,
        fetch_page=lambda _id, _key, offset, count: source_rows[offset:offset + count],
    )
    assert state == "archived"
    return path


@pytest.fixture
def planned_shards():
    return build_full_inventory_plan(
        strategy="sharded", shard_size=25,
        expected_package_sha256=PACKAGE_SHA,
    )


@pytest.fixture
def full_fake_archives(tmp_path, planned_shards):
    return [
        fake_job_archive(tmp_path, job, job_num=i + 1)
        for i, job in enumerate(planned_shards["jobs"])
    ]


def test_full_plan_shards_cover_all_460_exactly_once(planned_shards):
    plan = planned_shards
    assert plan["kind"] == "unapproved_offline_full_inventory_validation_plan"
    assert plan["planned_jobs"] == 20
    assert plan["total_manifest_sources"] == 460
    assert len(plan["source_ids"]) == 460
    assert len(set(plan["source_ids"])) == 460
    assert plan["expected_primary_source_fetches"] == 457
    assert set(plan["expected_policy_skipped_source_ids"]) == {
        "v0_docs", "v0_pricing", "v0_changelog"
    }
    assert {c: d["planned_jobs"] for c, d in plan["categories"].items()} == {
        "documentation": 8, "pricing": 8, "changelog": 4
    }
    ids = [sid for job in plan["jobs"] for sid in job["source_ids"]]
    assert len(set(ids)) == len(ids) == 460
    assert all(job["requested_count"] <= 25 for job in plan["jobs"])
    assert all(job["spider_args"]["cohort"] == "all" and
               job["spider_args"]["collection_mode"] == "validation"
               and job["spider_args"]["source_ids"] ==
                   ",".join(job["source_ids"])
               and "confirm_full_inventory" not in job["spider_args"]
               and not job["automatic_execution_authorized"]
               for job in plan["jobs"])
    assert plan["publisher_access_review_not_automatically_authorized"]
    assert plan["approved_for_advisor"] is False


def test_exactly_three_full_category_jobs_work_without_source_ids():
    plan = build_full_inventory_plan(strategy="full",
                                     expected_package_sha256=PACKAGE_SHA)
    assert plan["planned_jobs"] == 3
    assert [job["requested_count"] for job in plan["jobs"]] == [194, 177, 89]
    assert all(job["spider_args"]["confirm_full_inventory"] == "yes"
               and "source_ids" not in job["spider_args"]
               and "offset" not in job["spider_args"]
               and "limit" not in job["spider_args"]
               for job in plan["jobs"])
    for job in plan["jobs"]:
        actual = select_sources(job["category"], "all")
        assert [s["id"] for s in actual] == job["source_ids"]
    assert plan["manual_execution_only"]


def test_modified_or_stale_plan_is_rejected(planned_shards):
    for mutate in (
        lambda plan: plan["jobs"][0]["source_ids"].pop(),
        lambda plan: plan["jobs"][0]["spider_args"].update(
            source_ids="fake"
        ),
        lambda plan: plan.update(
            source_registry_sha256="bad-publisher-policy"
        ),
        lambda plan: plan.update(manual_execution_only=False),
        lambda plan: plan.update(plan_sha256="0" * 64),
    ):
        value = deepcopy(planned_shards)
        mutate(value)
        with pytest.raises(ValueError, match="edited|stale"):
            validate_full_inventory_plan(value)


@pytest.mark.parametrize("kwargs", [
    {"strategy": "ALL"}, {"strategy": ""}, {"shard_size": 0},
    {"shard_size": -1}, {"shard_size": 101}, {"shard_size": True},
    {"shard_size": "25"}, {"expected_package_sha256": "cc5ba1a"},
    {"expected_package_sha256": "F" * 64},
])
def test_invalid_strategy_size_or_git_commit_mistaken_for_fingerprint(kwargs):
    with pytest.raises(ValueError):
        build_full_inventory_plan(**kwargs)


def test_manual_job_files_have_pinned_args_not_auto_crawl(tmp_path, planned_shards):
    write_full_inventory_plan(planned_shards, tmp_path)
    output = tmp_path / "manual_zyte_jobs.csv"
    assert output.exists()
    assert (tmp_path / "full_inventory_plan.json").exists()
    assert (tmp_path / "publisher_review_flags.csv").exists()
    data = json.loads((tmp_path / "full_inventory_plan.json").read_text())
    assert data["plan_sha256"] == planned_shards["plan_sha256"]
    validate_full_inventory_plan(data)
    assert not data["deployment_authorized"]
    assert not data["network_requests_performed"]


def test_full_460_immutable_archives_prove_accounting_not_truth(
        planned_shards, full_fake_archives, tmp_path):
    report = audit_full_inventory(
        planned_shards, archive_paths=full_fake_archives,
    )
    summary = report["summary"]
    assert summary["status"] == (
        "full_inventory_accounted_archives_verified_facts_unverified"
    )
    assert summary["accounted_source_count"] == 460
    assert summary["missing_source_count"] == 0
    assert summary["planned_job_count"] == 20
    assert summary["reported_job_count"] == 20
    assert summary["whole_inventory_accounted"] is True
    assert summary["verified_immutable_archives"] is True
    assert summary["package_pinned_and_verified"] is True
    assert summary["expected_policy_skips"] == [
        "v0_changelog", "v0_docs", "v0_pricing"
    ]
    assert {name: data["items_received"] for name, data in
            summary["category_metrics"].items()} == {
        "documentation": 194, "pricing": 177, "changelog": 89,
    }
    assert {name: data["policy_skipped"] for name, data in
            summary["category_metrics"].items()} == {
        "documentation": 1, "pricing": 1, "changelog": 1,
    }
    assert summary["publisher_evidence_accuracy_independently_verified"] is False
    assert summary["advisor_fact_approvals"] == 0
    assert summary["network_requests_performed_by_auditor"] == 0
    write_full_inventory_audit(report, tmp_path / "report")
    assert (tmp_path / "report/summary.json").exists()
    assert (tmp_path / "report/source_quality_triage.csv").exists()
    assert (tmp_path / "report/job_accounting.csv").exists()


def test_missing_archive_reports_missing_source_ids_without_fake_success(
        planned_shards, full_fake_archives):
    removed = planned_shards["jobs"][0]
    report = audit_full_inventory(planned_shards,
                                  archive_paths=full_fake_archives[1:])
    summary = report["summary"]
    assert summary["status"] == "full_inventory_accounting_incomplete"
    assert summary["missing_source_count"] == removed["requested_count"]
    assert set(summary["missing_source_ids"]) == set(removed["source_ids"])
    assert summary["missing_job_keys"] == [removed["job_key"]]
    assert not summary["whole_inventory_accounted"]


def test_partial_archive_reports_exact_missing_source_even_if_job_finished(
        planned_shards, tmp_path):
    first = planned_shards["jobs"][0]
    missing_sid = first["source_ids"][-1]
    path = fake_job_archive(tmp_path, first, job_num=50, missing_id=missing_sid)
    report = audit_full_inventory(planned_shards, archive_paths=[path])
    summary = report["summary"]
    assert missing_sid in summary["missing_source_ids"]
    assert first["job_key"] in summary["incomplete_job_keys"]
    assert not summary["whole_inventory_accounted"]


def test_job_metadata_mismatch_fails_closed(planned_shards, tmp_path):
    job = planned_shards["jobs"][0]
    args = dict(job["spider_args"], cohort="proven")
    path = fake_job_archive(
        tmp_path, job, job_num=30, args_override=args,
    )
    with pytest.raises(ValueError, match="scope does not match"):
        audit_full_inventory(planned_shards, archive_paths=[path])


def test_duplicate_archive_job_rejected(planned_shards, tmp_path):
    job = planned_shards["jobs"][0]
    path = fake_job_archive(tmp_path, job, job_num=35)
    with pytest.raises(ValueError, match="Duplicate job"):
        audit_full_inventory(planned_shards, archive_paths=[path, path])


def test_wrong_package_sha_never_meets_pinned_archive_gate(planned_shards, tmp_path):
    job = planned_shards["jobs"][0]
    path = fake_job_archive(tmp_path, job, job_num=40, package_sha="f" * 64)
    result = audit_full_inventory(planned_shards, archive_paths=[path])
    assert result["summary"]["package_pinned_and_verified"] is False
    assert result["summary"]["actual_package_fingerprints"] == ["f" * 64]


def test_quarantine_must_never_have_an_http_response(planned_shards, tmp_path):
    job = next(job for job in planned_shards["jobs"]
               if "v0_docs" in job["source_ids"])
    path = fake_job_archive(
        tmp_path, job, job_num=51, policy_fetch_violation=True,
    )
    with pytest.raises(ValueError, match="policy-restricted"):
        audit_full_inventory(planned_shards, archive_paths=[path])


def test_raw_460_items_can_be_inspected_but_never_verified(
        planned_shards, full_fake_archives, tmp_path):
    from scripts.archive_jobs import load_archive
    rows = []
    for path in full_fake_archives:
        _, items = load_archive(path)
        rows.extend(items)
    export = tmp_path / "dashboard-items.json"
    export.write_text(json.dumps(rows), encoding="utf-8")
    report = audit_full_inventory(planned_shards, items_paths=[export])
    summary = report["summary"]
    assert summary["accounted_source_count"] == 460
    assert summary["status"] == "raw_export_preliminary_not_verified"
    assert summary["verified_immutable_archives"] is False
    assert summary["publisher_evidence_accuracy_independently_verified"] is False
    assert summary["whole_inventory_accounted"] is False


def test_duplicate_source_in_raw_exports_is_not_silently_deduplicated(
        planned_shards, tmp_path):
    src = KNOWN[planned_shards["jobs"][0]["source_ids"][0]]
    row = {
        "source_id": src["id"], "source_url": src["url"],
        "provider": src["provider"], "category": src["category"],
        "status": "needs_review", "approved_for_advisor": False,
    }
    export = tmp_path / "duplicates.json"
    export.write_text(json.dumps([row, row]))
    with pytest.raises(ValueError, match="Repeated source"):
        audit_full_inventory(planned_shards, items_paths=[export])


def test_three_big_full_jobs_are_structurally_auditable(tmp_path):
    plan = build_full_inventory_plan(
        strategy="full", expected_package_sha256=PACKAGE_SHA,
    )
    archives = [
        fake_job_archive(tmp_path, job, job_num=i + 200)
        for i, job in enumerate(plan["jobs"])
    ]
    summary = audit_full_inventory(plan, archive_paths=archives)["summary"]
    assert summary["whole_inventory_accounted"] is True
    assert summary["verified_immutable_archives"] is True
    assert summary["reported_job_count"] == 3
