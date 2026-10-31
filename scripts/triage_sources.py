#!/usr/bin/env python3
"""Read-only, evidence-grounded review of the 460-source Zyte inventory.

Usage:
    python -m scripts.triage_sources --exports output/zyte/*.jsonl --out-dir output/source-triage

Never approves a source, edits the manifest, fetches a site, or promotes
observed prices/changelogs/capabilities into AgentFuse.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agentfuse_crawlers.source_lifecycle import (
    source_lifecycle, source_lifecycle_summary,
)
from agentfuse_crawlers.sources import load_sources
from scripts.compare_exports import read_jsonl

CSV_FIELDS = (
    "source_id", "provider", "category", "source_url", "lifecycle_state",
    "policy_status", "observed_status", "http_status", "observed_at_utc",
    "observed_final_url", "observed_canonical_url", "observed_redirect_target",
    "finding_codes", "review_status", "next_action",
)


def read_historical_audit(path):
    """Import the owner's archived per-source audit, never live verified Items.

    Its curated 'sources' records were derived from October 31 Zyte exports,
    but do not contain full raw HTML or current publisher validations.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    sources = data.get("sources")
    if not (isinstance(sources, list) and
            data.get("all_captures_unverified") is True and
            data.get("total_source_records") == len(sources)):
        raise ValueError("Invalid or not explicitly unverified source audit")
    observed = {}
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("source_id"), str):
            raise ValueError("Historical audit contains an invalid source")
        sid = item["source_id"]
        if sid in observed:
            raise ValueError("Historical audit contains duplicate source: " + sid)
        if item.get("approved_for_advisor") is not False:
            raise ValueError("Historical audit must contain only unapproved Items")
        observed[sid] = item
    return observed


def _safe_url(value):
    """Strip potentially sensitive query/credentials from untrusted Item URLs."""
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            return ""
        if parsed.username or parsed.password or parsed.port not in (None, 443):
            return ""
        return urlunsplit(("https", parsed.hostname, parsed.path[:600] or "/", "", ""))
    except ValueError:
        return ""


def _review_findings(source, latest, lifecycle):
    findings = []
    state, policy = lifecycle["state"], lifecycle["policy_status"]
    if state == "quarantined":
        findings.append("unresolved_policy_quarantine")
    elif state == "degraded":
        findings.append("known_degraded_source")
    elif state == "retired":
        findings.append("retired_source")
    if policy in ("unresolved", "prohibited_reviewed"):
        findings.append("publisher_policy_review_required")
    if latest is None:
        findings.append("not_observed_in_supplied_exports")
        return findings

    status = latest.get("status") or "unknown"
    error = latest.get("error") or ""
    http = latest.get("http_status")
    if latest.get("source_url") and latest["source_url"] != source["url"]:
        findings.append("source_url_changed_since_snapshot")
    if status == "rejected_redirect" or error == "cross_host_or_non_https_redirect":
        findings.append("publisher_migration_or_redirect_review")
    if status in {"robots_or_policy_denied", "source_quarantined"}:
        findings.append("robots_or_policy_denied_observed")
    if status == "source_access_limited" or http == 429:
        findings.append("publisher_rate_limit_or_access_review")
    if http in (403, 404):
        findings.append("http_403_404_source_repair")
    if error in {"canonical_path_differs", "source_path_redirected"}:
        findings.append("canonical_or_path_movement_review")
    if error in {"insufficient_substantive_text", "javascript_only_shell",
                 "documentation_insufficient_content",
                 "documentation_link_index_only"} or (
                     isinstance(latest.get("word_count"), int)
                     and latest["word_count"] < 45
                 ):
        findings.append("insufficient_html_or_js_shell")
    if error in {"no_price_or_billing_detail_detected",
                 "pricing_no_structured_rate_evidence",
                 "pricing_rate_dimensions_unresolved",
                 "pricing_product_scope_unresolved"}:
        findings.append("pricing_scope_or_billing_review")
    if source["category"] == "pricing" and (
        latest.get("pricing_inventory_complete") is False
        or latest.get("tables_truncated")
    ):
        findings.append("pricing_table_inventory_incomplete")
    if error in {"documentation_product_scope_ambiguous",
                 "documentation_product_scope_not_demonstrated"}:
        findings.append("documentation_product_scope_review")
    if latest.get("documentation_canonical_relation") in {
        "same_host_path_differs", "same_host_parameters_review",
    }:
        findings.append("canonical_or_path_movement_review")
    if (isinstance(latest.get("reported_cache_age_seconds"), int)
            and latest["reported_cache_age_seconds"] > 86_400):
        findings.append("long_cdn_age_uncertain_not_publish_date")
    if (source["category"] == "changelog" and
        (latest.get("release_events_truncated") or
         latest.get("release_recent_body_loss_count", 0) or
         error in {"text_exceeds_capture_limit", "changelog_sections_truncated",
                   "recent_release_body_incomplete", "recent_release_window_incomplete"})):
        findings.append("changelog_evidence_incomplete")
    if error in {"no_dated_release_section_detected", "latest_release_date_ambiguous",
                 "release_events_missing_publication_dates", "no_release_events_detected"}:
        findings.append("changelog_date_evidence_missing")
    if error == "server_cached_response_over_one_day":
        findings.append("long_cdn_age_uncertain_not_publish_date")
    if latest.get("source_policy_status") == "unresolved":
        findings.append("historical_policy_unresolved")
    if not findings:
        findings.append("observation_present_not_verified")
    # A report must not imply duplicates are independent issues.
    return list(dict.fromkeys(findings))


