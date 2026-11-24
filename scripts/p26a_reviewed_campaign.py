"""P26A: compile actual operator-reviewed source decisions, not permissions.

Use the existing P25 ranking and P21B policy schema. No network, Zyte jobs,
production registry writes, or generated human attestations. Draft run plans
are deliberately invalid for dispatch until separately reviewed and merged.
"""
import argparse
import csv
import hashlib
import io
import json
import shutil
from collections import Counter
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers import validation_access as policy
from agentfuse_crawlers.run_context import selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import collection_decision
from agentfuse_crawlers.sources import load_sources, select_sources
from scripts.p25_large_campaign import (
    ORDER, MANIFEST_COUNTS, G3_ALL_FILENAME, build_campaign, read_g3_review_csv, _target,
)
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)

IDENTITY = (
    "rank", "source_id", "provider", "category", "source_url", "hostname",
    "historical_status_NOT_CURRENT", "existing_caution_hint",
)
EDITABLE = (
    "decision", "reviewed_by", "reviewed_at_utc", "expires_at_utc",
    "ownership_evidence_url", "publisher_access_policy_url", "robots_url",
    "publisher_terms_reviewed", "robots_reviewed", "private_retention_reviewed",
    "retention_scope_and_TTL", "evidence_note",
)
FIELDS = IDENTITY + ("installed_record_sha256",) + EDITABLE
FLAGS = ("publisher_terms_reviewed", "robots_reviewed", "private_retention_reviewed")
MAX_CSV_BYTES = 4_000_000
KIND = "p26a_reviewed_campaign_preparation_NOT_AUTHORIZATION"


