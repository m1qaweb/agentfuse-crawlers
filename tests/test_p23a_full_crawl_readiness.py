"""P23A offline source census: synthetic policy claims are NOT real grants."""
import csv
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources, select_sources
import agentfuse_crawlers.validation_access as policy
from scripts.full_crawl_readiness import (
    FROZEN_MANIFEST_SHA256, build_readiness, write_readiness,
)

NOW = datetime.now(timezone.utc)
HUMAN = "Synthetic Test Reviewer"
NOTE = (
    "SYNTHETIC ONLY: this entry is NOT publisher authorization or real human "
    "review. A publisher owner, robots restrictions, terms, exact URL and "
    "private data retention would need independent operator review."
)


def _empty_access():
    return {
        "schema_version": policy.SCHEMA,
        "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {},
    }


def _empty_plans():
    return {
        "schema_version": policy.SCHEMA,
        "kind": policy.PLAN_KIND,
        "default_policy": "no_bulk_runs_authorized",
        "plans": {},
    }


def _stamp(delta):
    return (NOW + delta).isoformat(timespec="seconds")


def _review(source, *, expires=timedelta(days=5)):
    host = urlsplit(source["url"]).hostname
    return {
        "source_url": source["url"],
        "category": source["category"],
        "decision": "allowed_reviewed",
        "scopes": ["single_validation", "bulk_validation"],
        "reviewed_by": HUMAN,
        "reviewed_at_utc": _stamp(timedelta(days=-6) if expires.days < 0
                                  else timedelta(hours=-1)),
        "expires_at_utc": _stamp(expires),
        "ownership_evidence_url": source["url"],
        "publisher_access_policy_url": "https://" + host + "/terms",
        "robots_url": "https://" + host + "/robots.txt",
        "publisher_terms_reviewed": True,
        "robots_reviewed": True,
        "private_retention_reviewed": True,
        "evidence_note": NOTE,
    }


def _synthetic_packet():
    selected = select_sources("documentation", "all")[:3]
    access = _empty_access()
    for src in selected[:2]:
        access["reviews"][src["id"]] = _review(src)
    pid = "synthetic_p23a_bounded_001"
    plan = {
        "category": "documentation",
        "collection_mode": "validation",
        "cohort": "all",
        "source_ids": [s["id"] for s in selected],
        "authorized_source_ids": [s["id"] for s in selected[:2]],
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "access_registry_sha256": policy.validation_access_revision_sha256(access),
        "selection_ids_sha256": selection_ids_sha256(selected),
        "source_urls_sha256": policy._urls_digest(selected),
        "approved_by": HUMAN,
        "reviewed_at_utc": _stamp(timedelta(hours=-1)),
        "expires_at_utc": _stamp(timedelta(hours=3)),
        "max_primary_requests": 2,
        "max_redirects_per_source": 2,
        "purpose": "bounded_human_supervised_diagnostic",
        "publisher_policy_review_attested": True,
    }
    plans = _empty_plans()
    plans["plans"][pid] = plan
    return selected, access, plans, pid


def test_current_real_package_is_460_id_no_go_and_no_approvals():
    report, rows = build_readiness()
    c = report["counts"]
    assert manifest_sha256() == FROZEN_MANIFEST_SHA256
    assert c["configured_source_ids"] == len(rows) == 460
    assert report["expected_category_counts"] == {
        "changelog": 89, "documentation": 194, "pricing": 177,
    }
    assert c["technical_validation_eligible_NOT_permission"] == 457
    assert c["quarantined_or_lifecycle_held"] == 3
    assert c["publisher_review_records_present"] == 0
    assert c["current_bulk_review_attestations_NOT_legal_grants"] == 0
    assert c["packaged_reviewed_plan_count"] == 0
    assert c["locally_valid_plan_eligible_source_ids_NOT_remote_verified"] == 0
    assert c["actual_publisher_requests_authorized_by_this_report"] == 0
    assert c["frozen_canary_source_ids"] == 18
    assert c["frozen_canary_sources_with_current_single_review"] == 0
    assert report["status"] == report["supervised_diagnostic_status"] == "NO_GO"
    assert report["trusted_monitored_collection_status"] == "NO_GO"
    assert report["bulk_run_approved"] is False
    assert report["network_requests_performed"] == 0
    assert report["new_zyte_jobs"] == 0
    assert report["approved_for_advisor"] is False
    assert report["report_sha256"] == policy.digest({
        k: v for k, v in report.items() if k != "report_sha256"
    })
    assert report["all_source_ids_in_manifest_order"] == [
        s["id"] for s in load_sources()
    ]
    assert set(report["frozen_canary_source_ids"]) <= set(
        report["all_source_ids_in_manifest_order"]
    )
    assert len(set(report["all_source_ids_in_manifest_order"])) == 460
    held = {r["source_id"] for r in rows if r["source_disposition"] == "held_lifecycle"}
    assert held == {"v0_docs", "v0_pricing", "v0_changelog"}
    assert all(not r["planned_primary_source_get"] for r in rows)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "changed_url", "wrong_category"])
def test_manifest_drift_is_never_accepted_by_matching_a_lucky_count(mutation):
    src = deepcopy(load_sources())
    if mutation == "missing":
        src.pop()
    elif mutation == "duplicate":
        src[1]["id"] = src[0]["id"]
    elif mutation == "changed_url":
        src[0]["url"] += "/rewritten"
    else:
        src[0]["category"] = "pricing"
    with pytest.raises(ValueError, match="frozen 460-ID"):
        build_readiness(sources=src, access_registry=_empty_access(),
                        run_registry=_empty_plans(), now=NOW)