def _next_action(findings, lifecycle):
    if "publisher_policy_review_required" in findings:
        return lifecycle["next_action"] or "Verify official publisher policy; do not bypass."
    if "publisher_migration_or_redirect_review" in findings:
        return "Inspect official publisher migration announcement and source scope; change manifest only in a reviewed PR."
    if "http_403_404_source_repair" in findings:
        return "Verify official current source URL and access policy; pause if not permitted."
    if "documentation_product_scope_review" in findings:
        return "Confirm exact product and authoritative technical page before using any capability evidence."
    if "pricing_scope_or_billing_review" in findings:
        return "Review official product/tier/billing units; unresolved rates remain unverified."
    if "changelog_date_evidence_missing" in findings:
        return "Inspect current official release cards and exact publication-date evidence; never infer year from fetch time."
    if "changelog_evidence_incomplete" in findings:
        return "Inspect recent release window and omitted evidence; do not claim complete release coverage."
    if "canonical_or_path_movement_review" in findings:
        return "Inspect official same-product canonical/path; do not follow unapproved cross-host redirects."
    if "insufficient_html_or_js_shell" in findings:
        return "Review first-party static or Markdown alternative; do not use proxy/browser bypass."
    if "not_observed_in_supplied_exports" in findings:
        return "Obtain a scoped permitted Zyte observation; current evidence is absent."
    if lifecycle["state"] == "degraded":
        return lifecycle["next_action"]
    return "Review official ownership, publisher policy, product relevance and two stable comparable runs."


def generate_triage(latest, *, manifest=None):
    """One explicit row per configured source, never an approval decision."""
    manifest = manifest or load_sources()
    known = {source["id"] for source in manifest}
    unexpected = set(latest) - known
    if unexpected:
        raise ValueError("Exports contain unknown source IDs: " + ", ".join(sorted(unexpected)[:10]))
    rows = []
    for source in manifest:
        sid = source["id"]
        observed = latest.get(sid)
        lifecycle = source_lifecycle(source)
        findings = _review_findings(source, observed, lifecycle)
        rows.append({
            "source_id": sid,
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "lifecycle_state": lifecycle["state"],
            "policy_status": lifecycle["policy_status"],
            "observed_status": observed.get("status", "unobserved") if observed else "unobserved",
            "http_status": observed.get("http_status") if observed else None,
            "observed_at_utc": observed.get("fetched_at_utc") if observed else None,
            "observed_final_url": _safe_url(observed.get("final_url")) if observed else "",
            "observed_canonical_url": _safe_url(observed.get("canonical_url")) if observed else "",
            "observed_redirect_target": _safe_url(observed.get("redirect_review_target")) if observed else "",
            "finding_codes": "|".join(findings),
            "review_status": "pending_human_review",
            "next_action": _next_action(findings, lifecycle),
        })
    return rows


def write_triage(rows, out_dir, *, input_basis="zyte_items"):
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "source_review_queue.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    (output / "source_review_queue.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts = Counter(
        flag for row in rows for flag in row["finding_codes"].split("|") if flag
    )
    summary = {
        "schema_version": "1.0",
        "input_basis": input_basis,
        "source_count": len(rows),
        "observed_in_supplied_exports": sum(row["observed_status"] != "unobserved" for row in rows),
        "unobserved_in_supplied_exports": sum(row["observed_status"] == "unobserved" for row in rows),
        "finding_counts": dict(sorted(counts.items())),
        "lifecycle": source_lifecycle_summary(),
        "automatically_approved_sources": 0,
        "approved_for_advisor": False,
        "notice": (
            "Review tasks, not verified results. Cached headers are not publication dates. "
            "Missing a source does not mean a product is retired."
        ),
    }
    (output / "triage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--exports", type=Path, nargs="+",
                        help="Previously downloaded raw Zyte JSON/JSONL Items")
    source.add_argument("--audit", type=Path,
                        help="Owner's historical unverified 460-source audit JSON")
    parser.add_argument("--out-dir", type=Path, default=Path("output/source-triage"))
    args = parser.parse_args()
    if args.audit:
        latest = read_historical_audit(args.audit)
        basis = "historical_compiled_audit_not_live_verified"
    else:
        latest = read_jsonl(args.exports)
        basis = "zyte_items_unverified"
    summary = write_triage(generate_triage(latest), args.out_dir, input_basis=basis)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
