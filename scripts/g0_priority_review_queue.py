"""G0: deterministic, non-authorizing source priority and human review queue.

Reuses P23A's current exact-manifest/readiness audit; this module does not
fetch publishers, contact Zyte, modify review registries, or create job specs.
The priorities below are PRODUCT HEURISTICS, not publisher rights, demonstrated
HTML extractability, observed accuracy, or a recommendation to run 300 GETs.
"""

import argparse
import csv
import io
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.validation_access import digest
from scripts.full_crawl_readiness import build_readiness
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)

SCHEMA = "1.0"
KIND = "g0_ranked_source_review_queue_NOT_CRAWL_AUTHORIZATION"
CATEGORY_QUOTAS = {
    "documentation": 120,
    "pricing": 120,
    "changelog": 60,
}
# Business-value heuristics for initial review triage only. Exact names must
# exist in the pinned manifest; membership does not assert page quality.
CORE_PROVIDERS = frozenset({
    "OpenAI", "Anthropic", "Google Gemini", "DeepSeek", "Mistral",
    "xAI", "Perplexity", "Together AI", "Fireworks AI",
    "Cloudflare Workers AI", "AWS Bedrock", "OpenRouter", "GroqCloud",
    "Vercel AI Gateway", "Supabase", "Cursor", "GitHub Copilot",
    "Hugging Face", "Pinecone", "Weaviate", "Qdrant", "Voyage AI",
    "Tavily", "Exa", "Render", "Helicone", "LiteLLM",
})
# Supplemental *operational review candidates*, deliberately separate from
# P20A's original 18 sources/36 planned source-rounds. Distinct hostnames
# expose cross-site failure modes. None is pre-approved for a live request.
SUPPLEMENTAL = {
    "documentation": (
        "github_copilot_docs", "openai_api_docs",
        "vercel_ai_gateway_docs", "deepseek_docs",
    ),
    "pricing": (
        "anthropic_api_pricing", "xai_pricing",
        "cloudflare_workers_ai_pricing", "fireworks_ai_pricing",
    ),
    "changelog": (
        "cursor_changelog", "supabase_changelog",
        "mistral_changelog", "groqcloud_changelog",
    ),
}
COLUMNS = (
    "provisional_rank", "top_300_candidate_NOT_APPROVED",
    "supplemental_canary_review_candidate_NOT_APPROVED",
    "original_frozen_canary_source", "source_id", "provider", "category",
    "source_url", "hostname", "robots_candidate_url_NOT_VERIFIED",
    "business_priority_heuristic", "selection_reason_NOT_EVIDENCE",
    "technical_validation_eligible_NOT_PERMISSION", "lifecycle_state",
    "access_review_record", "access_review_expired",
    "single_scope_current_NOT_EXTERNAL_PERMISSION",
    "bulk_scope_current_NOT_EXTERNAL_PERMISSION", "source_disposition",
    "human_publisher_owner_evidence", "human_terms_url",
    "human_robots_user_agent_path_review",
    "human_commercial_use_and_retention_review",
    "human_exact_url_decision_NOT_ATTESTED",
)
HOST_COLUMNS = (
    "first_provisional_rank", "hostname", "top_300_candidate_count",
    "candidate_source_ids", "candidate_categories",
    "robots_candidate_url_NOT_VERIFIED", "exact_source_urls",
    "host_research_NOT_PERMISSION",
)


def _pilot_ids():
    ids = [sid for names in SUPPLEMENTAL.values() for sid in names]
    if len(ids) != 12 or len(set(ids)) != 12:
        raise ValueError("Supplemental 12-source review candidate list drift")
    return ids


