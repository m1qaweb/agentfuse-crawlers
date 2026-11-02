"""P17B2: replay raw original publisher pricing HTML against pinned parser builds.

Operator supplies independent, byte-frozen, policy-reviewed source captures.
This tool never fetches websites, invokes Zyte, enables a new parser, changes
production data, or promotes a rate into an AgentFuse decision.

Run the *same capture manifest* in separately checked-out v4 and v5 builds,
then compare the two replay reports. More rate candidates is NOT evidence of
higher accuracy until a separate, independent blinded review is completed.
"""
import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.provider_profiles import identify_source_product
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256, source_lifecycle
from agentfuse_crawlers.sources import load_sources
from scripts.compare_acquisition_snapshots import _snapshot_bytes

VERSION = "1.0"
KIND = "original_pricing_html_replay_not_publisher_gold"
MAX_SNAPSHOTS = 64
MAX_REVIEW_PER_SOURCE = 20
MAX_BLIND_REVIEW_CASES = 1000
MAX_INPUT_BYTES = 180_000
SHA = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[0-9a-f]{24}$")
CATEGORIES = {"pricing"}
ORIGIN = "operator_supplied_unverified"
MANIFEST_FIELDS = frozenset({
    "schema_version", "kind", "expected_manifest_sha256",
    "expected_source_registry_sha256", "approved_for_advisor",
    "snapshots",
})
SNAP_FIELDS = frozenset({"source_id", "snapshot"})
OBSERVED_FIELDS = (
    "amount", "currency", "billing_unit", "price_dimension",
    "model_or_service", "region", "tier_or_plan",
)


def _digest_json(obj):
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _sources():
    all_sources = load_sources()
    if len(all_sources) != 460:
        raise ValueError("P17B replay requires the pinned 460-source manifest")
    return {s["id"]: s for s in all_sources if s["category"] == "pricing"}


def _case_id(sid, snapshot_sha, cell_key):
    return hashlib.sha256(
        (sid + "|" + snapshot_sha + "|" + cell_key).encode("utf-8")
    ).hexdigest()[:24]


def _cell_key(obs):
    """Physical cell identity stable across parser revisions and rate splits."""
    kind = obs.get("evidence_kind")
    if (isinstance(kind, str) and kind.startswith("structured_table")
            and isinstance(obs.get("table_id"), str)
            and type(obs.get("row_index")) is int
            and type(obs.get("column_index")) is int):
        return "table|" + str(obs["table_id"]) + "|" + str(
            obs["row_index"]
        ) + "|" + str(obs["column_index"])
    # Cards may not have physical table coordinates; the identity remains
    # review-only and is not automatically matched to a table price.
    for key in ("source_evidence_sha256", "observation_id"):
        candidate = obs.get(key)
        if isinstance(candidate, str) and len(candidate) >= 24:
            return "other|" + str(kind) + "|" + candidate[:64]
    raise ValueError("Pricing evidence has no replayable physical-cell identity")


