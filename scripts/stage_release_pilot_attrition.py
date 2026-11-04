"""P19A6: attrition-aware original-HTML changelog pilot, offline only.

An original frozen P19A4 15-25-source selection MUST remain the denominator
even when the P19A5 policy ledger holds a publisher, or a policy-permitted
manual P19A1 original-HTML capture was not supplied. Never substitute sources
or turn missing publisher gold into parser negatives, zeroes or 100% accuracy.

Input layout (operator's manually produced P19A1 per-source captures):
  <capture-root>/wave_01/<source_id>/{frozen_release_snapshots.json,
                                     capture_audit.json,<source>-<hash>.html}
A previously completed 5-source <capture-root>/wave_01/ capture is accepted
only when every publisher in that wave was operator-policy-eligible.

Staging generates P19A1 original-page replay, P19A2 BLANK human census
templates, original audit receipts, an all-selected-source attrition ledger,
and a captured-subset P19A3 cohort. The score command independently
recomputes P19A3 from the staged HTML after genuine filled reviews arrive;
it reports both the ORIGINAL denominator and scored-only diagnostics.

Zero external requests, new spiders, publisher permissions, advisor facts,
Zyte jobs, automated release alerts, production DB writes or deployment.
"""
import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.sources import load_sources
from scripts.aggregate_release_pilot import (
    _json, _safe_member, aggregate_release_pilot,
)
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)
from scripts.prepare_release_pilot import (
    _audit_batch, _mkdir, _put, _read_plan, _recheck_plan,
)
from scripts.replay_release_snapshots import (
    MANIFEST_KIND, VERSION, _digest, replay_changelog_html,
    validate_capture_manifest,
)
from scripts.review_release_pilot_policy import (
    DECISION_ELIGIBLE, validate_policy_ledger,
)
from scripts.score_release_gold import (
    _split_key, prepare_census_packet, reviewer_template,
)

KIND = "p19a6_full_frozen_source_selection_capture_attrition"
SCORE_KIND = "p19a6_full_selection_owner_date_diagnostics"
MAX_JSON_BYTES = 4_000_000


def _one_source_batch(wave, source):
    return {
        "batch_id": wave["batch_id"] + "/" + source["source_id"],
        "sources": [source],
        "source_ids": [source["source_id"]],
    }


def _safe_existing_capture(root, relative):
    """Missing is a held source, symlinks/unsafe types are fatal."""
    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        raise ValueError("Capture root must be a real directory")
    member = base
    for part in relative.split("/"):
        if part in {"", ".", ".."}:
            raise ValueError("Capture location attempted directory traversal")
        member = member / part
        if member.is_symlink():
            raise ValueError("Capture location contains symlink")
        if member.exists() and not member.is_dir():
            raise ValueError("Capture path must be a directory")
    return member.is_dir()


