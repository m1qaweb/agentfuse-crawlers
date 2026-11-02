"""P16B: offline, source-pinned method comparison of independent raw captures.

This tool NEVER makes HTTP requests. An operator privately supplies a pair
of byte-exact original static HTML and alternate rendered HTML or the known
official Markdown release feed, and their SHA-256 + response metadata.

It measures *observable extraction changes*, not publisher truth:
more words, parsed prices or release events cannot establish accuracy,
completeness, crawl permission, a new adapter, or advisor eligibility.
"""
import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.acquisition_experiments import (
    acquire_method_plan, acquisition_registry_sha256,
    load_acquisition_experiments,
)
from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.markdown_releases import parse_markdown_releases
from agentfuse_crawlers.provider_profiles import identify_source_product
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources

SHA = re.compile(r"^[a-f0-9]{64}$")
SCHEMA = "1.0"
MAX_SNAPSHOT_BYTES = 8_000_000
MAX_MANIFEST_BYTES = 120_000
MAX_CAPTURE_TIME_DELTA_SECONDS = 2 * 60 * 60
MAX_OUTPUT_ROWS = 16
SNAPSHOT_FIELDS = frozenset({
    "file", "sha256", "request_url", "final_url", "http_status",
    "media_type", "capture_method", "captured_at_utc",
    "capture_origin_review_status",
})
PAIR_FIELDS = frozenset({"source_id", "experiment_id", "static_html", "alternate"})
ROOT_FIELDS = frozenset({"schema_version", "approved_for_advisor", "pairs"})
RESULT_FIELDS = (
    "experiment_id", "source_id", "category", "candidate_method",
    "static_snapshot_sha256", "alternate_snapshot_sha256",
    "static_status", "alternate_status",
    "static_word_count", "alternate_word_count",
    "static_scope", "alternate_scope",
    "static_structured_evidence_count", "alternate_structured_evidence_count",
    "static_dated_release_count", "alternate_dated_release_count",
    "static_pricing_comparable_count", "alternate_pricing_comparable_count",
    "static_product_title_conflict", "alternate_product_title_conflict",
    "observed_comparison", "manual_review_action",
    "automatic_method_selected", "publisher_truth_verified",
)


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Capture timestamp must be ISO 8601")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid capture timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("Timestamp must have an explicit UTC offset")
    return result.astimezone(timezone.utc)


def _snapshot_bytes(snapshot, root, *, expected_url, method):
    """Only an exact original HTTPS URL, no redirects, tokens or local escapes."""
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
        raise ValueError("Snapshot missing mandatory provenance fields")
    if (snapshot["request_url"] != expected_url
            or snapshot["final_url"] != expected_url):
        raise ValueError("Snapshot URL/redirect differs from pinned original page")
    if type(snapshot["http_status"]) is not int or snapshot["http_status"] != 200:
        raise ValueError("Only explicit HTTP 200 snapshots may be compared")
    if (snapshot["capture_method"] != method
            or snapshot["capture_origin_review_status"] !=
               "operator_supplied_unverified"):
        raise ValueError("Snapshot method or provenance is not a review-only capture")
    media_type = (
        "text/markdown" if method == "official_markdown" else "text/html"
    )
    if snapshot["media_type"] != media_type:
        raise ValueError("Snapshot media type does not match pinned method")
    digest = snapshot["sha256"]
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("Snapshot must have a lowercase SHA-256")
    raw = snapshot["file"]
    if (not isinstance(raw, str) or not 1 <= len(raw) <= 240
            or "\\" in raw or "\x00" in raw
            or raw.startswith("/") or raw.endswith("/")
            or "//" in raw):
        raise ValueError("Snapshot file must be a safe relative path")
    relative = Path(raw)
    if (relative.is_absolute() or not relative.parts
            or any(part in {".", "..", ""} for part in raw.split("/"))):
        raise ValueError("Snapshot path traversal or invalid relative path")
    base = Path(root).resolve(strict=True)
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Snapshot symlink forbidden")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(base) or not current.is_file():
        raise ValueError("Snapshot is not a regular file inside private root")
    if not 1 <= current.stat().st_size <= MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot is empty or exceeds bounded HTML/Markdown size")
    contents = current.read_bytes()
    if hashlib.sha256(contents).hexdigest() != digest:
        raise ValueError("Snapshot bytes differ from declared SHA-256")
    try:
        return contents.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Offline snapshots must be UTF-8") from exc


