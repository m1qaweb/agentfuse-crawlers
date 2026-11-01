"""P14A: synthetic immutable archive/annotation binding safety tests.

All fixtures are INVENTED; they never count as real independent vendor gold.
"""

from copy import deepcopy

import pytest

from agentfuse_crawlers.run_context import (
    manifest_sha256, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import archive_job
from scripts.quality_gates import grade_release
from scripts.real_gold_binding import (
    bind_human_gold, load_bound_archives, prepare_review_candidates,
)

SOURCES = {s["id"]: s for s in load_sources()}
PACKAGE_SHA = "f" * 64
PRICING = "openai_api_pricing"
CHANGELOG = "openai_api_changelog"
DOCS = "openai_api_docs"


def pricing_observation(name, comparable):
    return {
        "observation_id": name * 32,
        "source_id": PRICING, "source_url": SOURCES[PRICING]["url"],
        "normalized_amount_decimal": "1.50" if comparable else None,
        "currency": "USD" if comparable else None,
        "billing_unit": "per_1m_tokens",
        "model_or_service": "Model Alpha",
        "region": "Global" if comparable else None,
        "tier_or_plan": "Standard" if comparable else None,
        "price_dimension": "input",
        "service_mode": None, "effective_from": None, "effective_until": None,
        "comparable_candidate": comparable,
        "raw_displayed_price": "USD 1.50" if comparable else "$1.50",
        "normalization_blockers": [] if comparable
            else ["missing_explicit_currency", "missing_explicit_region"],
        "approved_for_advisor": False,
    }


def event(letter, day):
    return {
        "event_id": CHANGELOG + ":" + letter * 24,
        "body_sha256": letter * 64,
        "title": "Example release " + letter,
        "published_at": day,
        "published_date_provenance": "html_time_datetime",
        "date_evidence_text": day,
        "permalink": SOURCES[CHANGELOG]["url"],
        "approved_for_advisor": False,
        "excerpt": "Synthetic example event for internal test only.",
    }


def item(sid, job, ordinal=0, *, reversed_events=False):
    source = SOURCES[sid]
    spider = {
        "pricing": "official_pricing", "changelog": "official_changelogs",
        "documentation": "official_documentation",
    }[source["category"]]
    record = {
        "_key": f"{job}/{ordinal}", "source_id": sid,
        "provider": source["provider"], "category": source["category"],
        "source_url": source["url"], "final_url": source["url"],
        "http_status": 200, "status": "captured",
        "content_sha256": "a" * 64,
        "schema_version": "2.1", "approved_for_advisor": False,
        "source_policy_status": "not_reviewed",
        "source_lifecycle_state": "needs_validation",
        "zyte_job_id": job,
        "spider_name": spider, "requested_cohort": "all",
        "collection_mode": "validation",
        "selection_source_count": 1,
        "selection_ids_sha256": selection_ids_sha256([source]),
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "run_started_at_utc": "2026-11-01T12:00:00+00:00",
        "fetched_at_utc": "2026-11-01T12:02:00+00:00",
        "deployment_revision_kind": "package_py_json_sha256_v1",
        "deployment_revision": PACKAGE_SHA,
        "pricing_observations": [],
        "release_events": [],
    }
    if source["category"] == "pricing":
        record["pricing_observations"] = [
            pricing_observation("0", True),
            pricing_observation("1", False),
        ]
    if source["category"] == "changelog":
        records = [event("a", "2026-10-30"), event("b", "2026-10-28")]
        if reversed_events:
            records.reverse()
        record["release_events"] = records
        record["release_events_schema"] = "1.1"
        record["release_identity_revision"] = "release_owner_date_scope_v3"
        record["release_window_complete"] = True
    if source["category"] == "documentation":
        record["documentation_topic_candidates"] = [{
            "candidate_id": "c" * 24, "topic_hint": "authentication",
            "section_id": "authentication",
            "section_sha256": "b" * 64,
            "excerpt": "Synthetic example technical guide content.",
        }]
    return record


def make_archive(root, sid, jobid, *, version=1, reverse=False):
    row = item(sid, jobid, reversed_events=reverse)
    spider = row["spider_name"]
    metadata = {
        "state": "finished",
        "spider": spider,
        "close_reason": "finished",
        "version": "placeholder",
        "deploy_id": 28,
        "finished_time": 1793550000000 + version * 60000,
        "spider_args": {
            "cohort": "all", "source_ids": sid,
            "collection_mode": "validation",
        },
        "scrapystats": {
            "item_scraped_count": 1, "memusage/max": 140000000,
        },
    }
    path, _, status = archive_job(
        jobid, root, api_key="SYNTHETIC-TEST-ONLY",
        fetch_metadata=lambda *_: metadata,
        fetch_page=lambda *_: [row],
    )
    assert status == "archived"
    return path


def reviewed_fixture():
    a = SOURCES[PRICING]
    b = SOURCES[CHANGELOG]
    rate = pricing_observation("0", True)
    return {
        "schema_version": "1.0",
        "origin": "human_annotated_official_source_evidence",
        "synthetic_only": False,  # Exercise format only; these are NOT real.
        "approved_for_advisor": False,
        "expected_package_sha256": PACKAGE_SHA,
        "reviewed_by": "Synthetic reviewer only",
        "reviewed_at_utc": "2026-11-01T14:00:00+00:00",
        "pricing_rows": [{
            "case_id": "price-01",
            "source_id": PRICING, "source_url": a["url"],
            "evidence_url": a["url"], "job_id": "883514/3/901",
            "approved_for_advisor": False,
            "observation_id": "0" * 32,
            "evidence_review_note": "Synthetic evidence annotation for regression; no real vendor price.",
            "expected": {
                "amount": "1.50", "currency": "USD",
                "billing_unit": "per_1m_tokens",
                "model_or_service": "Model Alpha",
                "region": "Global", "tier_or_plan": "Standard",
                "price_dimension": "input",
                "service_mode": None, "effective_from": None,
                "effective_until": None,
            },
            "observed": {
                "amount": rate["normalized_amount_decimal"],
                "currency": rate["currency"],
                "billing_unit": rate["billing_unit"],
                "model_or_service": rate["model_or_service"],
                "region": rate["region"], "tier_or_plan": rate["tier_or_plan"],
                "price_dimension": rate["price_dimension"],
                "service_mode": None, "effective_from": None,
                "effective_until": None, "comparable_candidate": True,
            },
        }],
        "negative_rate_rows": [{
            "case_id": "negative-01", "source_id": PRICING,
            "source_url": a["url"], "evidence_url": a["url"],
            "job_id": "883514/3/901",
            "approved_for_advisor": False,
            "observation_id": "1" * 32,
            "evidence_review_note": "Synthetic ambiguous dollar and missing region are not comparable.",
            "expected_comparable": False, "observed_comparable": False,
        }],
        "date_rows": [{
            "case_id": "date-01", "source_id": CHANGELOG,
            "source_url": b["url"], "evidence_url": b["url"],
            "job_id": "883514/1/901", "approved_for_advisor": False,
            "event_id": CHANGELOG + ":" + "a" * 24,
            "event_body_sha256": "a" * 64,
            "evidence_review_note": "Synthetic event publication time, not independently reviewed vendor date.",
            "expected_day": "2026-10-30", "observed_day": "2026-10-30",
        }],
        "change_safety_rows": [{
            "case_id": "baseline-01", "source_id": CHANGELOG,
            "source_url": b["url"], "evidence_url": b["url"],
            "job_id": "883514/1/901", "approved_for_advisor": False,
            "scenario": "first_baseline",
            "evidence_review_note": "Synthetic source baseline cannot imply that any event was published today.",
            "observed_new_release_alert": False,
        }],
    }


@pytest.fixture
def fake_verified_job_paths(tmp_path):
    return [
        make_archive(tmp_path, PRICING, "883514/3/901"),
        make_archive(tmp_path, CHANGELOG, "883514/1/901"),
        make_archive(tmp_path, DOCS, "883514/2/901"),
    ]


def test_review_packet_has_only_unreviewed_observations(fake_verified_job_paths):
    packet = prepare_review_candidates(fake_verified_job_paths)
    assert packet["human_review_completed"] is False
    assert packet["not_for_release_quality_gates"] is True
    assert packet["verified_immutable_archive_count"] == 3
    assert len(packet["samples"]["pricing"]) == 2
    assert len(packet["samples"]["release_dates"]) == 2
    assert len(packet["samples"]["documentation"]) == 1
    assert all(row["review_status"] == "unreviewed"
               and row["reviewer_expected_value"] is None
               and row["approved_for_advisor"] is False
               for rows in packet["samples"].values() for row in rows)
    assert packet["advisor_fact_approvals"] == 0
    assert packet["auto_crawls_performed"] == 0


def test_all_four_gold_types_are_bound_to_the_exact_archived_items(fake_verified_job_paths):
    gold = reviewed_fixture()
    report = bind_human_gold(gold, fake_verified_job_paths)
    assert report["binding_complete"] is True
    assert report["verified_immutable_job_count"] == 3
    assert report["pricing_cases_bound"] == 1
    assert report["negative_cases_bound"] == 1
    assert report["date_cases_bound"] == 1
    assert report["change_cases_bound"] == 1
    assert report["total_cases_bound"] == 4
    assert report["independent_publisher_truth_confirmed"] is False
    assert report["deployment_authorized"] is False
    result = grade_release(human_gold=gold, gold_archives=fake_verified_job_paths)
    assert result["checks"]["archive_bound_human_gold"] is True
    assert result["checks"]["independent_pricing_gold"] is False
    assert result["status"] == "blocked_pending_evidence_or_quality"
    assert result["deployment_authorized"] is False


@pytest.mark.parametrize("edit", [
    lambda gold: gold["pricing_rows"][0]["observed"].update(amount="999"),
    lambda gold: gold["pricing_rows"][0]["observed"].update(currency="EUR"),
    lambda gold: gold["negative_rate_rows"][0].update(observed_comparable=True),
    lambda gold: gold["date_rows"][0].update(observed_day="2026-10-25"),
    lambda gold: gold["date_rows"][0].update(event_body_sha256="b" * 64),
    lambda gold: gold["pricing_rows"][0].update(observation_id="e" * 32),
    lambda gold: gold["date_rows"][0].update(event_id=CHANGELOG + ":" + "f" * 24),
    lambda gold: gold.update(expected_package_sha256="a" * 64),
    lambda gold: gold["pricing_rows"][0].update(evidence_review_note=""),
])
def test_forged_or_unlinked_observations_fail_closed(fake_verified_job_paths, edit):
    gold = reviewed_fixture()
    edit(gold)
    with pytest.raises(ValueError):
        bind_human_gold(gold, fake_verified_job_paths)


def test_repeating_same_observation_in_another_job_cannot_inflate_200(fake_verified_job_paths, tmp_path):
    other_job = make_archive(tmp_path, PRICING, "883514/3/902", version=2)
    gold = reviewed_fixture()
    duplicated = deepcopy(gold["pricing_rows"][0])
    duplicated["case_id"] = "price-02"
    duplicated["job_id"] = "883514/3/902"
    gold["pricing_rows"].append(duplicated)
    with pytest.raises(ValueError, match="inflate"):
        bind_human_gold(gold, [*fake_verified_job_paths, other_job])


def test_repeat_job_directory_is_rejected(fake_verified_job_paths):
    with pytest.raises(ValueError, match="Duplicate Zyte job"):
        load_bound_archives([fake_verified_job_paths[0], fake_verified_job_paths[0]])


def test_corrupt_zipped_archive_is_rejected(fake_verified_job_paths):
    gz = fake_verified_job_paths[0] / "items.jsonl.gz"
    gz.write_bytes(gz.read_bytes() + b"tampering")
    with pytest.raises(ValueError, match="gzip checksum"):
        bind_human_gold(reviewed_fixture(), fake_verified_job_paths)


def test_archive_revision_identity_cannot_be_confused_with_github_commit(fake_verified_job_paths):
    gold = reviewed_fixture()
    gold["expected_package_sha256"] = "cc5ba1a"
    with pytest.raises(ValueError, match="package"):
        bind_human_gold(gold, fake_verified_job_paths)


def test_missing_archives_always_keep_release_blocked():
    gold = reviewed_fixture()
    gate = grade_release(human_gold=gold)
    assert gate["checks"]["archive_bound_human_gold"] is False
    assert gate["deployment_authorized"] is False


def test_reorder_cases_require_real_second_job_and_no_false_new_alert(
        fake_verified_job_paths, tmp_path):
    newer = make_archive(
        tmp_path, CHANGELOG, "883514/1/902", version=2, reverse=True
    )
    gold = reviewed_fixture()
    gold["change_safety_rows"][0].update({
        "scenario": "reordered_same_events",
        "case_id": "reorder-01",
        "job_id": "883514/1/902",
        "previous_job_id": "883514/1/901",
    })
    report = bind_human_gold(gold, [*fake_verified_job_paths, newer])
    assert report["change_cases_bound"] == 1
    assert report["binding_complete"] is True
    gold["change_safety_rows"][0]["previous_job_id"] = "883514/1/902"
    with pytest.raises(ValueError):
        bind_human_gold(gold, [*fake_verified_job_paths, newer])
