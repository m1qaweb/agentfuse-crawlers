"""P17B2 frozen-HTML replay, dual reviewer and fail-closed delta tests.

All model names, HTML and prices are synthetic. These fixtures prove only
deterministic software behavior, NOT publisher authenticity or accuracy.
"""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.replay_pricing_snapshots import (
    _digest_json, _check_report, compare_frozen_replays,
    prepare_blind_cell_tasks, replay_pricing_snapshots, reviewer_template,
)
from scripts.score_pricing_replay_gold import score_independent_pricing_gold

KNOWN = {s["id"]: s for s in load_sources()}
SID = "fireworks_ai_pricing"
URL = KNOWN[SID]["url"]
LEGEND = (
    "In each Standard or Priority cell, prices are input / cached input "
    "/ output (USD per 1M tokens), in that order."
)
QUOTE = "Ember-1 $3.00 / $0.30 / $15.00 $3.75 / $0.375 / $18.75"
HTML = (
    "<html><head><title>Fireworks AI Pricing</title></head><body>"
    "<main><h1>Fireworks AI Pricing</h1>"
    "<h2>Text and vision models</h2><p>" + LEGEND + "</p>"
    "<table><thead><tr><th>Model</th><th>Standard</th>"
    "<th>Priority</th></tr></thead><tbody><tr>"
    "<th><strong>Ember-1</strong></th>"
    "<td>$3.00 / $0.30 / $15.00</td>"
    "<td>$3.75 / $0.375 / $18.75</td>"
    "</tr></tbody></table></main></body></html>"
)
CAPTURED = "2026-11-02T10:00:00Z"
REVIEWED = "2026-11-02T11:00:00+00:00"


def _capture(tmp_path, *, source_id=SID, body=HTML):
    target = tmp_path / (source_id + "_captured.html")
    target.write_text(body, encoding="utf-8")
    src = KNOWN[source_id]
    return {
        "source_id": source_id,
        "snapshot": {
            "file": target.name,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "request_url": src["url"],
            "final_url": src["url"],
            "http_status": 200,
            "media_type": "text/html",
            "capture_method": "static_html",
            "captured_at_utc": CAPTURED,
            "capture_origin_review_status": "operator_supplied_unverified",
        },
    }


def _manifest(entries):
    return {
        "schema_version": "1.0",
        "kind": "frozen_original_pricing_html_manifest",
        "expected_manifest_sha256": manifest_sha256(),
        "expected_source_registry_sha256": registry_revision_sha256(),
        "approved_for_advisor": False,
        "snapshots": entries,
    }


def _synthetic_old_version(after):
    """Simulated v4 result; a separate v4 process is needed for real replay."""
    before = deepcopy(after)
    before["local_package_sha256"] = "9" * 64
    for source in before["sources"]:
        source["pricing_parser_revision"] = "evidence_quote_v4_model_identity"
        source["pricing_inline_rate_cells_split"] = 0
        source["pricing_legend_backed_triplet_cells_split"] = 0
        source["observed_component_count"] = 0
        by_cell = {}
        for o in source["observations"]:
            by_cell.setdefault(o["cell_key"], o)
        source["observations"] = []
        for k, example in by_cell.items():
            old = deepcopy(example)
            old["amount"] = None
            old["price_dimension"] = None
            old["component_count"] = None
            old["component_index"] = None
            old["component_origin"] = None
            old["normalized_amount_decimal"] = None
            old["review_quote_candidate"] = False
            old["comparable_candidate"] = False
            source["observations"].append(old)
        source["pricing_observation_total_detected"] = len(by_cell)
    before["replay_sha256"] = _digest_json({
        k: v for k, v in before.items() if k != "replay_sha256"
    })
    return before


@pytest.fixture
def scenario(tmp_path):
    capture = _capture(tmp_path)
    manifest = _manifest([capture])
    after = replay_pricing_snapshots(manifest, tmp_path)
    before = _synthetic_old_version(after)
    return tmp_path, manifest, before, after


