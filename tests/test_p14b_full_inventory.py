"""P14B: entire 460-source plan and read-only immutable archive audits.

Synthetic job bytes are used to test accounting logic, not provider truth.
No test makes a network call, creates an actual Zyte run or approves facts.
"""

from copy import deepcopy
import json

import pytest

from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.source_lifecycle import collection_decision, source_lifecycle
from scripts.archive_jobs import archive_job, load_archive
from scripts.real_gold_binding import (
    load_bound_archives, prepare_review_candidates, bind_human_gold,
)
from scripts.quality_gates import grade_release
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
            "source_policy_status": source_lifecycle(src)["policy_status"],
            "source_lifecycle_state": source_lifecycle(src)["state"],
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
        if sid == "openai_api_pricing":
            row["pricing_observations"] = [{
                "observation_id": "0" * 32,
                "normalized_amount_decimal": "1.50",
                "raw_displayed_price": "USD 1.50",
                "source_url": src["url"],
                "currency": "USD",
                "billing_unit": "per_1m_tokens",
                "model_or_service": "Synthetic Model Alpha",
                "region": "Global",
                "tier_or_plan": "Standard",
                "price_dimension": "input",
                "service_mode": None,
                "effective_from": None, "effective_until": None,
                "comparable_candidate": True,
                "approved_for_advisor": False,
            }, {
                "observation_id": "1" * 32,
                "normalized_amount_decimal": None,
                "raw_displayed_price": "$1.50",
                "source_url": src["url"],
                "currency": None,
                "billing_unit": "per_1m_tokens",
                "model_or_service": "Synthetic Model Alpha",
                "region": None,
                "tier_or_plan": None,
                "price_dimension": "input",
                "service_mode": None,
                "effective_from": None, "effective_until": None,
                "comparable_candidate": False,
                "approved_for_advisor": False,
            }]
        if sid == "openai_api_changelog":
            row["release_events"] = [{
                "event_id": sid + ":" + "a" * 24,
                "body_sha256": "b" * 64,
                "title": "Synthetic API change",
                "published_at": "2026-10-30",
                "permalink": src["url"],
                "approved_for_advisor": False,
            }]
        if sid == "openai_api_docs":
            row["documentation_topic_candidates"] = [{
                "candidate_id": "c" * 24,
                "topic_hint": "authentication",
                "section_id": "authentication",
                "section_sha256": "d" * 64,
                "excerpt": "Synthetic documentation snippet for regression only.",
            }]
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


def test_batch_archives_require_exact_plan_for_real_gold(
        planned_shards, full_fake_archives):
    with pytest.raises(ValueError, match="one explicitly scoped"):
        load_bound_archives([full_fake_archives[0]])
    rows, jobs, sha = load_bound_archives(
        full_fake_archives, full_inventory_plan=planned_shards,
    )
    assert sha == PACKAGE_SHA
    assert len(jobs) == 20
    # Three publisher-blocked sources remain present in the coverage audit
    # but must not count as independently reviewable gold observations.
    assert len(rows) == 457
    assert not any(sid.startswith("v0_") for sid, _ in rows)


def test_full_batch_campaign_generates_diverse_unreviewed_gold_queue(
        planned_shards, full_fake_archives):
    packet = prepare_review_candidates(
        full_fake_archives, full_inventory_plan=planned_shards,
    )
    assert packet["verified_immutable_archive_count"] == 20
    assert packet["human_review_completed"] is False
    assert packet["not_for_release_quality_gates"] is True
    assert packet["independently_verified_vendor_facts"] == 0
    assert any(x["source_id"] == "openai_api_pricing"
               for x in packet["samples"]["pricing"])
    assert any(x["source_id"] == "openai_api_changelog"
               for x in packet["samples"]["release_dates"])
    assert any(x["source_id"] == "openai_api_docs"
               for x in packet["samples"]["documentation"])


def _synthetic_gold_from_campaign(plan, archives):
    packet = prepare_review_candidates(archives, full_inventory_plan=plan)
    price = next(
        x for x in packet["samples"]["pricing"]
        if x["source_id"] == "openai_api_pricing" and
        x["observation_id"] == "0" * 32
    )
    negative = next(
        x for x in packet["samples"]["pricing"]
        if x["source_id"] == "openai_api_pricing" and
        x["observation_id"] == "1" * 32
    )
    release = next(
        x for x in packet["samples"]["release_dates"]
        if x["source_id"] == "openai_api_changelog"
    )
    price_expected = dict(price["observed"])
    price_expected.pop("comparable_candidate")
    def base(case_id, sample):
        return {
            "case_id": case_id,
            "source_id": sample["source_id"],
            "source_url": sample["source_url"],
            "evidence_url": sample["source_url"],
            "job_id": sample["job_id"],
            "approved_for_advisor": False,
            "evidence_review_note": (
                "Invented synthetic regression label: not a verified publisher fact."
            ),
        }
    return {
        "schema_version": "1.0",
        "origin": "human_annotated_official_source_evidence",
        "synthetic_only": False,  # Synthetic TEST contract only.
        "approved_for_advisor": False,
        "reviewed_by": "Synthetic CI annotator",
        "reviewed_at_utc": "2026-11-01T19:00:00+00:00",
        "expected_package_sha256": PACKAGE_SHA,
        "pricing_rows": [{
            **base("price-synthetic-1", price),
            "observation_id": price["observation_id"],
            "expected": price_expected,
            "observed": price["observed"],
        }],
        "negative_rate_rows": [{
            **base("negative-synthetic-1", negative),
            "observation_id": negative["observation_id"],
            "expected_comparable": False,
            "observed_comparable": False,
        }],
        "date_rows": [{
            **base("date-synthetic-1", release),
            "event_id": release["event_id"],
            "event_body_sha256": release["event_body_sha256"],
            "expected_day": release["observed_day"],
            "observed_day": release["observed_day"],
        }],
        "change_safety_rows": [{
            **base("baseline-synthetic-1", release),
            "scenario": "first_baseline",
            "observed_new_release_alert": False,
        }],
    }


