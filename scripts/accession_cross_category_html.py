"""P22A1: offline accession of independently collected ORIGINAL HTML.

Precommit P20A's exact 18 sources / 36 rounds. Validate user-supplied
byte snapshots with the existing P16B checker; replay production extraction
only as UNVERIFIED diagnostics. No publisher access, Zyte, gold labels,
advisor approvals or production writes. Captures and reviewers are PRIVATE.
"""
import argparse
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.run_context import manifest_sha256, package_fingerprint
from agentfuse_crawlers.source_lifecycle import collection_decision, registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.validation_access import _https
from scripts.compare_acquisition_snapshots import _snapshot_bytes, _quality_features
from scripts.full_inventory_readiness import WAVES
from scripts.plan_documentation_children import _private_new_directory, _write_private
from scripts.replay_release_snapshots import _digest

VERSION = "1.0"
PLAN_KIND = "p22a1_exact_p20a_cross_category_source_plan_not_permission"
LEDGER_KIND = "p22a1_private_operator_original_html_receipts_not_authentication"
STAGE_KIND = "p22a1_cross_category_evidence_attrition_not_human_gold"
BLIND_KIND = "p22a1_blank_independent_source_wide_review"
EXPECTED = {"documentation": 6, "pricing": 6, "changelog": 6}
DECISIONS = {
    "pending_review", "operator_attested_manual_permitted",
    "denied_by_terms", "denied_by_robots", "denied_by_access_controls",
    "deferred_unknown_ownership", "deferred_retention_rights",
}
STATES = {
    "not_attempted", "captured", "held_by_terms", "held_by_robots",
    "held_by_access_controls", "held_by_retention",
    "held_unknown_product_owner", "capture_failed",
}
POLICY_FIELDS = {
    "decision", "reviewer", "reviewed_at_utc", "expires_at_utc",
    "ownership_url", "terms_url", "robots_url", "retention_reviewed", "note",
}
ROUND_FIELDS = {"round", "state", "snapshot", "capture_receipt_id"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{3,89}$")
RECEIPT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,119}$")


def _utc(s):
    if not isinstance(s, str) or not 12 <= len(s) <= 45:
        raise ValueError("Missing timezone-aware policy or capture timestamp")
    try:
        value = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Missing timezone")
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Malformed source review/capture timestamp") from exc


def frozen_plan():
    sources = load_sources()
    if len(sources) != 460:
        raise ValueError("P20A source manifest must remain 460 entries")
    known = {s["id"]: s for s in sources}
    rows, ids = [], set()
    for wave_no, wave in enumerate(WAVES, 1):
        if len(wave) != 9:
            raise ValueError("Original P20A nine-source wave changed")
        for sid, hint in wave:
            if sid in ids or sid not in known:
                raise ValueError("P20A source ID changed or repeated")
            ids.add(sid)
            source = known[sid]
            rows.append({
                "source_id": sid, "source_url": source["url"],
                "category": source["category"], "wave": wave_no,
                "provider_label_unverified": source["provider"],
                "historical_triage_hint": hint,
            })
    if (len(rows) != 18
            or Counter(r["category"] for r in rows) != EXPECTED
            or len({r["provider_label_unverified"] for r in rows}) != 18):
        raise ValueError("P20A cross-category study selection changed")
    plan = {
        "schema_version": VERSION, "kind": PLAN_KIND,
        "expected_manifest_sha256": manifest_sha256(sources),
        "expected_source_registry_sha256": registry_revision_sha256(),
        "selection_origin": "p20a_two_frozen_nine_source_waves",
        "sources": rows, "selected_source_count": 18,
        "source_round_denominator": 36, "rounds_per_source": 2,
        "category_counts": EXPECTED,
        "source_replacement_on_denial_allowed": False,
        "publisher_permissions_granted": 0,
        "real_human_gold_cases": 0, "approved_for_advisor": False,
    }
    plan["plan_sha256"] = _digest(plan)
    return plan


def validate_plan(plan):
    if not isinstance(plan, dict) or plan != frozen_plan():
        raise ValueError("Frozen P20A source selection edited or stale")
    return plan


