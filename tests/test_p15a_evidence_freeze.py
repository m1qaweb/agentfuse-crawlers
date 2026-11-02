"""P15A synthetic evidence freeze tests. No network and no publisher claims."""
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources, select_sources
from scripts.build_failure_matrix import (
    CATEGORIES, EXPECTED, SPIDERS, _safe_csv, build_failure_matrix,
)
from scripts.freeze_baseline import (
    _lock_key, freeze_dashboard_exports, write_freeze,
)

PACKAGE = "a" * 64


def synthetic_full_inventory():
    dataset = {}
    for cat in CATEGORIES:
        chosen = select_sources(cat, "all")
        rows = []
        for src in chosen:
            allowed = collection_decision(src, "validation")[0]
            rows.append({
                "source_id": src["id"],
                "source_url": src["url"],
                "provider": src["provider"],
                "category": cat,
                "spider_name": SPIDERS[cat],
                "zyte_job_id": {
                    "pricing": "120/3/10", "documentation": "120/2/12",
                    "changelog": "120/1/13",
                }[cat],
                "manifest_sha256": manifest_sha256(),
                "source_registry_sha256": registry_revision_sha256(),
                "selection_ids_sha256": selection_ids_sha256(chosen),
                "selection_source_count": len(chosen),
                "requested_cohort": "all", "run_scope_explicit": True,
                "collection_mode": "validation",
                "deployment_revision": PACKAGE,
                "deployment_revision_kind": "package_py_json_sha256_v1",
                "approved_for_advisor": False,
                "source_policy_status": "not_reviewed" if allowed else "unresolved",
                "source_lifecycle_state": "needs_validation" if allowed else "quarantined",
                "status": "needs_review" if allowed else "source_quarantined",
                "http_status": 200 if allowed else None,
                "content_sha256": "b" * 64 if allowed else None,
                "word_count": 120 if allowed else 0,
                "latest_publication_verified": False,
                "pricing_observations": [],
                "documentation_topic_candidates": [],
                "release_events": [],
            })
        dataset[cat] = rows
    # Source evidence is deliberately invented and never human-reviewed.
    price = next(x for x in dataset["pricing"] if x["source_id"] == "openai_api_pricing")
    price["pricing_evidence_schema"] = "1.0"
    price["pricing_observation_total_detected"] = 2
    price["pricing_inventory_complete"] = False
    price["pricing_observations"] = [{
        "observation_id": "1" * 32,
        "source_id": price["source_id"], "source_url": price["source_url"],
        "evidence_kind": "structured_table", "raw_displayed_price": "$1",
        "region": None, "currency": None, "tier_or_plan": None,
        "billing_unit": "per_1m_tokens", "price_state": "single",
        "normalization_blockers": ["missing_explicit_region"],
        "approved_for_advisor": False,
    }, {
        "observation_id": "2" * 32,
        "source_id": price["source_id"], "source_url": price["source_url"],
        "evidence_kind": "structured_table", "raw_displayed_price": "$1 / $2",
        "region": None, "currency": None, "tier_or_plan": None,
        "billing_unit": None, "price_state": "multiple_or_time_dependent",
        "normalization_blockers": ["multiple_amounts_in_cell"],
        "approved_for_advisor": False,
    }]
    docs = next(x for x in dataset["documentation"] if x["source_id"] == "kiro_docs")
    docs["documentation_static_capture_status"] = "javascript_shell_suspected"
    docs["documentation_scope_status"] = "insufficient_content"
    docs["documentation_nav_candidate_total_detected"] = 117
    docs["documentation_nav_candidate_omitted"] = 93
    docs["documentation_topic_candidates"] = [{
        "candidate_id": "0" * 24, "topic_hint": "sdk",
        "approved_for_advisor": False,
    }]
    changelog = next(
        x for x in dataset["changelog"] if x["source_id"] == "openai_api_changelog"
    )
    changelog["release_events_schema"] = "1.1"
    changelog["release_window_complete"] = False
    changelog["release_event_identity_collision"] = True
    changelog["release_event_count"] = 2
    changelog["release_events"] = [{
        "event_id": changelog["source_id"] + ":" + "e" * 24,
        "published_at": "2026-10-31",
        "approved_for_advisor": False,
    }, {
        "event_id": changelog["source_id"] + ":" + "e" * 24,
        "published_at": None,
        "approved_for_advisor": False,
    }]
    return dataset


@pytest.fixture
def records():
    return synthetic_full_inventory()


