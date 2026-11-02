"""PR08 offline canary planning/verification and strict human quality evidence."""

import csv
import json
from pathlib import Path

import pytest

from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import archive_job
from scripts.canary_rollout import (
    MAX_CANARY_SOURCES, build_canary_plan, write_canary_plan,
)
from scripts.quality_gates import grade_release, score_human_gold
from scripts.replay_gold import replay_synthetic
from scripts.score_canaries import load_mapping, score_canaries, write_score


BY_ID = {s["id"]: s for s in load_sources()}


def test_dry_run_canary_plan_uses_exact_ids_twice_and_never_calls_network(tmp_path):
    ids = ["openai_api_changelog", "openai_api_pricing", "openai_api_docs"]
    plan = build_canary_plan(ids)
    assert plan["execution_permitted"] is False
    assert plan["network_requests_performed"] == 0
    assert plan["approved_for_advisor"] is False
    assert plan["total_expected_jobs"] == 6
    assert plan["source_count"] == 3
    assert all(job["execution_status"].startswith("not_scheduled")
               for job in plan["jobs"])
    assert {(job["source_id"], job["round"]) for job in plan["jobs"]} == {
        (sid, round_number) for sid in ids for round_number in (1, 2)
    }
    for job in plan["jobs"]:
        assert job["spider_args"]["cohort"] == "all"
        assert job["spider_args"]["source_ids"] == job["source_id"]
        assert job["spider_args"]["collection_mode"] == "validation"
        assert len(job["spider_args"]["expected_manifest_sha256"]) == 64
        assert len(job["spider_args"]["expected_selection_ids_sha256"]) == 64
        assert len(job["spider_args"]["expected_source_registry_sha256"]) == 64
    assert all(x["collection_permission_review_required"]
               for x in plan["sources"])
    write_canary_plan(plan, tmp_path)
    files = list(tmp_path.iterdir())
    assert {x.name for x in files} == {"canary_plan.json", "manual_job_args.csv"}
    parsed = json.loads((tmp_path / "canary_plan.json").read_text())
    assert parsed["jobs"] == plan["jobs"]
    assert len(list(csv.DictReader((tmp_path / "manual_job_args.csv").open()))) == 6


@pytest.mark.parametrize("bad", [
    "v0_docs", "v0_pricing", "v0_changelog",
    "openai_api_docs,openai_api_docs", "fake_vendor_source", "",
])
def test_canary_block_quarantine_duplicates_unknown_and_empty(bad):
    with pytest.raises(ValueError):
        build_canary_plan(bad)


def test_canary_hard_cap_and_no_implicit_all_460():
    ids = [s["id"] for s in load_sources() if s["category"] == "changelog"][:10]
    with pytest.raises(ValueError, match="1-9"):
        build_canary_plan(ids)
    with pytest.raises(ValueError, match="Explicit"):
        build_canary_plan(None)


