"""P17B2: independently reviewed extraction deltas from pinned original HTML.

Two different reviewers label *physical cells*, blind to crawler prices.
Each reviewer cites a unique original publisher quote present in the
immutable raw HTML. Agreement yields an offline benchmark for the old/new
parser on identical bytes. This does NOT authenticate the HTML origin,
publisher ownership, reviewer independence, or authorize advisor facts.
"""
import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import html

from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.replay_pricing_snapshots import (
    VERSION, OBSERVED_FIELDS, _check_report, _digest_json,
    _sources, compare_frozen_replays, prepare_blind_cell_tasks,
    validate_snapshot_manifest,
)

LABEL_FIELDS = frozenset({
    "case_id", "resolution", "expected_components",
    "publisher_evidence_quote", "review_note", "reviewed_at_utc",
    "approved_for_advisor",
})
EXPECTED_FIELDS = frozenset(OBSERVED_FIELDS)
REVIEWER_FIELDS = frozenset({
    "schema_version", "kind", "reviewer_id", "task_bundle_sha256",
    "labels", "approved_for_advisor",
})
RESOLUTIONS = frozenset({"established", "not_price", "unresolved"})
MAX_NOTE = 1200
MAX_QUOTE = 450
MIN_QUOTE = 24
MIN_NOTE = 24
MAX_REVIEW_CASES = 1200


def _text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Review timestamp must be timezone-aware ISO 8601")
    try:
        x = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Malformed review timestamp") from exc
    if x.tzinfo is None:
        raise ValueError("Review timestamp missing timezone")
    return x.astimezone(timezone.utc)


def _decimal(value):
    if not isinstance(value, str):
        raise ValueError("Manually established price requires a decimal string")
    try:
        x = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed decimal amount") from exc
    if not x.is_finite() or x < 0 or x > Decimal("1000000000"):
        raise ValueError("Negative, huge or non-finite reference rate")
    return str(x.normalize())


def _expected_component(value):
    if not isinstance(value, dict) or set(value) != EXPECTED_FIELDS:
        raise ValueError("Gold component requires every exact typed pricing dimension")
    for key in EXPECTED_FIELDS:
        raw = value[key]
        if key == "amount":
            _decimal(raw)
        elif key in {"region", "tier_or_plan"}:
            if raw is not None and (
                not isinstance(raw, str) or not raw.strip() or len(raw) > 120
            ):
                raise ValueError("Invalid optional gold pricing region/plan scope")
        elif not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 150:
            raise ValueError("Gold pricing fact missing an explicit named dimension")
    return tuple(
        _decimal(value[k]) if k == "amount" else value[k]
        for k in OBSERVED_FIELDS
    )


def _observed_component(value):
    if not isinstance(value, dict) or value.get("amount") is None:
        return None
    try:
        a = _decimal(value["amount"])
    except ValueError:
        return None
    return tuple(
        a if key == "amount" else value.get(key)
        for key in OBSERVED_FIELDS
    )


def _publisher_text(source_id, snapshot_manifest, snapshot_root, cache):
    if source_id not in cache:
        known = _sources()
        snapshot = next(
            (
                x["snapshot"] for x in snapshot_manifest["snapshots"]
                if x["source_id"] == source_id
            ),
            None
        )
        if snapshot is None:
            raise ValueError("Human gold references source without raw snapshot")
        contents = _snapshot_bytes(
            snapshot, snapshot_root,
            expected_url=known[source_id]["url"], method="static_html",
        )
        # Iterating DOM text nodes inserts a space between adjacent elements
        # rather than silently gluing the model name to the price amount.
        root = html.fromstring(contents)
        for noise in root.xpath("//script|//style|//noscript"):
            noise.drop_tree()
        raw = " ".join(
            t for t in root.itertext() if isinstance(t, str) and t.strip()
        )
        cache[source_id] = (_text(raw), _timestamp(snapshot["captured_at_utc"]))
    return cache[source_id]