def _inspect_waves(plan, receipt, capture_root):
    """Preflight ALL source coverage before writing any new staged output."""
    waves, source_rows = [], []
    known = {x["id"]: x for x in load_sources()}
    eligible_by_wave = {
        wave["batch_id"]: set(
            wave["operator_attested_capture_eligible_source_ids"]
        ) for wave in receipt["batches"]
    }
    for path in Path(capture_root).iterdir():
        if (path.is_symlink() or path.name not in {
                x["batch_id"] for x in plan["batches"]
            }):
            raise ValueError("Orphan/unknown publisher capture outside frozen waves")
    for wave in plan["batches"]:
        wid = wave["batch_id"]
        ids = wave["source_ids"]
        ready = eligible_by_wave[wid]
        wave_dir = _safe_existing_capture(capture_root, wid)
        full_capture = bool(
            wave_dir and _safe_member_directory_or_none(
                capture_root, wid + "/frozen_release_snapshots.json",
            )
        )
        any_individual = any(
            _safe_existing_capture(capture_root, wid + "/" + sid)
            for sid in ids
        )
        if full_capture and any_individual:
            raise ValueError("Ambiguous full-wave and individual publisher captures")
        all_inspected = {}
        if full_capture:
            if set(ids) != ready:
                raise ValueError(
                    "A combined wave cannot include any policy-held source"
                )
            complete = _audit_batch(wave, capture_root)
            _check_receipt(complete["audit"], receipt)
            snapshots = complete["manifest"]["snapshots"]
            for source, entry in zip(wave["sources"], snapshots):
                sid = source["source_id"]
                original = entry["snapshot"]["file"]
                matched = [v for v in complete["html"] if v[0] == original]
                if len(matched) != 1:
                    raise ValueError("Combined original HTML file identity ambiguous")
                all_inspected[sid] = {
                    "entry": entry, "original_html": matched[0][1],
                    "audit": complete["audit"],
                }
        else:
            for source in wave["sources"]:
                sid = source["source_id"]
                if not _safe_existing_capture(capture_root, wid + "/" + sid):
                    continue
                if sid not in ready:
                    raise ValueError("Capturing a publisher blocked by frozen policy")
                single = _audit_batch(_one_source_batch(wave, source), capture_root)
                _check_receipt(single["audit"], receipt)
                # P19A1 creates exactly an HTML file and two JSON
                # receipts. Extra symlinks or files are an uninspected
                # evidence bundle, not a valid original-page snapshot.
                folder = _safe_member(
                    capture_root, wid + "/" + sid, directory=True,
                )
                allowed_files = {
                    "frozen_release_snapshots.json", "capture_audit.json",
                    single["manifest"]["snapshots"][0]["snapshot"]["file"],
                }
                if any(
                    p.is_symlink() or not p.is_file()
                    or p.name not in allowed_files for p in folder.iterdir()
                ):
                    raise ValueError("Unexpected file or symlink in source capture")
                all_inspected[sid] = {
                    "entry": single["manifest"]["snapshots"][0],
                    "original_html": single["html"][0][1],
                    "audit": single["audit"],
                }
        # Unknown captured source IDs are never silently ignored; reject
        # files/directories that appear to represent unplanned publisher work.
        if wave_dir:
            folder = _safe_member(capture_root, wid, directory=True)
            allowed = set(ids) | (
                {"frozen_release_snapshots.json", "capture_audit.json"}
                if full_capture else set()
            )
            if full_capture:
                allowed.update(x["entry"]["snapshot"]["file"] for x
                               in all_inspected.values())
            unexpected = [
                p.name for p in folder.iterdir()
                if p.name not in allowed or p.is_symlink()
            ]
            if unexpected:
                raise ValueError("Unplanned/orphan capture files in frozen wave")
        picked = []
        for source in wave["sources"]:
            sid = source["source_id"]
            eligible = sid in ready
            matched = all_inspected.get(sid)
            if matched:
                status = "captured_original_html_unreviewed"
            elif eligible:
                status = "eligible_but_original_html_not_supplied"
            else:
                status = "publisher_policy_held"
            record = {
                "source_id": sid,
                "source_url": source["source_url"],
                "provisional_provider_group":
                    source["provisional_provider_group"],
                "frozen_batch_id": wid,
                "publisher_policy_decision": next(
                    rev["decision"] for rev in receipt["policy_rows"]
                    if rev["source_id"] == sid
                ),
                "capture_status": status,
                "raw_snapshot_sha256": (
                    matched["entry"]["snapshot"]["sha256"] if matched else None
                ),
                "publisher_capture_audit_sha256": (
                    _digest(matched["audit"]) if matched else None
                ),
                "publisher_origin_independently_authenticated": False,
                "approved_for_advisor": False,
            }
            source_rows.append(record)
            if matched:
                picked.append(matched)
        waves.append((wave, picked))
    if len(source_rows) != plan["source_count"]:
        raise ValueError("Original frozen source denominator no longer matches")
    return waves, source_rows


def _safe_member_directory_or_none(root, relative):
    # Only missing individual capture files are expected. A symlinked
    # evidence file must never be interpreted as a harmless missing source.
    base = Path(root)
    child = base
    for part in relative.split("/"):
        if part in {"", ".", ".."}:
            raise ValueError("Path traversal in original publisher capture")
        child = child / part
        if child.is_symlink():
            raise ValueError("Symlink in original publisher capture")
    if not child.exists():
        return False
    if not child.is_file():
        raise ValueError("Unexpected publisher capture metadata type")
    return True