def write_synthetic_exports(tmp_path, records):
    filenames = {}
    for cat in CATEGORIES:
        plural = "changelogs" if cat == "changelog" else cat
        job_id = records[cat][0]["zyte_job_id"]
        files = {
            "items": records[cat],
            "requests": [{
                "url": row["source_url"], "status": 200,
                "duration": 10, "method": "GET",
            } for row in records[cat] if row["http_status"] is not None],
            "log": [
                {"time": 1, "level": 20, "message": (
                    f"[{SPIDERS[cat]}] Starting {cat} "
                    f"{len(records[cat])} configured URLs job_id={job_id}"
                )},
                {"time": 2, "level": 30, "message": (
                    f"[{SPIDERS[cat]}] Job accounted for "
                    f"{EXPECTED[cat]}/{EXPECTED[cat]} sources "
                    "but evidence quality=degraded_unverified"
                )},
                {"time": 3, "level": 20,
                 "message": "[scrapy.core.engine] Closing spider (finished)"},
            ],
        }
        filenames[cat] = {}
        for kind, content in files.items():
            name = f"{kind}_official_{plural}_13.json"
            path = tmp_path / name
            path.write_text(
                json.dumps(content, ensure_ascii=False), encoding="utf-8",
            )
            filenames[cat][kind] = path
    return filenames


def test_exact_460_source_multi_axis_triage(records):
    report = build_failure_matrix(records)
    summary = report["summary"]
    assert summary["source_item_count"] == 460
    assert summary["manifest_source_count"] == 460
    assert summary["missing_or_duplicate_source_count"] == 0
    assert summary["observed_counters"]["http_200_sources"] == 457
    assert summary["observed_counters"]["policy_skipped_sources"] == 3
    assert summary["observed_counters"]["pricing_observations_retained"] == 2
    assert summary["observed_counters"]["pricing_region_unknown"] == 2
    assert summary["observed_counters"]["pricing_currency_unknown"] == 2
    assert summary["observed_counters"]["pricing_composite_observations"] == 1
    assert summary["observed_counters"]["documentation_topic_candidates"] == 1
    assert summary["observed_counters"]["documentation_nav_links_detected"] == 117
    assert summary["observed_counters"]["release_events_retained"] == 2
    assert summary["observed_counters"]["release_events_dated"] == 1
    assert summary["observed_counters"]["release_duplicate_id_surplus"] == 1
    assert summary["deployed_package_sha256"] == PACKAGE
    assert not summary["full_original_publisher_html_replay_available"]
    assert not summary["source_snapshot_integrity_verified_against_zyte_api"]
    assert not summary["publisher_fact_accuracy_independently_verified"]
    assert summary["advisor_fact_approvals"] == 0
    assert not summary["deployment_authorized"]
    flagged = {x["source_id"]: x for x in report["sources"]}
    assert flagged["kiro_docs"]["documentation_js_shell"]
    assert flagged["openai_api_changelog"]["release_identity_collision"]
    assert flagged["openai_api_changelog"]["release_window_incomplete"]
    assert flagged["v0_docs"]["policy_not_fetched"]
    assert flagged["v0_docs"]["review_action"] == (
        "do_not_fetch_without_reviewed_permission"
    )
    assert flagged["openai_api_pricing"]["priority"] == "P0_candidate"


def test_matrix_does_not_depend_on_items_list_order(records):
    original = build_failure_matrix(records)
    shuffled = {k: list(reversed(v)) for k, v in records.items()}
    revised = build_failure_matrix(shuffled)
    assert revised == original


def test_missing_duplicate_unknown_and_unapproved_items_refused(records):
    missing = deepcopy(records)
    missing["pricing"].pop()
    with pytest.raises(ValueError, match="Missing or extra"):
        build_failure_matrix(missing)
    duplicate = deepcopy(records)
    duplicate["pricing"][1] = duplicate["pricing"][2]
    with pytest.raises(ValueError, match="Duplicate"):
        build_failure_matrix(duplicate)
    unknown = deepcopy(records)
    unknown["documentation"][1]["source_url"] = "https://evil.invalid"
    with pytest.raises(ValueError, match="identity"):
        build_failure_matrix(unknown)
    unsafe = deepcopy(records)
    unsafe["changelog"][0]["approved_for_advisor"] = True
    with pytest.raises(ValueError, match="approval"):
        build_failure_matrix(unsafe)


def test_cross_package_hash_and_quarantine_bypass_refused(records):
    rows = deepcopy(records)
    rows["pricing"][10]["deployment_revision"] = "f" * 64
    with pytest.raises(ValueError, match="package"):
        build_failure_matrix(rows)
    rows = deepcopy(records)
    skipped = next(x for x in rows["documentation"]
                   if x["source_id"] == "v0_docs")
    skipped["http_status"] = 200
    with pytest.raises(ValueError, match="restricted"):
        build_failure_matrix(rows)
    rows = deepcopy(records)
    obs = next(x for x in rows["pricing"]
               if x["source_id"] == "openai_api_pricing")
    obs["pricing_observations"][0]["approved_for_advisor"] = True
    with pytest.raises(ValueError, match="Unverified observation"):
        build_failure_matrix(rows)


