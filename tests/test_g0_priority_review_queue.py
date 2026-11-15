"""G0: output is a review priority queue, never executable publisher access."""

import csv
import json
from collections import Counter
from copy import deepcopy

import pytest

from scripts import g0_priority_review_queue as g0


def test_460_300_12_and_original_18_are_separate_and_non_authorizing():
    report, all_rows, top, pilot, hosts = g0.build_queue()
    assert report["status"] == "NO_GO_NOT_AUTHORIZED"
    assert report["ranking_is_authorization"] is False
    assert report["ranking_is_empirical_quality_measurement"] is False
    assert report["publisher_permissions_added"] == 0
    assert report["publisher_gets_performed"] == 0
    assert report["zyte_jobs_started"] == 0
    assert report["bulk_plans_created"] == 0
    assert len(all_rows) == 460
    assert len({r["source_id"] for r in all_rows}) == 460
    assert len(top) == 300
    assert len(pilot) == 12
    assert len({r["hostname"] for r in pilot}) == 12
    assert Counter(r["category"] for r in top) == g0.CATEGORY_QUOTAS
    assert Counter(r["category"] for r in pilot) == {
        "documentation": 4, "pricing": 4, "changelog": 4,
    }
    assert len(hosts) == report["distinct_hosts_top_300"]
    assert sum(h["top_300_candidate_count"] for h in hosts) == 300
    assert report["distinct_hosts_all_460"] == 305
    assert report["original_frozen_canary_round_denominator"] == 36
    frozen = set(report["original_frozen_canary_source_ids"])
    assert len(frozen) == 18
    assert frozen.isdisjoint(report["supplemental_canary_source_ids"])
    assert {r["source_id"] for r in pilot} == set(
        report["supplemental_canary_source_ids"]
    )
    assert [r["provisional_rank"] for r in all_rows] == list(range(1, 461))
    assert all(r["human_exact_url_decision_NOT_ATTESTED"] ==
               "PENDING_INDEPENDENT_REVIEW" for r in all_rows)
    assert all(r["top_300_candidate_NOT_APPROVED"] for r in top)
    assert all(not r["top_300_candidate_NOT_APPROVED"] for r in all_rows[300:])
    assert all(r["supplemental_canary_review_candidate_NOT_APPROVED"]
               for r in pilot)


def test_supplimental_candidates_are_immutable_source_id_url_category_records():
    report, all_rows, _, pilot, _ = g0.build_queue()
    assert {r["source_id"] for r in pilot} == set(g0._pilot_ids())
    assert len({r["source_url"] for r in all_rows}) == 460
    assert all(r["source_url"].startswith("https://") for r in all_rows)
    assert all(r["robots_candidate_url_NOT_VERIFIED"] ==
               "https://" + r["hostname"] + "/robots.txt" for r in pilot)
    assert report["original_frozen_study_preserved"] is True
    assert all(r["human_terms_url"] == "" for r in pilot)
    assert all(r["human_publisher_owner_evidence"] == "" for r in pilot)


def test_report_fails_closed_for_unreconciled_or_authorizing_inputs():
    from scripts.full_crawl_readiness import build_readiness
    base, rows = build_readiness()
    bad = deepcopy(base)
    bad["status"] = "GO"
    with pytest.raises(ValueError):
        g0.build_queue(readiness=bad, dispositions=rows)

    bad = deepcopy(base)
    bad["full_run_approved"] = True
    with pytest.raises(ValueError):
        g0.build_queue(readiness=bad, dispositions=rows)

    wrong = deepcopy(rows)
    wrong[0]["source_id"] = wrong[1]["source_id"]
    with pytest.raises(ValueError):
        g0.build_queue(readiness=base, dispositions=wrong)

    bad = deepcopy(base)
    bad["frozen_canary_source_ids"] = bad["frozen_canary_source_ids"][:17]
    with pytest.raises(ValueError):
        g0.build_queue(readiness=bad, dispositions=rows)

    with pytest.raises(ValueError):
        g0.build_queue(readiness=base)


def test_a_fictional_review_status_never_authorizes_this_packet():
    from scripts.full_crawl_readiness import build_readiness
    base, original = build_readiness()
    rows = deepcopy(original)
    sample = next(r for r in rows if r["source_id"] == "github_copilot_docs")
    sample["access_review"] = "allowed_reviewed"
    sample["single_scope_current"] = True
    report, ranked, _, pilot, _ = g0.build_queue(
        readiness=base, dispositions=rows,
    )
    assert report["status"] == "NO_GO_NOT_AUTHORIZED"
    assert report["publisher_permissions_added"] == 0
    assert report["zyte_jobs_started"] == 0
    selected = next(r for r in pilot if r["source_id"] == "github_copilot_docs")
    assert selected["access_review_record"] == "allowed_reviewed"
    assert selected["human_exact_url_decision_NOT_ATTESTED"] == (
        "PENDING_INDEPENDENT_REVIEW"
    )
    assert all(r["human_exact_url_decision_NOT_ATTESTED"] ==
               "PENDING_INDEPENDENT_REVIEW" for r in ranked)


def test_artifacts_are_safe_new_only_and_counted(tmp_path):
    artifacts = g0.build_queue()
    out = tmp_path / "priority"
    assert g0.write_queue(*artifacts, out) == out
    expected = {
        "g0_source_priority_summary_NO_GO.json",
        "source_priorities_all460_NOT_APPROVED.csv",
        "priority_top300_NOT_APPROVED.csv",
        "supplemental_canary12_REVIEW_ONLY.csv",
        "host_review_groups_top300_NOT_PERMISSIONS.csv",
    }
    assert {p.name for p in out.iterdir()} == expected
    report = json.loads((out / "g0_source_priority_summary_NO_GO.json").read_text())
    assert report["report_sha256"] == artifacts[0]["report_sha256"]
    for filename, expected_count in (
        ("source_priorities_all460_NOT_APPROVED.csv", 460),
        ("priority_top300_NOT_APPROVED.csv", 300),
        ("supplemental_canary12_REVIEW_ONLY.csv", 12),
        ("host_review_groups_top300_NOT_PERMISSIONS.csv",
         artifacts[0]["distinct_hosts_top_300"]),
    ):
        with (out / filename).open(encoding="utf-8-sig", newline="") as handle:
            assert len(list(csv.DictReader(handle))) == expected_count
    with pytest.raises(ValueError, match="NEW non-symlink"):
        g0.write_queue(*artifacts, out)