def _read(path):
    path = Path(path)
    if (not path.is_file() or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)):
        raise ValueError("Expected a non-symlink private CSV file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("CSV exceeds bounded review packet size")
    return raw


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n").encode("utf-8")


def _record_sha(access, sid):
    record = access["reviews"].get(sid)
    return policy.digest(record) if record is not None else ""


def worksheet(g3_rows, installed_access):
    known = {s["id"]: s for s in load_sources()}
    if len(g3_rows) != 460 or {r["source_id"] for r in g3_rows} != set(known):
        raise ValueError("P26A requires the full all-460 G3 ranking")
    result = []
    for rank, row in enumerate(g3_rows, 1):
        source = known[row["source_id"]]
        if (row["source_url"] != source["url"] or row["category"] != source["category"]
                or row["provider"] != source["provider"]):
            raise ValueError("G3 ranking identity differs from pinned manifest")
        result.append({
            "rank": str(rank), "source_id": source["id"],
            "provider": source["provider"], "category": source["category"],
            "source_url": source["url"], "hostname": urlsplit(source["url"]).hostname,
            "historical_status_NOT_CURRENT": row["historical_status_NOT_CURRENT"],
            "existing_caution_hint": row.get("g1_elevated_terms_review_hint", ""),
            "installed_record_sha256": _record_sha(installed_access, source["id"]),
            **{field: "" for field in EDITABLE},
        })
    return result


def worksheet_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        # The immutable cells are all manifest/ranking metadata. Do not
        # create spreadsheet formulas from any source text.
        writer.writerow({k: _safe_csv(row[k]) for k in FIELDS})
    return stream.getvalue().encode("utf-8-sig")


def read_completed_worksheet(path):
    reader = csv.DictReader(io.StringIO(_read(path).decode("utf-8-sig"), newline=""))
    if reader.fieldnames != list(FIELDS):
        raise ValueError("Review worksheet columns changed; use the P26A template")
    rows = list(reader)
    if len(rows) != 460 or any(set(row) != set(FIELDS) or
                               any(not isinstance(v, str) for v in row.values()) for row in rows):
        raise ValueError("Expected all 460 exact worksheet rows and columns")
    return rows


def compile_reviews(g3_rows, installed_access, completed, *, now=None):
    """Import explicit human decisions only; blank rows preserve current records.

    Positive rows explicitly attest terms, robots and permitted retention.
    Denied/deferred decisions remove access scopes. This is schema checking,
    not verification that the named person actually performed the review.
    """
    clock = policy._now(now)
    policy.validate_access_registry(installed_access, now=clock)
    expected = {r["source_id"]: r for r in worksheet(g3_rows, installed_access)}
    candidate = deepcopy(installed_access)
    seen = set()
    imported = Counter()
    if len(completed) != 460:
        raise ValueError("Do not omit any of the 460 worksheet rows")
    for row in completed:
        sid = row.get("source_id")
        baseline = expected.get(sid)
        if (baseline is None or sid in seen or set(row) != set(FIELDS)
                or any(row.get(k) != baseline[k] for k in IDENTITY)):
            raise ValueError("Duplicate or modified worksheet source identity/ranking")
        seen.add(sid)
        decision = row["decision"].strip()
        if decision in ("", "not_reviewed"):
            # Research notes are not decisions; do not promote them or erase
            # an existing record simply because the row remains incomplete.
            continue
        if decision not in policy.ACCESS_STATES:
            raise ValueError(f"{sid}: use allowed_reviewed, prohibited_reviewed or deferred")
        if row["installed_record_sha256"] != baseline["installed_record_sha256"]:
            raise ValueError(f"{sid}: installed access record changed; regenerate/review worksheet")
        positive = decision == "allowed_reviewed"
        flag_values = [row[k].strip() for k in FLAGS]
        retention = row["retention_scope_and_TTL"].strip()
        note = row["evidence_note"].strip()
        if positive:
            if flag_values != ["yes", "yes", "yes"] or not retention or not note:
                raise ValueError(f"{sid}: explicit yes attestations, retention scope/TTL and notes required")
        elif any(value not in ("", "no") for value in flag_values):
            raise ValueError(f"{sid}: denied/deferred rows cannot assert positive attestations")
        # Store the explicit retention details inside the EXISTING evidence
        # note field. The production validator checks its substantive length.
        if retention:
            note += "\nRetention scope and TTL: " + retention
        record = {
            "source_url": baseline["source_url"], "category": baseline["category"],
            "decision": decision, "scopes": ["bulk_validation"] if positive else [],
            "reviewed_by": row["reviewed_by"].strip(),
            "reviewed_at_utc": row["reviewed_at_utc"].strip(),
            "expires_at_utc": row["expires_at_utc"].strip(),
            **{k: row[k].strip() or None for k in
               ("ownership_evidence_url", "publisher_access_policy_url", "robots_url")},
            **{k: positive for k in FLAGS},
            "evidence_note": note,
        }
        # Existing policy performs the authoritative schema, URL, reviewer
        # and expiry validation below. Reject newly imported expired or
        # future positive reviews instead of counting them toward quotas.
        if positive and not (
                policy._utc(record["reviewed_at_utc"]) <= clock
                < policy._utc(record["expires_at_utc"])):
            raise ValueError(f"{sid}: positive review must be current at import")
        candidate["reviews"][sid] = record
        imported[decision] += 1
    policy.validate_access_registry(candidate, now=clock)
    return candidate, dict(sorted(imported.items()))


def prepare_campaign(g3_rows, candidate, installed_plans, target, *, now=None):
    """Determine actual quota feasibility and generate unsigned plan scopes."""
    target = _target(target)
    clock = policy._now(now)
    policy.validate_access_registry(candidate, now=clock)
    policy.validate_plan_registry(installed_plans, now=clock)
    known = {s["id"]: s for s in load_sources()}
    if len(g3_rows) != 460 or {r["source_id"] for r in g3_rows} != set(known):
        raise ValueError("All 460 ranked identities required for fallback selection")
    eligible = set()
    disposition = Counter()
    for sid, src in known.items():
        review = candidate["reviews"].get(sid)
        if not collection_decision(src, "validation")[0]:
            state = "lifecycle_held"
        elif not review:
            state = "not_reviewed"
        elif review["decision"] != "allowed_reviewed":
            state = review["decision"]
        elif "bulk_validation" not in review["scopes"]:
            state = "bulk_scope_missing"
        elif not policy._utc(review["reviewed_at_utc"]) <= clock < policy._utc(review["expires_at_utc"]):
            state = "review_not_current"
        else:
            state = "current_bulk_review"
            eligible.add(sid)
        disposition[(src["category"], state)] += 1

    counts = {cat: sum(known[sid]["category"] == cat for sid in eligible) for cat in ORDER}
    feasible = [n for n in range(200, 301, 5)
                if counts["pricing"] >= 2*n//5 and counts["documentation"] >= 2*n//5
                and counts["changelog"] >= n//5]
    empty_plans = {
        "schema_version": policy.SCHEMA, "kind": policy.PLAN_KIND,
        "default_policy": "no_bulk_runs_authorized", "plans": {},
    }
    # P25 chooses the exact reviewed-first subset, in manifest order. The
    # current package digest is NOT a digest of the proposed policy files.
    # Never expose its intermediate campaign SHA as launch-ready.
    report = build_campaign(g3_rows, target, access=candidate, plans=empty_plans, now=clock)
    selected_all = {sid for job in report["jobs"] for sid in job["target_source_ids_manifest_order"]}
    complete = target in feasible and selected_all <= eligible and len(selected_all) == target
    draft = deepcopy(empty_plans) if complete else None
    category_rows = {}
    for job in report["jobs"]:
        cat = job["category"]
        ids = job["target_source_ids_manifest_order"]
        wanted = job["target_authorized_primary_urls"]
        selected_count = sum(sid in eligible for sid in ids)
        category_rows[cat] = {
            "manifest_slots": MANIFEST_COUNTS[cat],
            "target_primary_urls": wanted,
            "current_bulk_reviewed_candidates": counts[cat],
            "additional_reviews_needed": max(0, wanted - counts[cat]),
            "dispositions": {state: count for (c, state), count in sorted(disposition.items()) if c == cat},
            "selected_current_review_ids": [sid for sid in ids if sid in eligible],
            "selected_pending_review_ids": [sid for sid in ids if sid not in eligible],
        }
        if not complete:
            continue
        full = select_sources(cat, "all")
        category_rows[cat]["latest_selected_source_review_expiry_utc"] = min(
            policy._utc(candidate["reviews"][sid]["expires_at_utc"]) for sid in ids
        ).isoformat()
        plan_id = "p26a_" + cat + "_" + report["access_registry_sha256"][:12]
        draft["plans"][plan_id] = {
            "category": cat, "collection_mode": "validation", "cohort": "all",
            "source_ids": [s["id"] for s in full],
            "authorized_source_ids": ids,
            "manifest_sha256": report["manifest_sha256"],
            "source_registry_sha256": report["source_registry_sha256"],
            "access_registry_sha256": report["access_registry_sha256"],
            "selection_ids_sha256": selection_ids_sha256(full),
            "source_urls_sha256": policy._urls_digest(full),
            # Never manufacture the final named operator attestation.
            "approved_by": "", "reviewed_at_utc": "", "expires_at_utc": "",
            "max_primary_requests": wanted, "max_redirects_per_source": 0,
            "purpose": "bounded_human_supervised_diagnostic",
            "publisher_policy_review_attested": False,
        }
    summary = {
        "kind": KIND, "status": "NO_GO_REVIEW_AND_MERGE_REQUIRED",
        "target_primary_urls": target, "feasible_targets_from_current_records": feasible,
        "largest_feasible_target_at_or_below_requested": max((n for n in feasible if n <= target), default=None),
        "all_target_ids_have_current_candidate_reviews": complete,
        "unsigned_plan_drafts_created": len(draft["plans"]) if draft else 0,
        "existing_installed_bulk_plan_count": len(installed_plans["plans"]),
        "candidate_access_registry_sha256": report["access_registry_sha256"],
        "manifest_sha256": report["manifest_sha256"],
        "categories": category_rows,
        "publisher_terms_independently_verified_by_tool": False,
        "ready_to_dispatch": False, "new_zyte_jobs": 0,
        "publisher_requests_performed": 0, "approved_for_advisor": False,
    }
    return summary, draft


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--g3-all460", type=Path, required=True)
    parser.add_argument("--reviewed-csv", type=Path,
                        help="Actual human-completed P26A worksheet; optional")
    parser.add_argument("--target", type=int, choices=range(200, 301, 5), default=300)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.g3_all460.name != G3_ALL_FILENAME:
        parser.error("Use the authentic G3 all-460 review CSV, not top300")
    raw_ranking = _read(args.g3_all460)
    rows = read_g3_review_csv(args.g3_all460)
    if raw_ranking != _read(args.g3_all460):
        raise ValueError("Ranking changed during preparation")
    clock = policy._now()
    installed = policy.load_access_registry()
    candidate, imported = (compile_reviews(rows, installed, read_completed_worksheet(args.reviewed_csv), now=clock)
                           if args.reviewed_csv else (deepcopy(installed), {}))
    report, draft = prepare_campaign(rows, candidate, policy.load_run_plan_registry(), args.target, now=clock)
    report.update(g3_ranking_sha256=hashlib.sha256(raw_ranking).hexdigest(),
                  installed_access_registry_sha256=policy.digest(installed),
                  explicitly_imported_decisions=imported)
    root = _private_new_directory(args.out_dir)
    try:
        if not args.reviewed_csv:
            _write_private(root / "p26a_exact_url_review_worksheet.csv",
                           worksheet_bytes(worksheet(rows, installed)))
        _write_private(root / "validation_access_reviews_CANDIDATE_NOT_MERGED.json", _json(candidate))
        if draft is not None:
            _write_private(root / "bulk_run_authorizations_DRAFT_NOT_AUTHORIZED.json", _json(draft))
        _write_private(root / "p26a_campaign_review_NO_GO.json", _json(report))
    except BaseException:
        shutil.rmtree(root)
        raise
    print(json.dumps({
        "status": report["status"], "target": args.target,
        "current_reviewed_by_category": {c: v["current_bulk_reviewed_candidates"]
                                         for c, v in report["categories"].items()},
        "largest_feasible_target": report["largest_feasible_target_at_or_below_requested"],
        "unsigned_plans": report["unsigned_plan_drafts_created"], "ready_to_dispatch": False,
        "output": str(root),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