def test_synthetic_source_review_without_run_plan_is_a_hold_not_permission():
    src = select_sources("documentation", "all")[0]
    access = _empty_access()
    access["reviews"][src["id"]] = _review(src)
    report, rows = build_readiness(
        access_registry=access, run_registry=_empty_plans(), now=NOW,
    )
    one = next(row for row in rows if row["source_id"] == src["id"])
    assert one["bulk_scope_current"] is True
    assert one["source_disposition"] == "held_no_exact_reviewed_run_plan"
    assert report["counts"]["current_bulk_review_attestations_NOT_legal_grants"] == 1
    assert report["bulk_run_approved"] is False


def test_expired_or_denied_synthetic_review_never_authorizes_a_get():
    selected = select_sources("documentation", "all")[:2]
    access = _empty_access()
    access["reviews"][selected[0]["id"]] = _review(
        selected[0], expires=timedelta(days=-1),
    )
    denied = _review(selected[1])
    denied.update({
        "decision": "prohibited_reviewed",
        "scopes": [],
        "publisher_terms_reviewed": False,
        "robots_reviewed": False,
        "private_retention_reviewed": False,
    })
    access["reviews"][selected[1]["id"]] = denied
    report, rows = build_readiness(
        access_registry=access, run_registry=_empty_plans(), now=NOW,
    )
    by_id = {r["source_id"]: r for r in rows}
    assert by_id[selected[0]["id"]]["source_disposition"] == (
        "held_expired_publisher_review")
    assert by_id[selected[1]["id"]]["source_disposition"] == (
        "held_prohibited_reviewed")
    assert not by_id[selected[0]["id"]]["bulk_scope_current"]
    assert not by_id[selected[1]["id"]]["bulk_scope_current"]
    assert report["counts"]["expired_publisher_reviews"] == 1
    assert report["counts"]["locally_valid_plan_eligible_source_ids_NOT_remote_verified"] == 0


def test_actual_p21b_authorization_logic_is_used_but_no_remote_go_is_claimed():
    selected, access, plans, pid = _synthetic_packet()
    report, rows = build_readiness(
        access_registry=access, run_registry=plans, now=NOW,
    )
    matching = [r for r in rows if r["approved_local_plan_id"] == pid]
    assert {r["source_id"] for r in matching} == {
        selected[0]["id"], selected[1]["id"],
    }
    assert report["counts"]["locally_valid_plan_eligible_source_ids_NOT_remote_verified"] == 2
    assert report["counts"]["packaged_reviewed_plan_count"] == 1
    assert report["status"] == "NO_GO"
    assert report["deployed_zyte_fingerprint_independently_verified"] is False
    assert report["publisher_permission_independently_verified"] is False
    assert report["full_run_approved"] is False
    assert report["counts"]["actual_publisher_requests_authorized_by_this_report"] == 0


@pytest.mark.parametrize("breakage", [
    "expired_plan", "changed_manifest_sha", "wrong_order", "mismatched_access",
])
def test_stale_or_wrong_scoped_plan_is_held_without_publisher_fetch(breakage):
    selected, access, plans, pid = _synthetic_packet()
    plan = plans["plans"][pid]
    if breakage == "expired_plan":
        plan["expires_at_utc"] = _stamp(timedelta(minutes=-1))
    elif breakage == "changed_manifest_sha":
        plan["manifest_sha256"] = "f" * 64
    elif breakage == "wrong_order":
        plan["source_ids"] = list(reversed(plan["source_ids"]))
    else:
        plan["access_registry_sha256"] = "e" * 64
    report, rows = build_readiness(
        access_registry=access, run_registry=plans, now=NOW,
    )
    assert report["status"] == "NO_GO"
    assert "RUN_PLANS_REJECTED_BY_P21B" in report["blocker_codes"]
    assert report["invalid_or_stale_run_plan_holds"][0]["plan_id"] == pid
    assert all(not row["planned_primary_source_get"] for row in rows)
    assert report["counts"]["locally_valid_plan_eligible_source_ids_NOT_remote_verified"] == 0


def test_forged_access_registry_raises_instead_of_claiming_no_go_with_silent_skip():
    selected, access, plans, pid = _synthetic_packet()
    access["reviews"][selected[0]["id"]]["private_retention_reviewed"] = False
    with pytest.raises(ValueError, match="Positive bulk review"):
        build_readiness(access_registry=access, run_registry=plans, now=NOW)


def test_readiness_artifact_is_new_only_and_never_contains_private_human_notes(tmp_path):
    report, rows = build_readiness()
    target = tmp_path / "p23a"
    out = write_readiness(report, rows, target)
    assert out == target
    payload = json.loads((out / "full_crawl_readiness_NO_GO.json").read_text())
    assert payload["status"] == "NO_GO"
    with (out / "source_dispositions_460.csv").open(encoding="utf-8-sig") as f:
        actual = list(csv.DictReader(f))
    assert len(actual) == 460
    assert "reviewed_by" not in payload
    assert "raw_html" not in str(payload).lower()
    assert all("evidence_note" not in r for r in actual)
    with pytest.raises((FileExistsError, ValueError, OSError)):
        write_readiness(report, rows, target)