def _check_receipt(audit, receipt):
    if (audit.get("source_specific_policy_review_completed") is not True
            or audit.get("source_specific_policy_review_receipt_sha256") !=
                receipt["receipt_sha256"]):
        raise ValueError(
            "Original P19A1 capture is not bound to the currently frozen "
            "per-publisher P19A5 policy review"
        )


def stage_partial_pilot(plan, ledger, capture_root, out_dir, *,
                        selection_key, split_key):
    """Stage any lawfully captured sources without replacing held publishers."""
    _split_key(split_key)
    frozen = _recheck_plan(plan, selection_key=selection_key)
    receipt = validate_policy_ledger(
        frozen, ledger, selection_key=selection_key,
    )
    inspected, original_rows = _inspect_waves(
        frozen, _inject_decisions(receipt, ledger), capture_root,
    )
    # Validation and private capture integrity checks finish BEFORE writing.
    root = _private_new_directory(out_dir)
    cohort = []
    try:
        for wave, captured in inspected:
            if not captured:
                continue
            wid = wave["batch_id"]
            _mkdir(root, wid)
            directory = _mkdir(root, wid, "capture")
            _mkdir(root, wid, "replay")
            _mkdir(root, wid, "census")
            _mkdir(root, wid, "capture_audits")
            entries = []
            for item in captured:
                entry = item["entry"]
                src = entry["source_id"]
                filename = entry["snapshot"]["file"]
                _write_private(directory / filename, item["original_html"])
                entries.append(entry)
                _put(root / wid / "capture_audits" / (src + ".json"),
                     item["audit"])
            combined = {
                "schema_version": VERSION,
                "kind": MANIFEST_KIND,
                "expected_manifest_sha256": frozen["source_manifest_sha256"],
                "expected_source_registry_sha256": frozen["source_registry_sha256"],
                "approved_for_advisor": False,
                "snapshots": entries,
            }
            validate_capture_manifest(combined)
            _put(directory / "frozen_release_snapshots.json", combined)
            replay = replay_changelog_html(combined, directory)
            _put(root / wid / "replay" / "changelog_html_replay.json", replay)
            packet = prepare_census_packet(
                replay, combined, directory, split_key=split_key,
                holdout_percent=frozen["holdout_percent"],
            )
            _put(root / wid / "census" / "blind_source_census_packet.json", packet)
            for label in ("a", "b"):
                _put(root / wid / "census" /
                     ("reviewer_" + label + "_template.json"),
                     reviewer_template(packet, label))
            cohort.append({
                "batch_id": wid,
                "replay": wid + "/replay/changelog_html_replay.json",
                "capture_manifest":
                    wid + "/capture/frozen_release_snapshots.json",
                "snapshot_root": wid + "/capture",
                "blind_packet": wid + "/census/blind_source_census_packet.json",
                "reviewer_a": wid + "/census/reviewer_a_filled.json",
                "reviewer_b": wid + "/census/reviewer_b_filled.json",
            })
        # This is a captured-SUBSET input to the existing P19A3 scorer,
        # not a claim of full 20-source coverage. The P19A6 score CLI
        # recomputes and appends the ORIGINAL selection denominator.
        subset = {
            "schema_version": VERSION,
            "kind": "p19a3_reviewed_release_source_batch_cohort",
            "approved_for_advisor": False,
            "holdout_percent": frozen["holdout_percent"],
            "batches": cohort,
        }
        statuses = Counter(row["capture_status"] for row in original_rows)
        full = {
            "schema_version": VERSION,
            "kind": KIND,
            "pilot_plan_sha256": frozen["plan_sha256"],
            "source_manifest_sha256": frozen["source_manifest_sha256"],
            "source_registry_sha256": frozen["source_registry_sha256"],
            "policy_ledger_sha256": receipt["ledger_sha256"],
            "source_policy_receipt_sha256": receipt["receipt_sha256"],
            "captured_subset_cohort_sha256": _digest(subset),
            "frozen_source_count": frozen["source_count"],
            "frozen_provisional_provider_groups":
                frozen["selected_provisional_provider_groups"],
            "captured_source_count":
                statuses["captured_original_html_unreviewed"],
            "policy_held_count": statuses["publisher_policy_held"],
            "eligible_uncaptured_count":
                statuses["eligible_but_original_html_not_supplied"],
            "original_selected_sources": original_rows,
            "status_counts": dict(sorted(statuses.items())),
            "owner_date_scored_source_count": 0,
            "pilot_accuracy_established": False,
            "new_source_permissions": 0,
            "network_requests_performed": 0,
            "zyte_jobs_created": 0,
            "advisor_fact_approvals": 0,
            "deployment_authorized": False,
            "approved_for_advisor": False,
        }
        full["ledger_sha256"] = _digest(full)
        _put(root / "captured_subset_review_cohort.json", subset)
        _put(root / "full_frozen_selection_accounting.json", full)
    except Exception:
        shutil.rmtree(root)
        raise
    return {
        "private_staged_root": str(root),
        "frozen_selected_sources": frozen["source_count"],
        "original_html_captured": full["captured_source_count"],
        "source_policy_held": full["policy_held_count"],
        "eligible_original_html_missing": full["eligible_uncaptured_count"],
        "blank_independent_reviewer_templates": 2 * len(cohort),
        "ready_to_score_human_gold": False,
        "accurate_for_full_selected_population": False,
        "publisher_facts_authenticated": False,
        "new_source_permissions": 0,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "advisor_fact_approvals": 0,
        "deployment_authorized": False,
    }


