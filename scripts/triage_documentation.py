"""Offline documentation crawl review queue — never a crawler or URL promoter.

Reads Zyte Items already emitted by the three pinned spiders. Reports
canonical migration/product-identity issues, JS shells and review-only child
links. It never contacts a publisher, edits the 460-source manifest,
registers new source IDs or approves a fact.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.documentation_scope import (
    _same_official_host, _trusted_page_family, canonical_relationship,
)
from agentfuse_crawlers.sources import load_sources

SOURCE_COLUMNS = (
    "source_id", "provider", "source_url", "status", "primary_error",
    "profile_status", "product_scope", "product_marker_signal",
    "static_capture_status", "observed_scope", "observed_word_count",
    "canonical_relation", "canonical_review_url",
    "child_link_review_candidates", "child_link_count_omitted",
    "nav_scan_truncated", "next_review_action", "advisor_approved",
)
CHILD_COLUMNS = (
    "source_id", "provider", "source_url", "candidate_url", "anchor_text",
    "found_in", "review_status", "approved_for_crawl", "approved_for_advisor",
)


def _safe_csv(value):
    """Prevent formula execution when inspecting untrusted page labels in CSV."""
    raw = str(value if value is not None else "")
    if raw.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + raw
    return raw


def _valid_child(item, candidate):
    if not isinstance(candidate, dict):
        return False
    url = candidate.get("candidate_url")
    source_url = item["source_url"]
    family = _trusted_page_family(source_url)
    if not isinstance(url, str) or not family or len(url) > 800:
        return False
    try:
        parts = urlsplit(url)
        return bool(
            _same_official_host(url, source_url)
            and not parts.query and not parts.fragment
            and "%" not in url and "//" not in parts.path
            and parts.path.startswith(family)
            and parts.path.rstrip("/") != urlsplit(source_url).path.rstrip("/")
            and candidate.get("source_id") == item["source_id"]
            and candidate.get("approved_for_crawl") is False
            and candidate.get("approved_for_advisor") is False
            and candidate.get("review_status") == "pending_human_url_and_policy_review"
        )
    except (TypeError, ValueError):
        return False


def triage_documentation_items(items):
    sources = {
        s["id"]: s for s in load_sources() if s["category"] == "documentation"
    }
    if not isinstance(items, list):
        raise ValueError("Input must be an array of Zyte Items")
    seen = set()
    result = []
    children = []
    counts = Counter()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Every Item must be an object")
        if item.get("category") != "documentation":
            continue  # May inspect mixed three-spider exports, but never edit them.
        sid = item.get("source_id")
        pinned = sources.get(sid) if isinstance(sid, str) else None
        if (not pinned or item.get("provider") != pinned["provider"]
                or item.get("source_url") != pinned["url"]):
            raise ValueError("Unrecognized or mismatched pinned documentation source")
        if sid in seen:
            raise ValueError("Duplicate source Item in offline docs review: " + sid)
        seen.add(sid)
        if item.get("approved_for_advisor") is not False:
            raise ValueError("Documentation Item must not authorize advisor facts")
        links = item.get("documentation_nav_candidates") or []
        if not isinstance(links, list) or len(links) > 24:
            raise ValueError("Invalid bounded documentation child link inventory")
        for candidate in links:
            if not _valid_child(item, candidate):
                raise ValueError("Unsafe/unapproved documentation child URL for " + sid)
            children.append({
                "source_id": sid, "provider": pinned["provider"],
                "source_url": pinned["url"],
                "candidate_url": candidate["candidate_url"],
                "anchor_text": candidate.get("anchor_text", ""),
                "found_in": candidate.get("found_in", ""),
                "review_status": candidate["review_status"],
                "approved_for_crawl": False,
                "approved_for_advisor": False,
            })
        relation = item.get("documentation_canonical_relation") or "not_recorded"
        proposed = item.get("documentation_canonical_review_url")
        canonical = canonical_relationship(item["source_url"], proposed)
        # The URL alone does not prove the claimed relationship. An attacker
        # can mutate the Item; re-evaluate provenance rather than trust it.
        if proposed and (
            canonical["review_url"] != proposed
            or canonical["relation"] not in {"equivalent_path", "same_host_path_differs"}
        ):
            raise ValueError("Unsafe canonical review URL for " + sid)
        if relation == "same_host_path_differs" and (
            not proposed or canonical["relation"] != "same_host_path_differs"
        ):
            raise ValueError("Canonical migration requires matching same-host proof")
        if relation == "external_or_unsafe_ignored" and proposed:
            raise ValueError("External canonical cannot be proposed as migration")
        if item.get("source_lifecycle_state") == "quarantined":
            action = "quarantine_no_fetch"
        elif item.get("status") in {"http_error", "source_access_limited",
                                     "robots_or_policy_denied", "blocked"}:
            action = "review_access_and_publisher_policy"
        elif relation in {"same_host_path_differs", "same_host_parameters_review"}:
            action = "manual_canonical_and_product_migration_review"
        elif item.get("documentation_requires_product_review") or item.get(
            "documentation_product_scope_signal"
        ) == "marker_not_found":
            action = "verify_product_scope_against_official_page"
        elif item.get("documentation_static_capture_status") == "javascript_shell_suspected":
            action = "investigate_publisher_static_html_or_explicit_official_alternate"
        elif item.get("documentation_scope_status") == "insufficient_content":
            action = "investigate_empty_or_unrendered_source_html"
        elif item.get("documentation_scope_status") == "index_only" or links:
            action = "human_review_same_host_child_pages_and_robots"
        elif item.get("documentation_profile_status") == "unprofiled":
            action = "curate_exact_url_product_profile_before_diff"
        elif item.get("documentation_scope_status") != "scoped_page":
            action = "review_page_specific_technical_evidence"
        else:
            action = "human_review_scoped_unverified_evidence"
        counts[action] += 1
        result.append({
            "source_id": sid,
            "provider": pinned["provider"], "source_url": pinned["url"],
            "status": item.get("status", ""),
            "primary_error": item.get("error", ""),
            "profile_status": item.get("documentation_profile_status", "not_recorded"),
            "product_scope": item.get("documentation_product_scope", ""),
            "product_marker_signal": item.get(
                "documentation_product_scope_signal", ""),
            "static_capture_status": item.get(
                "documentation_static_capture_status", "not_recorded"),
            "observed_scope": item.get("documentation_scope_status", "not_recorded"),
            "observed_word_count": item.get("word_count", ""),
            "canonical_relation": relation, "canonical_review_url": proposed or "",
            "child_link_review_candidates": len(links),
            "child_link_count_omitted": item.get(
                "documentation_nav_candidate_omitted", 0),
            "nav_scan_truncated": bool(
                item.get("documentation_nav_links_scan_truncated")),
            "next_review_action": action,
            "advisor_approved": False,
        })
    result.sort(key=lambda r: r["source_id"])
    children.sort(key=lambda r: (r["source_id"], r["candidate_url"]))
    return {
        "summary": {
            "report_schema": "1.0",
            "kind": "offline_documentation_review_not_source_registry",
            "expected_pinned_documentation_sources": len(sources),
            "documentation_items": len(result),
            "complete_docs_manifest_accounted": len(result) == len(sources),
            "missing_source_ids": sorted(set(sources) - seen),
            "review_child_link_count": len(children),
            "next_review_actions": dict(sorted(counts.items())),
            "eligible_new_auto_crawl_urls": 0,
            "advisor_approved_facts": 0,
            "publisher_policy_review_still_required": True,
        },
        "sources": result,
        "child_links": children,
    }


def write_triage(triage, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(triage["summary"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for filename, fields, rows in (
        ("source_triage.csv", SOURCE_COLUMNS, triage["sources"]),
        ("review_only_child_links.csv", CHILD_COLUMNS, triage["child_links"]),
    ):
        with (output / filename).open(
            "w", newline="", encoding="utf-8-sig"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows({
                key: _safe_csv(row.get(key, "")) for key in fields
            } for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, nargs="+", required=True)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/documentation-review"))
    args = parser.parse_args()
    rows = []
    for path in args.items:
        content = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(content, list):
            raise ValueError("Zyte exports must be JSON arrays")
        rows.extend(content)
    report = triage_documentation_items(rows)
    write_triage(report, args.out_dir)
    print(json.dumps({
        "documentation_source_items": report["summary"]["documentation_items"],
        "complete_manifest_accounted": report["summary"][
            "complete_docs_manifest_accounted"
        ],
        "review_only_child_urls": report["summary"]["review_child_link_count"],
        "approved_new_crawl_urls": 0, "approved_advisor_facts": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
