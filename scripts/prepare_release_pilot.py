"""P19A4: preregister a diverse changelog pilot and stage MANUALLY captured HTML.

PLAN: offline HMAC-based one-source-per-provider selection, 15-25 existing
configured changelog source IDs. It does not grant collection permission.
STAGE: offline, all-or-none verification and COPY of operator-captured P19A1
HTML into P19A1 replay / P19A2 blind-review / P19A3 cohort layout.

NO requests, capture flags, Zyte jobs, source registry updates, changes to
three spiders, fake human labels, release alerts, advisor or DB writes.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.provider_profiles import load_provider_profiles
from scripts.aggregate_release_pilot import _safe_member
from scripts.capture_release_html import capture_plan
from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)
from scripts.replay_release_snapshots import (
    _capture_time, _digest, replay_changelog_html,
    validate_capture_manifest,
)
from scripts.score_release_gold import (
    _group, _split_key, prepare_census_packet, reviewer_template,
)

VERSION = "1.0"
PLAN_KIND = "p19a4_frozen_offline_changelog_pilot_plan_not_permission"
STAGE_KIND = "p19a4_offline_staged_changelog_pilot_unreviewed"
MIN_SOURCES = 15
MAX_SOURCES = 25
MAX_CAPTURE_BATCH = 5
HEX64 = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
CAPTURE_FILE = re.compile(r"^[a-z0-9_-]+-[a-f0-9]{20}\.html$")
MAX_JSON_BYTES = 4_000_000


def _seed_bytes(key):
    return _split_key(key)


def _rank(key, purpose, value):
    return hmac.new(
        key, ("p19a4-changelog-selection-v1|" + purpose + "|" + value).encode(),
        hashlib.sha256,
    ).hexdigest()


def _known_eligible():
    sources = load_sources()
    if len(sources) != 460:
        raise ValueError("P19A4 requires unchanged 460-source manifest")
    changelogs = {s["id"]: s for s in sources if s["category"] == "changelog"}
    if len(changelogs) != 89:
        raise ValueError("P19A4 requires 89 original changelog source IDs")
    allowed = {}
    blocked = {}
    for sid, source in changelogs.items():
        permitted, reason = collection_decision(source, "validation")
        if permitted:
            allowed[sid] = source
        else:
            blocked[sid] = reason
    return changelogs, allowed, blocked


def make_plan(*, selection_key, size=20, batch_size=5, holdout_percent=25):
    """Deterministic, HMAC-shuffled provisional provider groups.

    No source is called 'verified', 'permission granted', or representative.
    The operator must separately inspect publisher access/retention policy.
    """
    secret = _seed_bytes(selection_key)
    if (type(size) is not int or not MIN_SOURCES <= size <= MAX_SOURCES
            or type(batch_size) is not int
            or not 1 <= batch_size <= MAX_CAPTURE_BATCH
            or type(holdout_percent) is not int
            or not 10 <= holdout_percent <= 40):
        raise ValueError("Pilot needs 15-25 sources, batch size 1-5 and 10-40% holdout")
    all_sources, allowed, blocked = _known_eligible()
    profiles = load_provider_profiles()
    groups = {}
    for sid, source in allowed.items():
        key = _group(sid, {
            "provider": source["provider"],
        }, profiles)
        groups.setdefault(key, []).append(sid)
    if len(groups) < size:
        raise ValueError("Not enough distinct validation-eligible provider groups")
    ranked_groups = sorted(groups, key=lambda g: (_rank(secret, "group", g), g))
    selection = []
    for group in ranked_groups[:size]:
        sid = min(
            groups[group], key=lambda x: (_rank(secret, "source", x), x),
        )
        selection.append((sid, group))
    batches = []
    for index in range(0, len(selection), batch_size):
        subset = selection[index:index + batch_size]
        ids = [sid for sid, _ in subset]
        pins = capture_plan(ids)
        entries = []
        for (_, group), source_pin in zip(subset, pins["sources"]):
            entries.append({
                "source_id": source_pin["source_id"],
                "source_url": source_pin["official_source_url"],
                "provisional_provider_group": group,
                "robots_url": source_pin["robots_url"],
                "validation_lifecycle_status":
                    source_pin["lifecycle_validation_status"],
                "publisher_ownership_reviewed": False,
                "publisher_policy_reviewed": False,
                "raw_html_capture_permission_granted": False,
                "approved_for_advisor": False,
            })
        batches.append({
            "batch_id": "wave_" + str(len(batches) + 1).zfill(2),
            "source_ids": ids,
            "sources": entries,
            "read_only_capture_plan_command":
                "python -m scripts.capture_release_html --source-ids " +
                ",".join(ids),
            "operator_policy_review_required_for_each_source": True,
            "network_requests_performed": 0,
            "approved_for_advisor": False,
        })
    plan = {
        "schema_version": VERSION,
        "kind": PLAN_KIND,
        "source_manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "selection_key_commitment_sha256": hashlib.sha256(
            b"p19a4-selection-key-commitment-v1|" + secret
        ).hexdigest(),
        "selection_method":
            "private_fixed_hmac_per_provider_group_one_source_each",
        "changelog_source_count": len(all_sources),
        "eligible_validation_source_count": len(allowed),
        "blocked_source_count": len(blocked),
        "blocked_reason_counts": dict(sorted(
            (reason, sum(v == reason for v in blocked.values()))
            for reason in set(blocked.values())
        )),
        "eligible_provisional_provider_groups": len(groups),
        "selected_provisional_provider_groups": size,
        "source_count": size,
        "batch_size": batch_size,
        "batch_count": len(batches),
        "holdout_percent": holdout_percent,
        "batches": batches,
        "selection_frozen_before_capture": True,
        "publisher_policy_review_completed": False,
        "captured_snapshots": 0,
        "blind_human_census_completed": False,
        "advisor_approved_facts": 0,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "deployment_authorized": False,
        "approved_for_advisor": False,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def _recheck_plan(plan, *, selection_key):
    if not isinstance(plan, dict):
        raise ValueError("Pilot plan must be a JSON object")
    expected = make_plan(
        selection_key=selection_key,
        size=plan.get("source_count"),
        batch_size=plan.get("batch_size"),
        holdout_percent=plan.get("holdout_percent"),
    )
    if plan != expected:
        raise ValueError(
            "Frozen pilot plan differs from recomputed selection or lifecycle pins"
        )
    return expected


def _private_json(root, relative):
    return json.loads(_safe_member(root, relative).read_text(encoding="utf-8-sig"))


def _audit_batch(plan_batch, capture_root):
    """Cross-check the P19A1 capture audit against exact original HTML bytes."""
    batch_id = plan_batch["batch_id"]
    manifest = _private_json(
        capture_root, batch_id + "/frozen_release_snapshots.json",
    )
    audit = _private_json(capture_root, batch_id + "/capture_audit.json")
    known = validate_capture_manifest(manifest)
    expected_ids = plan_batch["source_ids"]
    saved_ids = [x["source_id"] for x in manifest["snapshots"]]
    if saved_ids != expected_ids:
        raise ValueError("Manual capture does not match frozen planned source order")
    if (not isinstance(audit, dict)
            or audit.get("schema_version") != VERSION
            or audit.get("kind") != "p19a1_manual_original_changelog_capture_audit"
            or audit.get("capture_count") != len(saved_ids)
            or audit.get("source_ids") != expected_ids
            or audit.get("publisher_policy_review_operator_attested") is not True
            or audit.get("publisher_policy_independently_verified") is not False
            or audit.get("approved_for_advisor") is not False
            or audit.get("new_release_alerts") != 0
            or audit.get("zyte_jobs_created") != 0
            or audit.get("automatic_schedules_enabled") is not False
            or audit.get("advisor_approved_facts") != 0
            or not isinstance(audit.get("policy_review_note"), str)
            or not 30 <= len(audit["policy_review_note"].strip()) <= 500
            or type(audit.get("robots_checks")) is not int
            or not 1 <= audit["robots_checks"] <= len(saved_ids)
            or audit.get("network_requests_performed") !=
                audit["robots_checks"] + len(saved_ids)
            or not isinstance(audit.get("receipts"), list)
            or len(audit["receipts"]) != len(saved_ids)):
        raise ValueError("Capture audit absent, privileged or inconsistent with P19A1")
    raw_copies = []
    receipts = {x["source_id"]: x for x in audit["receipts"]
                if isinstance(x, dict) and isinstance(x.get("source_id"), str)}
    if len(receipts) != len(saved_ids) or set(receipts) != set(saved_ids):
        raise ValueError("Duplicate or missing robots/HTML capture receipt")
    capture_dir = _safe_member(capture_root, batch_id, directory=True)
    for row in manifest["snapshots"]:
        sid, snapshot = row["source_id"], row["snapshot"]
        source = known[sid]
        name = snapshot["file"]
        if (not isinstance(name, str) or not CAPTURE_FILE.fullmatch(name)
                or not name.startswith(sid + "-")):
            raise ValueError("Unexpected generated original publisher file path")
        raw = _snapshot_bytes(
            snapshot, capture_dir, expected_url=source["url"],
            method="static_html",
        ).encode("utf-8")
        if (not isinstance(snapshot["sha256"], str)
                or not HEX64.fullmatch(snapshot["sha256"])):
            raise ValueError("Capture SHA-256 missing or malformed")
        if _capture_time(snapshot["captured_at_utc"]) > datetime.now(timezone.utc):
            raise ValueError("Original HTML cannot be captured in the future")
        receipt = receipts[sid]
        if (receipt.get("official_source_url") != source["url"]
                or receipt.get("raw_html_sha256") != snapshot["sha256"]
                or receipt.get("raw_html_bytes") != len(raw)
                or receipt.get("robots_url") != next(
                    source_entry["robots_url"]
                    for source_entry in plan_batch["sources"]
                    if source_entry["source_id"] == sid
                )
                or not isinstance(receipt.get("robots_sha256"), str)
                or not HEX64.fullmatch(receipt["robots_sha256"])
                or receipt.get("robots_allowed_for_agent") is not True
                or receipt.get("publisher_origin_independently_authenticated") is not False
                or receipt.get("published_release_facts_independently_verified") is not False
                or receipt.get("approved_for_advisor") is not False):
            raise ValueError("Captured original HTML differs from publisher-policy receipt")
        raw_copies.append((name, raw))
    return {
        "batch_id": batch_id,
        "manifest": manifest,
        "audit": audit,
        "html": raw_copies,
    }


def _mkdir(root, *parts):
    folder = root.joinpath(*parts)
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o700)
    return folder


def _put(path, value):
    _write_private(
        path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    )


def stage_captures(plan, capture_root, out_dir, *,
                   selection_key, split_key, source_policy_preflight=None):
    """Offline all-or-none conversion to P19A3 cohort with BLANK reviews."""
    _split_key(split_key)
    frozen = _recheck_plan(plan, selection_key=selection_key)
    captures = [
        _audit_batch(batch, capture_root) for batch in frozen["batches"]
    ]
    if len(captures) != frozen["batch_count"]:
        raise ValueError("Missing original HTML capture batch")
    if source_policy_preflight is not None:
        receipt = source_policy_preflight
        if (not isinstance(receipt, dict) or receipt.get("kind") !=
                "p19a5_offline_policy_preflight_not_permission"
                or receipt.get("frozen_pilot_plan_sha256") != frozen["plan_sha256"]
                or receipt.get("all_frozen_sources_operator_attested_eligible")
                    is not True
                or receipt.get("approved_for_advisor") is not False
                or receipt.get("network_requests_performed") != 0):
            raise ValueError("Staging requires full source-policy preflight")
        for row in captures:
            audit = row["audit"]
            if (audit.get("source_specific_policy_review_completed") is not True
                    or audit.get("source_specific_policy_review_receipt_sha256")
                        != receipt.get("receipt_sha256")):
                raise ValueError(
                    "Captured original HTML lacks exact pilot policy review receipt"
                )
    # No stage mutation until ALL captured bytes and receipt metadata validate.
    root = _private_new_directory(out_dir)
    wave_inputs = []
    stage_audit = {
        "schema_version": VERSION,
        "kind": STAGE_KIND,
        "frozen_selection_plan_sha256": frozen["plan_sha256"],
        "source_manifest_sha256": frozen["source_manifest_sha256"],
        "source_registry_sha256": frozen["source_registry_sha256"],
        "source_count": frozen["source_count"],
        "batch_count": frozen["batch_count"],
        "publisher_policy_review_operator_attested_only": True,
        "publisher_policy_independently_verified": False,
        "source_specific_policy_review_receipt_sha256": (
            source_policy_preflight["receipt_sha256"]
            if source_policy_preflight is not None else None
        ),
        "independent_census_reviewers_completed": 0,
        "original_html_copied_bytes": 0,
        "replays_computed_offline": 0,
        "blank_human_review_templates_created": 0,
        "source_captures": [],
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "advisor_approved_facts": 0,
        "new_release_alerts": 0,
        "approved_for_advisor": False,
    }
    try:
        for captured in captures:
            wave = captured["batch_id"]
            _mkdir(root, wave)
            capture_dir = _mkdir(root, wave, "capture")
            replay_dir = _mkdir(root, wave, "replay")
            census_dir = _mkdir(root, wave, "census")
            for filename, raw in captured["html"]:
                _write_private(capture_dir / filename, raw)
                stage_audit["original_html_copied_bytes"] += len(raw)
            _put(
                capture_dir / "frozen_release_snapshots.json",
                captured["manifest"],
            )
            _put(capture_dir / "capture_audit.json", captured["audit"])
            replay = replay_changelog_html(captured["manifest"], capture_dir)
            stage_audit["replays_computed_offline"] += 1
            _put(replay_dir / "changelog_html_replay.json", replay)
            packet = prepare_census_packet(
                replay, captured["manifest"], capture_dir,
                split_key=split_key,
                holdout_percent=frozen["holdout_percent"],
            )
            _put(census_dir / "blind_source_census_packet.json", packet)
            for name in ("a", "b"):
                _put(
                    census_dir / ("reviewer_" + name + "_template.json"),
                    reviewer_template(packet, name),
                )
                stage_audit["blank_human_review_templates_created"] += 1
            wave_inputs.append({
                "batch_id": wave,
                "replay": wave + "/replay/changelog_html_replay.json",
                "capture_manifest":
                    wave + "/capture/frozen_release_snapshots.json",
                "snapshot_root": wave + "/capture",
                "blind_packet":
                    wave + "/census/blind_source_census_packet.json",
                "reviewer_a": wave + "/census/reviewer_a_filled.json",
                "reviewer_b": wave + "/census/reviewer_b_filled.json",
            })
            stage_audit["source_captures"].append({
                "batch_id": wave,
                "source_ids": [
                    s["source_id"] for s in captured["manifest"]["snapshots"]
                ],
                "original_capture_manifest_sha256":
                    _digest(captured["manifest"]),
                "original_capture_audit_sha256": _digest(captured["audit"]),
                "replay_sha256": replay["replay_sha256"],
                "blind_census_packet_sha256": packet["packet_sha256"],
                "publisher_origin_independently_authenticated": False,
            })
        cohort = {
            "schema_version": VERSION,
            "kind": "p19a3_reviewed_release_source_batch_cohort",
            "approved_for_advisor": False,
            "holdout_percent": frozen["holdout_percent"],
            "batches": wave_inputs,
        }
        _put(root / "cohort.json", cohort)
        _put(root / "pilot_staging_audit.json", stage_audit)
    except Exception:
        shutil.rmtree(root)
        raise
    return {
        "private_staged_root": str(root),
        "cohort_path": str(root / "cohort.json"),
        "selected_source_count": frozen["source_count"],
        "verified_capture_hashes": frozen["source_count"],
        "blank_reviewer_templates": 2 * frozen["batch_count"],
        "human_review_completed": False,
        "ready_for_p19a3_scoring": False,
        "missing_filled_reviewer_files": 2 * frozen["batch_count"],
        "publisher_origin_independently_authenticated": False,
        "advisor_fact_approvals": 0,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0,
        "deployment_authorized": False,
    }


def _read_plan(path):
    target = Path(path)
    if (target.is_symlink() or not target.is_file()
            or not 1 <= target.stat().st_size <= MAX_JSON_BYTES
            or any(parent.is_symlink() for parent in target.parents)):
        raise ValueError("Missing or symlinked oversized P19A4 private pilot plan")
    return json.loads(target.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--plan", action="store_true",
                         help="Select and freeze 15-25 publisher groups, no requests")
    actions.add_argument("--stage", action="store_true",
                         help="Recheck pre-captured HTML and prepare BLANK reviews")
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--holdout-percent", type=int, default=25)
    parser.add_argument("--input-plan", type=Path)
    parser.add_argument("--capture-root", type=Path)
    parser.add_argument("--policy-ledger", type=Path,
                        help="Completed per-source P19A5 ledger (required for stage CLI)")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    seed = os.environ.get("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY", "")
    if not seed:
        parser.error("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY must be private and set")
    if args.plan:
        if args.input_plan or args.capture_root:
            parser.error("--plan takes no capture inputs")
        payload = make_plan(
            selection_key=seed, size=args.size,
            batch_size=args.batch_size,
            holdout_percent=args.holdout_percent,
        )
        root = _private_new_directory(args.out_dir)
        try:
            _put(root / "pilot_selection_plan.json", payload)
        except Exception:
            shutil.rmtree(root)
            raise
        print(json.dumps({
            "private_plan_path": str(root / "pilot_selection_plan.json"),
            "selected_sources": payload["source_count"],
            "distinct_provisional_groups":
                payload["selected_provisional_provider_groups"],
            "batches": payload["batch_count"],
            "publisher_policy_review_completed": False,
            "network_requests_performed": 0,
            "zyte_jobs_created": 0,
            "advisor_fact_approvals": 0,
        }, indent=2))
        return
    if not args.input_plan or not args.capture_root or not args.policy_ledger:
        parser.error("--stage needs --input-plan --capture-root --policy-ledger")
    gold_key = os.environ.get("AGENTFUSE_RELEASE_GOLD_SPLIT_KEY", "")
    if not gold_key:
        parser.error("AGENTFUSE_RELEASE_GOLD_SPLIT_KEY must be private and set")
    from scripts.review_release_pilot_policy import validate_policy_ledger
    frozen_plan = _read_plan(args.input_plan)
    receipt = validate_policy_ledger(
        frozen_plan, _read_plan(args.policy_ledger), selection_key=seed,
    )
    result = stage_captures(
        frozen_plan, args.capture_root, args.out_dir,
        selection_key=seed, split_key=gold_key,
        source_policy_preflight=receipt,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