def _synthetic_canary_archive(tmp_path, plan, round_number, *, job_id=None,
                              status="captured", override_args=None,
                              finished_time=None, policy_status="not_reviewed"):
    job_spec = next(job for job in plan["jobs"] if job["round"] == round_number)
    source = BY_ID[job_spec["source_id"]]
    job_id = job_id or f"883514/1/{100 + round_number}"
    row = {
        "_key": f"{job_id}/0", "source_id": source["id"],
        "source_url": source["url"], "provider": source["provider"],
        "category": source["category"], "status": status,
        "content_sha256": "page-hash" if status == "captured" else "",
        "schema_version": "2.1", "approved_for_advisor": False,
        "review_status": "unverified", "source_cohort": "proven",
        "source_lifecycle_state": "needs_validation",
        "source_policy_status": policy_status,
        "collection_mode": "validation",
        "zyte_job_id": job_id, "spider_name": job_spec["spider"],
        "requested_cohort": "all", "selection_source_count": 1,
        "selection_ids_sha256": job_spec["spider_args"]["expected_selection_ids_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "source_registry_sha256": plan["source_registry_sha256"],
        "run_started_at_utc": "2026-10-31T09:00:00+00:00",
        "fetched_at_utc": "2026-10-31T09:05:00+00:00",
        "release_events_schema": "1.1", "release_window_complete": True,
        "release_event_evidence_lost": False,
        "release_event_identity_collision": False,
        "release_recent_body_loss_count": 0,
        "release_events": [{
            "event_id": "example", "body_sha256": "body-hash",
            "published_at": "2026-10-30", "title": "Example change",
            "version": "1.2.0",
        }],
    }
    metadata = {
        "state": "finished", "spider": job_spec["spider"],
        "close_reason": "finished",
        "finished_time": finished_time or (1793440000000 + round_number * 100000),
        "deploy_id": 30, "version": "deadbeef",
        "spider_args": override_args or job_spec["spider_args"],
        "scrapystats": {"item_scraped_count": 1, "memusage/max": 155000000},
    }
    target, _, _ = archive_job(
        job_id, tmp_path, api_key="test-key",
        fetch_metadata=lambda *_: metadata,
        fetch_page=lambda *_: [row],
    )
    return target


def test_two_realistic_mock_archives_are_diagnostic_not_approved(tmp_path):
    plan = build_canary_plan(["openai_api_changelog"])
    one = _synthetic_canary_archive(tmp_path, plan, 1)
    two = _synthetic_canary_archive(tmp_path, plan, 2)
    result = score_canaries(plan, {
        ("openai_api_changelog", 1): one, ("openai_api_changelog", 2): two,
    })
    assert result["expected_jobs"] == 2
    assert result["observed_archives"] == 2
    assert result["usable_diagnostic_captures"] == 2
    assert result["source_accounting_complete"] is True
    assert result["reviewed_collection_eligible_sources"] == 0
    assert result["reviewed_eligible_usable_rate"] is None
    assert result["two_round_95pct_gate"] is False
    assert result["policy_violation_count"] == 0
    assert result["approved_for_advisor"] is False
    write_score(result, tmp_path / "report")
    assert (tmp_path / "report/canary_score.json").exists()
    assert (tmp_path / "report/canary_source_outcomes.csv").exists()


def test_missing_second_canary_is_visible_and_blocks_source_accounting(tmp_path):
    plan = build_canary_plan("openai_api_changelog")
    first = _synthetic_canary_archive(tmp_path, plan, 1)
    result = score_canaries(plan, {("openai_api_changelog", 1): first})
    assert result["observed_archives"] == 1
    assert result["archive_mapping_complete"] is False
    assert result["source_accounting_complete"] is False
    assert [x["status"] for x in result["outcomes"]] == ["captured", "missing_archive"]
    assert result["two_round_95pct_gate"] is False


def test_unexpected_job_args_never_pass_as_correct_canary(tmp_path):
    plan = build_canary_plan("openai_api_changelog")
    modified = dict(plan["jobs"][0]["spider_args"], cohort="proven")
    one = _synthetic_canary_archive(
        tmp_path, plan, 1, override_args=modified
    )
    report = score_canaries(plan, {("openai_api_changelog", 1): one})
    assert report["outcomes"][0]["job_identity_valid"] is False
    assert report["outcomes"][0]["usable"] is False


def test_duplicate_completed_job_id_cannot_count_as_two_independent_rounds(tmp_path):
    plan = build_canary_plan("openai_api_changelog")
    one = _synthetic_canary_archive(tmp_path, plan, 1)
    report = score_canaries(plan, {
        ("openai_api_changelog", 1): one,
        ("openai_api_changelog", 2): one,
    })
    assert report["duplicate_job_id"] is True
    assert report["source_accounting_complete"] is False


def test_out_of_order_finished_timestamps_reject_two_round_canary(tmp_path):
    plan = build_canary_plan("openai_api_changelog")
    first = _synthetic_canary_archive(
        tmp_path, plan, 1, finished_time=1793450000000
    )
    second = _synthetic_canary_archive(
        tmp_path, plan, 2, finished_time=1793440000000
    )
    result = score_canaries(plan, {
        ("openai_api_changelog", 1): first,
        ("openai_api_changelog", 2): second,
    })
    assert result["strict_round_order"] is False
    assert result["two_round_95pct_gate"] is False


def test_policy_warning_prevents_using_captured_source_as_healthy(tmp_path):
    plan = build_canary_plan("openai_api_changelog")
    first = _synthetic_canary_archive(
        tmp_path, plan, 1, policy_status="unresolved"
    )
    second = _synthetic_canary_archive(tmp_path, plan, 2)
    result = score_canaries(plan, {
        ("openai_api_changelog", 1): first,
        ("openai_api_changelog", 2): second,
    })
    assert result["policy_violation_count"] == 1
    assert result["usable_diagnostic_captures"] == 1
    assert result["two_round_95pct_gate"] is False


def test_canary_archive_map_parser_rejects_duplicate_and_bad_round(tmp_path):
    file = tmp_path / "map.csv"
    file.write_text(
        "source_id,round,archive_path\n"
        "openai_api_changelog,1,/tmp/job-one\n"
        "openai_api_changelog,1,/tmp/job-two\n"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_mapping(file)
    file.write_text(
        "source_id,round,archive_path\n"
        "openai_api_changelog,3,/tmp/job-three\n"
    )
    with pytest.raises(ValueError, match="invalid canary"):
        load_mapping(file)


def test_release_gate_fails_closed_without_independent_gold_or_live_canaries():
    synthetic = replay_synthetic()
    result = grade_release(synthetic=synthetic)
    assert result["hard_gate_count"] == 7
    assert result["hard_gates_passed"] == 1
    assert result["checks"]["archive_bound_human_gold"] is False
    assert result["checks"]["blind_dual_review_publisher_gold"] is False
    assert result["status"] == "blocked_pending_evidence_or_quality"
    assert result["deployment_authorized"] is False
    assert result["advisor_fact_approvals"] == 0


def _human_gold_template():
    import copy
    pricing_src = BY_ID["openai_api_pricing"]
    release_src = BY_ID["openai_api_changelog"]
    dims = {
        "amount": "1.50", "currency": "USD",
        "billing_unit": "per_1m_tokens", "model_or_service": "Model Alpha",
        "region": "Global", "tier_or_plan": "Standard",
        "price_dimension": "input",
        "service_mode": None, "effective_from": None, "effective_until": None,
    }
    pricing = []
    for i in range(200):
        pricing.append({
            "case_id": f"rate-{i}", "source_id": pricing_src["id"],
            "source_url": pricing_src["url"], "evidence_url": pricing_src["url"],
            "job_id": "883514/1/200", "approved_for_advisor": False,
            "observation_id": f"{i:032x}",
            "expected": copy.deepcopy(dims),
            "observed": dict(dims, comparable_candidate=True),
        })
    dating = [{
        "case_id": f"date-{i}", "source_id": release_src["id"],
        "source_url": release_src["url"], "evidence_url": release_src["url"],
        "job_id": "883514/1/201", "approved_for_advisor": False,
        "event_id": release_src["id"] + ":" + f"{i:024x}",
        "expected_day": "2026-10-31", "observed_day": "2026-10-31",
    } for i in range(100)]
    return {
        "schema_version": "1.0", "origin": "human_annotated_official_source_evidence",
        "synthetic_only": False, "approved_for_advisor": False,
        "reviewed_by": "example-human-reviewer", "reviewed_at_utc": "2026-10-31T09:00:00Z",
        "pricing_rows": pricing, "date_rows": dating,
        "negative_rate_rows": [{
            "case_id": "negative-rate-1", "source_id": pricing_src["id"],
            "source_url": pricing_src["url"], "evidence_url": pricing_src["url"],
            "job_id": "883514/1/200", "approved_for_advisor": False,
            "expected_comparable": False, "observed_comparable": False,
        }],
        "change_safety_rows": [{
            "case_id": "first-baseline-1", "source_id": release_src["id"],
            "source_url": release_src["url"], "evidence_url": release_src["url"],
            "job_id": "883514/1/201", "approved_for_advisor": False,
            "scenario": "first_baseline", "observed_new_release_alert": False,
        }],
    }


def test_200_annotated_rate_and_100_date_cases_are_scored_but_not_auto_approved():
    # This is a structure-only synthetic test of FUTURE human review input,
    # NOT a genuine independently reviewed vendor accuracy benchmark.
    gold = _human_gold_template()
    score = score_human_gold(gold)
    assert score["pricing_examples"] == 200
    assert score["pricing_accuracy"] == 1.0
    assert score["date_examples"] == 100
    assert score["date_accuracy"] == 1.0
    assert score["false_latest_date_count"] == 0
    result = grade_release(
        synthetic=replay_synthetic(), human_gold=gold, canaries=None
    )
    assert result["status"] == "blocked_pending_evidence_or_quality"
    assert result["checks"]["archive_bound_human_gold"] is False
    assert result["deployment_authorized"] is False


def test_gold_blocks_wrong_currency_unit_missing_price_and_false_latest():
    gold = _human_gold_template()
    gold["pricing_rows"][0]["observed"]["currency"] = "EUR"
    gold["pricing_rows"][1]["observed"]["billing_unit"] = None
    gold["date_rows"][0]["expected_day"] = None
    score = score_human_gold(gold)
    assert score["pricing_correct"] == 198
    assert score["false_latest_date_count"] == 1
    result = grade_release(human_gold=gold)
    assert result["checks"]["independent_pricing_gold"] is True  # 198/200 = 99%
    assert result["checks"]["independent_date_gold"] is False
    assert result["status"] == "blocked_pending_evidence_or_quality"


def test_forged_human_gold_cannot_claim_synthetic_as_reviewed():
    gold = _human_gold_template()
    gold["synthetic_only"] = True
    with pytest.raises(ValueError, match="provenance"):
        score_human_gold(gold)
    gold = _human_gold_template()
    gold["reviewed_by"] = ""
    with pytest.raises(ValueError, match="reviewer"):
        score_human_gold(gold)
    gold = _human_gold_template()
    gold["pricing_rows"][0]["source_url"] = "https://evil.invalid/pricing"
    with pytest.raises(ValueError, match="official manifest"):
        score_human_gold(gold)
    gold = _human_gold_template()
    gold["pricing_rows"][1]["case_id"] = gold["pricing_rows"][0]["case_id"]
    with pytest.raises(ValueError, match="repeated"):
        score_human_gold(gold)
