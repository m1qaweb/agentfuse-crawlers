"""P23C3B first human/operator handoff tests: no network or approvals.

All positive access decisions in this file are explicitly fictional,
injected in memory and NEVER written into production policy registries.
"""
import csv
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

import agentfuse_crawlers.validation_access as access
import scripts.p23c3b_first_canary_operator_handoff as handoff
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.run_context import (
    manifest_sha256, selection_ids_sha256, package_fingerprint,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from scripts.accession_cross_category_html import frozen_plan

NOW = datetime.now(timezone.utc)
NOTE = (
    "SYNTHETIC TEST ONLY, NOT HUMAN PERMISSION: the source owner, robots, "
    "publisher site terms, intended crawler and original HTML retention "
    "must all be separately and genuinely checked by an operator."
)


def _time(delta=timedelta()):
    return (NOW + delta).isoformat(timespec="seconds")


def _source(sid):
    return next(s for s in load_sources() if s["id"] == sid)


def _empty_registry():
    return {
        "schema_version": access.SCHEMA,
        "kind": access.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {},
    }


def _synthetic_review(source, *, decision="allowed_reviewed",
                      scopes=("single_validation",), expires_days=5):
    host = urlsplit(source["url"]).hostname
    permitted = decision == "allowed_reviewed"
    return {
        "source_url": source["url"],
        "category": source["category"],
        "decision": decision,
        "scopes": list(scopes) if permitted else [],
        "reviewed_by": "Fictional Test Reviewer",
        "reviewed_at_utc": _time(timedelta(days=-8) if expires_days < 0
                                 else timedelta(hours=-1)),
        "expires_at_utc": _time(timedelta(days=expires_days)),
        "ownership_evidence_url": source["url"],
        "publisher_access_policy_url": "https://" + host + "/terms",
        "robots_url": "https://" + host + "/robots.txt",
        "publisher_terms_reviewed": permitted,
        "robots_reviewed": permitted,
        "private_retention_reviewed": permitted,
        "evidence_note": NOTE,
    }


def test_exact_three_frozen_sources_and_six_manual_jobs_are_held():
    report = handoff.build_handoff(
        access_registry=_empty_registry(), now=NOW,
    )
    plan = frozen_plan()
    assert report["original_plan_sha256"] == plan["plan_sha256"]
    assert report["original_frozen_source_count"] == 18
    assert report["original_frozen_source_round_denominator"] == 36
    assert report["initial_pilot_source_ids"] == [
        "kiro_docs", "gemini_api_pricing", "openai_api_changelog",
    ]
    assert report["initial_pilot_sources"] == 3
    assert report["initial_pilot_manual_job_specs"] == 6
    assert report["source_policy_status_counts"] == {
        "single_source_policy_not_reviewed": 3,
    }
    assert report["local_reviewed_single_validation_sources_NOT_PERMISSION"] == 0
    assert report["status"] == "NO_GO_PENDING_REAL_SOURCE_REVIEW_AND_OPERATOR"
    assert report["execution_permitted"] is False
    assert report["publisher_permission_independently_authenticated"] is False
    assert report["remote_zyte_deployment_independently_verified"] is False
    assert report["operator_cost_budget_approved"] is False
    assert report["publisher_network_requests_performed"] == 0
    assert report["canary_jobs_started"] == 0
    assert report["source_access_registry_edited"] is False
    assert report["approved_for_advisor"] is False
    assert report["report_sha256"] == access.digest({
        k: v for k, v in report.items() if k != "report_sha256"
    })
    source_ids = [row["source_id"] for row in report["sources"]]
    assert source_ids == list(handoff.PILOT_SOURCE_IDS)
    assert [row["category"] for row in report["sources"]] == [
        "documentation", "pricing", "changelog",
    ]
    assert [job["source_id"] for job in report["jobs"]] == source_ids * 2
    assert [job["round"] for job in report["jobs"]] == [1] * 3 + [2] * 3
    for row in report["sources"]:
        assert row["human_operator_decision"] == "PENDING_INDEPENDENT_HUMAN_REVIEW"
        assert row["human_terms_review"] == "NOT_ATTESTED_BY_THIS_PACKET"
        assert row["robots_candidate_url"] == (
            "https://" + urlsplit(row["source_url"]).hostname + "/robots.txt"
        )
    for job in report["jobs"]:
        sid = job["source_id"]
        src = _source(sid)
        assert job["source_policy_gate"] == "HELD_BY_P23B_SOURCE_POLICY"
        assert job["operator_canary_authorization"] == "NOT_AUTHORIZED_BY_PACKET"
        assert job["zyte_job_id"] is None
        assert job["advisor_approved"] is False
        assert job["spider_args"] == {
            "cohort": "all",
            "source_ids": sid,
            "collection_mode": "validation",
            "expected_manifest_sha256": manifest_sha256(),
            "expected_selection_ids_sha256": selection_ids_sha256([src]),
            "expected_source_registry_sha256": registry_revision_sha256(),
        }


def test_public_policy_research_is_source_specific_and_never_permission():
    report = handoff.build_handoff(access_registry=_empty_registry(), now=NOW)
    rows = {row["source_id"]: row for row in report["sources"]}
    assert set(rows) == set(handoff.PILOT_SOURCE_IDS)
    assert all(row["public_policy_research_as_of"] == "2026-11-07"
               for row in rows.values())
    assert rows["kiro_docs"]["public_policy_research_status"] == (
        "HIGH_RISK_LINKED_AWS_SITE_TERMS"
    )
    assert rows["kiro_docs"]["public_policy_evidence_url"] == (
        "https://aws.amazon.com/terms/"
    )
    assert rows["gemini_api_pricing"]["public_policy_research_status"] == (
        "ROBOTS_PUBLIC_READABLE_RIGHTS_UNRESOLVED"
    )
    assert rows["openai_api_changelog"]["public_policy_research_status"] == (
        "ROBOTS_UNVERIFIED_TERMS_UNRESOLVED"
    )
    assert all(row["human_terms_review"] == "NOT_ATTESTED_BY_THIS_PACKET"
               and row["human_operator_decision"] ==
               "PENDING_INDEPENDENT_HUMAN_REVIEW"
               and row["local_single_scope_record_present"] is False
               for row in rows.values())
    assert all(job["operator_canary_authorization"] == "NOT_AUTHORIZED_BY_PACKET"
               and job["zyte_job_id"] is None for job in report["jobs"])
    assert report["execution_permitted"] is False


def test_actual_current_registry_never_promotes_into_zyte_operator_approval():
    # Future real publisher reviews may appear; the handoff still cannot
    # claim human permission, remote deploy verification, or a crawl GO.
    report = handoff.build_handoff()
    assert report["execution_permitted"] is False
    assert report["canary_jobs_started"] == 0
    assert report["remote_zyte_deployment_independently_verified"] is False
    assert report["local_package_sha256_NOT_REMOTE_PROOF"] == package_fingerprint()
    assert report["monitoring_enabled"] is False


def test_one_fictional_positive_record_only_counts_local_schema_not_permission():
    data = _empty_registry()
    source = _source("kiro_docs")
    data["reviews"][source["id"]] = _synthetic_review(source)
    report = handoff.build_handoff(access_registry=data, now=NOW)
    assert report["local_reviewed_single_validation_sources_NOT_PERMISSION"] == 1
    assert report["source_policy_status_counts"] == {
        "git_reviewed_source_single_validation_access": 1,
        "single_source_policy_not_reviewed": 2,
    }
    assert report["jobs"][0]["source_policy_gate"] == (
        "local_p23b_attestation_NOT_EXTERNAL_PERMISSION"
    )
    assert report["jobs"][3]["source_policy_gate"] == (
        "local_p23b_attestation_NOT_EXTERNAL_PERMISSION"
    )
    assert all(job["operator_canary_authorization"] == "NOT_AUTHORIZED_BY_PACKET"
               for job in report["jobs"])
    assert all(job["zyte_job_id"] is None for job in report["jobs"])
    assert report["publisher_permission_independently_authenticated"] is False
    assert report["operator_cost_budget_approved"] is False
    assert report["execution_permitted"] is False


@pytest.mark.parametrize("outcome,reason", [
    ("expired", "single_source_policy_review_expired"),
    ("deferred", "single_source_policy_denied_or_deferred"),
    ("denied", "single_source_policy_denied_or_deferred"),
    ("bulk_only", "single_source_review_scope_not_approved"),
])
def test_missing_or_expired_single_scope_never_mints_a_canary_job(outcome, reason):
    src = _source("kiro_docs")
    registry = _empty_registry()
    if outcome == "expired":
        review = _synthetic_review(src, expires_days=-1)
    elif outcome == "deferred":
        review = _synthetic_review(src, decision="deferred")
    elif outcome == "denied":
        review = _synthetic_review(src, decision="prohibited_reviewed")
    else:
        review = _synthetic_review(src, scopes=("bulk_validation",))
    registry["reviews"][src["id"]] = review
    report = handoff.build_handoff(access_registry=registry, now=NOW)
    assert report["source_policy_status_counts"][reason] == 1
    assert report["sources"][0]["publisher_access_registry_status"] == reason
    assert report["jobs"][0]["source_policy_gate"] == "HELD_BY_P23B_SOURCE_POLICY"
    assert report["jobs"][3]["zyte_job_id"] is None
    assert report["local_reviewed_single_validation_sources_NOT_PERMISSION"] == 0
    assert report["execution_permitted"] is False


@pytest.mark.parametrize("mutation", [
    "wrong_owner", "wrong_category", "future_attestation",
    "missing_robots_review", "fabricated_scope",
])
def test_forged_source_review_is_rejected_at_production_policy_boundary(mutation):
    src = _source("gemini_api_pricing")
    registry = _empty_registry()
    review = _synthetic_review(src)
    if mutation == "wrong_owner":
        review["source_url"] = "https://evil.invalid/pricing"
    elif mutation == "wrong_category":
        review["category"] = "documentation"
    elif mutation == "future_attestation":
        review["reviewed_at_utc"] = _time(timedelta(days=1))
    elif mutation == "missing_robots_review":
        review["robots_reviewed"] = False
    else:
        review["scopes"] = ["single_validation", "single_validation"]
    registry["reviews"][src["id"]] = review
    with pytest.raises(ValueError):
        handoff.build_handoff(access_registry=registry, now=NOW)


def test_no_source_substitution_if_wave_changes(monkeypatch):
    monkeypatch.setattr(handoff, "PILOT_SOURCE_IDS", (
        "supabase_docs", "gemini_api_pricing", "openai_api_changelog",
    ))
    with pytest.raises(ValueError, match="first-wave"):
        handoff.build_handoff(
            access_registry=_empty_registry(), now=NOW,
        )


def test_operator_artifacts_new_only_and_no_private_approval_claim(tmp_path):
    report = handoff.build_handoff(
        access_registry=_empty_registry(), now=NOW,
    )
    out = tmp_path / "first"
    handoff.write_handoff(report, out)
    assert (out / "READ_ME_NO_CRAWL.txt").is_file()
    payload = json.loads((out / "first_3_source_canary_handoff_NO_GO.json").read_text())
    assert payload == report
    with (out / "human_first_source_review_queue_NOT_APPROVED.csv").open(
            encoding="utf-8-sig") as f:
        queue = list(csv.DictReader(f))
    assert len(queue) == 3
    assert all(row["human_robots_review"] == "NOT_ATTESTED_BY_THIS_PACKET"
               for row in queue)
    with (out / "six_manual_zyte_job_specs_NOT_AUTHORIZED.csv").open(
            encoding="utf-8-sig") as f:
        jobs = list(csv.DictReader(f))
    assert len(jobs) == 6
    assert all(row["operator_canary_authorization"] ==
               "NOT_AUTHORIZED_BY_PACKET" for row in jobs)
    assert all(row["source_policy_gate"] == "HELD_BY_P23B_SOURCE_POLICY"
               for row in jobs)
    assert "Fictional Test Reviewer" not in (out / "READ_ME_NO_CRAWL.txt").read_text()
    with pytest.raises((FileExistsError, OSError, ValueError)):
        handoff.write_handoff(report, out)
    tampered = {**report, "execution_permitted": True}
    with pytest.raises(ValueError):
        handoff.write_handoff(tampered, tmp_path / "bad")


def test_operator_packet_does_not_mutate_registry_across_multiple_builds():
    registry = _empty_registry()
    snapshot = json.dumps(registry, sort_keys=True)
    for _ in range(3):
        report = handoff.build_handoff(access_registry=registry, now=NOW)
        assert report["publisher_network_requests_performed"] == 0
    assert json.dumps(registry, sort_keys=True) == snapshot