def test_replay_freezes_exact_original_html_and_extractor_version(scenario):
    root, manifest, before, after = scenario
    assert after["kind"] == "original_pricing_html_replay_not_publisher_gold"
    assert after["source_count"] == 1
    assert after["network_requests_performed"] == 0
    assert after["verified_publisher_pricing_facts"] == 0
    assert after["advisor_fact_approvals"] == 0
    assert not after["deployment_authorized"]
    assert after["capture_manifest_sha256"] == _digest_json(manifest)
    assert len(after["local_package_sha256"]) == 64
    source = after["sources"][0]
    assert source["source_id"] == SID
    assert source["snapshot_sha256"] == manifest[
        "snapshots"][0]["snapshot"]["sha256"]
    assert source["pricing_parser_revision"] == (
        "evidence_quote_v5_inline_labeled_components"
    )
    assert source["pricing_inline_rate_cells_split"] == 2
    assert source["pricing_legend_backed_triplet_cells_split"] == 2
    assert source["pricing_inventory_complete"] is True
    assert source["pricing_observation_total_detected"] == 6
    assert source["observed_component_count"] == 6
    assert source["unreviewed_physical_cell_count"] == 2
    assert len(source["observations"]) == 6
    assert len({x["case_id"] for x in source["observations"]}) == 2
    assert len({x["cell_key"] for x in source["observations"]}) == 2
    assert len({x["observation_id"] for x in source["observations"]}) == 6
    assert {x["price_dimension"] for x in source["observations"]} == {
        "input", "cached_input", "output"
    }
    assert all(
        not x["comparable_candidate"] and not x["review_quote_candidate"]
        and not x["publisher_fact_verified"]
        and x["amount"] is not None
        and x["approved_for_advisor"] is False
        for x in source["observations"]
    )


def test_replay_is_deterministic_without_network_or_personal_data(scenario):
    root, manifest, before, after = scenario
    again = replay_pricing_snapshots(manifest, root)
    assert again == after
    assert _check_report(again)[SID]["source_url"] == URL
    doc = json.dumps(after)
    assert "Fireworks AI Pricing</title>" not in doc
    assert "<html>" not in doc
    assert str(root) not in doc
    assert "https://evil.invalid" not in doc


def test_cross_version_compares_only_same_source_bytes_and_reports_unverified_gain(
        scenario):
    _, manifest, before, after = scenario
    delta = compare_frozen_replays(before, after)
    assert delta["source_count"] == 1
    assert delta["sources"][0]["observed_amounts_before"] == 0
    assert delta["sources"][0]["observed_amounts_after"] == 6
    assert delta["sources"][0]["physical_cells_gained"] == 0
    assert delta["sources"][0]["physical_cells_lost"] == 0
    assert delta["sources"][0]["legend_backed_cells_after"] == 2
    assert delta["sources"][0]["comparison"] == (
        "new_structured_observations_unverified"
    )
    assert delta["independent_gold_precision"] is None
    assert not delta["publisher_accuracy_improved_proven"]
    assert delta["advisor_fact_approvals"] == 0


@pytest.mark.parametrize("mutation,error", [
    (lambda x: x["snapshots"][0]["snapshot"].update(sha256="a" * 64),
     "SHA-256"),
    (lambda x: x["snapshots"][0]["snapshot"].update(
        final_url="https://evil.invalid/pricing"), "URL/redirect"),
    (lambda x: x["snapshots"][0]["snapshot"].update(
        request_url="https://evil.invalid/pricing"), "URL/redirect"),
    (lambda x: x["snapshots"][0]["snapshot"].update(http_status=403),
     "HTTP 200"),
    (lambda x: x["snapshots"][0]["snapshot"].update(
        capture_method="rendered_html"), "method or provenance"),
    (lambda x: x["snapshots"][0]["snapshot"].update(
        capture_origin_review_status="publisher_verified"),
     "method or provenance"),
    (lambda x: x.update(approved_for_advisor=True),
     "source-pinned"),
    (lambda x: x.update(expected_manifest_sha256="f" * 64),
     "source-pinned"),
    (lambda x: x.update(expected_source_registry_sha256="f" * 64),
     "source-pinned"),
])
def test_replay_fails_closed_on_forged_or_mismatched_bytes(
        scenario, mutation, error):
    root, manifest, _, _ = scenario
    changed = deepcopy(manifest)
    mutation(changed)
    with pytest.raises(ValueError, match=error):
        replay_pricing_snapshots(changed, root)


