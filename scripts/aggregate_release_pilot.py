"""P19A3: fail-closed, source-stratified original-HTML changelog pilot.

P19A2 scores at most five sources at a time. This offline command recomputes
each source-wide census against the actual original publisher HTML bytes,
rather than adding unverifiable scorecard JSON. It aggregates 3+ batches for
a useful 15-25-provider pilot without changing spiders or collection policy.

All observed metrics are provisional diagnostics. Publisher origin, reviewer
independence, representativeness, fact truth and advisor approvals remain
UNVERIFIED even when the engineering sample thresholds are satisfied.
"""
import argparse
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)
from scripts.replay_release_snapshots import _digest
from scripts.score_release_gold import (
    _ratio, _split_key, score_census,
)

VERSION = "1.0"
MANIFEST_KIND = "p19a3_reviewed_release_source_batch_cohort"
RESULT_KIND = "p19a3_unverified_cross_batch_release_accuracy_diagnostic"
BATCH_FIELDS = frozenset({
    "batch_id", "replay", "capture_manifest", "snapshot_root",
    "blind_packet", "reviewer_a", "reviewer_b",
})
ROOT_FIELDS = frozenset({
    "schema_version", "kind", "approved_for_advisor",
    "holdout_percent", "batches",
})
ID = re.compile(r"^[a-z][a-z0-9_-]{2,59}$")
MAX_BATCHES = 12
MAX_SOURCES = 60
MAX_JSON_BYTES = 4_000_000
SOURCE_METRIC_COUNTS = (
    "release_owner_tp", "release_owner_fp", "release_owner_fn",
    "publication_date_exact_matches", "publication_date_checked_matches",
    "publication_date_unresolved_reference_matches",
    "title_exact_matches", "title_checked_matches",
    "version_exact_matches", "version_checked_matches",
)
PILOT_MIN_BATCHES = 3
PILOT_MIN_SOURCES = 15
PILOT_MIN_PROVIDER_GROUPS = 15
PILOT_MIN_REFERENCE_RELEASES = 60
PILOT_MIN_HOLDOUT_PROVIDER_GROUPS = 3
PILOT_MIN_HOLDOUT_REFERENCE_RELEASES = 15
PILOT_MIN_DATE_COMPARISONS = 30