def _host(source_url):
    parts = urlsplit(source_url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("A pinned publisher URL is not HTTPS")
    return parts.hostname


def _sort_key(row):
    # Prefer sources eligible for *technical* validation, then deliberately
    # chosen pilot candidates and configured core-provider sources. A positive
    # local review record must NOT serve as a substitute for this value ranking.
    return (
        not row["technical_validation_eligible"],
        row["source_id"] not in _pilot_ids(),
        row["provider"] not in CORE_PROVIDERS,
        row["source_id"],
    )


def build_queue(*, readiness=None, dispositions=None):
    """Return a non-executable report plus 460 / 300 / 12 / grouped-host rows."""
    if (readiness is None) != (dispositions is None):
        raise ValueError("Supply both audited P23A inputs or neither")
    if readiness is None:
        readiness, dispositions = build_readiness()
    rows = list(dispositions)
    ids = [r["source_id"] for r in rows]
    if (readiness.get("status") != "NO_GO"
            or readiness.get("full_run_approved") is not False
            or readiness.get("actual_publisher_requests_authorized_by_this_report",
                             readiness.get("counts", {}).get(
                                 "actual_publisher_requests_authorized_by_this_report")) not in (None, 0)
            or len(rows) != 460 or len(set(ids)) != 460
            or ids != readiness.get("all_source_ids_in_manifest_order")
            or len(readiness.get("frozen_canary_source_ids", [])) != 18):
        raise ValueError("Only an exact P23A 460-ID NO-GO snapshot is accepted")
    frozen = set(readiness["frozen_canary_source_ids"])
    pilot = set(_pilot_ids())
    if frozen & pilot or not pilot <= set(ids):
        raise ValueError("Supplemental sources must not replace frozen canaries")
    by_id = {r["source_id"]: r for r in rows}
    hosts = [_host(by_id[sid]["source_url"]) for sid in _pilot_ids()]
    if len(set(hosts)) != 12:
        raise ValueError("Supplemental canary host diversity changed")
    if any(by_id[sid]["category"] != category
           for category, source_ids in SUPPLEMENTAL.items()
           for sid in source_ids):
        raise ValueError("Supplemental canary categories changed")

    selected = set()
    for category, quota in CATEGORY_QUOTAS.items():
        eligible_rows = sorted(
            (r for r in rows if r["category"] == category),
            key=_sort_key,
        )
        if len(eligible_rows) < quota:
            raise ValueError("Category quota exceeds frozen source inventory")
        selected.update(r["source_id"] for r in eligible_rows[:quota])
    if len(selected) != 300 or not pilot <= selected:
        raise ValueError("Ranked 300 candidate accounting failed")

    ordered = (sorted((r for r in rows if r["source_id"] in selected),
                      key=_sort_key)
               + sorted((r for r in rows if r["source_id"] not in selected),
                        key=_sort_key))
    ranked = []
    for rank, source in enumerate(ordered, start=1):
        sid = source["source_id"]
        is_pilot = sid in pilot
        core = source["provider"] in CORE_PROVIDERS
        if is_pilot:
            why = "supplemental cross-category, distinct-host canary REVIEW candidate"
        elif core:
            why = "curated AI-stack provider value heuristic; human triage required"
        else:
            why = "category coverage and source-ID ordering heuristic; human triage required"
        hostname = _host(source["source_url"])
        ranked.append({
            "provisional_rank": rank,
            "top_300_candidate_NOT_APPROVED": sid in selected,
            "supplemental_canary_review_candidate_NOT_APPROVED": is_pilot,
            "original_frozen_canary_source": sid in frozen,
            "source_id": sid,
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["source_url"],
            "hostname": hostname,
            "robots_candidate_url_NOT_VERIFIED": f"https://{hostname}/robots.txt",
            "business_priority_heuristic": (
                "supplemental_pilot" if is_pilot else
                "core_AI_stack" if core else "general_inventory"
            ),
            "selection_reason_NOT_EVIDENCE": why,
            "technical_validation_eligible_NOT_PERMISSION":
                source["technical_validation_eligible"],
            "lifecycle_state": source["lifecycle_state"],
            "access_review_record": source["access_review"],
            "access_review_expired": source["access_review_expired"],
            "single_scope_current_NOT_EXTERNAL_PERMISSION":
                source["single_scope_current"],
            "bulk_scope_current_NOT_EXTERNAL_PERMISSION":
                source["bulk_scope_current"],
            "source_disposition": source["source_disposition"],
            "human_publisher_owner_evidence": "",
            "human_terms_url": "",
            "human_robots_user_agent_path_review": "",
            "human_commercial_use_and_retention_review": "",
            "human_exact_url_decision_NOT_ATTESTED": "PENDING_INDEPENDENT_REVIEW",
        })

    top = ranked[:300]
    shortlist = [r for r in ranked if r[
        "supplemental_canary_review_candidate_NOT_APPROVED"]]
    if (len(shortlist) != 12
            or Counter(r["category"] for r in shortlist) !=
            Counter({category: 4 for category in CATEGORY_QUOTAS})
            or set(r["source_id"] for r in top) != selected):
        raise ValueError("Shortlist or top-300 coverage drift")

    hosts_by_name = defaultdict(list)
    for r in top:
        hosts_by_name[r["hostname"]].append(r)
    host_rows = []
    for hostname, members in hosts_by_name.items():
        host_rows.append({
            "first_provisional_rank": min(x["provisional_rank"] for x in members),
            "hostname": hostname,
            "top_300_candidate_count": len(members),
            "candidate_source_ids": " | ".join(x["source_id"] for x in members),
            "candidate_categories": " | ".join(
                f"{c}:{n}" for c, n in sorted(Counter(
                    x["category"] for x in members).items())
            ),
            "robots_candidate_url_NOT_VERIFIED": f"https://{hostname}/robots.txt",
            "exact_source_urls": " | ".join(x["source_url"] for x in members),
            "host_research_NOT_PERMISSION": "PENDING; decide every exact URL separately",
        })
    host_rows.sort(key=lambda r: (r["first_provisional_rank"], r["hostname"]))
    report = {
        "schema_version": SCHEMA,
        "kind": KIND,
        "status": "NO_GO_NOT_AUTHORIZED",
        "ranking_is_authorization": False,
        "ranking_is_empirical_quality_measurement": False,
        "publisher_permissions_added": 0,
        "publisher_gets_performed": 0,
        "zyte_jobs_started": 0,
        "bulk_plans_created": 0,
        "original_frozen_study_preserved": True,
        "original_frozen_canary_source_ids": readiness["frozen_canary_source_ids"],
        "original_frozen_canary_round_denominator": 36,
        "supplemental_canary_source_ids": _pilot_ids(),
        "supplemental_canary_distinct_hostnames": len(set(hosts)),
        "top_300_category_quota_NOT_PERMISSION": CATEGORY_QUOTAS,
        "top_300_category_counts": dict(Counter(r["category"] for r in top)),
        "total_configured_sources": len(ranked),
        "top_300_provisional_source_count": len(top),
        "distinct_hosts_all_460": len({_host(r["source_url"]) for r in ranked}),
        "distinct_hosts_top_300": len(host_rows),
        "source_manifest_sha256": readiness["source_manifest_sha256"],
        "p23a_readiness_report_sha256": readiness["report_sha256"],
        "recorded_access_review_states": dict(sorted(Counter(
            r["access_review_record"] for r in ranked).items())),
        "ranking_basis": (
            "Explicit 12-source supplemental review candidate list; curated "
            "AI-stack provider labels; category representation quotas of "
            "120 documentation, 120 pricing, 60 changelog; stable source IDs. "
            "No historical Item status, robots conclusion, license, page "
            "quality, price or accuracy is inferred by this ranking."
        ),
        "human_next_action": (
            "Review exact source/host ownership, actual robots, applicable terms, "
            "commercial use, private retention, redirects and rate limits. "
            "Keep decisions and evidence private until an independently substantiated "
            "P23B review is explicitly Git-reviewed. No Zyte job is authorized."
        ),
    }
    report["report_sha256"] = digest(report)
    return report, ranked, top, shortlist, host_rows


def _csv_bytes(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _safe_csv(row.get(k, "")) for k in fields})
    return stream.getvalue().encode("utf-8-sig")


