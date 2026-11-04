"""P21A -- offline, fail-closed Nov 4 Zyte three-spider evidence audit.

Raw Zyte Dashboard exports are NOT independently authenticated job archives.
This tool proves file integrity relative to a pinned user-supplied baseline,
manifest/record accounting and internal consistency, not publisher accuracy
or legal permission. It never performs network IO or changes source policy.

Input: EXACT nine Nov 4 exported JSON arrays in --input-dir. Raw originals
remain untouched; only PRIVATE, NEW output files are written.
"""
import argparse
import csv
import hashlib
import hmac
import io
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.run_context import (
    manifest_sha256, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import (
    registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources, select_sources
from scripts.audit_pricing_items import inspect as inspect_pricing
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)
from scripts.replay_release_snapshots import _digest

VERSION = "1.0"
MANIFEST_SHA = "231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933"
REGISTRY_SHA = "776384e860fe3207c734719a19b782adb20b30468f856549bfe35378709e6cc2"
PACKAGE_SHA = "1f02ac83f9388b8636ce46c861f92bdddc80b0463fd3a8c4ce12690d698d8a17"
BASELINES = {
    "documentation": {"suffix": "15", "count": 194, "spider": "official_documentation",
                      "job": "883514/2/15",
                      "sha": {
                          "items": "9e8166b9bc43baf4efe60d95fb3f728f0374d16b9530fcff44aaadcb1e492e78",
                          "requests": "5bcf776b462d5eaed8f8e8f7d5a0c9a4c433e12a9edafc8d0c37d11f144b15b1",
                          "log": "0afa4c5bb861a546fe7e35a10843f604061f5fa90e26d41e550e79619bfb1490"}},
    "pricing": {"suffix": "11", "count": 177, "spider": "official_pricing",
                "job": "883514/3/11",
                "sha": {
                    "items": "e55b786b3d7f9d8290432a343220e827e81e0beba4ad41651c9abe8e37b10663",
                    "requests": "eb27c99e9466038133ad4e3d374d5464b8f8e968d0324f1f17aefb9e510bcc32",
                    "log": "26f704ff452653509626d3710cd1e1a895173df65db1a8b31134034e964ed049"}},
    "changelog": {"suffix": "16", "count": 89, "spider": "official_changelogs",
                  "job": "883514/1/16",
                  "sha": {
                      "items": "3a06ffb552493e89ec04c76d0d4cac4a108a587a8b6bb7bd5e11b25e3cac188c",
                      "requests": "44ae4c0f5c2cbeaddd549eb44d5d6621d4c6d988ee25c886f636a709c8e7cb90",
                      "log": "da152cfeebcc53570a4b969819fe05f93a1f81ac54291a57d469f7bf62149c3f"}},
}
SOURCE_FIELDS = (
    "rank", "source_id", "category", "provider", "source_url",
    "status", "http_status", "primary_error", "request_chain_status",
    "request_count_for_configured_url", "final_response_matched",
    "robots_requests_for_source_host", "source_policy_status",
    "diagnostic_reasons", "risk_family", "risk_score",
    "pricing_observations", "pricing_numeric_candidates",
    "pricing_review_quotes", "pricing_comparable_candidates",
    "pricing_relevant_tables_omitted",
    "release_detected", "release_retained", "release_id_collision",
    "release_window_complete", "documentation_scope",
    "documentation_nav_omitted", "source_hash_present",
    "external_publisher_accuracy_verified", "next_action",
)
REQUEST_FIELDS = (
    "category", "job_id", "request_index", "request_time_ms", "status",
    "method", "request_url", "request_class", "source_ids_exact_url",
    "source_ids_final_url", "parent_request_index", "response_size_bytes",
)
RISKS = {
    "policy_or_access": "Review human publisher access, robots and actual exact URL before any further fetch",
    "redirect_or_canonical": "Manually verify source owner, product and proposed canonical; no automatic cross-host following",
    "pricing_inventory": "Replay identical permitted source HTML; reconcile every relevant table and observation window",
    "pricing_dimensions": "Review first-party currency, rate unit, model, tier and region applicability without inference",
    "changelog_identity": "Use original owner-boundary HTML and dual independent source-wide release census",
    "changelog_window": "Replay original HTML and recover recent event body without inferred latest date",
    "documentation_scope": "Validate exact product scope and separately policy-reviewed child pages",
    "unknown_semantics": "Inspect original HTML and record unverified semantics, not a price or date claim",
}
RISK_WEIGHTS = {
    "policy_or_access": 100, "redirect_or_canonical": 90,
    "pricing_inventory": 85, "pricing_dimensions": 75,
    "changelog_identity": 82, "changelog_window": 70,
    "documentation_scope": 65, "unknown_semantics": 40,
}
MAX_JSON_BYTES = {"items": 16_000_000, "requests": 2_000_000, "log": 2_000_000}
MIN_HOLDOUT_KEY_BYTES = 32


def _export_name(category, suffix, kind):
    return f"{kind}_official_{category}s_{suffix}.json" if category == "changelog" else (
        f"{kind}_official_{category}_{suffix}.json"
    )


def _raw_exports(directory):
    """Read all nine exact bounded originals, with SHA-256 pins, no modification."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Existing real input directory required (no symlinks)")
    files = {}
    payload = {}
    for category, setup in BASELINES.items():
        payload[category] = {}
        for kind, expected_sha in setup["sha"].items():
            name = _export_name(category, setup["suffix"], kind)
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Missing or unsafe original export: " + name)
            data = path.read_bytes()
            if not 2 <= len(data) <= MAX_JSON_BYTES[kind]:
                raise ValueError("Original export bytes out of allowed range: " + name)
            digest = hashlib.sha256(data).hexdigest()
            if digest != expected_sha:
                raise ValueError("Original Nov 4 exported bytes changed: " + name)
            try:
                value = json.loads(data.decode("utf-8-sig"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError("Invalid original JSON array: " + name) from exc
            if not isinstance(value, list) or not all(
                isinstance(entry, dict) for entry in value
            ):
                raise ValueError("Original export must be JSON object array: " + name)
            payload[category][kind] = value
            files[name] = {
                "sha256": digest, "bytes": len(data),
                "unaltered_original_input": True,
            }
    return payload, files


def _holdout(sources, key):
    if not isinstance(key, str) or len(key.encode("utf-8")) < MIN_HOLDOUT_KEY_BYTES:
        raise ValueError("Private AGENTFUSE_P21A_HOLDOUT_KEY must be >=32 bytes")
    keyed = key.encode("utf-8")
    chosen = {}
    for category in sorted(BASELINES):
        options = [s for s in sources if s["category"] == category]
        ranked = sorted(
            options, key=lambda s: hmac.digest(
                keyed, (category + ":" + s["id"]).encode(), "sha256"
            ),
        )
        chosen[category] = sorted(s["id"] for s in ranked[:6])
    result = {
        "schema_version": VERSION,
        "kind": "p21a_private_source_id_holdout_precommitted_no_gold",
        "selection_method": "hmac_sha256_category_source_id_six_per_category",
        "source_count": 18, "categories": chosen,
        "key_sha256_not_the_key": hashlib.sha256(keyed).hexdigest(),
        "selection_before_new_parser_replay": True,
        "independent_human_reference_labels_supplied": False,
        "approved_for_advisor": False,
    }
    result["manifest_sha256"] = MANIFEST_SHA
    result["holdout_sha256"] = _digest(result)
    return result


def _risk(item):
    cat, status = item["category"], item.get("status")
    reasons = item.get("diagnostic_reason_codes") or []
    reason_text = " ".join(str(x) for x in reasons) + " " + str(item.get("error", ""))
    if (status in ("source_quarantined", "source_retired",
                   "source_access_limited", "http_error", "blocked")
            or item.get("http_status") in (403, 429)):
        return "policy_or_access"
    if status in ("rejected_redirect", "redirect_needs_review") or (
        "redirect" in reason_text or "canonical" in reason_text
    ):
        return "redirect_or_canonical"
    if cat == "pricing":
        return ("pricing_inventory" if not item.get("pricing_inventory_complete", True)
                else "pricing_dimensions")
    if cat == "changelog":
        return ("changelog_identity" if item.get("release_event_identity_collision")
                else "changelog_window")
    if cat == "documentation":
        return "documentation_scope"
    return "unknown_semantics"


def _source_risk_score(item, family):
    # A deterministic prioritization heuristic, NOT a claim about price/date
    # truth, user popularity, publisher legal rights or verified impact.
    score = RISK_WEIGHTS[family]
    if item.get("http_status") == 200:
        score += 3
    if item.get("pricing_observation_count", 0):
        score += min(item["pricing_observation_count"], 300) // 30
    if item.get("release_event_count", 0):
        score += min(item["release_event_count"], 500) // 50
    if item.get("documentation_nav_candidate_omitted", 0):
        score += min(item["documentation_nav_candidate_omitted"], 500) // 50
    return score


def audit_bundle(bundle, *, holdout_key, files=None, allow_synthetic=False):
    """Reconcile three full jobs. Synthetic tests may skip raw SHA pins only."""
    sources = load_sources()
    if (len(sources) != 460 or manifest_sha256(sources) != MANIFEST_SHA
            or registry_revision_sha256() != REGISTRY_SHA):
        raise ValueError("Source manifest or registry differs from frozen Nov 4 run")
    if set(bundle) != set(BASELINES):
        raise ValueError("Exactly 3 complete category bundles required")
    known = {s["id"]: s for s in sources}
    all_source_rows, all_request_rows = [], []
    category_reports, log_receipts, risks = {}, {}, defaultdict(list)
    package_seen = set()
    emitted = set()
    operational_errors = []
    for category, setup in BASELINES.items():
        data = bundle[category]
        if not isinstance(data, dict) or set(data) != {"items", "requests", "log"}:
            raise ValueError("Missing Items, Requests or Log for " + category)
        items, reqs, logs = data["items"], data["requests"], data["log"]
        if not all(isinstance(x, list) for x in (items, reqs, logs)):
            raise ValueError("Original exports must be JSON arrays")
        if len(items) != setup["count"]:
            raise ValueError("Source summary count mismatch: " + category)
        if not reqs or not logs:
            raise ValueError("Request trace and finished-job Log required")
        selected = select_sources(category, "all")
        if len(selected) != setup["count"]:
            raise ValueError("Current source category count changed")
        selection_sha = selection_ids_sha256(selected)
        expected = {s["id"] for s in selected}
        by_url = defaultdict(list)
        for i, req in enumerate(reqs):
            if (not isinstance(req, dict) or req.get("method") != "GET"
                    or not isinstance(req.get("url"), str)
                    or not req["url"].startswith("https://")
                    or type(req.get("status")) is not int
                    or not 100 <= req["status"] <= 599
                    or type(req.get("time")) is not int
                    or type(req.get("rs")) is not int):
                raise ValueError("Malformed GET request record")
            by_url[req["url"]].append((i, req))
        if any(not isinstance(log, dict) for log in logs):
            raise ValueError("Malformed Zyte log record")
        lines = [str(log.get("message") or "") for log in logs]
        combined = "\n".join(lines)
        if not any("Spider closed (finished)" in line for line in lines):
            raise ValueError("Job not finished in supplied log")
        starts = [line for line in lines if
                  f"Starting {category}" in line and
                  f"{setup['count']} configured URLs" in line]
        if not starts:
            raise ValueError("Log does not match expected full category")
        recorded_stats = {}
        for label in ("expected_sources", "reported_sources", "captured_sources"):
            found = re.search(
                rf"'agentfuse/coverage/{label}': (\d+)", combined
            )
            if not found:
                raise ValueError("Coverage counter missing from job log: " + label)
            recorded_stats[label] = int(found.group(1))
        if recorded_stats["expected_sources"] != setup["count"] or (
            recorded_stats["reported_sources"] != len(items)
        ):
            raise ValueError("Source accounting differs from Zyte log")
        initial_urls = {known[sid]["url"]: sid for sid in expected}
        final_urls = defaultdict(list)
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("final_url"), str):
                final_urls[item["final_url"]].append(item.get("source_id"))
        robots_by_host = Counter()
        request_statuses = Counter()
        for n, req in enumerate(reqs):
            url = req["url"]
            hostname = (urlsplit(url).hostname or "").lower()
            robots = urlsplit(url).path.endswith("/robots.txt")
            if robots:
                kind = "robots"
                robots_by_host[hostname] += 1
            elif url in initial_urls:
                kind = "configured_source_request"
            elif url in final_urls:
                kind = "redirected_final_request"
            else:
                kind = "other_request_no_unique_source_attribution"
            request_statuses[str(req["status"])] += 1
            all_request_rows.append({
                "category": category, "job_id": setup["job"],
                "request_index": n, "request_time_ms": req["time"],
                "status": req["status"], "method": req["method"],
                "request_url": url, "request_class": kind,
                "source_ids_exact_url": initial_urls.get(url, ""),
                "source_ids_final_url": ",".join(sorted(str(x) for x in final_urls.get(url, []))),
                "parent_request_index": req.get("parent", ""),
                "response_size_bytes": req["rs"],
            })
        statuses, recorded, http_counts = Counter(), Counter(), Counter()
        price_measured, release_measured, doc_measured = Counter(), Counter(), Counter()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Malformed source Item object")
            sid = item.get("source_id")
            if (not isinstance(sid, str) or sid not in expected
                    or sid in emitted):
                raise ValueError("Missing, duplicated or unknown source ID")
            emitted.add(sid)
            source = known[sid]
            if (item.get("spider_name") != setup["spider"]
                    or item.get("category") != category
                    or item.get("provider") != source["provider"]
                    or item.get("source_url") != source["url"]
                    or item.get("zyte_job_id") != setup["job"]
                    or item.get("requested_cohort") != "all"
                    or item.get("selection_source_count") != setup["count"]
                    or item.get("selection_ids_sha256") != selection_sha
                    or item.get("source_registry_sha256") != REGISTRY_SHA
                    or item.get("manifest_sha256") != MANIFEST_SHA
                    or item.get("deployment_revision") != PACKAGE_SHA
                    or item.get("deployment_revision_kind") != "package_py_json_sha256_v1"
                    or item.get("collection_mode") != "validation"
                    or item.get("run_scope_explicit") is not True
                    or item.get("approved_for_advisor") is not False
                    or item.get("review_status") != "unverified"):
                raise ValueError("Source/selection/package/fact trust violated: " + sid)
            package_seen.add(item["deployment_revision"])
            if item.get("deployment_source_revision_claim"):
                raise ValueError("Original job incorrectly claimed verified git revision")
            if (not isinstance(item.get("diagnostic_reason_codes"), list)
                    or any(not isinstance(x, str) for x in item["diagnostic_reason_codes"])):
                raise ValueError("Source diagnostics not a list of reason codes")
            status = item.get("status")
            http = item.get("http_status")
            if not isinstance(status, str) or not status:
                raise ValueError("Missing crawl status")
            if http is not None and (type(http) is not int or not 100 <= http <= 599):
                raise ValueError("Invalid HTTP status in source record")
            if status in {"captured", "needs_review", "partial_capture"} and http != 200:
                raise ValueError("Semantic source status cannot have non-200 response")
            if status in {"source_quarantined", "source_retired"} and http is not None:
                raise ValueError("Held source illegally recorded as fetched")
            first = by_url.get(source["url"], [])
            if http is None:
                if first:
                    raise ValueError("Policy-held source URL had source GET: " + sid)
                request_proof = "no_source_get"
                final_match = False
            else:
                if not first:
                    raise ValueError("Source has HTTP metadata but missing initial GET: " + sid)
                final = item.get("final_url")
                matching = by_url.get(final, [])
                if (not isinstance(final, str) or
                        not any(entry["status"] == http for _, entry in matching)):
                    raise ValueError("No final URL+HTTP status in request archive: " + sid)
                request_proof = (
                    "original_url_http_match" if any(entry["status"] == http for _, entry in first)
                    else "same_run_redirect_chain_observed"
                )
                final_match = True
            if status == "source_quarantined" and (
                item.get("source_policy_status") != "unresolved"
                or item.get("source_lifecycle_state") != "quarantined"
            ):
                raise ValueError("Policy-quarantined Item lost source policy status")
            statuses[status] += 1
            http_counts[str(http)] += 1
            recorded[request_proof] += 1
            family = _risk(item)
            risks[family].append(sid)
            price_rows = item.get("pricing_observations") or []
            releases = item.get("release_events") or []
            if category == "pricing":
                if (not isinstance(price_rows, list)
                        or item.get("pricing_observation_count", 0) != len(price_rows)
                        or item.get("pricing_observation_total_detected", 0) < len(price_rows)):
                    raise ValueError("Pricing observation inventory inconsistent: " + sid)
                for x in price_rows:
                    if (not isinstance(x, dict)
                            or x.get("source_id") != sid
                            or x.get("source_url") != source["url"]
                            or x.get("approved_for_advisor") is not False):
                        raise ValueError("Unbound pricing observation: " + sid)
                price_measured["retained_observations"] += len(price_rows)
                price_measured["numeric_candidates"] += sum(x.get("price_state") == "numeric_candidate" for x in price_rows)
                price_measured["review_quote_candidates"] += sum(x.get("review_quote_candidate") is True for x in price_rows)
                price_measured["fully_comparable_candidates"] += sum(x.get("comparable_candidate") is True for x in price_rows)
                price_measured["detected_observations"] += item.get("pricing_observation_total_detected", 0)
                price_measured["recognized_relevant_tables"] += item.get("pricing_table_relevant", 0)
                price_measured["selected_relevant_tables"] += item.get("pricing_table_selected", 0)
                if price_rows:
                    price_measured["sources_with_observations"] += 1
            elif category == "changelog":
                if (not isinstance(releases, list)
                        or item.get("release_recent_event_count", 0) != len(releases)
                        or item.get("release_event_count", 0) < len(releases)):
                    raise ValueError("Changelog release-event inventory inconsistent: " + sid)
                for x in releases:
                    if not isinstance(x, dict) or x.get("approved_for_advisor") is not False:
                        raise ValueError("Unverified release event invariant broken: " + sid)
                release_measured["detected_entries"] += item.get("release_event_count", 0)
                release_measured["retained_entries"] += len(releases)
                release_measured["historical_entries_omitted"] += item.get("release_historical_event_count_omitted", 0)
                release_measured["entries_with_day"] += sum(bool(x.get("published_at")) for x in releases)
                release_measured["entries_without_day"] += sum(not x.get("published_at") for x in releases)
                release_measured["collision_sources"] += bool(item.get("release_event_identity_collision"))
                release_measured["incomplete_window_sources"] += item.get("release_window_complete") is False
                counts = Counter(x.get("event_id") for x in releases if x.get("event_id"))
                release_measured["duplicated_event_id_count"] += sum(n > 1 for n in counts.values())
                release_measured["excess_duplicate_id_occurrences"] += sum(n - 1 for n in counts.values() if n > 1)
            elif category == "documentation":
                doc_measured["overview_only_sources"] += item.get("documentation_scope_status") == "overview_only"
                doc_measured["scoped_sources"] += item.get("documentation_scope_status") == "scoped_page"
                doc_measured["unprofiled_sources"] += item.get("documentation_profile_status") == "unprofiled"
                doc_measured["navigation_candidates_detected"] += item.get("documentation_nav_candidate_total", 0)
                doc_measured["navigation_candidates_omitted"] += item.get("documentation_nav_candidate_omitted", 0)
            all_source_rows.append({
                "source_id": sid, "category": category,
                "provider": source["provider"], "source_url": source["url"],
                "status": status, "http_status": http,
                "primary_error": item.get("error") or "",
                "request_chain_status": request_proof,
                "request_count_for_configured_url": len(first),
                "final_response_matched": final_match,
                "robots_requests_for_source_host": robots_by_host.get(
                    (urlsplit(source["url"]).hostname or "").lower(), 0
                ),
                "source_policy_status": item.get("source_policy_status") or "",
                "diagnostic_reasons": ";".join(item.get("diagnostic_reason_codes", [])),
                "risk_family": family,
                "risk_score": _source_risk_score(item, family),
                "pricing_observations": len(price_rows) if category == "pricing" else 0,
                "pricing_numeric_candidates": sum(x.get("price_state") == "numeric_candidate" for x in price_rows) if category == "pricing" else 0,
                "pricing_review_quotes": sum(x.get("review_quote_candidate") is True for x in price_rows) if category == "pricing" else 0,
                "pricing_comparable_candidates": sum(x.get("comparable_candidate") is True for x in price_rows) if category == "pricing" else 0,
                "pricing_relevant_tables_omitted": item.get("pricing_table_omitted_relevant", 0) if category == "pricing" else 0,
                "release_detected": item.get("release_event_count", 0) if category == "changelog" else 0,
                "release_retained": len(releases) if category == "changelog" else 0,
                "release_id_collision": bool(item.get("release_event_identity_collision")) if category == "changelog" else False,
                "release_window_complete": item.get("release_window_complete") if category == "changelog" else "",
                "documentation_scope": item.get("documentation_scope_status") if category == "documentation" else "",
                "documentation_nav_omitted": item.get("documentation_nav_candidate_omitted", 0) if category == "documentation" else 0,
                "source_hash_present": bool(item.get("content_sha256")),
                "external_publisher_accuracy_verified": False,
                "next_action": RISKS[family],
            })
        if recorded_stats["captured_sources"] != statuses["captured"]:
            raise ValueError("Zyte log captured count differs from source records")
        category_reports[category] = {
            "expected_source_ids": setup["count"], "reported_source_ids": len(items),
            "job_id": setup["job"], "status_counts": dict(sorted(statuses.items())),
            "http_200_source_items": http_counts["200"],
            "request_count": len(reqs),
            "request_http_status_counts": dict(sorted(request_statuses.items())),
            "source_request_trace_classification": dict(sorted(recorded.items())),
            "pricing_evidence": dict(sorted(price_measured.items())),
            "changelog_evidence": dict(sorted(release_measured.items())),
            "documentation_evidence": dict(sorted(doc_measured.items())),
            "archive_job_metadata_independently_authenticated": False,
            "publisher_facts_independently_verified": False,
        }
        log_receipts[category] = {
            "job_id": setup["job"], "finished_log_marker": True,
            "log_reported_coverage": recorded_stats,
            "start_log_matches_requested_category": True,
        }
    if len(emitted) != 460:
        raise ValueError("Not exactly 460 distinct configured source Items")
    result = {
        "schema_version": VERSION, "kind": "p21a_original_export_integrity_not_publisher_fact_truth",
        "baseline_date_utc": "2026-11-04",
        "source_manifest_sha256": MANIFEST_SHA,
        "source_registry_sha256": REGISTRY_SHA,
        "deployment_package_fingerprint": PACKAGE_SHA,
        "input_integrity": {
            "nine_original_export_sha256_pins_checked": files is not None,
            "raw_files": files or {},
            "dashboard_exports_not_immutable_zyte_job_archive": True,
            "original_publisher_html_in_export": False,
            "legally_permitted_private_source_html_retention_verified": False,
        },
        "operational_run_integrity": {
            "configured_source_count": 460,
            "accounted_source_count": len(emitted),
            "three_job_names": [BASELINES[c]["spider"] for c in BASELINES],
            "three_job_ids": [BASELINES[c]["job"] for c in BASELINES],
            "category_metrics": category_reports,
            "log_reconciliation": log_receipts,
            "sources_independently_policy_approved_for_bulk": 0,
            "source_accounting_complete": True,
            "complete_immutable_zyte_archives_authenticated": False,
        },
        "evidence_and_semantic_quality": {
            "accuracy_established": False,
            "qualifications_observed_not_verified": True,
            "source_triage_count": len(all_source_rows),
            "root_cause_source_clusters": {
                k: len(v) for k, v in sorted(risks.items())
            },
            "pricing": category_reports["pricing"]["pricing_evidence"],
            "changelog": category_reports["changelog"]["changelog_evidence"],
            "documentation": category_reports["documentation"]["documentation_evidence"],
            "advisor_fact_approvals": 0,
        },
        "new_zyte_jobs": 0, "network_requests_performed": 0,
        "source_registry_mutations": 0,
        "deployment_authorized": False, "approved_for_advisor": False,
    }
    # Freeze held-out source IDs using a private key, independently of
    # these items' parser errors; the key is NEVER emitted.
    holdout = _holdout(sources, holdout_key)
    blocked = {sid for ids in holdout["categories"].values() for sid in ids}
    prioritized = sorted(
        (x for x in all_source_rows if x["source_id"] not in blocked),
        key=lambda x: (-x["risk_score"], x["source_id"]),
    )
    for i, row in enumerate(prioritized, 1):
        row["rank"] = i
    for row in all_source_rows:
        if row["source_id"] in blocked:
            row["rank"] = ""  # avoid exposing held-out ranking
    result["review_queue"] = {
        "priority_ranked_development_count": len(prioritized),
        "blind_holdout_source_count": len(blocked),
        "selection_not_based_on_parser_success": True,
        "risk_score_is_heuristic_not_impact_proof": True,
    }
    result["report_sha256"] = _digest(result)
    clusters = {
        "schema_version": VERSION,
        "kind": "p21a_source_risk_clusters_for_manual_replay_only",
        "groups": {
            k: {"count": len(ids), "source_ids": sorted(ids),
                "next_action": RISKS[k]}
            for k, ids in sorted(risks.items())
        },
        "source_risk_not_verified_impact": True,
        "publisher_facts_verified": False,
        "network_requests_performed": 0,
    }
    return result, sorted(all_source_rows, key=lambda x: (
        x["rank"] == "", x["rank"] if x["rank"] else 99999,
    )), all_request_rows, clusters, holdout


def _csv_bytes(columns, rows):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            field: _csv_safe(row.get(field)) for field in columns
        })
    return buf.getvalue().encode("utf-8-sig")


def _csv_safe(value):
    data = "" if value is None else str(value)
    return "'" + data if data.lstrip().startswith(("=", "+", "-", "@")) else data


def write_private_audit(outputs, directory):
    """New-only private output, no secret or original publisher HTML copied."""
    report, rows, requests, clusters, holdout = outputs
    root = _private_new_directory(directory)
    try:
        def write(name, data):
            _write_private(
                root / name, (json.dumps(data, indent=2, ensure_ascii=False)
                             + "\n").encode("utf-8"),
            )
        write("baseline_metrics.json", report)
        write("risk_clusters.json", clusters)
        write("holdout_source_ids_PRIVATE.json", holdout)
        _write_private(root / "source_triage.csv", _csv_bytes(SOURCE_FIELDS, rows))
        _write_private(root / "request_outcomes.csv", _csv_bytes(REQUEST_FIELDS, requests))
        note = [
            "# P21A Nov 4 export integrity and unverified evidence freeze",
            "",
            "All nine input files are preserved in place, never rewritten or included in this output.",
            "Their exact SHA-256 and byte sizes are recorded in baseline_metrics.json.",
            "Source HTML was NOT provided; publisher fact accuracy remains unknown.",
            "Request rows include robotstxt probes and same-host redirects; they are",
            "NOT 1:1 with the 460 source-summary Items.",
            "The dashboard exports lack a separately authenticated original Zyte job archive.",
            "Source status 'captured' is NOT an approved pricing/date/docs fact.",
            "The source risk scores are transparent review priorities, not verified business value.",
            "PRIVATE holdout IDs are selected independently of results using an operator HMAC key.",
            "Never commit original exports, the holdout key or operator review results to Git.",
            "This tool performs zero publisher or Zyte requests and never approves AgentFuse facts.",
            "",
        ]
        _write_private(root / "README.md", "\n".join(note).encode("utf-8"))
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir", type=Path, required=True,
                   help="Existing private directory with nine exact Nov 4 JSON exports")
    p.add_argument("--out-dir", type=Path, required=True,
                   help="New private directory; no overwrite")
    args = p.parse_args()
    key = os.getenv("AGENTFUSE_P21A_HOLDOUT_KEY", "")
    if len(key.encode("utf-8")) < MIN_HOLDOUT_KEY_BYTES:
        p.error("AGENTFUSE_P21A_HOLDOUT_KEY >=32 bytes required (never saved)")
    data, receipts = _raw_exports(args.input_dir)
    outputs = audit_bundle(data, holdout_key=key, files=receipts)
    out = write_private_audit(outputs, args.out_dir)
    report = outputs[0]
    print(json.dumps({
        "private_baseline": str(out / "baseline_metrics.json"),
        "source_triage": str(out / "source_triage.csv"),
        "request_outcomes": str(out / "request_outcomes.csv"),
        "original_inputs_rewritten": False,
        "total_source_ids": report["operational_run_integrity"]["accounted_source_count"],
        "accuracy_verified": False, "new_zyte_jobs": 0,
        "advisor_fact_approvals": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