def _freeze_observation(obs, sid, snapshot_sha):
    if not isinstance(obs, dict) or obs.get("approved_for_advisor") is not False:
        raise ValueError("Crawler pricing observation must explicitly forbid approval")
    if obs.get("source_id") != sid:
        raise ValueError("Pricing observation source attribution disagrees with snapshot")
    locator = _cell_key(obs)
    amount = obs.get("observed_single_amount_decimal")
    # The original page contains *observed* amounts, but not automatically
    # normalized comparable prices. Preserve both separate.
    if amount is not None and not isinstance(amount, str):
        raise ValueError("Observed price amount must use exact decimal text")
    def dimension(value):
        return value if value is None or isinstance(value, str) else str(value)
    out = {
        "case_id": _case_id(sid, snapshot_sha, locator),
        "cell_key": locator,
        "observation_id": obs.get("observation_id"),
        "evidence_kind": obs.get("evidence_kind"),
        "component_index": obs.get("inline_component_index"),
        "component_count": obs.get("inline_component_count"),
        "component_origin": obs.get("inline_component_parent_identity_review_status"),
        "raw_parent_sha256": hashlib.sha256(str(
            obs.get("raw_parent_cell_text") or obs.get("raw_displayed_price") or ""
        ).encode("utf-8")).hexdigest(),
        "source_evidence_sha256": obs.get("source_evidence_sha256"),
        "amount": amount,
        "currency": dimension(obs.get("currency")),
        "billing_unit": dimension(obs.get("billing_unit")),
        "price_dimension": dimension(obs.get("price_dimension")),
        "model_or_service": dimension(obs.get("model_or_service")),
        "region": dimension(obs.get("region")),
        "tier_or_plan": dimension(obs.get("tier_or_plan")),
        "model_label_hygiene_status": obs.get("model_label_hygiene_status"),
        "normalization_blockers": list(obs.get("normalization_blockers") or [])[:25],
        "normalized_amount_decimal": obs.get("normalized_amount_decimal"),
        "comparable_candidate": obs.get("comparable_candidate") is True,
        "review_quote_candidate": obs.get("review_quote_candidate") is True,
        "publisher_fact_verified": False,
        "approved_for_advisor": False,
    }
    if out["component_index"] is not None and (
        type(out["component_index"]) is not int or
        not 0 <= out["component_index"] < 4
    ):
        raise ValueError("Inline component index is invalid")
    if out["comparable_candidate"] and out["normalization_blockers"]:
        raise ValueError("Price with normalization blockers cannot be comparable")
    if (out["component_origin"] and
            (out["normalized_amount_decimal"] is not None
             or out["comparable_candidate"]
             or out["review_quote_candidate"])):
        raise ValueError("Review-only P17B component was promoted to a normal rate")
    return out


def validate_snapshot_manifest(manifest):
    if (not isinstance(manifest, dict)
            or set(manifest) != MANIFEST_FIELDS
            or manifest["schema_version"] != VERSION
            or manifest["kind"] != "frozen_original_pricing_html_manifest"
            or manifest["approved_for_advisor"] is not False
            or manifest["expected_manifest_sha256"] != manifest_sha256()
            or manifest["expected_source_registry_sha256"] !=
               registry_revision_sha256()
            or not isinstance(manifest["snapshots"], list)
            or not 1 <= len(manifest["snapshots"]) <= MAX_SNAPSHOTS):
        raise ValueError("P17B2 input manifest must be complete and source-pinned")
    known = _sources()
    seen = set()
    for entry in manifest["snapshots"]:
        if not isinstance(entry, dict) or set(entry) != SNAP_FIELDS:
            raise ValueError("P17B2 snapshot entry has unknown/missing fields")
        sid = entry["source_id"]
        if not isinstance(sid, str) or sid in seen or sid not in known:
            raise ValueError("Duplicate, invalid or unconfigured pricing source")
        seen.add(sid)
        if source_lifecycle(known[sid])["state"] in {"quarantined", "retired"}:
            raise ValueError("Publisher-blocked source is not eligible for pilot")
        # Actual bytes, redirects and first-party exact URL are checked by
        # _snapshot_bytes(), not by trusting a source_id string alone.
    return known