def blank_ledger(plan):
    validate_plan(plan)
    return {
        "schema_version": VERSION, "kind": LEDGER_KIND,
        "frozen_plan_sha256": plan["plan_sha256"],
        "human_gold_supplied": False, "approved_for_advisor": False,
        "rows": [{
            "source_id": s["source_id"], "source_url": s["source_url"],
            "category": s["category"], "wave": s["wave"],
            "policy_review": {
                "decision": "pending_review", "reviewer": None,
                "reviewed_at_utc": None, "expires_at_utc": None,
                "ownership_url": None, "terms_url": None,
                "robots_url": None, "retention_reviewed": False,
                "note": None,
            },
            "rounds": [
                {"round": n, "state": "not_attempted",
                 "snapshot": None, "capture_receipt_id": None}
                for n in (1, 2)
            ],
        } for s in plan["sources"]],
    }


def _policy(row, source, *, now):
    review = row["policy_review"]
    if not isinstance(review, dict) or set(review) != POLICY_FIELDS:
        raise ValueError("Missing exact per-source private policy-review record")
    decision = review["decision"]
    if decision not in DECISIONS:
        raise ValueError("Unknown operator publisher-policy decision")
    if decision == "pending_review":
        if any(v is not None for key, v in review.items()
               if key not in ("decision", "retention_reviewed")) or (
                   review["retention_reviewed"] is not False
               ):
            raise ValueError("Unreviewed publisher must have BLANK review evidence")
        return False
    if (not isinstance(review["reviewer"], str)
            or not NAME.fullmatch(review["reviewer"])
            or not isinstance(review["note"], str)
            or not 80 <= len(review["note"].strip()) <= 1200
            or type(review["retention_reviewed"]) is not bool):
        raise ValueError("Missing source-specific human reviewer and detailed policy note")
    t0, expiry = _utc(review["reviewed_at_utc"]), _utc(review["expires_at_utc"])
    if t0 > now + timedelta(minutes=5) or expiry <= t0 or (
        expiry - t0 > timedelta(days=30)
    ):
        raise ValueError("Source review future/expired window inconsistent")
    host = urlsplit(source["url"]).hostname
    _https(review["ownership_url"], expected_host=host)
    _https(review["terms_url"])
    _https(review["robots_url"], expected_host=host, robots=True)
    if decision == "operator_attested_manual_permitted":
        if expires <= now:
            raise ValueError("Original HTML retention policy review expired at staging")
        if not review["retention_reviewed"]:
            raise ValueError("HTML retention must be explicitly reviewed")
        return True
    return False


