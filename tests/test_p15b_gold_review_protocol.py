"""P15B human gold validation. Every fixture is synthetic; no vendor facts."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import (
    manifest_sha256, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import archive_job
from scripts.gold_review_protocol import (
    _check_expected, prepare_blind_bundle, reviewer_template,
    score_dual_review,
)
from scripts.real_gold_binding import prepare_review_candidates
from scripts.quality_gates import grade_release

SOURCES = {r["id"]: r for r in load_sources()}
KEY = "test-secret-hmac-grouping-2026-never-production"
PKG = "a" * 64
SOURCE_GROUP = (
    "openai_api_pricing",
    "openai_api_changelog",
    "openai_api_docs",
)
QUOTE = {
    "pricing": ("Model Alpha input price is USD 1.50 per one million "
                "tokens in the standard global tier."),
    "release_dates": ("Release notes were explicitly published on "
                      "October 30, 2026 for the API update."),
    "documentation": ("The official guide describes authenticated "
                      "invocation of a defined tool through its API."),
}


def _item(sid, job_id):
    src = SOURCES[sid]
    category = src["category"]
    spider = {
        "pricing": "official_pricing",
        "changelog": "official_changelogs",
        "documentation": "official_documentation",
    }[category]
    row = {
        "_key": job_id + "/0",
        "source_id": sid, "provider": src["provider"],
        "source_url": src["url"], "category": category,
        "status": "captured", "http_status": 200,
        "content_sha256": "b" * 64,
        "schema_version": "2.1", "approved_for_advisor": False,
        "source_policy_status": "not_reviewed",
        "source_lifecycle_state": "needs_validation",
        "zyte_job_id": job_id, "spider_name": spider,
        "requested_cohort": "all", "collection_mode": "validation",
        "selection_source_count": 1,
        "selection_ids_sha256": selection_ids_sha256([src]),
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "deployment_revision_kind": "package_py_json_sha256_v1",
        "deployment_revision": PKG,
        "run_started_at_utc": "2026-11-02T09:59:00Z",
        "fetched_at_utc": "2026-11-02T10:00:00Z",
        "pricing_observations": [], "release_events": [],
        "documentation_topic_candidates": [],
    }
    if category == "pricing":
        row["pricing_observations"] = [{
            "observation_id": "1" * 32,
            "source_id": sid, "source_url": src["url"],
            "raw_displayed_price": "USD 1.50",
            "normalized_amount_decimal": "1.50",
            "currency": "USD", "billing_unit": "per_1m_tokens",
            "model_or_service": "Model Alpha", "region": "Global",
            "tier_or_plan": "Standard", "price_dimension": "input",
            "service_mode": None, "effective_from": None,
            "effective_until": None,
            "comparable_candidate": True,
            "approved_for_advisor": False,
        }]
    elif category == "changelog":
        row.update({
            "release_events_schema": "1.1",
            "release_identity_revision": "release_owner_date_scope_v3",
            "release_window_complete": True,
        })
        row["release_events"] = [{
            "event_id": sid + ":" + "c" * 24,
            "title": "New API update",
            "body_sha256": "d" * 64,
            "published_at": "2026-10-30",
            "permalink": src["url"], "approved_for_advisor": False,
        }]
    else:
        row["documentation_topic_candidates"] = [{
            "candidate_id": "e" * 24,
            "source_id": sid, "topic_hint": "tools_and_mcp",
            "product_scope": "OpenAI API",
            "section_id": "tools", "section_sha256": "e" * 64,
            "excerpt": QUOTE["documentation"],
            "approved_for_advisor": False,
        }]
    return row


def _archive(tmp_path, sid, index):
    job_id = f"883514/{index}/{200+index}"
    row = _item(sid, job_id)
    src = SOURCES[sid]
    meta = {
        "state": "finished", "spider": row["spider_name"],
        "close_reason": "finished", "version": "synthetic-test",
        "deploy_id": 30, "finished_time": 1793614500000 + index,
        "spider_args": {
            "cohort": "all", "source_ids": sid,
            "collection_mode": "validation",
            "expected_manifest_sha256": manifest_sha256(),
            "expected_selection_ids_sha256": selection_ids_sha256([src]),
            "expected_source_registry_sha256": registry_revision_sha256(),
        },
        "scrapystats": {"item_scraped_count": 1},
    }
    path, _, status = archive_job(
        job_id, tmp_path, api_key="SYNTHETIC-ONLY",
        fetch_metadata=lambda *_: meta,
        fetch_page=lambda *_: [row],
    )
    assert status == "archived"
    return path


@pytest.fixture
def case_setup(tmp_path):
    archives = [_archive(tmp_path, sid, n+1)
                for n, sid in enumerate(SOURCE_GROUP)]
    packet = prepare_review_candidates(archives)
    bundle = prepare_blind_bundle(packet, split_key=KEY)
    snapshots = {"approved_for_advisor": False, "snapshots": []}
    a = reviewer_template(bundle, "independent_reviewer_one")
    b = reviewer_template(bundle, "independent_reviewer_two")
    root = tmp_path / "snapshots"
    root.mkdir()
    for task in bundle["tasks"]:
        kind = task["kind"]
        quote = QUOTE[kind]
        page = "<html><body><main><p>" + quote + "</p></main></body></html>"
        file = root / (task["case_id"] + ".html")
        file.write_text(page)
        digest = hashlib.sha256(page.encode()).hexdigest()
        snapshots["snapshots"].append({
            "case_id": task["case_id"],
            "source_id": task["source_id"],
            "publisher_url": task["source_url"],
            "captured_at_utc": "2026-11-02T10:05:00Z",
            "file": file.name, "sha256": digest,
            "media_type": "text/html", "approved_for_advisor": False,
        })
        if kind == "pricing":
            expected = {
                "amount": "1.50", "currency": "USD",
                "billing_unit": "per_1m_tokens",
                "model_or_service": "Model Alpha",
                "region": "Global", "tier_or_plan": "Standard",
                "price_dimension": "input",
                "service_mode": None, "effective_from": None,
                "effective_until": None,
            }
            resolution = "established"
        elif kind == "release_dates":
            expected, resolution = "2026-10-30", "published_date"
        else:
            expected, resolution = {
                "support_state": "supported",
                "capability_statement": (
                    "Authenticated API-based invocation of defined tools."
                ),
                "conditions": "",
            }, "topic_relevant"
        label = {
            "case_id": task["case_id"],
            "resolution": resolution,
            "expected": expected,
            "publisher_evidence_url": task["source_url"],
            "publisher_evidence_quote": quote,
            "review_note": ("Synthetic independent review fixture only. "
                            "It does not establish a genuine publisher claim."),
            "reviewed_at_utc": "2026-11-02T10:10:00Z",
            "approved_for_advisor": False,
        }
        a["labels"].append(deepcopy(label))
        b["labels"].append(deepcopy(label))
    return packet, bundle, a, b, snapshots, root, archives


def _score(scenario):
    packet, _, a, b, snapshots, root, archives = scenario
    return score_dual_review(
        packet, a, b, snapshots, snapshot_root=root,
        split_key=KEY, archive_paths=archives,
    )


def test_blind_packet_hides_predicted_values_but_keeps_evidence_locator(case_setup):
    packet, bundle, a, b, snapshots, root, archives = case_setup
    repr_tasks = json.dumps(bundle)
    assert "1.50" not in repr_tasks
    assert "2026-10-30" not in repr_tasks
    assert "normalized_amount_decimal" not in repr_tasks
    assert "raw_displayed_price" not in repr_tasks
    assert "comparable_candidate" not in repr_tasks
    assert "observed" not in repr_tasks
    assert "support_state" not in repr_tasks
    assert len(bundle["tasks"]) == 3
    assert len({x["case_id"] for x in bundle["tasks"]}) == 3
    assert all("expected" not in task for task in bundle["tasks"])
    template = reviewer_template(bundle, "a_second_reviewer")
    assert template["labels"] == []
    assert bundle["advisor_fact_approvals"] == 0
    assert not bundle["independent_publisher_truth_confirmed"]


def test_blind_source_split_is_deterministic_and_provider_grouped(case_setup):
    packet = deepcopy(case_setup[0])
    # Introduce independently plausible second-provider SAMPLE identity.
    # This checks split assignment only; no accuracy claim is evaluated.
    other = SOURCES["anthropic_api_pricing"]
    sample = deepcopy(packet["samples"]["pricing"][0])
    sample.update({
        "source_id": other["id"], "source_url": other["url"],
        "evidence_url": other["url"], "job_id": "883514/3/999",
        "observation_id": "2" * 32,
    })
    packet["samples"]["pricing"].append(sample)
    bundle = prepare_blind_bundle(packet, split_key=KEY)
    again = prepare_blind_bundle(packet, split_key=KEY)
    assert bundle == again
    assert {t["partition"] for t in bundle["tasks"]} == {"train", "holdout"}
    group = {}
    for task in bundle["tasks"]:
        group.setdefault(task["provider"], set()).add(task["partition"])
    assert all(len(splits) == 1 for splits in group.values())
    changed = prepare_blind_bundle(
        packet, split_key="a completely different private seed 2026"
    )
    assert changed["task_bundle_sha256"] != bundle["task_bundle_sha256"]
    assert bundle["split_key_sha256_commitment"] != changed[
        "split_key_sha256_commitment"
    ]


def test_snapshot_bound_double_review_scored_but_not_advisor_approved(case_setup):
    result = _score(case_setup)
    assert result["case_count"] == 3
    assert result["verified_archive_job_count"] == 3
    assert result["reviewer_count"] == 2
    assert result["publisher_snapshot_count"] == 3
    assert result["unresolved_disagreements"] == []
    assert sum(
        result["training_and_holdout"][split][kind].get("consensus", 0)
        for split in ("train", "holdout")
        for kind in ("pricing", "release_dates", "documentation")
    ) == 3
    assert not result["eligible_for_human_accuracy_signoff"]
    assert result["status"] == "blocked_pending_publisher_gold_and_consensus"
    assert result["documentation_supported_feature_accuracy"] is None
    assert not result["independent_publisher_truth_confirmed"]
    assert not result["publisher_snapshot_origin_externally_authenticated"]
    assert result["advisor_fact_approvals"] == 0
    assert result["network_requests_performed"] == 0
    assert result["deployment_authorized"] is False


def test_disagreement_is_excluded_instead_of_silently_majority_voted(case_setup):
    packet, bundle, a, b, snaps, root, archives = case_setup
    doc_case = next(t for t in bundle["tasks"] if t["kind"] == "documentation")
    dissent = next(x for x in b["labels"] if x["case_id"] == doc_case["case_id"])
    dissent["resolution"] = "topic_irrelevant"
    dissent["expected"] = {
        "support_state": "unknown", "capability_statement": "", "conditions": ""
    }
    report = _score(case_setup)
    assert len(report["unresolved_disagreements"]) == 1
    assert report["unresolved_disagreements"][0]["kind"] == "documentation"
    assert not report["checks"]["all_cases_dual_reviewed_and_agreed"]
    assert not report["eligible_for_human_accuracy_signoff"]


def test_distinct_reviewer_id_and_unknown_task_rejected(case_setup):
    packet, bundle, a, b, snapshots, root, archives = case_setup
    b["reviewer_id"] = a["reviewer_id"]
    with pytest.raises(ValueError, match="two distinct"):
        _score(case_setup)
    b["reviewer_id"] = "reviewer_beta"
    b["labels"][0]["case_id"] = "f" * 24
    with pytest.raises(ValueError, match="unknown or duplicate"):
        _score(case_setup)


@pytest.mark.parametrize("mutator,error", [
    (lambda s: s.update(sha256="f" * 64), "SHA-256 mismatch"),
    (lambda s: s.update(publisher_url="https://evil.invalid/"), "first-party"),
    (lambda s: s.update(captured_at_utc="2026-11-10T10:05:00Z"),
     "not contemporaneous"),
    (lambda s: s.update(file="../outside.html"), "safe relative"),
])
def test_tampered_snapshot_wrong_host_stale_or_traversal_blocked(
        case_setup, mutator, error):
    _, _, _, _, snapshots, _, _ = case_setup
    mutator(snapshots["snapshots"][0])
    with pytest.raises(ValueError, match=error):
        _score(case_setup)


def test_quote_not_in_original_publisher_snapshot_is_not_valid_gold(case_setup):
    _, _, a, _, _, _, _ = case_setup
    a["labels"][0]["publisher_evidence_quote"] = (
        "An invented highly specific claim that does not appear on the publisher page"
    )
    with pytest.raises(ValueError, match="absent or ambiguous"):
        _score(case_setup)


def test_stale_crawler_observation_cannot_be_substituted_for_archive(case_setup):
    packet, _, _, _, _, _, _ = case_setup
    packet["samples"]["pricing"][0]["observed"]["amount"] = "999"
    with pytest.raises(ValueError, match="not the checksum-bound"):
        _score(case_setup)


def test_missing_snapshot_for_reviewed_case_rejected(case_setup):
    _, _, _, _, snapshots, _, _ = case_setup
    snapshots["snapshots"].pop()
    with pytest.raises(ValueError, match="No immutable publisher snapshot"):
        _score(case_setup)


def test_missing_one_review_stays_blocked_without_forging_agreement(case_setup):
    _, _, a, _, _, _, _ = case_setup
    a["labels"].pop()
    report = _score(case_setup)
    assert not report["checks"]["all_cases_dual_reviewed_and_agreed"]
    assert report["eligible_for_human_accuracy_signoff"] is False


@pytest.mark.parametrize("bad", [
    {"resolution": "established", "expected": {"amount": "1.50"}},
    {"resolution": "established", "expected": {
        "amount": "NaN", "currency": "USD", "billing_unit": "tokens",
        "model_or_service": "Model", "region": "Global",
        "tier_or_plan": "Standard", "price_dimension": "input"}},
    {"resolution": "incomplete", "expected": {"amount": "1.50"}},
])
def test_invalid_price_truth_rejected(bad):
    with pytest.raises(ValueError):
        _check_expected("pricing", bad)


def test_missing_or_weak_split_key_is_rejected(case_setup):
    packet = case_setup[0]
    for key in ("", "short", "just-fourteen!", None):
        with pytest.raises(ValueError, match="at least 16"):
            prepare_blind_bundle(packet, split_key=key)


def test_incomplete_or_topic_only_docs_not_a_supported_capability():
    assert _check_expected("documentation", {
        "resolution": "topic_relevant",
        "expected": {"support_state": "unknown",
                     "capability_statement": "", "conditions": ""},
    })[0] == "topic_relevant"
    with pytest.raises(ValueError, match="Irrelevant"):
        _check_expected("documentation", {
            "resolution": "topic_irrelevant",
            "expected": {
                "support_state": "supported",
                "capability_statement": "Support is verified",
                "conditions": "",
            },
        })
    with pytest.raises(ValueError, match="conditions"):
        _check_expected("documentation", {
            "resolution": "topic_relevant",
            "expected": {
                "support_state": "conditional",
                "capability_statement": "This API supports tools conditionally",
                "conditions": "",
            },
        })


def test_scorecard_stays_blocked_without_double_review_even_if_old_synthetic():
    result = grade_release()
    assert result["status"] == "blocked_pending_evidence_or_quality"
    assert result["advisor_fact_approvals"] == 0
    assert result["deployment_authorized"] is False