def replay_pricing_snapshots(manifest, snapshot_root):
    known = validate_snapshot_manifest(manifest)
    packet_sha = _digest_json(manifest)
    results = []
    for entry in sorted(manifest["snapshots"], key=lambda e: e["source_id"]):
        sid = entry["source_id"]
        src = known[sid]
        snapshot = entry["snapshot"]
        raw = _snapshot_bytes(
            snapshot, snapshot_root,
            expected_url=src["url"], method="static_html",
        )
        evidence = extract_evidence(
            raw, src["url"], category="pricing", source_id=sid,
        )
        identity = identify_source_product(src, evidence)
        quality_status, quality_reason = assess_capture(
            "pricing", evidence, evidence.get("text", ""),
        )
        observations = evidence.get("pricing_observations") or []
        if not isinstance(observations, list):
            raise ValueError("Non-list pricing observations")
        typed = [
            _freeze_observation(o, sid, snapshot["sha256"])
            for o in observations
        ]
        physical = defaultdict(list)
        for obs in typed:
            physical[obs["cell_key"]].append(obs)
        # Never "win" on a page with silent observation truncation.
        incomplete = not (
            evidence.get("pricing_inventory_complete") is True
        ) or evidence.get("pricing_observation_limit_reached") is True
        if any(len(parts) > 4 for parts in physical.values()):
            raise ValueError("More than four components from one physical rate cell")
        results.append({
            "source_id": sid,
            "source_url": src["url"],
            "provider": src["provider"],
            "snapshot_sha256": snapshot["sha256"],
            "snapshot_captured_at_utc": snapshot["captured_at_utc"],
            "snapshot_origin_review_status": ORIGIN,
            "capture_status": quality_status,
            "capture_reason": quality_reason,
            "source_product_title_conflict": identity["source_product_title_conflict"],
            "source_product_ownership_verified": False,
            "pricing_parser_revision": evidence.get("pricing_parser_revision"),
            "pricing_evidence_schema": evidence.get("pricing_evidence_schema"),
            "content_text_sha256": evidence.get("content_sha256"),
            "pricing_relevant_table_count": evidence.get("pricing_table_relevant", 0),
            "pricing_table_scan_truncated": bool(evidence.get(
                "pricing_table_scan_truncated"
            )),
            "pricing_inventory_complete": not incomplete,
            "pricing_observation_limit_reached": bool(evidence.get(
                "pricing_observation_limit_reached"
            )),
            "pricing_observation_total_detected": evidence.get(
                "pricing_observation_total_detected", len(typed)
            ),
            "pricing_inline_rate_cells_split": evidence.get(
                "pricing_inline_rate_cells_split", 0
            ),
            "pricing_legend_backed_triplet_cells_split": evidence.get(
                "pricing_legend_backed_triplet_cells_split", 0
            ),
            "pricing_model_label_recovered_rows": evidence.get(
                "pricing_model_label_recovered_rows", 0
            ),
            "observed_component_count": sum(
                obs["amount"] is not None for obs in typed
            ),
            "comparable_candidate_count": sum(
                obs["comparable_candidate"] for obs in typed
            ),
            "unreviewed_physical_cell_count": len(physical),
            "observations": typed,
            "publisher_fact_verified": False,
            "approved_for_advisor": False,
        })
    result = {
        "schema_version": VERSION,
        "kind": KIND,
        "capture_manifest_sha256": packet_sha,
        "source_manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "local_package_sha256": package_fingerprint(),
        "source_count": len(results),
        "sources": results,
        "independently_authenticated_publisher_captures": False,
        "independent_human_review_completed": False,
        "verified_publisher_pricing_facts": 0,
        "advisor_fact_approvals": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }
    result["replay_sha256"] = _digest_json(result)
    return result


def _check_report(report):
    if (not isinstance(report, dict)
            or report.get("kind") != KIND
            or report.get("schema_version") != VERSION
            or report.get("deployment_authorized") is not False
            or report.get("advisor_fact_approvals") != 0
            or report.get("verified_publisher_pricing_facts") != 0
            or not isinstance(report.get("sources"), list)
            or not isinstance(report.get("replay_sha256"), str)
            or not SHA.fullmatch(report["replay_sha256"])):
        raise ValueError("Invalid unapproved P17B2 replay report")
    old = dict(report)
    digest = old.pop("replay_sha256")
    if _digest_json(old) != digest:
        raise ValueError("P17B2 replay self-checksum mismatch")
    ids = []
    for source in report["sources"]:
        if (not isinstance(source, dict) or
                source.get("approved_for_advisor") is not False
                or not isinstance(source.get("observations"), list)
                or any(o.get("approved_for_advisor") is not False
                       for o in source["observations"])):
            raise ValueError("Replay source or observation was falsely approved")
        ids.append(source.get("source_id"))
    if len(set(ids)) != len(ids):
        raise ValueError("Replay duplicates a source")
    return {entry["source_id"]: entry for entry in report["sources"]}