def stage_data(plan, ledger, capture_root, *, now=None):
    validate_plan(plan)
    if (not isinstance(ledger, dict)
            or set(ledger) != {
                "schema_version", "kind", "frozen_plan_sha256",
                "human_gold_supplied", "approved_for_advisor", "rows",
            }
            or ledger["schema_version"] != VERSION
            or ledger["kind"] != LEDGER_KIND
            or ledger["frozen_plan_sha256"] != plan["plan_sha256"]
            or ledger["human_gold_supplied"] is not False
            or ledger["approved_for_advisor"] is not False
            or not isinstance(ledger["rows"], list)
            or len(ledger["rows"]) != 18):
        raise ValueError("Missing or privileged 18-source operator accession ledger")
    root = Path(capture_root)
    if not root.is_dir() or root.is_symlink() or any(
        p.is_symlink() for p in root.parents
    ):
        raise ValueError("Original HTML root must be a real private non-symlink directory")
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise ValueError("Review clock must be timezone aware")
    clock = clock.astimezone(timezone.utc)
    all_sources = {s["id"]: s for s in load_sources()}
    cases, blind, counts, seen_receipts = [], [], Counter(), set()
    captured_ids = set()
    for selected, row in zip(plan["sources"], ledger["rows"]):
        if (not isinstance(row, dict)
                or set(row) != {
                    "source_id", "source_url", "category", "wave",
                    "policy_review", "rounds",
                }
                or any(row[k] != selected[k] for k in (
                    "source_id", "source_url", "category", "wave"
                ))
                or not isinstance(row["rounds"], list)
                or len(row["rounds"]) != 2):
            raise ValueError("Removed/changed/reordered source from 18-source denominator")
        src = all_sources[row["source_id"]]
        permitted = _policy(row, src, now=clock)
        review = row["policy_review"]
        times = []
        for number, capture in enumerate(row["rounds"], 1):
            if (not isinstance(capture, dict) or set(capture) != ROUND_FIELDS
                    or type(capture.get("round")) is not int
                    or capture["round"] != number
                    or capture.get("state") not in STATES):
                raise ValueError("Missing or altered round 1/2 capture record")
            state = capture["state"]
            receipt = capture["capture_receipt_id"]
            snap = capture["snapshot"]
            case = {
                "source_id": src["id"], "source_url": src["url"],
                "category": src["category"], "wave": selected["wave"],
                "round": number, "state": state,
                "operator_policy_decision": review["decision"],
                "source_policy_independently_verified": False,
                "publisher_origin_independently_authenticated": False,
                "publisher_fact_verified": False,
                "human_gold_cases": 0, "approved_for_advisor": False,
            }
            counts[state] += 1
            if state == "captured":
                if not permitted or not collection_decision(src, "validation")[0]:
                    raise ValueError("Original HTML retained for unreviewed/denied source")
                if (not isinstance(receipt, str) or not RECEIPT.fullmatch(receipt)
                        or receipt in seen_receipts or not isinstance(snap, dict)):
                    raise ValueError("Captured round lacks unique receipt/original snapshot")
                seen_receipts.add(receipt)
                when = _utc(snap.get("captured_at_utc"))
                if not (_utc(review["reviewed_at_utc"]) <= when
                        < _utc(review["expires_at_utc"])
                        and when <= clock + timedelta(minutes=5)):
                    raise ValueError("Original capture outside reviewed policy/retention window")
                original = _snapshot_bytes(
                    snap, root, expected_url=src["url"], method="static_html",
                )
                features = _quality_features(src, original, "static_html", None)
                if features["approved_for_advisor"] is not False:
                    raise ValueError("Parser returned privileged source claim")
                case.update({
                    "raw_html_sha256": snap["sha256"],
                    "raw_html_private_file": snap["file"],
                    "raw_html_byte_count": len(original.encode("utf-8")),
                    "captured_at_utc": when.isoformat(),
                    "capture_receipt_id": receipt,
                    "parser_package_fingerprint": package_fingerprint(),
                    "parser_capture_status_unverified": features["capture_status"],
                    "parser_evidence_candidates_not_gold":
                        features["structural_evidence_count"],
                    "parser_identity_conflict_unverified":
                        features["product_title_conflict"],
                })
                times.append(when)
                captured_ids.add(src["id"])
                blind.append({
                    "source_id": src["id"], "category": src["category"],
                    "source_url": src["url"], "wave": selected["wave"],
                    "round": number, "raw_html_sha256": snap["sha256"],
                    "raw_html_private_file": snap["file"],
                    "reviewer_id": None, "reviewed_at_utc": None,
                    "whole_page_review_completed": False,
                    "evidence_inventory": [], "no_relevant_evidence_observed": None,
                    "parser_predictions_hidden": True,
                    "human_gold_established": False,
                    "approved_for_advisor": False,
                })
            else:
                if snap is not None or receipt is not None:
                    raise ValueError("Held or failed sources cannot smuggle HTML receipts")
                if state == "capture_failed" and not permitted:
                    raise ValueError("Unreviewed source cannot claim attempted capture")
            cases.append(case)
        if len(times) == 2 and times[1] <= times[0]:
            raise ValueError("Second capture must be later than first")
    if len(cases) != 36:
        raise ValueError("Every original source must contribute both rounds")
    metrics = {
        "schema_version": VERSION, "kind": STAGE_KIND,
        "frozen_plan_sha256": plan["plan_sha256"],
        "source_manifest_sha256": plan["expected_manifest_sha256"],
        "source_lifecycle_sha256": plan["expected_source_registry_sha256"],
        "source_denominator": 18, "source_round_denominator": 36,
        "sources_with_original_html": len(captured_ids),
        "source_rounds_with_valid_byte_sha256": counts["captured"],
        "sources_without_original_html": 18-len(captured_ids),
        "round_state_counts": dict(sorted(counts.items())),
        "no_replacement_for_denied_or_missing_sources": True,
        "publisher_origin_authenticated": False,
        "human_gold_label_count": 0, "independent_review_a_done": False,
        "independent_review_b_done": False, "accuracy_measurable": False,
        "held_sources_are_not_parser_false_negatives": True,
        "network_requests_performed": 0, "zyte_jobs_created": 0,
        "advisor_fact_approvals": 0, "approved_for_advisor": False,
    }
    metrics["accession_sha256"] = _digest({"metrics": metrics, "cases": cases})
    return metrics, cases, blind