def _quality_features(source, text, method, alternate_url):
    """Run the unchanged production extractors against actual supplied bytes."""
    if method == "official_markdown":
        if source["category"] != "changelog":
            raise ValueError("Official release Markdown only applies to changelogs")
        extracted = parse_markdown_releases(
            text, source["id"], source["url"], alternate_url,
        )
    else:
        extracted = extract_evidence(
            text, source["url"],
            category=source["category"], source_id=source["id"],
        )
    identity = identify_source_product(source, extracted)
    visible_text = extracted.get("text", "")
    status, reason = assess_capture(
        source["category"], extracted, visible_text,
    )
    events = extracted.get("release_events") or []
    prices = extracted.get("pricing_observations") or []
    topics = extracted.get("documentation_topic_candidates") or []
    if any(not isinstance(x, dict) for xs in (events, prices, topics) for x in xs):
        raise ValueError("Extractor produced malformed observation")
    if any(x.get("approved_for_advisor") is not False
           for xs in (events, prices, topics) for x in xs):
        raise ValueError("Extractor unexpectedly emitted an approved observation")
    category = source["category"]
    count = len({
        "pricing": prices, "documentation": topics, "changelog": events,
    }[category])
    return {
        "capture_status": status,
        "capture_reason": reason,
        "word_count": extracted.get("word_count", 0),
        "content_text_sha256": extracted.get("content_sha256"),
        "page_title": str(extracted.get("title") or "")[:240],
        "structural_evidence_count": count,
        "page_family": identity["source_page_family_candidate"],
        "source_expected_product_id": identity["source_expected_product_id"],
        "product_title_conflict": identity["source_product_title_conflict"],
        "product_identity_unverified": True,
        "documentation_scope_status": (
            extracted.get("documentation_scope_status")
            if category == "documentation" else None
        ),
        "documentation_static_capture_status": (
            extracted.get("documentation_static_capture_status")
            if category == "documentation" else None
        ),
        "documentation_topic_candidate_count": (
            len(topics) if category == "documentation" else None
        ),
        "pricing_inventory_complete": (
            extracted.get("pricing_inventory_complete") is True
            if category == "pricing" else None
        ),
        "pricing_observation_count": (
            len(prices) if category == "pricing" else None
        ),
        "pricing_comparable_candidate_count": (
            extracted.get("pricing_comparable_candidate_count", 0)
            if category == "pricing" else None
        ),
        "pricing_relevant_table_count": (
            extracted.get("pricing_table_relevant", 0)
            if category == "pricing" else None
        ),
        "release_window_complete": (
            extracted.get("release_window_complete") is True
            if category == "changelog" else None
        ),
        "release_event_identity_collision": (
            extracted.get("release_event_identity_collision") is True
            if category == "changelog" else None
        ),
        "release_dated_event_count": (
            extracted.get("release_dated_event_count", 0)
            if category == "changelog" else None
        ),
        "source_format": (
            extracted.get("source_format") or
            ("official_markdown" if method == "official_markdown"
             else "static_or_rendered_html_not_authenticated")
        ),
        "all_facts_unverified": True,
        "approved_for_advisor": False,
    }


def _review_outcome(category, static, alternate):
    """No scalar quality score and no automatic acquisition method promotion."""
    if alternate["product_title_conflict"]:
        return "alternate_product_title_conflict", "review_exact_product_owner"
    if static["product_title_conflict"]:
        return "baseline_product_title_conflict", "review_original_product_scope"
    if alternate["capture_status"] == "blocked":
        return "alternate_access_or_login_challenge", "do_not_bypass_access_controls"
    if category == "documentation":
        weak = {"index_only", "overview_only", "insufficient_content",
                "scope_not_established"}
        if (static["documentation_scope_status"] in weak
                and alternate["documentation_scope_status"] == "scoped_page"
                and alternate["documentation_topic_candidate_count"] > 0):
            return "more_scoped_docs_candidate", "independent_topic_scope_and_owner_review"
        if (static["documentation_scope_status"] == "scoped_page"
                and alternate["documentation_scope_status"] in weak):
            return "alternative_docs_scope_regression", "retain_static_until_review"
    if category == "pricing":
        if (alternate["pricing_inventory_complete"]
                and alternate["pricing_comparable_candidate_count"] >
                    static["pricing_comparable_candidate_count"]):
            return "more_comparable_rate_candidates", "verify_pricing_dimensions_in_gold"
        if alternate["pricing_observation_count"] > static["pricing_observation_count"]:
            return "more_raw_pricing_evidence", "review_rate_scope_and_table_completeness"
        if (static["pricing_inventory_complete"]
                and not alternate["pricing_inventory_complete"]):
            return "alternate_pricing_inventory_regression", "retain_static_until_review"
    if category == "changelog":
        if (alternate["release_dated_event_count"] >
                    static["release_dated_event_count"]
                and alternate["release_window_complete"]
                and not alternate["release_event_identity_collision"]):
            return "more_dated_release_candidates", "independently_verify_publication_dates"
        if alternate["structural_evidence_count"] > static["structural_evidence_count"]:
            return "more_version_events_dates_unverified", "review_release_identity_and_dates"
        if (static["release_window_complete"]
                and not alternate["release_window_complete"]):
            return "alternate_release_window_regression", "retain_static_until_review"
    if alternate["word_count"] > static["word_count"] + 150:
        return "more_visible_text_without_scope_proof", "review_content_not_volume"
    return "no_demonstrated_structural_improvement", "retain_static_and_review_hard_cases"