def _validate_reviewer(reviewer, tasks, snapshot_manifest, snapshot_root, cache):
    if (not isinstance(reviewer, dict) or set(reviewer) != REVIEWER_FIELDS
            or reviewer["schema_version"] != VERSION
            or reviewer["kind"] != "p17b2_blind_independent_rate_cells"
            or reviewer["approved_for_advisor"] is not False
            or reviewer["task_bundle_sha256"] != tasks["task_bundle_sha256"]
            or not isinstance(reviewer["reviewer_id"], str)
            or not 3 <= len(reviewer["reviewer_id"].strip()) <= 75
            or not isinstance(reviewer["labels"], list)
            or len(reviewer["labels"]) > MAX_REVIEW_CASES):
        raise ValueError("Reviewer file was not created from matching blind tasks")
    by_id = {t["case_id"]: t for t in tasks["tasks"]}
    labels = {}
    for label in reviewer["labels"]:
        if not isinstance(label, dict) or set(label) != LABEL_FIELDS:
            raise ValueError("Malformed human reference label")
        case_id = label["case_id"]
        if case_id not in by_id or case_id in labels:
            raise ValueError("Duplicate/unknown human review case")
        task = by_id[case_id]
        if label["approved_for_advisor"] is not False:
            raise ValueError("Reviewer cannot approve an advisor fact")
        resolution = label["resolution"]
        if resolution not in RESOLUTIONS:
            raise ValueError("Invalid gold resolution")
        components = label["expected_components"]
        if resolution == "established":
            if not isinstance(components, list) or not 1 <= len(components) <= 4:
                raise ValueError("Established reference must name 1–4 component rates")
            typed = [_expected_component(x) for x in components]
            if len(set(typed)) != len(typed):
                raise ValueError("Duplicate typed reference components")
        else:
            if components is not None:
                raise ValueError("Unresolved/negative case cannot invent reference rates")
            typed = None if resolution == "unresolved" else []
        note = label["review_note"]
        quote = label["publisher_evidence_quote"]
        if not isinstance(note, str) or not MIN_NOTE <= len(note.strip()) <= MAX_NOTE:
            raise ValueError("Independent reviewer needs substantive notes")
        if not isinstance(quote, str) or not MIN_QUOTE <= len(quote.strip()) <= MAX_QUOTE:
            raise ValueError("Independent reviewer needs a source-specific quote")
        original, captured = _publisher_text(
            task["source_id"], snapshot_manifest, snapshot_root, cache,
        )
        if original.count(_text(quote)) != 1:
            raise ValueError("Publisher evidence quote missing/ambiguous in frozen HTML")
        if _timestamp(label["reviewed_at_utc"]) < captured:
            raise ValueError("Reviewer timestamp predates publisher capture")
        # A reviewer must cite the actual model/rate row, not just a
        # generic page heading or the global input/cache/output legend.
        if resolution == "established" and not any(
            _text(x["model_or_service"]) in _text(quote)
            and _text(x["amount"]) in _text(quote)
            for x in components
        ):
            raise ValueError("Gold quote must identify a reviewed model AND its amount")
        labels[case_id] = (
            resolution, tuple(sorted(typed)) if typed is not None else None,
        )
    return labels


def _cells_for_source(report, sid):
    values = defaultdict(list)
    for obs in report[sid]["observations"]:
        values[obs["cell_key"]].append(obs)
    return values