def compare_frozen_replays(before, after):
    """Compare distinct parser versions ONLY on identical source HTML bytes."""
    old_sources = _check_report(before)
    new_sources = _check_report(after)
    hashes = (
        "capture_manifest_sha256", "source_manifest_sha256",
        "source_registry_sha256",
    )
    if (any(before.get(k) != after.get(k) for k in hashes)
            or old_sources.keys() != new_sources.keys()
            or before["local_package_sha256"] == after["local_package_sha256"]):
        raise ValueError("Replay comparison must use same frozen input and different packages")
    changes = []
    overall = Counter()
    for sid in sorted(old_sources):
        original, current = old_sources[sid], new_sources[sid]
        if (original.get("snapshot_sha256") != current.get("snapshot_sha256")
                or original.get("source_url") != current.get("source_url")
                or original.get("provider") != current.get("provider")
                or original.get("pricing_parser_revision") ==
                   current.get("pricing_parser_revision")):
            raise ValueError("Changed publisher snapshot or unchanged pricing parser")
        old_cells = {r["cell_key"] for r in original["observations"]}
        new_cells = {r["cell_key"] for r in current["observations"]}
        gained = new_cells - old_cells
        lost = old_cells - new_cells
        old_observed = original["observed_component_count"]
        new_observed = current["observed_component_count"]
        error = bool(
            current["source_product_title_conflict"]
            or current["capture_status"] == "blocked"
            or current["pricing_observation_limit_reached"]
            or not current["pricing_inventory_complete"]
            or (original["pricing_inventory_complete"]
                and not current["pricing_inventory_complete"])
        )
        status = (
            "review_coverage_or_product_regression" if error or lost
            else "new_structured_observations_unverified" if
            new_observed > old_observed
            else "fewer_observations_requires_review" if
            new_observed < old_observed
            else "no_verified_accuracy_gain"
        )
        overall[status] += 1
        changes.append({
            "source_id": sid, "source_url": original["source_url"],
            "snapshot_sha256": original["snapshot_sha256"],
            "parser_revision_before": original["pricing_parser_revision"],
            "parser_revision_after": current["pricing_parser_revision"],
            "observed_amounts_before": old_observed,
            "observed_amounts_after": new_observed,
            "physical_cells_before": len(old_cells),
            "physical_cells_after": len(new_cells),
            "physical_cells_gained": len(gained),
            "physical_cells_lost": len(lost),
            "legend_backed_cells_after": current.get(
                "pricing_legend_backed_triplet_cells_split", 0
            ),
            "inventory_complete_before": original["pricing_inventory_complete"],
            "inventory_complete_after": current["pricing_inventory_complete"],
            "comparison": status,
            "manually_checked_gold_accuracy": False,
            "adapter_rollout_authorized": False,
        })
    return {
        "schema_version": VERSION,
        "kind": "p17b2_frozen_html_parser_delta_not_gold_accuracy",
        "source_count": len(changes),
        "capture_manifest_sha256": before["capture_manifest_sha256"],
        "before_package_sha256": before["local_package_sha256"],
        "after_package_sha256": after["local_package_sha256"],
        "outcome_counts": dict(sorted(overall.items())),
        "sources": changes,
        "independent_gold_precision": None,
        "independent_gold_recall": None,
        "publisher_accuracy_improved_proven": False,
        "advisor_fact_approvals": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }


def prepare_blind_cell_tasks(report):
    """Balanced physical-cell review tasks; no crawler-derived prices shown.

    Bound each provider before the global cap, and preserve the omitted
    count so a 300-row table cannot create a fake representative dataset.
    """
    sources = _check_report(report)
    by_source = {}
    omitted = 0
    for sid in sorted(sources):
        row = sources[sid]
        if row["source_product_title_conflict"]:
            continue
        cells = sorted({o["cell_key"] for o in row["observations"]})
        omitted += max(0, len(cells) - MAX_REVIEW_PER_SOURCE)
        by_source[sid] = cells[:MAX_REVIEW_PER_SOURCE]
    tasks = []
    for depth in range(MAX_REVIEW_PER_SOURCE):
        for sid in sorted(by_source):
            cells = by_source[sid]
            if depth >= len(cells):
                continue
            if len(tasks) >= MAX_BLIND_REVIEW_CASES:
                omitted += 1
                continue
            row = sources[sid]
            cell_key = cells[depth]
            tasks.append({
                "case_id": _case_id(sid, row["snapshot_sha256"], cell_key),
                "source_id": sid,
                "source_url": row["source_url"],
                "snapshot_sha256": row["snapshot_sha256"],
                "cell_key": cell_key,
                "expected_values_prefilled": False,
                "publisher_fact_approved": False,
            })
    basis = {
        "schema_version": VERSION,
        "kind": "p17b2_blind_physical_cells_unreviewed",
        "replay_sha256": report["replay_sha256"],
        "capture_manifest_sha256": report["capture_manifest_sha256"],
        "tasks": tasks,
        "sampling": "source_round_robin_max_20_cells_per_source",
        "omitted_by_bounded_sampling": omitted,
        "reviewers_needed": 2,
        "approved_for_advisor": False,
    }
    basis["task_bundle_sha256"] = _digest_json(basis)
    return basis