def compare_acquisition_snapshots(manifest, snapshot_root):
    if (not isinstance(manifest, dict) or set(manifest) != ROOT_FIELDS
            or manifest["schema_version"] != SCHEMA
            or manifest["approved_for_advisor"] is not False
            or not isinstance(manifest["pairs"], list)
            or not 1 <= len(manifest["pairs"]) <= MAX_OUTPUT_ROWS):
        raise ValueError("Invalid or unbounded P16B snapshot comparison manifest")
    registry = load_acquisition_experiments()
    known = {x["id"]: x for x in load_sources()}
    output, seen_sources, outcome_count = [], set(), Counter()
    for pair in manifest["pairs"]:
        if not isinstance(pair, dict) or set(pair) != PAIR_FIELDS:
            raise ValueError("Malformed comparison pair")
        sid = pair["source_id"]
        experiment = registry.get(sid) if isinstance(sid, str) else None
        if (experiment is None or sid in seen_sources
                or pair["experiment_id"] != experiment["experiment_id"]):
            raise ValueError("Duplicate/unknown/misidentified acquisition experiment")
        seen_sources.add(sid)
        src = known[sid]
        primary, alternate = pair["static_html"], pair["alternate"]
        started = _timestamp(primary.get("captured_at_utc")
                             if isinstance(primary, dict) else None)
        ended = _timestamp(alternate.get("captured_at_utc")
                           if isinstance(alternate, dict) else None)
        if abs((ended - started).total_seconds()) > MAX_CAPTURE_TIME_DELTA_SECONDS:
            raise ValueError("Comparisons need contemporaneous captures within two hours")
        raw_static = _snapshot_bytes(
            primary, snapshot_root, expected_url=src["url"],
            method="static_html",
        )
        raw_alt = _snapshot_bytes(
            alternate, snapshot_root,
            expected_url=experiment["candidate_url"],
            method=experiment["candidate_acquisition_method"],
        )
        metrics_static = _quality_features(
            src, raw_static, "static_html", src["url"],
        )
        metrics_alt = _quality_features(
            src, raw_alt, experiment["candidate_acquisition_method"],
            experiment["candidate_url"],
        )
        label, action = _review_outcome(
            src["category"], metrics_static, metrics_alt,
        )
        outcome_count[label] += 1
        output.append({
            "experiment_id": experiment["experiment_id"],
            "source_id": sid,
            "category": src["category"],
            "official_source_url": src["url"],
            "alternate_method": experiment["candidate_acquisition_method"],
            "alternate_source_url": experiment["candidate_url"],
            "static_snapshot_sha256": primary["sha256"],
            "alternate_snapshot_sha256": alternate["sha256"],
            "snapshot_capture_seconds_apart":
                abs(round((ended - started).total_seconds())),
            "static": metrics_static,
            "alternate": metrics_alt,
            "observed_comparison": label,
            "manual_review_action": action,
            "publisher_response_origin_independently_authenticated": False,
            "original_robots_terms_permission_independently_verified": False,
            "crawler_extractor_observations_independently_verified": False,
            "static_source_replaced": False,
            "automatic_method_selected": False,
            "source_specific_adapter_authorized": False,
            "approved_for_advisor": False,
        })
    output.sort(key=lambda r: r["source_id"])
    return {
        "summary": {
            "schema_version": SCHEMA,
            "kind": "p16b_paired_raw_acquisition_extractor_observations_not_truth",
            "experiment_registry_sha256": acquisition_registry_sha256(),
            "current_source_manifest_sha256": manifest_sha256(),
            "current_source_registry_sha256": registry_revision_sha256(),
            "local_parser_package_sha256_not_deployed_revision": package_fingerprint(),
            "paired_sources": len(output),
            "candidate_registry_sources": len(registry),
            "outcomes": dict(sorted(outcome_count.items())),
            "publisher_snapshot_origin_authenticated": False,
            "independent_accuracy_gold_evaluated": False,
            "official_structured_feed_candidates_confirmed": 0,
            "automatic_browser_render_requests": 0,
            "automatic_source_swaps": 0,
            "source_policy_promotions": 0,
            "approved_for_advisor_facts": 0,
            "network_requests_performed": 0,
            "deployment_authorized": False,
        },
        "pairs": output,
    }