def score_independent_pricing_gold(before, after, snapshot_manifest,
                                   snapshot_root, reviewer_a, reviewer_b):
    """Report exact typed extraction on dual-agreed ORIGINAL HTML cells only."""
    raw_delta = compare_frozen_replays(before, after)
    validate_snapshot_manifest(snapshot_manifest)
    if _digest_json(snapshot_manifest) != after["capture_manifest_sha256"]:
        raise ValueError("Gold snapshots differ from frozen before/after publisher bytes")
    tasks = prepare_blind_cell_tasks(after)
    if (not isinstance(reviewer_a, dict) or not isinstance(reviewer_b, dict)
            or reviewer_a.get("reviewer_id", "").strip().casefold() ==
               reviewer_b.get("reviewer_id", "").strip().casefold()):
        raise ValueError("Two distinct independently identified reviewers required")
    if len(tasks["tasks"]) > MAX_REVIEW_CASES:
        raise ValueError("Review task set exceeds bounded human evaluation")
    cache = {}
    a = _validate_reviewer(
        reviewer_a, tasks, snapshot_manifest, snapshot_root, cache,
    )
    b = _validate_reviewer(
        reviewer_b, tasks, snapshot_manifest, snapshot_root, cache,
    )
    old = _check_report(before)
    new = _check_report(after)
    metrics = {"before": Counter(), "after": Counter()}
    cases = []
    providers = set()
    disagreements = 0
    incomplete = 0
    unresolved = 0
    for task in tasks["tasks"]:
        case = task["case_id"]
        sid = task["source_id"]
        if case not in a or case not in b:
            incomplete += 1
            continue
        if a[case] != b[case]:
            disagreements += 1
            cases.append({
                "case_id": case, "source_id": sid,
                "status": "disagreement_needs_human_adjudication",
            })
            continue
        status, expected = a[case]
        if status == "unresolved":
            unresolved += 1
            continue
        providers.add(new[sid]["provider"])
        row = {"case_id": case, "source_id": sid, "status": status}
        for name, source in (("before", old), ("after", new)):
            metric = metrics[name]
            observed = [
                _observed_component(x)
                for x in _cells_for_source(source, sid).get(task["cell_key"], [])
            ]
            observed = [x for x in observed if x is not None]
            expected_counts, actual_counts = Counter(expected), Counter(observed)
            matched = sum(
                min(n, actual_counts[token])
                for token, n in expected_counts.items()
            )
            false = sum(actual_counts.values()) - matched
            missing = sum(expected_counts.values()) - matched
            metric["reviewed_cells"] += 1
            metric["correct_exact_typed_components"] += matched
            metric["false_or_misattributed_components"] += false
            metric["missed_expected_components"] += missing
            metric["predicted_components"] += sum(actual_counts.values())
            metric["expected_components"] += sum(expected_counts.values())
            metric["exact_matching_cells"] += (false == 0 and missing == 0)
            row[name] = {
                "correct_components": matched,
                "false_or_misattributed": false,
                "missed": missing,
                "exact_cell_match": false == 0 and missing == 0,
            }
        cases.append(row)
    summary = {}
    for key, counts in metrics.items():
        summary[key] = {
            **dict(counts),
            "exact_typed_precision_on_reviewed_cells": (
                counts["correct_exact_typed_components"] /
                counts["predicted_components"]
                if counts["predicted_components"] else None
            ),
            "exact_typed_recall_on_reviewed_cells": (
                counts["correct_exact_typed_components"] /
                counts["expected_components"]
                if counts["expected_components"] else None
            ),
            "exact_cell_match_fraction": (
                counts["exact_matching_cells"] / counts["reviewed_cells"]
                if counts["reviewed_cells"] else None
            ),
        }
    return {
        "schema_version": VERSION,
        "kind": "p17b2_independent_dual_review_candidate_accuracy_not_release_gold",
        "task_bundle_sha256": tasks["task_bundle_sha256"],
        "frozen_capture_manifest_sha256": after["capture_manifest_sha256"],
        "before_package_sha256": before["local_package_sha256"],
        "after_package_sha256": after["local_package_sha256"],
        "blind_task_count": len(tasks["tasks"]),
        "agreed_evaluable_cells": metrics["after"]["reviewed_cells"],
        "missing_dual_review_cells": incomplete,
        "unresolved_reference_cells": unresolved,
        "reviewer_disagreement_cells": disagreements,
        "provider_count_with_agreed_evaluable_cells": len(providers),
        "evaluator_versions": summary,
        "case_assessments": cases,
        "generalizable_vendor_accuracy_verified": False,
        "publisher_snapshot_origin_authenticated": False,
        "publisher_reviewer_independence_authenticated": False,
        "human_accuracy_signoff_completed": False,
        "advisor_fact_approvals": 0,
        "source_policy_promotions": 0,
        "automatic_adapter_activation": False,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--before", required=True, type=Path)
    p.add_argument("--after", required=True, type=Path)
    p.add_argument("--snapshot-manifest", required=True, type=Path)
    p.add_argument("--snapshot-root", required=True, type=Path)
    p.add_argument("--reviewer-a", required=True, type=Path)
    p.add_argument("--reviewer-b", required=True, type=Path)
    p.add_argument("--out", type=Path,
                   default=Path("output/private/p17b2/independent_pricing_gold.json"))
    args = p.parse_args()
    def load(path):
        if path.stat().st_size > 2_000_000:
            raise ValueError("Review metadata is oversized")
        return json.loads(path.read_text(encoding="utf-8"))
    from scripts.replay_pricing_snapshots import _save_private
    report = score_independent_pricing_gold(
        load(args.before), load(args.after), load(args.snapshot_manifest),
        args.snapshot_root, load(args.reviewer_a), load(args.reviewer_b),
    )
    _save_private(args.out, report)
    print(json.dumps({
        "evaluated_cells": report["agreed_evaluable_cells"],
        "reviewer_disagreements": report["reviewer_disagreement_cells"],
        "generalizable_accuracy_verified": False,
        "advisor_fact_approvals": 0, "network_requests": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