def test_three_triplets_match_job_and_initial_request_evidence(tmp_path, records):
    files = write_synthetic_exports(tmp_path, records)
    result, matrix = freeze_dashboard_exports(files)
    second, same_matrix = freeze_dashboard_exports(files)
    assert result == second
    assert matrix == same_matrix
    assert result["source_item_count"] == 460
    assert result["freeze_manifest_sha256"] == second["freeze_manifest_sha256"]
    assert result["job_ids"] == matrix["summary"]["job_ids"]
    assert all(result["files"][cat]["scrapy_finish_log_observed"]
               for cat in CATEGORIES)
    assert all(result["files"][cat]["source_initial_request_urls_accounted"]
               == EXPECTED[cat] - 1 for cat in CATEGORIES)
    assert result["network_requests_performed"] == 0
    assert result["advisor_fact_approvals"] == 0
    assert not result["raw_publisher_http_html_available"]


def test_export_tamper_and_wrong_job_log_refused(tmp_path, records):
    files = write_synthetic_exports(tmp_path, records)
    report, _ = freeze_dashboard_exports(files)
    locked = {
        **_lock_key(report),
        "expected_observed_counters": {
            "pricing_observations_retained": 2,
            "release_duplicate_id_surplus": 1,
        },
    }
    lock = tmp_path / "baseline-lock.json"
    lock.write_text(json.dumps(locked))
    freeze_dashboard_exports(files, baseline_lock=lock)
    file = files["pricing"]["requests"]
    req = json.loads(file.read_text())
    req[0]["url"] = "https://evil.invalid/other"
    file.write_text(json.dumps(req))
    with pytest.raises(ValueError, match="missing original URL"):
        freeze_dashboard_exports(files)
    files = write_synthetic_exports(tmp_path, records)
    data = json.loads(files["changelog"]["log"].read_text())
    data[0]["message"] = "[wrong_spider] Starting something"
    files["changelog"]["log"].write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Log export"):
        freeze_dashboard_exports(files)


def test_exact_export_hashes_are_pinned_by_lock(tmp_path, records):
    files = write_synthetic_exports(tmp_path, records)
    report, _ = freeze_dashboard_exports(files)
    locked = {
        **_lock_key(report),
        "expected_observed_counters": {"pricing_observations_retained": 2},
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(locked))
    freeze_dashboard_exports(files, baseline_lock=path)
    docs = files["documentation"]["items"]
    docs.write_text(docs.read_text() + " ")
    with pytest.raises(ValueError, match="lock mismatch"):
        freeze_dashboard_exports(files, baseline_lock=path)


def test_reports_private_copy_requires_explicit_acknowledgment(tmp_path, records):
    files = write_synthetic_exports(tmp_path, records)
    frozen, matrix = freeze_dashboard_exports(files)
    out = tmp_path / "p15a-output"
    with pytest.raises(ValueError, match="acknowledge"):
        write_freeze(frozen, matrix, out, paths_by_category=files,
                     copy_unencrypted_exports=True)
    write_freeze(frozen, matrix, out)
    assert (out / "source_failure_matrix.csv").exists()
    assert (out / "source_failure_matrix.jsonl").exists()
    assert (out / "quality_baseline.json").exists()
    assert (out / "freeze_manifest.json").exists()
    assert not (out / "source_exports_PRIVATE_UNENCRYPTED").exists()
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o700
        assert (out / "freeze_manifest.json").stat().st_mode & 0o777 == 0o600
    write_freeze(
        frozen, matrix, out, paths_by_category=files,
        copy_unencrypted_exports=True,
        acknowledge_plaintext_private_storage=True,
    )
    assert (out / "source_exports_PRIVATE_UNENCRYPTED"
            / files["pricing"]["items"].name).exists()
    assert _safe_csv("=HYPERLINK('https://evil.invalid')").startswith("'")
    assert _safe_csv("safe name") == "safe name"


def test_original_nov2_lock_contains_no_publisher_snapshots():
    lock = json.loads(
        (Path(__file__).resolve().parents[1]
         / "baselines/2026-11-02_dashboard_export_lock.json").read_text()
    )
    assert lock["source_item_count"] == 460
    assert set(lock["job_ids"]) == set(CATEGORIES)
    assert lock["expected_observed_counters"]["pricing_comparable_candidates"] == 0
    assert lock["expected_observed_counters"]["release_events_dated"] == 1762
    assert all(len(lock["input_export_files"][cat]) == 3 for cat in CATEGORIES)
    assert "raw_html" not in repr(lock).lower()
    assert "api_key" not in repr(lock).lower()