def _safe_csv(value):
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _private_output(directory):
    target = Path(directory)
    if target.is_symlink():
        raise ValueError("Output destination is a symlink")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    return target


def write_acquisition_report(report, out_dir):
    target = _private_output(out_dir)
    (target / "acquisition_comparison_summary.json").write_text(
        json.dumps(report["summary"], indent=2) + "\n", encoding="utf-8",
    )
    (target / "acquisition_comparison_pairs.json").write_text(
        json.dumps(report["pairs"], indent=2) + "\n", encoding="utf-8",
    )
    with (target / "acquisition_review_queue.csv").open(
        "w", newline="", encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for row in report["pairs"]:
            before, after = row["static"], row["alternate"]
            flat = {
                "experiment_id": row["experiment_id"],
                "source_id": row["source_id"],
                "category": row["category"],
                "candidate_method": row["alternate_method"],
                "static_snapshot_sha256": row["static_snapshot_sha256"],
                "alternate_snapshot_sha256": row["alternate_snapshot_sha256"],
                "static_status": before["capture_status"],
                "alternate_status": after["capture_status"],
                "static_word_count": before["word_count"],
                "alternate_word_count": after["word_count"],
                "static_scope": before["documentation_scope_status"],
                "alternate_scope": after["documentation_scope_status"],
                "static_structured_evidence_count": before["structural_evidence_count"],
                "alternate_structured_evidence_count": after["structural_evidence_count"],
                "static_dated_release_count": before["release_dated_event_count"],
                "alternate_dated_release_count": after["release_dated_event_count"],
                "static_pricing_comparable_count": before["pricing_comparable_candidate_count"],
                "alternate_pricing_comparable_count": after["pricing_comparable_candidate_count"],
                "static_product_title_conflict": before["product_title_conflict"],
                "alternate_product_title_conflict": after["product_title_conflict"],
                "observed_comparison": row["observed_comparison"],
                "manual_review_action": row["manual_review_action"],
                "automatic_method_selected": False,
                "publisher_truth_verified": False,
            }
            writer.writerow({key: _safe_csv(flat.get(key)) for key in RESULT_FIELDS})
    for output in target.iterdir():
        if output.is_file():
            os.chmod(output, 0o600)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true",
                        help="Print only exact manual source/method experiments")
    parser.add_argument("--manifest", type=Path,
                        help="JSON of operator-supplied capture pairs")
    parser.add_argument("--snapshot-root", type=Path,
                        help="Private original raw UTF-8 capture directory")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/private/p16b-acquisition"))
    args = parser.parse_args()
    if args.plan_only:
        if args.manifest or args.snapshot_root:
            parser.error("--plan-only cannot combine with private capture files")
        plan = acquire_method_plan()
        out = _private_output(args.out_dir)
        dest = out / "manual_acquisition_experiments.json"
        dest.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        os.chmod(dest, 0o600)
        print(json.dumps({"planned_candidates": plan["planned_sources"],
                          "network_requests": 0, "path": str(dest)}, indent=2))
    else:
        if not args.manifest or not args.snapshot_root:
            parser.error("Comparison requires --manifest and --snapshot-root")
        if args.manifest.stat().st_size > MAX_MANIFEST_BYTES:
            parser.error("Unreviewed capture manifest exceeds allowed size")
        incoming = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = compare_acquisition_snapshots(incoming, args.snapshot_root)
        out = write_acquisition_report(report, args.out_dir)
        print(json.dumps({
            "paired": report["summary"]["paired_sources"],
            "status": "review_only_no_auto_acquisition",
            "network_requests": 0, "out_dir": str(out),
        }, indent=2))


if __name__ == "__main__":
    main()