def test_replay_rejects_path_traversal_symlinks_and_duplicate_source(
        scenario):
    root, manifest, _, _ = scenario
    bad = deepcopy(manifest)
    bad["snapshots"][0]["snapshot"]["file"] = "../outside.html"
    with pytest.raises(ValueError, match="traversal"):
        replay_pricing_snapshots(bad, root)
    bad = deepcopy(manifest)
    symlink = root / "alias.html"
    symlink.symlink_to(root / manifest["snapshots"][0]["snapshot"]["file"])
    bad["snapshots"][0]["snapshot"]["file"] = symlink.name
    with pytest.raises(ValueError, match="symlink"):
        replay_pricing_snapshots(bad, root)
    bad = deepcopy(manifest)
    bad["snapshots"].append(deepcopy(bad["snapshots"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        replay_pricing_snapshots(bad, root)


def test_replay_does_not_accept_source_quarantined_before_processing(tmp_path):
    data = _manifest([_capture(tmp_path, source_id="v0_pricing", body=HTML)])
    with pytest.raises(ValueError, match="Publisher-blocked"):
        replay_pricing_snapshots(data, tmp_path)


def test_comparison_rejects_changed_publisher_bytes_and_different_scope(
        scenario):
    root, manifest, before, after = scenario
    tampered = deepcopy(after)
    tampered["sources"][0]["snapshot_sha256"] = "b" * 64
    tampered["replay_sha256"] = _digest_json({
        k: v for k, v in tampered.items() if k != "replay_sha256"
    })
    with pytest.raises(ValueError, match="Changed publisher snapshot"):
        compare_frozen_replays(before, tampered)
    tampered = deepcopy(after)
    tampered["local_package_sha256"] = before["local_package_sha256"]
    tampered["replay_sha256"] = _digest_json({
        k: v for k, v in tampered.items() if k != "replay_sha256"
    })
    with pytest.raises(ValueError, match="different packages"):
        compare_frozen_replays(before, tampered)
    tampered = deepcopy(after)
    tampered["capture_manifest_sha256"] = "b" * 64
    tampered["replay_sha256"] = _digest_json({
        k: v for k, v in tampered.items() if k != "replay_sha256"
    })
    with pytest.raises(ValueError, match="same frozen input"):
        compare_frozen_replays(before, tampered)


def _labels(tasks):
    a = reviewer_template(tasks, "publisher_reviewer_A")
    b = reviewer_template(tasks, "publisher_reviewer_B")
    for task in tasks["tasks"]:
        column = task["cell_key"].rsplit("|", 1)[-1]
        # In this synthetic 2-column price grid the prices live at col 1,2.
        tier = "Standard" if column == "1" else "Priority"
        prices = (
            ("3.00", "0.30", "15.00") if tier == "Standard"
            else ("3.75", "0.375", "18.75")
        )
        dims = ("input", "cached_input", "output")
        expected = [
            {
                "amount": amount,
                "currency": "USD",
                "billing_unit": "per_1m_tokens",
                "price_dimension": dimension,
                "model_or_service": "Ember-1",
                "region": None,
                "tier_or_plan": tier,
            }
            for dimension, amount in zip(dims, prices)
        ]
        label = {
            "case_id": task["case_id"],
            "resolution": "established",
            "expected_components": expected,
            "publisher_evidence_quote": QUOTE,
            "review_note": (
                "Synthetic fixture reviewed against original raw HTML. "
                "This is a test, not an actual publisher assertion."
            ),
            "reviewed_at_utc": REVIEWED,
            "approved_for_advisor": False,
        }
        a["labels"].append(deepcopy(label))
        b["labels"].append(deepcopy(label))
    return a, b


def test_tasks_are_blind_and_stable_with_independent_reviewer_templates(
        scenario):
    _, manifest, before, after = scenario
    task = prepare_blind_cell_tasks(after)
    assert len(task["tasks"]) == 2
    assert task["omitted_by_bounded_sampling"] == 0
    assert task["sampling"] == "source_round_robin_max_20_cells_per_source"
    assert task["approved_for_advisor"] is False
    assert all(t["source_id"] == SID for t in task["tasks"])
    assert all(t["expected_values_prefilled"] is False for t in task["tasks"])
    for token in ("3.00", "15.00", "cached_input", "USD", "Ember-1"):
        assert token not in json.dumps(task)
    assert reviewer_template(task, "person_a")["labels"] == []


def test_two_reviewers_recover_six_exact_typed_unapproved_components(
        scenario):
    root, manifest, before, after = scenario
    tasks = prepare_blind_cell_tasks(after)
    a, b = _labels(tasks)
    score = score_independent_pricing_gold(
        before, after, manifest, root, a, b,
    )
    assert score["agreed_evaluable_cells"] == 2
    assert score["blind_task_count"] == 2
    assert score["reviewer_disagreement_cells"] == 0
    assert score["missing_dual_review_cells"] == 0
    assert score["provider_count_with_agreed_evaluable_cells"] == 1
    assert score["evaluator_versions"]["before"]["correct_exact_typed_components"] == 0
    assert score["evaluator_versions"]["before"]["missed_expected_components"] == 6
    assert score["evaluator_versions"]["after"]["correct_exact_typed_components"] == 6
    assert score["evaluator_versions"]["after"]["missed_expected_components"] == 0
    assert score["evaluator_versions"]["after"]["false_or_misattributed_components"] == 0
    assert score["evaluator_versions"]["after"]["exact_typed_precision_on_reviewed_cells"] == 1
    assert score["evaluator_versions"]["after"]["exact_typed_recall_on_reviewed_cells"] == 1
    assert score["evaluator_versions"]["after"]["exact_cell_match_fraction"] == 1
    assert score["evaluator_versions"]["after"][
        "fully_scoped_exact_review_matches"
    ] == 0
    assert score["evaluator_versions"]["after"][
        "partial_scope_review_matches"
    ] == 6
    assert score["evaluator_versions"]["after"][
        "fully_scoped_exact_fraction_of_expected"
    ] == 0
    assert score["null_scope_never_counts_as_fully_scoped"] is True
    assert score["comparable_publisher_rates_verified"] == 0
    assert score["publisher_snapshot_origin_authenticated"] is False
    assert score["human_accuracy_signoff_completed"] is False
    assert score["generalizable_vendor_accuracy_verified"] is False
    assert score["advisor_fact_approvals"] == 0
    assert score["deployment_authorized"] is False


def test_reviewer_disagreement_excluded_and_requires_independent_adjudication(
        scenario):
    root, manifest, before, after = scenario
    tasks = prepare_blind_cell_tasks(after)
    a, b = _labels(tasks)
    b["labels"][0]["resolution"] = "unresolved"
    b["labels"][0]["expected_components"] = None
    score = score_independent_pricing_gold(
        before, after, manifest, root, a, b,
    )
    assert score["reviewer_disagreement_cells"] == 1
    assert score["agreed_evaluable_cells"] == 1
    assert not score["deployment_authorized"]


def test_missing_gold_review_lowers_sample_coverage_instead_of_passing(scenario):
    root, manifest, before, after = scenario
    tasks = prepare_blind_cell_tasks(after)
    a, b = _labels(tasks)
    a["labels"] = []
    score = score_independent_pricing_gold(
        before, after, manifest, root, a, b,
    )
    assert score["missing_dual_review_cells"] == 2
    assert score["agreed_evaluable_cells"] == 0
    assert score["evaluator_versions"]["after"]["exact_typed_precision_on_reviewed_cells"] is None


@pytest.mark.parametrize("mutate,error", [
    (lambda a,b: b.update(reviewer_id=a["reviewer_id"]), "distinct"),
    (lambda a,b: a["labels"][0].update(
        publisher_evidence_quote="Model amount not found in this publisher page"
    ), "missing/ambiguous"),
    (lambda a,b: a["labels"][0].update(
        publisher_evidence_quote=LEGEND
    ), "model AND its amount"),
    (lambda a,b: a["labels"][0].update(
        reviewed_at_utc="2026-11-01T09:00:00Z"), "predates"),
    (lambda a,b: a["labels"][0].update(
        approved_for_advisor=True), "cannot approve"),
    (lambda a,b: a["labels"][0].update(
        expected_components=[{"amount": "3.00"}]), "every exact"),
    (lambda a,b: a["labels"][0]["expected_components"][0].update(
        amount="NaN"), "non-finite"),
])
def test_reviewers_cannot_invent_gold_or_skip_evidence(
        scenario, mutate, error):
    root, manifest, before, after = scenario
    tasks = prepare_blind_cell_tasks(after)
    a, b = _labels(tasks)
    mutate(a, b)
    with pytest.raises(ValueError, match=error):
        score_independent_pricing_gold(
            before, after, manifest, root, a, b,
        )


def test_scoring_cannot_use_changed_snapshot_manifest(scenario):
    root, manifest, before, after = scenario
    tasks = prepare_blind_cell_tasks(after)
    a, b = _labels(tasks)
    changed = deepcopy(manifest)
    changed["snapshots"][0]["snapshot"]["sha256"] = "e" * 64
    with pytest.raises(ValueError, match="snapshots differ"):
        score_independent_pricing_gold(
            before, after, changed, root, a, b,
        )


def test_bounded_review_candidates_sample_per_source_not_whole_table(scenario):
    root, manifest, before, after = scenario
    changed = deepcopy(after)
    source = changed["sources"][0]
    template = source["observations"][0]
    for i in range(25):
        extra = deepcopy(template)
        extra["cell_key"] = f"table|table-1|{30 + i}|1"
        extra["case_id"] = "a" * 24
        source["observations"].append(extra)
    changed["replay_sha256"] = _digest_json({
        k: v for k, v in changed.items() if k != "replay_sha256"
    })
    bundle = prepare_blind_cell_tasks(changed)
    assert len(bundle["tasks"]) == 20
    assert bundle["omitted_by_bounded_sampling"] == 7


def test_review_fails_closed_on_tampered_observation_hash(scenario):
    root, manifest, before, after = scenario
    tasks = prepare_blind_cell_tasks(after)
    a, b = _labels(tasks)
    changed = deepcopy(after)
    changed["sources"][0]["observations"][0]["amount"] = "999"
    # A copyedited JSON alone does not change the recorded digest.
    with pytest.raises(ValueError, match="self-checksum"):
        score_independent_pricing_gold(
            before, changed, manifest, root, a, b,
        )



def test_blocked_capture_can_never_be_classified_as_candidate_improvement(
        scenario):
    root, manifest, before, after = scenario
    changed = deepcopy(after)
    changed["sources"][0]["capture_status"] = "blocked"
    changed["replay_sha256"] = _digest_json({
        k: v for k, v in changed.items() if k != "replay_sha256"
    })
    diff = compare_frozen_replays(before, changed)
    assert diff["sources"][0]["comparison"] == (
        "review_coverage_or_product_regression"
    )
    assert not diff["publisher_accuracy_improved_proven"]