def _inject_decisions(receipt, ledger):
    decisions = {r["source_id"]: r["decision"] for r in ledger["reviews"]}
    enriched = {**receipt, "policy_rows": [
        {"source_id": sid, "decision": decision}
        for sid, decision in decisions.items()
    ]}
    return enriched


def score_partial_pilot(plan, ledger, staged_root, *, selection_key, split_key):
    """Recompute review evidence then force full original cohort denominators."""
    frozen = _recheck_plan(plan, selection_key=selection_key)
    receipt = validate_policy_ledger(
        frozen, ledger, selection_key=selection_key,
    )
    stored = _json(staged_root, "full_frozen_selection_accounting.json")
    subset = _json(staged_root, "captured_subset_review_cohort.json")
    if (stored.get("kind") != KIND or stored.get("schema_version") != VERSION
            or stored.get("pilot_plan_sha256") != frozen["plan_sha256"]
            or stored.get("policy_ledger_sha256") != receipt["ledger_sha256"]
            or stored.get("source_policy_receipt_sha256") != receipt["receipt_sha256"]
            or stored.get("source_manifest_sha256") != frozen["source_manifest_sha256"]
            or stored.get("source_registry_sha256") != frozen["source_registry_sha256"]
            or stored.get("captured_subset_cohort_sha256") != _digest(subset)
            or stored.get("ledger_sha256") != _digest({
                k: v for k, v in stored.items() if k != "ledger_sha256"
            }) or stored.get("approved_for_advisor") is not False):
        raise ValueError("Tampered or unbound original 20-source selection ledger")
    original = stored["original_selected_sources"]
    sources = {
        row["source_id"]: row for row in original
    }
    planned = {
        item["source_id"]: item
        for wave in frozen["batches"] for item in wave["sources"]
    }
    if (len(original) != frozen["source_count"]
            or set(sources) != set(planned)
            or stored.get("frozen_source_count") != len(planned)):
        raise ValueError("Frozen source denominator is incomplete or replaced")
    # Never trust stored attrition categories as reviewer truth; reconstruct
    # from operator-policy decisions and the staged actual source manifest.
    expected_status = {
        sid: (
            "publisher_policy_held" if rev["decision"] != DECISION_ELIGIBLE
            else None
        )
        for sid, rev in ((r["source_id"], r) for r in ledger["reviews"])
    }
    expected_captured = set()
    audit_hashes = {}
    snapshot_hashes = {}
    if (not isinstance(subset, dict)
            or subset.get("kind") != "p19a3_reviewed_release_source_batch_cohort"
            or subset.get("holdout_percent") != frozen["holdout_percent"]
            or not isinstance(subset.get("batches"), list)):
        raise ValueError("Invalid captured-subset P19A3 cohort")
    seen_waves = set()
    for entry in subset["batches"]:
        wid = entry["batch_id"]
        if wid in seen_waves:
            raise ValueError("Repeated wave would double-count publisher evidence")
        seen_waves.add(wid)
        wave = next((w for w in frozen["batches"]
                    if w["batch_id"] == wid), None)
        if wave is None:
            raise ValueError("Unknown frozen wave in captured subset")
        manifest = _json(staged_root, entry["capture_manifest"])
        validate_capture_manifest(manifest)
        expected_wave = set(wave["source_ids"])
        for saved in manifest["snapshots"]:
            sid = saved["source_id"]
            if (sid not in expected_wave or sid in expected_captured
                    or expected_status[sid] == "publisher_policy_held"):
                raise ValueError("Duplicate/unplanned/blocked source in captured subset")
            expected_captured.add(sid)
            expected_status[sid] = "captured_original_html_unreviewed"
            snapshot_hashes[sid] = saved["snapshot"]["sha256"]
            audit_path = wid + "/capture_audits/" + sid + ".json"
            audit = _json(staged_root, audit_path)
            if (audit.get("source_specific_policy_review_completed") is not True
                    or audit.get("source_specific_policy_review_receipt_sha256")
                       != receipt["receipt_sha256"]):
                raise ValueError("Staged capture audit lost exact policy receipt")
            audit_hashes[sid] = _digest(audit)
    for sid in expected_status:
        if expected_status[sid] is None:
            expected_status[sid] = "eligible_but_original_html_not_supplied"
    if any(
        (
            row.get("source_url") != planned[sid]["source_url"]
            or row.get("provisional_provider_group")
               != planned[sid]["provisional_provider_group"]
            or row.get("capture_status") != expected_status[sid]
            or row.get("frozen_batch_id") != next(
                x["batch_id"] for x in frozen["batches"]
                if sid in x["source_ids"]
            )
            or row.get("raw_snapshot_sha256") != snapshot_hashes.get(sid)
            or row.get("publisher_capture_audit_sha256") !=
               audit_hashes.get(sid)
            or row.get("publisher_policy_decision") != next(
                x["decision"] for x in ledger["reviews"] if x["source_id"] == sid
            )
            or row.get("approved_for_advisor") is not False
        )
        for sid, row in sources.items()
    ):
        raise ValueError("Selected source attrition and captured audit diverged")
    if (stored["captured_source_count"] != len(expected_captured)
            or stored["policy_held_count"] != sum(
                x == "publisher_policy_held" for x in expected_status.values()
            ) or stored["eligible_uncaptured_count"] != sum(
                x == "eligible_but_original_html_not_supplied"
                for x in expected_status.values()
            )):
        raise ValueError("Sample attrition counts or policy gating were forged")
    if subset.get("approved_for_advisor") is not False:
        raise ValueError("Captured subset attempted automatic approval")
    if not expected_captured:
        subset_report = None
        measured = {}
    else:
        subset_report = aggregate_release_pilot(
            subset, staged_root, split_key=split_key,
        )
        measured = {r["source_id"]: r for r in subset_report["sources"]}
        if set(measured) != expected_captured:
            raise ValueError("Captured subset evidence was cherry-picked in scoring")
    frozen_out = []
    for source_id in sorted(planned):
        orig = sources[source_id]
        evidence = measured.get(source_id)
        frozen_out.append({
            "source_id": source_id,
            "source_url": orig["source_url"],
            "frozen_batch_id": orig["frozen_batch_id"],
            "provisional_provider_group": orig["provisional_provider_group"],
            "publisher_policy_decision": orig["publisher_policy_decision"],
            "capture_status": orig["capture_status"],
            "hold_reason": (
                orig["publisher_policy_decision"]
                if orig["capture_status"] == "publisher_policy_held"
                else "eligible_original_html_missing"
                if orig["capture_status"] != "captured_original_html_unreviewed"
                else ";".join(evidence["hold_reasons"])
                if evidence["hold_reasons"] else None
            ),
            "diagnostic_only_metrics": (
                evidence["diagnostic_only_metrics"] if evidence else None
            ),
            "approved_for_advisor": False,
        })
    count = sum(
        r["diagnostic_only_metrics"] is not None for r in frozen_out
    )
    unavailable = len(frozen_out) - count
    out = {
        "schema_version": VERSION,
        "kind": SCORE_KIND,
        "frozen_pilot_plan_sha256": frozen["plan_sha256"],
        "source_policy_receipt_sha256": receipt["receipt_sha256"],
        "source_count_in_original_preregistered_selection": len(planned),
        "operator_attested_policy_eligible_source_count":
            receipt["operator_attested_attempt_eligible_count"],
        "captured_original_html_source_count": len(expected_captured),
        "scored_source_count": count,
        "missing_policy_capture_or_review_source_count": unavailable,
        "selection_capture_coverage": (
            len(expected_captured) / len(planned)
        ),
        "selection_reviewed_and_scored_coverage": (
            count / len(planned)
        ),
        "frozen_selected_sources": frozen_out,
        "subset_scored_only_diagnostics": subset_report,
        "pilot_sample_coverage_diagnostic_ready": bool(
            subset_report
            and subset_report["pilot_sample_coverage_diagnostic_ready"]
            and unavailable == 0
        ),
        "full_selected_population_accuracy_established": False,
        "unavailable_sources_never_counted_as_zero_parser_errors": True,
        "original_source_denominator_preserved": True,
        "publisher_origin_independently_authenticated": False,
        "advisor_fact_approvals": 0,
        "new_release_alerts": 0,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "deployment_authorized": False,
    }
    out["report_sha256"] = _digest(out)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stage-partial", action="store_true")
    mode.add_argument("--score-partial", action="store_true")
    p.add_argument("--input-plan", type=Path, required=True)
    p.add_argument("--policy-ledger", type=Path, required=True)
    p.add_argument("--capture-root", type=Path)
    p.add_argument("--staged-root", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    selection = os.environ.get("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY", "")
    split = os.environ.get("AGENTFUSE_RELEASE_GOLD_SPLIT_KEY", "")
    if not selection or not split:
        p.error("Both private selection and holdout HMAC keys required")
    plan = _read_plan(args.input_plan)
    ledger = _read_plan(args.policy_ledger)
    if args.stage_partial:
        if not args.capture_root or args.staged_root:
            p.error("--stage-partial requires --capture-root only")
        result = stage_partial_pilot(
            plan, ledger, args.capture_root, args.out_dir,
            selection_key=selection, split_key=split,
        )
        print(json.dumps(result, indent=2))
        return
    if not args.staged_root or args.capture_root:
        p.error("--score-partial requires --staged-root only")
    result = score_partial_pilot(
        plan, ledger, args.staged_root,
        selection_key=selection, split_key=split,
    )
    root = _private_new_directory(args.out_dir)
    try:
        _put(root / "full_frozen_source_pilot_diagnostics.json", result)
    except Exception:
        shutil.rmtree(root)
        raise
    print(json.dumps({
        "private_report": str(
            root / "full_frozen_source_pilot_diagnostics.json"
        ),
        "selected": result["source_count_in_original_preregistered_selection"],
        "scored": result["scored_source_count"],
        "unavailable": result[
            "missing_policy_capture_or_review_source_count"
        ],
        "pilot_sample_coverage_diagnostic_ready":
            result["pilot_sample_coverage_diagnostic_ready"],
        "publisher_origin_independently_authenticated": False,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "advisor_fact_approvals": 0,
        "deployment_authorized": False,
    }, indent=2))


if __name__ == "__main__":
    main()