def write_queue(report, ranked, top, shortlist, host_rows, out_dir):
    if (report.get("status") != "NO_GO_NOT_AUTHORIZED"
            or report.get("ranking_is_authorization") is not False
            or report.get("publisher_gets_performed") != 0
            or len(ranked) != 460 or len(top) != 300 or len(shortlist) != 12
            or report.get("report_sha256") != digest({
                k: v for k, v in report.items() if k != "report_sha256"
            })):
        raise ValueError("Cannot export incorrect or authorizing review materials")
    root = _private_new_directory(out_dir)
    try:
        files = {
            "g0_source_priority_summary_NO_GO.json":
                (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            "source_priorities_all460_NOT_APPROVED.csv":
                _csv_bytes(COLUMNS, ranked),
            "priority_top300_NOT_APPROVED.csv":
                _csv_bytes(COLUMNS, top),
            "supplemental_canary12_REVIEW_ONLY.csv":
                _csv_bytes(COLUMNS, shortlist),
            "host_review_groups_top300_NOT_PERMISSIONS.csv":
                _csv_bytes(HOST_COLUMNS, host_rows),
        }
        for filename, content in files.items():
            _write_private(root / filename, content)
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build_queue()
    root = write_queue(*result, args.out_dir)
    report = result[0]
    print(json.dumps({
        "status": report["status"],
        "inventory": report["total_configured_sources"],
        "provisional_top300": report["top_300_provisional_source_count"],
        "supplemental_canary_candidates": len(report["supplemental_canary_source_ids"]),
        "distinct_hostnames": report["distinct_hosts_all_460"],
        "publisher_gets": 0,
        "zyte_jobs": 0,
        "out_dir": str(root),
    }, indent=2))


if __name__ == "__main__":
    main()