def _safe_member(root, value, *, directory=False):
    """Reject paths escaping operator private root, including symlink hops."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 240
            or not value.isascii() or "\\" in value or "\x00" in value
            or value.startswith("/") or value.endswith("/") or "//" in value):
        raise ValueError("Unsafe private cohort input path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Private cohort input path escapes its root")
    base = Path(root)
    if base.is_symlink() or not base.is_dir():
        raise ValueError("Private cohort input root must be a real directory")
    base = base.resolve(strict=True)
    location = base
    for part in parts:
        location = location / part
        if location.is_symlink():
            raise ValueError("Private cohort path contains a symlink")
    resolved = location.resolve(strict=True)
    if not resolved.is_relative_to(base):
        raise ValueError("Private cohort path is outside input root")
    if directory:
        if not resolved.is_dir():
            raise ValueError("Snapshot root must be a directory")
    else:
        if (not resolved.is_file() or not 1 <= resolved.stat().st_size
                <= MAX_JSON_BYTES):
            raise ValueError("Private cohort JSON missing, empty or too large")
    return resolved


def _json(root, path):
    return json.loads(_safe_member(root, path).read_text(encoding="utf-8-sig"))


def _batch_inputs(manifest, input_root):
    if (not isinstance(manifest, dict) or set(manifest) != ROOT_FIELDS
            or manifest["schema_version"] != VERSION
            or manifest["kind"] != MANIFEST_KIND
            or manifest["approved_for_advisor"] is not False
            or type(manifest["holdout_percent"]) is not int
            or not 10 <= manifest["holdout_percent"] <= 40
            or not isinstance(manifest["batches"], list)
            or not 1 <= len(manifest["batches"]) <= MAX_BATCHES):
        raise ValueError("Unpinned or privileged P19A3 pilot input manifest")
    batches = []
    seen = set()
    for entry in manifest["batches"]:
        if not isinstance(entry, dict) or set(entry) != BATCH_FIELDS:
            raise ValueError("Pilot batch requires exact six source-evidence files and ID")
        name = entry["batch_id"]
        if not isinstance(name, str) or not ID.fullmatch(name) or name in seen:
            raise ValueError("Duplicate/invalid source batch ID")
        seen.add(name)
        batches.append({
            "batch_id": name,
            "replay": _json(input_root, entry["replay"]),
            "capture_manifest": _json(input_root, entry["capture_manifest"]),
            "snapshot_root": _safe_member(
                input_root, entry["snapshot_root"], directory=True,
            ),
            "blind_packet": _json(input_root, entry["blind_packet"]),
            "reviewer_a": _json(input_root, entry["reviewer_a"]),
            "reviewer_b": _json(input_root, entry["reviewer_b"]),
        })
    return batches


def _source_counts(value):
    if not isinstance(value, dict):
        raise ValueError("P19A2 source lacks current original-HTML diagnostics")
    counts = {}
    for name in SOURCE_METRIC_COUNTS:
        v = value.get(name)
        if type(v) is not int or v < 0:
            raise ValueError("Invalid source-wide release gold metric: " + name)
        counts[name] = v
    tp, fp, fn = (counts["release_owner_tp"], counts["release_owner_fp"],
                  counts["release_owner_fn"])
    if (counts["title_checked_matches"] != tp
            or counts["title_exact_matches"] > tp
            or counts["version_exact_matches"] > counts["version_checked_matches"]
            or counts["version_checked_matches"] > tp
            or counts["publication_date_exact_matches"] >
                counts["publication_date_checked_matches"]
            or counts["publication_date_checked_matches"] +
                counts["publication_date_unresolved_reference_matches"] != tp):
        raise ValueError("Inconsistent release owner/date reference denominators")
    return counts


def _split_report(items):
    """Report source-weighted micro and equally weighted provisional providers.

    A provider group with ANY unscorable source is excluded from macro
    diagnostics, never silently counted as complete coverage.
    """
    totals = Counter()
    grouped = defaultdict(lambda: {"counts": Counter(), "held": 0,
                                    "sources": 0, "reference_releases": 0})
    for record in items:
        group = grouped[record["provisional_provider_group"]]
        group["sources"] += 1
        if record["diagnostic_only_metrics"] is None:
            group["held"] += 1
            continue
        counts = _source_counts(record["diagnostic_only_metrics"])
        totals.update(counts)
        group["counts"].update(counts)
        group["reference_releases"] += (
            counts["release_owner_tp"] + counts["release_owner_fn"]
        )
    fully_scored_groups = []
    macro_precision, macro_recall, macro_date = [], [], []
    for name in sorted(grouped):
        group = grouped[name]
        if group["held"]:
            continue
        fully_scored_groups.append(name)
        c = group["counts"]
        precision = _ratio(
            c["release_owner_tp"],
            c["release_owner_tp"] + c["release_owner_fp"],
        )
        recall = _ratio(
            c["release_owner_tp"],
            c["release_owner_tp"] + c["release_owner_fn"],
        )
        dated = _ratio(
            c["publication_date_exact_matches"],
            c["publication_date_checked_matches"],
        )
        if precision is not None:
            macro_precision.append(precision)
        if recall is not None:
            macro_recall.append(recall)
        if dated is not None:
            macro_date.append(dated)
    def mean(values):
        return sum(values) / len(values) if values else None
    tp, fp, fn = (
        totals["release_owner_tp"], totals["release_owner_fp"],
        totals["release_owner_fn"],
    )
    return {
        "selected_source_count": len(items),
        "diagnostic_scored_source_count": sum(
            x["diagnostic_only_metrics"] is not None for x in items
        ),
        "held_source_count": sum(
            x["diagnostic_only_metrics"] is None for x in items
        ),
        "selected_provisional_provider_groups": len(grouped),
        "fully_scored_provisional_provider_groups": len(fully_scored_groups),
        "provisional_provider_groups_with_held_sources": sorted(
            name for name, x in grouped.items() if x["held"]
        ),
        "reference_releases_scored": tp + fn,
        "owner_tp": tp,
        "owner_fp": fp,
        "owner_fn": fn,
        "date_exact": totals["publication_date_exact_matches"],
        "date_checked": totals["publication_date_checked_matches"],
        "date_ambiguous_reference_count":
            totals["publication_date_unresolved_reference_matches"],
        "title_exact": totals["title_exact_matches"],
        "title_checked": totals["title_checked_matches"],
        "version_exact": totals["version_exact_matches"],
        "version_checked": totals["version_checked_matches"],
        "micro_owner_precision_on_scored_sources_only": _ratio(tp, tp + fp),
        "micro_owner_recall_on_scored_sources_only": _ratio(tp, tp + fn),
        "micro_date_exact_on_scored_matches_only": _ratio(
            totals["publication_date_exact_matches"],
            totals["publication_date_checked_matches"],
        ),
        "macro_owner_precision_on_complete_providers_only":
            mean(macro_precision),
        "macro_owner_recall_on_complete_providers_only":
            mean(macro_recall),
        "macro_date_exact_on_complete_providers_only": mean(macro_date),
        "macro_owner_precision_group_denominator": len(macro_precision),
        "macro_owner_recall_group_denominator": len(macro_recall),
        "macro_date_group_denominator": len(macro_date),
        "publisher_truth_verified": False,
        "generalizable_release_accuracy_established": False,
    }


def aggregate_release_pilot(cohort, input_root, *, split_key):
    """Re-run each P19A2 census from exact HTML: no trust in scorecard JSON."""
    _split_key(split_key)
    batches = _batch_inputs(cohort, input_root)
    all_sources, all_groups = set(), {}
    all_hashes, job_fingerprints = set(), set()
    holding = Counter()
    rows, batch_provenance = [], []
    split_commitment = None
    for item in batches:
        name = item["batch_id"]
        report = score_census(
            item["replay"], item["capture_manifest"], item["snapshot_root"],
            item["blind_packet"], item["reviewer_a"], item["reviewer_b"],
            split_key=split_key,
            holdout_percent=cohort["holdout_percent"],
        )
        if (report.get("publisher_truth_verified") is not False
                or report.get("generalizable_release_accuracy_established") is not False
                or report.get("benchmark_or_adapter_rollout_authorized") is not False
                or report.get("deployment_authorized") is not False
                or report.get("advisor_fact_approvals") != 0
                or report.get("network_requests_performed") != 0
                or report.get("new_release_alerts") != 0):
            raise ValueError("Batch attempted to promote unverified changelog facts")
        packet = item["blind_packet"]
        commitment = packet["split_key_commitment_sha256"]
        if split_commitment is None:
            split_commitment = commitment
        elif split_commitment != commitment:
            raise ValueError("Source batches disagree on committed provider-group split")
        pins = (
            report["source_manifest_sha256"], report["local_package_sha256"],
            packet["source_registry_sha256"],
        )
        job_fingerprints.add(pins)
        batch_provenance.append({
            "batch_id": name,
            "capture_manifest_sha256": report["capture_manifest_sha256"],
            "replay_sha256": report["replay_sha256"],
            "blind_packet_sha256": report["blind_census_packet_sha256"],
            "source_count": report["source_count"],
            "held_sources": report["outcome_counts"].get(
                "source_held_unscorable", 0,
            ),
            "reviewer_distinctness_operator_attested_only": True,
        })
        for row in report["sources"]:
            sid = row["source_id"]
            if sid in all_sources:
                raise ValueError("Duplicate source in two pilot batches: " + sid)
            all_sources.add(sid)
            raw_sha = row["snapshot_sha256"]
            if raw_sha in all_hashes:
                raise ValueError("Two sources reuse identical original HTML bytes")
            all_hashes.add(raw_sha)
            group = row["provisional_provider_group"]
            split = row["evaluation_split"]
            if group in all_groups and all_groups[group] != split:
                raise ValueError("Same provisional publisher split across batches changed")
            all_groups[group] = split
            if row.get("approved_for_advisor") is not False:
                raise ValueError("Source in pilot attempted advisor fact approval")
            if row["diagnostic_only_metrics"] is None:
                for reason in row["hold_reasons"]:
                    holding[reason] += 1
            rows.append({
                "source_id": sid,
                "source_url": row["source_url"],
                "source_batch_id": name,
                "snapshot_sha256": raw_sha,
                "evaluation_split": split,
                "provisional_provider_group": group,
                "status": row["status"],
                "reviewer_a_census_count":
                    row["reviewer_a_visible_release_count"],
                "reviewer_b_census_count":
                    row["reviewer_b_visible_release_count"],
                "hold_reasons": row["hold_reasons"],
                "diagnostic_only_metrics": row["diagnostic_only_metrics"],
                "publisher_fact_authenticated": False,
                "approved_for_advisor": False,
            })
    if len(job_fingerprints) != 1:
        raise ValueError("Pilot batches must use same manifest, registry and parser package")
    if len(rows) > MAX_SOURCES:
        raise ValueError("Pilot includes more than 60 pinned changelog sources")
    sections = {
        split: _split_report([r for r in rows if r["evaluation_split"] == split])
        for split in ("development", "holdout")
    }
    overall = _split_report(rows)
    blockers = []
    def require(ok, reason):
        if not ok:
            blockers.append(reason)
    require(len(batches) >= PILOT_MIN_BATCHES,
            "need_at_least_3_independently_reviewed_small_batches")
    require(len(rows) >= PILOT_MIN_SOURCES,
            "need_at_least_15_pinned_unique_changelog_sources")
    require(overall["selected_provisional_provider_groups"] >=
            PILOT_MIN_PROVIDER_GROUPS,
            "need_at_least_15_distinct_provisional_publisher_groups")
    require(overall["held_source_count"] == 0,
            "unattributable_colliding_clipped_or_disagreed_sources_remain")
    require(overall["reference_releases_scored"] >= PILOT_MIN_REFERENCE_RELEASES,
            "need_at_least_60_dual_agreed_reference_release_cards")
    require(sections["holdout"]["fully_scored_provisional_provider_groups"] >=
            PILOT_MIN_HOLDOUT_PROVIDER_GROUPS,
            "need_at_least_3_wholly_reviewed_holdout_provider_groups")
    require(sections["holdout"]["reference_releases_scored"] >=
            PILOT_MIN_HOLDOUT_REFERENCE_RELEASES,
            "need_at_least_15_holdout_reference_releases")
    require(overall["date_checked"] >= PILOT_MIN_DATE_COMPARISONS,
            "need_at_least_30_attributable_date_or_explicitly_undated_decisions")
    require(sections["development"]["diagnostic_scored_source_count"] > 0,
            "missing_scored_development_sources")
    require(sections["holdout"]["diagnostic_scored_source_count"] > 0,
            "missing_scored_holdout_sources")
    require(overall["micro_owner_precision_on_scored_sources_only"] is not None,
            "no_attributable_parser_release_owners")
    result = {
        "schema_version": VERSION,
        "kind": RESULT_KIND,
        "cohort_manifest_sha256": _digest(cohort),
        "source_manifest_sha256": next(iter(job_fingerprints))[0],
        "local_package_sha256": next(iter(job_fingerprints))[1],
        "source_registry_sha256": next(iter(job_fingerprints))[2],
        "provider_group_split_commitment_sha256": split_commitment,
        "batch_count": len(batches),
        "source_count": len(rows),
        "provisional_publisher_group_count": len(all_groups),
        "input_manifest_batches": batch_provenance,
        "sources": sorted(rows, key=lambda row: row["source_id"]),
        "splits": sections,
        "all_selected_sources": overall,
        "held_reason_counts": dict(sorted(holding.items())),
        "pilot_sample_coverage_diagnostic_ready": not blockers,
        "pilot_coverage_blockers": blockers,
        "nonrepresentative_or_cherry_picked_sources_still_possible": True,
        "publisher_origin_independently_authenticated": False,
        "reviewer_independence_cryptographically_verified": False,
        "publisher_truth_verified": False,
        "generalizable_release_accuracy_established": False,
        "approval_of_provider_specific_adapters": False,
        "new_release_alerts": 0,
        "advisor_fact_approvals": 0,
        "zyte_jobs_created": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }
    result["report_sha256"] = _digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True,
                        help="Single private root containing all frozen batch inputs")
    parser.add_argument("--cohort-manifest", required=True,
                        help="Relative JSON path beneath input-root")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="NEW private directory for no-approval pilot metrics")
    args = parser.parse_args()
    key = os.environ.get("AGENTFUSE_RELEASE_GOLD_SPLIT_KEY", "")
    if not key:
        parser.error("Private AGENTFUSE_RELEASE_GOLD_SPLIT_KEY required")
    cohort = _json(args.input_root, args.cohort_manifest)
    report = aggregate_release_pilot(cohort, args.input_root, split_key=key)
    output = _private_new_directory(args.out_dir)
    try:
        _write_private(output / "release_pilot_diagnostics.json", (
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8"))
    except Exception:
        shutil.rmtree(output)
        raise
    print(json.dumps({
        "private_report": str(output / "release_pilot_diagnostics.json"),
        "source_count": report["source_count"],
        "provider_groups": report["provisional_publisher_group_count"],
        "sample_coverage_diagnostic_ready":
            report["pilot_sample_coverage_diagnostic_ready"],
        "coverage_blockers": report["pilot_coverage_blockers"],
        "publisher_truth_verified": False,
        "advisor_fact_approvals": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }, indent=2))


if __name__ == "__main__":
    main()
