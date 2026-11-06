"""P23C1 synthetic-only archived Zyte 18/36 evidence binding regression.

These tests never make publisher requests or pretend a valid SHA-256 proves
actual publisher origin, human permissions, remote deploy or pricing accuracy.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
import agentfuse_crawlers.validation_access as access
from scripts.archive_jobs import archive_job, archive_path
from scripts.accession_cross_category_html import frozen_plan
from scripts.p23c1_zyte_canary_archive_gate import (
    audit_receipts, blank_receipts, prepare, write_audit,
)

NOW = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
NOTE = (
    "SYNTHETIC TEST ONLY: the actual owner, intended API product, publisher "
    "terms, robots policy, specific source and private HTML retention would "
    "need genuine independent human review before any Zyte publisher GET."
)


def _time(delta):
    return (NOW + delta).isoformat(timespec="seconds")


def _source(sid):
    return next(x for x in load_sources() if x["id"] == sid)


def _registry(source=None, *, scope="single_validation",
              decision="allowed_reviewed"):
    reviews = {}
    if source:
        host = source["url"].split("/")[2]
        allowed = decision == "allowed_reviewed"
        reviews[source["id"]] = {
            "source_url": source["url"],
            "category": source["category"],
            "decision": decision,
            "scopes": [scope] if allowed else [],
            "reviewed_by": "Synthetic Only Reviewer",
            "reviewed_at_utc": _time(timedelta(days=-2)),
            "expires_at_utc": _time(timedelta(days=2)),
            "ownership_evidence_url": source["url"],
            "publisher_access_policy_url": "https://" + host + "/terms",
            "robots_url": "https://" + host + "/robots.txt",
            "publisher_terms_reviewed": allowed,
            "robots_reviewed": allowed,
            "private_retention_reviewed": allowed,
            "evidence_note": NOTE,
        }
    result = {
        "schema_version": access.SCHEMA,
        "kind": access.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": reviews,
    }
    access.validate_access_registry(result, now=NOW)
    return result


def _slot(ledger, source_id, round_no, job_id):
    entry = next(x for x in ledger["rows"] if x["source_id"] == source_id)
    entry["rounds"][round_no - 1]["zyte_job_id"] = job_id


def _fake_archive(root, source, registry, job_id, *,
                  started_at=None, edits=None, close_reason="finished"):
    jobtime = started_at or _time(timedelta(minutes=-35))
    args = {
        "cohort": "all",
        "source_ids": source["id"],
        "collection_mode": "validation",
        "expected_manifest_sha256": manifest_sha256(),
        "expected_selection_ids_sha256": selection_ids_sha256([source]),
        "expected_source_registry_sha256": registry_revision_sha256(),
    }
    item = {
        "_key": job_id + "/0",
        "source_id": source["id"], "source_url": source["url"],
        "provider": source["provider"], "category": source["category"],
        "spider_name": {
            "documentation": "official_documentation",
            "pricing": "official_pricing",
            "changelog": "official_changelogs",
        }[source["category"]],
        "collection_mode": "validation",
        "validation_scope": "single_exact_source",
        "single_validation_access_required": True,
        "bulk_validation_required": False,
        "run_scope_explicit": True,
        "selection_source_count": 1,
        "selection_ids_sha256": selection_ids_sha256([source]),
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "bulk_access_registry_sha256":
            access.validation_access_revision_sha256(registry),
        "deployment_revision": package_fingerprint(),
        "zyte_job_id": job_id,
        "run_started_at_utc": jobtime,
        "status": "captured",
        "http_status": 200,
        "final_url": source["url"],
        "approved_for_advisor": False,
    }
    if edits:
        item.update(edits)
    def fake_metadata(*_args):
        return {
            "state": "finished", "spider": item["spider_name"],
            "close_reason": close_reason,
            "scrapystats": {"item_scraped_count": 1},
            "spider_args": args,
        }
    def fake_page(*_args):
        return [item]
    archive_job(job_id, root, api_key="SYNTHETIC_ONLY",
                fetch_metadata=fake_metadata, fetch_page=fake_page)
    return archive_path(root, job_id)


def test_blank_has_original_18_and_36_with_zero_fake_job_receipts(tmp_path):
    plan = frozen_plan()
    ledger = blank_receipts(plan)
    assert plan["selected_source_count"] == 18
    assert plan["source_round_denominator"] == 36
    assert ledger["frozen_plan_sha256"] == plan["plan_sha256"]
    assert ledger["expected_package_sha256"] == package_fingerprint()
    assert len(ledger["rows"]) == 18
    assert sum(len(r["rounds"]) for r in ledger["rows"]) == 36
    assert all(slot["zyte_job_id"] is None
               for r in ledger["rows"] for slot in r["rounds"])
    archive_root = tmp_path / "empty-archives"
    archive_root.mkdir()
    report, rows = audit_receipts(
        ledger, archive_root, now=NOW, access_registry=_registry(),
    )
    assert len(rows) == 36
    assert report["status"] == "NO_GO"
    assert report["original_selected_sources"] == 18
    assert report["original_source_round_denominator"] == 36
    assert report["source_rounds_with_immutable_item_archives"] == 0
    assert report["source_rounds_with_http200_item_candidate"] == 0
    assert report["sources_with_two_distinct_archived_jobs"] == 0
    assert report["network_requests_performed"] == report["zyte_jobs_created"] == 0
    assert report["human_gold_accuracy_measured"] is False
    assert report["publisher_permission_independently_authenticated"] is False
    assert all(r["approved_for_advisor"] is False for r in rows)
    assert report["report_sha256"] == access.digest({
        k: v for k, v in report.items() if k != "report_sha256"
    })


def test_private_prepare_only_writes_blank_plan_and_never_overwrites(tmp_path):
    out = tmp_path / "preparation"
    assert prepare(out) == out
    plan = json.loads((out / "frozen_p20a_plan.json").read_text())
    ledger = json.loads((out / "zyte_canary_job_receipts_BLANK.json").read_text())
    assert ledger == blank_receipts(plan)
    assert "NOT crawl approvals" in (out / "READ_ME_NO_CRAWL.txt").read_text()
    with pytest.raises((ValueError, FileExistsError, OSError)):
        prepare(out)


def test_two_self_consistent_synthetic_archives_never_claim_full_canary_go(tmp_path):
    plan = frozen_plan()
    ledger = blank_receipts(plan)
    source_id = plan["sources"][0]["source_id"]
    src = _source(source_id)
    registry = _registry(src)
    j1, j2 = "883514/1/801", "883514/1/802"
    _slot(ledger, source_id, 1, j1)
    _slot(ledger, source_id, 2, j2)
    archive_root = tmp_path / "archived"
    _fake_archive(
        archive_root, src, registry, j1,
        started_at=_time(timedelta(minutes=-35)),
    )
    _fake_archive(
        archive_root, src, registry, j2,
        started_at=_time(timedelta(minutes=-10)),
    )
    report, rows = audit_receipts(
        ledger, archive_root, now=NOW, access_registry=registry,
    )
    assert len(rows) == 36
    assert report["source_rounds_with_immutable_item_archives"] == 2
    assert report["source_rounds_with_http200_item_candidate"] == 2
    assert report["sources_with_two_distinct_archived_jobs"] == 1
    assert report["sources_with_two_http200_items"] == 1
    assert report["status"] == "NO_GO"
    assert report["remote_zyte_deployment_independently_attested"] is False
    assert report["requests_and_logs_independently_inspected"] is False
    assert report["original_publisher_html_bytes_supplied"] is False
    assert not report["two_round_canary_ready_for_full_inventory"]
    assert sum(r["archive_item_integrity_checked"] for r in rows) == 2
    results = [r for r in rows if r["source_id"] == source_id]
    assert len(results) == 2 and all(
        r["slot_state"] == "http200_item_observed_NOT_ORIGINAL_HTML_VERIFIED"
        for r in results
    )
    assert all(r["http_status"] == 200 for r in results)
    dest = write_audit(report, rows, tmp_path / "audit1")
    assert json.loads((dest / "zyte_canary_36_rounds_NO_GO.json").read_text()
                     )["source_rounds_with_immutable_item_archives"] == 2
    assert (dest / "all_36_rounds.csv").is_file()


def test_held_source_job_is_attrition_not_an_invalid_archive(tmp_path):
    src = _source(frozen_plan()["sources"][0]["source_id"])
    registry = _registry(src)
    ledger = blank_receipts()
    job = "883514/1/803"
    _slot(ledger, src["id"], 1, job)
    root = tmp_path / "a"
    _fake_archive(
        root, src, registry, job,
        edits={
            "status": "source_single_validation_not_approved",
            "http_status": None, "final_url": "",
        },
        close_reason="agentfuse_no_usable_sources",
    )
    report, _ = audit_receipts(
        ledger, root, access_registry=registry, now=NOW,
    )
    assert report["source_rounds_with_immutable_item_archives"] == 1
    assert report["source_rounds_with_http200_item_candidate"] == 0
    assert report["source_round_status_counts"]["held_item_no_publisher_response"] == 1


@pytest.mark.parametrize("tamper", [
    "missing_source", "extra_round", "wrong_round", "swap_source_id",
    "wrong_wave", "wrong_url", "foreign_job", "duplicate_job",
    "future_only_round2", "approval_claim", "wrong_package_pin",
])
def test_tampered_or_substituted_denominator_is_rejected(tmp_path, tamper):
    ledger = blank_receipts()
    source_id = ledger["rows"][0]["source_id"]
    if tamper == "missing_source":
        ledger["rows"].pop()
    elif tamper == "extra_round":
        ledger["rows"][0]["rounds"].append({"round": 3, "zyte_job_id": None})
    elif tamper == "wrong_round":
        ledger["rows"][0]["rounds"][0]["round"] = 2
    elif tamper == "swap_source_id":
        ledger["rows"][0]["source_id"] = "unselected_source"
    elif tamper == "wrong_wave":
        ledger["rows"][0]["wave"] = 2
    elif tamper == "wrong_url":
        ledger["rows"][0]["source_url"] = "https://evil.invalid/migrated"
    elif tamper == "foreign_job":
        ledger["rows"][0]["rounds"][0]["zyte_job_id"] = "../bad"
    elif tamper == "duplicate_job":
        _slot(ledger, source_id, 1, "883514/1/901")
        _slot(ledger, source_id, 2, "883514/1/901")
    elif tamper == "future_only_round2":
        _slot(ledger, source_id, 2, "883514/1/902")
    elif tamper == "approval_claim":
        ledger["approved_for_advisor"] = True
    elif tamper == "wrong_package_pin":
        ledger["expected_package_sha256"] = "f" * 64
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(ValueError):
        audit_receipts(ledger, root, now=NOW, access_registry=_registry())


@pytest.mark.parametrize("policy", [
    "not_reviewed", "bulk_scope_only", "prohibited_reviewed", "deferred",
])
def test_unapproved_source_archives_refused_even_if_operator_supplies_job(
        tmp_path, policy):
    src = _source(frozen_plan()["sources"][0]["source_id"])
    registry = (
        _registry() if policy == "not_reviewed"
        else _registry(
            src, scope=("bulk_validation" if policy == "bulk_scope_only"
                        else "single_validation"),
            decision=(policy if policy in {"prohibited_reviewed", "deferred"}
                      else "allowed_reviewed"),
        )
    )
    ledger = blank_receipts()
    _slot(ledger, src["id"], 1, "883514/1/915")
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(ValueError, match="without CURRENT reviewed"):
        audit_receipts(ledger, root, now=NOW, access_registry=registry)


@pytest.mark.parametrize("edit", [
    {"source_id": "other_source_id"},
    {"source_url": "https://evil.invalid/moved"},
    {"provider": "Wrong publisher"},
    {"collection_mode": "monitor"},
    {"validation_scope": "bulk_reviewed_plan_required"},
    {"single_validation_access_required": False},
    {"manifest_sha256": "f" * 64},
    {"selection_ids_sha256": "f" * 64},
    {"source_registry_sha256": "f" * 64},
    {"bulk_access_registry_sha256": "f" * 64},
    {"deployment_revision": "f" * 64},
    {"approved_for_advisor": True},
    {"run_scope_explicit": False},
    {"zyte_job_id": "883514/1/999"},
    {"http_status": "200"},
])
def test_internally_consistent_but_wrong_provenance_is_denied(
        tmp_path, edit):
    src = _source(frozen_plan()["sources"][0]["source_id"])
    registry = _registry(src)
    ledger = blank_receipts()
    job = "883514/1/920"
    _slot(ledger, src["id"], 1, job)
    root = tmp_path / "archive"
    # Some malformed changes are already rejected by archive_jobs, which is
    # equally correct; other changes are caught by the P23C1 scope gate.
    with pytest.raises(ValueError):
        _fake_archive(root, src, registry, job, edits=edit)
        audit_receipts(ledger, root, now=NOW, access_registry=registry)


def test_wrong_start_order_across_two_distinct_jobs_is_refused(tmp_path):
    src = _source(frozen_plan()["sources"][0]["source_id"])
    registry = _registry(src)
    ledger = blank_receipts()
    j1, j2 = "883514/1/931", "883514/1/932"
    _slot(ledger, src["id"], 1, j1)
    _slot(ledger, src["id"], 2, j2)
    root = tmp_path / "archive"
    _fake_archive(root, src, registry, j1,
                  started_at=_time(timedelta(minutes=-10)))
    _fake_archive(root, src, registry, j2,
                  started_at=_time(timedelta(minutes=-35)))
    with pytest.raises(ValueError, match="Second source round must start"):
        audit_receipts(ledger, root, now=NOW, access_registry=registry)


def test_review_approved_after_job_started_is_not_retroactive(tmp_path):
    src = _source(frozen_plan()["sources"][0]["source_id"])
    registry = _registry(src)
    ledger = blank_receipts()
    job = "883514/1/941"
    _slot(ledger, src["id"], 1, job)
    root = tmp_path / "archive"
    _fake_archive(root, src, registry, job,
                  started_at=_time(timedelta(days=-3)))
    with pytest.raises(ValueError, match="did not cover archived job start"):
        audit_receipts(ledger, root, now=NOW, access_registry=registry)


def test_altered_gzip_is_refused_even_for_matching_source(tmp_path):
    src = _source(frozen_plan()["sources"][0]["source_id"])
    registry = _registry(src)
    ledger = blank_receipts()
    job = "883514/1/951"
    _slot(ledger, src["id"], 1, job)
    root = tmp_path / "archive"
    folder = _fake_archive(root, src, registry, job)
    gzip_path = folder / "items.jsonl.gz"
    gzip_path.write_bytes(gzip_path.read_bytes() + b"forged")
    with pytest.raises(ValueError, match="checksum"):
        audit_receipts(ledger, root, now=NOW, access_registry=registry)


def test_symlink_archives_and_private_output_overwrite_rejected(tmp_path):
    ledger = blank_receipts()
    root = tmp_path / "empty"
    root.mkdir()
    report, rows = audit_receipts(
        ledger, root, access_registry=_registry(), now=NOW,
    )
    dest = write_audit(report, rows, tmp_path / "audit")
    assert dest.is_dir()
    with pytest.raises((ValueError, FileExistsError, OSError)):
        write_audit(report, rows, dest)
    link = tmp_path / "linked-root"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="non-symlink"):
        audit_receipts(ledger, link, access_registry=_registry(), now=NOW)