def test_batch_gold_binding_checks_real_archive_without_re_crawling(
        planned_shards, full_fake_archives):
    annotations = _synthetic_gold_from_campaign(
        planned_shards, full_fake_archives,
    )
    bound = bind_human_gold(
        annotations, full_fake_archives,
        full_inventory_plan=planned_shards,
    )
    assert bound["binding_complete"] is True
    assert bound["pricing_cases_bound"] == 1
    assert bound["negative_cases_bound"] == 1
    assert bound["date_cases_bound"] == 1
    assert bound["change_cases_bound"] == 1
    assert bound["full_inventory_plan_sha256"] == planned_shards["plan_sha256"]
    assert bound["independent_publisher_truth_confirmed"] is False
    quality = grade_release(
        human_gold=annotations, gold_archives=full_fake_archives,
        gold_inventory_plan=planned_shards,
    )
    assert quality["checks"]["archive_bound_human_gold"] is True
    assert quality["checks"]["independent_pricing_gold"] is False
    assert quality["status"] == "blocked_pending_evidence_or_quality"
    assert quality["deployment_authorized"] is False


def test_batch_gold_binding_rejects_forged_plan_package(
        planned_shards, full_fake_archives):
    plan = deepcopy(planned_shards)
    plan["expected_package_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        load_bound_archives(full_fake_archives, full_inventory_plan=plan)


def test_forged_policy_state_in_an_archived_item_is_rejected(
        planned_shards, tmp_path):
    sid = "kiro_docs"  # current registry: degraded, not needs_validation
    job = next(job for job in planned_shards["jobs"]
               if sid in job["source_ids"])
    path = fake_job_archive(tmp_path, job, job_num=79)
    envelope, rows = load_archive(path)
    assert next(x for x in rows if x["source_id"] == sid)[
        "source_lifecycle_state"
    ] == "degraded"

    # We cannot corrupt immutable on-disk archives without their checksums
    # failing, so fake an Items-only input: it stays preliminary/unverified.
    bad = deepcopy(rows)
    next(x for x in bad if x["source_id"] == sid)[
        "source_lifecycle_state"
    ] = "validated_for_collection"
    raw = tmp_path / "forged-dashboard.json"
    raw.write_text(json.dumps(bad), encoding="utf-8")
    report = audit_full_inventory(planned_shards, items_paths=[raw])
    assert report["summary"]["verified_immutable_archives"] is False
    assert report["summary"]["status"] == "raw_export_preliminary_not_verified"


def test_large_provider_cannot_crowd_out_49_others_in_human_review_queue(
        monkeypatch):
    from scripts import real_gold_binding

    fake = {}
    for n in range(50):
        sid = f"synthetic_source_{n:02}"
        fake[(sid, f"883514/3/{n+500}")] = {
            "source_id": sid,
            "category": "pricing",
            "source_url": "https://synthetic.invalid/pricing",
            "content_sha256": "a" * 64,
            "pricing_observations": [{
                "observation_id": f"{k:032x}",
                "normalized_amount_decimal": "1.00",
                "raw_displayed_price": "USD 1.00",
                "currency": "USD",
                "model_or_service": "Synthetic",
                "comparable_candidate": True,
            } for k in range(50)],
        }
    monkeypatch.setattr(
        real_gold_binding, "load_bound_archives",
        lambda paths, full_inventory_plan=None: (
            fake, {"synthetic": {"job_id": "synthetic"}}, PACKAGE_SHA
        ),
    )
    packet = real_gold_binding.prepare_review_candidates(["synthetic-only"])
    prices = packet["samples"]["pricing"]
    assert len(prices) == 1200
    assert packet["source_diversity_counts"]["pricing"] == 50
    assert len({row["source_id"] for row in prices[:50]}) == 50
    assert packet["omitted_by_bounded_sample"]["pricing"] == 1300
    assert packet["per_source_candidate_limit"] == 40
    assert packet["sampling_strategy"] == (
        "bounded_source_round_robin_unreviewed"
    )
    assert all(p["review_status"] == "unreviewed" for p in prices)
    assert packet["independently_verified_vendor_facts"] == 0