def _private_json(root, name, obj):
    _write_private(
        root / name,
        (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def prepare(out_dir):
    plan = frozen_plan()
    root = _private_new_directory(out_dir)
    try:
        _private_json(root, "frozen_p20a_18_source_plan.json", plan)
        _private_json(root, "source_policy_and_capture_ledger_BLANK.json",
                      blank_ledger(plan))
        _write_private(
            root / "README_PRIVATE.txt",
            ("P22A1 — 18 fixed P20A sources, TWO rounds each. ALL pending.\n"
             "Fill private source-specific publisher reviews and only real\n"
             "permitted original HTML receipts. No capture is performed.\n"
             "P19A6 15–25 release pilot and P21A private holdout are DIFFERENT\n"
             "sample populations and must remain separate.\n").encode(),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def stage(plan, ledger, capture_root, out_dir, *, now=None):
    path = Path(out_dir)
    if path.exists() or path.is_symlink() or any(
        p.is_symlink() for p in path.parents
    ):
        raise ValueError("Use new private non-symlink result directory")
    metrics, cases, tasks = stage_data(plan, ledger, capture_root, now=now)
    path = _private_new_directory(out_dir)
    try:
        _private_json(path, "all_36_source_round_attribution.json", cases)
        _private_json(path, "attrition_and_parser_diagnostics_NOT_GOLD.json", metrics)
        for letter in ("A", "B"):
            _private_json(path, "reviewer_"+letter+"_BLANK.json", {
                "schema_version": VERSION, "kind": BLIND_KIND,
                "reviewer_letter": letter, "reviewer_id": None,
                "frozen_plan_sha256": plan["plan_sha256"],
                "tasks": tasks, "human_reviews_performed": 0,
                "all_observations_unverified": True,
                "approved_for_advisor": False,
            })
    except Exception:
        shutil.rmtree(path)
        raise
    return path


def _load(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or any(
        x.is_symlink() for x in p.parents
    ) or not 2 <= p.stat().st_size <= 200_000:
        raise ValueError("Missing/unsafe/oversized private JSON input")
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", action="store_true")
    g.add_argument("--stage", action="store_true")
    p.add_argument("--frozen-plan", type=Path)
    p.add_argument("--private-ledger", type=Path)
    p.add_argument("--capture-root", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    if args.prepare:
        if any((args.frozen_plan, args.private_ledger, args.capture_root)):
            p.error("--prepare takes no private HTML, ledger, or other inputs")
        root = prepare(args.out_dir)
    else:
        if not all((args.frozen_plan, args.private_ledger, args.capture_root)):
            p.error("--stage needs --frozen-plan --private-ledger --capture-root")
        root = stage(_load(args.frozen_plan), _load(args.private_ledger),
                     args.capture_root, args.out_dir)
    print(json.dumps({
        "private_result": str(root), "sampled_sources": 18,
        "source_rounds": 36, "new_network_requests": 0,
        "new_publisher_permissions": 0, "human_gold_cases": 0,
        "advisor_fact_approvals": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