def reviewer_template(tasks, reviewer_id):
    if not isinstance(reviewer_id, str) or not 3 <= len(reviewer_id) <= 75:
        raise ValueError("Distinct nonempty reviewer ID is required")
    return {
        "schema_version": VERSION,
        "kind": "p17b2_blind_independent_rate_cells",
        "reviewer_id": reviewer_id,
        "task_bundle_sha256": tasks["task_bundle_sha256"],
        "labels": [],
        "approved_for_advisor": False,
    }


def source_pins(source_ids):
    """Read-only exact source URL/manifest fingerprints; NO request issued."""
    if (not isinstance(source_ids, list)
            or not 1 <= len(source_ids) <= MAX_SNAPSHOTS
            or any(not isinstance(sid, str) for sid in source_ids)
            or len(set(source_ids)) != len(source_ids)):
        raise ValueError("Supply 1-64 distinct configured pricing source IDs")
    known = _sources()
    sources = []
    for sid in source_ids:
        src = known.get(sid)
        if src is None or source_lifecycle(src)["state"] in {"quarantined", "retired"}:
            raise ValueError("Unknown or publisher-blocked source for manifest")
        sources.append({
            "source_id": sid, "official_source_url": src["url"],
            "category": "pricing",
        })
    return {
        "expected_manifest_sha256": manifest_sha256(),
        "expected_source_registry_sha256": registry_revision_sha256(),
        "operator_source_urls": sources,
        "network_requests_performed": 0,
        "captures_created": 0,
        "approved_for_advisor": False,
    }


def _save_private(path, report):
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("Refusing symlink output")
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.chmod(target, 0o600)
    return str(target)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_mutually_exclusive_group(required=True)
    actions.add_argument("--replay", action="store_true")
    actions.add_argument("--compare", action="store_true")
    actions.add_argument("--blind-review-tasks", action="store_true")
    actions.add_argument("--source-pins", action="store_true")
    p.add_argument("--source-ids", type=str,
                   help="Comma-separated configured pricing source IDs (pins only)")
    p.add_argument("--manifest", type=Path)
    p.add_argument("--snapshot-root", type=Path)
    p.add_argument("--before", type=Path)
    p.add_argument("--after", type=Path)
    p.add_argument("--out-dir", type=Path,
                   default=Path("output/private/p17b2"))
    args = p.parse_args()

    def load(path):
        if not path or path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("Missing or oversized replay metadata input")
        return json.loads(path.read_text(encoding="utf-8"))
    if args.source_pins:
        if not args.source_ids:
            p.error("--source-pins requires --source-ids")
        print(json.dumps(source_pins(
            [x.strip() for x in args.source_ids.split(",")]
        ), indent=2))
        return
    if args.replay:
        if not (args.manifest and args.snapshot_root):
            p.error("--replay requires --manifest and --snapshot-root")
        result = replay_pricing_snapshots(load(args.manifest), args.snapshot_root)
        target = _save_private(args.out_dir / "pricing_html_replay.json", result)
        text = {"sources": result["source_count"], "report": target}
    elif args.compare:
        if not (args.before and args.after):
            p.error("--compare requires --before and --after replay outputs")
        result = compare_frozen_replays(load(args.before), load(args.after))
        target = _save_private(args.out_dir / "pricing_parser_delta.json", result)
        text = {"sources": result["source_count"], "report": target}
    else:
        if not args.after:
            p.error("--blind-review-tasks requires --after replay JSON")
        result = prepare_blind_cell_tasks(load(args.after))
        target = _save_private(args.out_dir / "blind_pricing_cell_tasks.json", result)
        _save_private(args.out_dir / "reviewer_a_template.json",
                      reviewer_template(result, "REVIEWER_A"))
        _save_private(args.out_dir / "reviewer_b_template.json",
                      reviewer_template(result, "REVIEWER_B"))
        text = {"review_tasks": len(result["tasks"]), "report": target}
    print(json.dumps({
        **text, "verified_publisher_facts": 0, "network_requests": 0
    }, indent=2))


if __name__ == "__main__":
    main()
