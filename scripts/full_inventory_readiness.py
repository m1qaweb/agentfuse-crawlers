"""P20A: zero-network 460-source readiness census + three-category manual canaries.

This workbench DOES NOT grant permission to crawl all sources. It gives the
operator a concrete, pinned and policy-aware path from synthetic CI to real
archived Zyte evidence. No Zyte or publisher calls, schedules, production DB
writes, auto-approvals, changed source IDs, spiders or deployed crawler code.

Two explicitly registered nine-source waves (3 docs, 3 pricing, 3 changes)
cover 18 distinct first-party manifest provider labels. Each planned job
selects ONE exact source ID and repeats in two independently archived rounds.
Previously observed defects are triage priorities, NOT current vendor facts.
"""
import argparse
import csv
import io
import json
import shutil
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256, source_lifecycle,
)
from agentfuse_crawlers.sources import load_sources
from scripts.canary_rollout import (
    SPIDERS, build_canary_plan,
)
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)
from scripts.prepare_release_pilot import _mkdir
from scripts.replay_release_snapshots import _digest

VERSION = "1.0"
KIND = "p20a_full_inventory_human_preflight_not_crawl_permission"
EXPECTED = {"documentation": 194, "pricing": 177, "changelog": 89}
EXPECTED_TOTAL = 460
WAVE_SIZE = 9
# Deliberately curated in advance, across 18 product/provider labels. No
# auto substitution for access denial or disappointing evaluation results.
WAVES = (
    (
        ("kiro_docs", "historical_js_shell_documentation"),
        ("google_cloud_ai_docs", "historical_product_scope_migration"),
        ("anthropic_api_docs", "documentation_baseline_control"),
        ("gemini_api_pricing", "historical_large_pricing_table"),
        ("aws_bedrock_pricing", "historical_large_pricing_table"),
        ("oracle_oci_generative_ai_pricing", "historical_large_pricing_table"),
        ("openai_api_changelog", "historical_release_card_conflation"),
        ("render_changelog", "historical_latest_date_anomaly"),
        ("xai_changelog", "historical_ambiguous_publication_year"),
    ),
    (
        ("cursor_docs", "documentation_product_scope"),
        ("supabase_docs", "documentation_scope_and_child_pages"),
        ("cloudflare_workers_ai_docs", "documentation_scope_and_product"),
        ("deepseek_pricing", "model_and_unit_price_completeness"),
        ("mistral_pricing", "pricing_plan_model_and_tier"),
        ("together_ai_pricing", "pricing_tier_region_and_units"),
        ("claude_code_changelog", "historical_oversized_changelog_sections"),
        ("gemini_cli_changelog", "versioned_release_changelog_ownership"),
        ("github_copilot_changelog", "mixed_product_changelog_scope"),
    ),
)
CSV_SOURCE_FIELDS = (
    "source_id", "provider", "category", "source_url",
    "source_lifecycle_state", "publisher_policy_status",
    "validation_lifecycle_allows_request", "monitor_collection_approved",
    "risk_priority", "next_manual_action",
)
CSV_JOB_FIELDS = (
    "wave", "round", "source_id", "category", "spider", "source_url",
    "cohort", "spider_source_ids", "collection_mode",
    "expected_manifest_sha256", "expected_selection_ids_sha256",
    "expected_source_registry_sha256", "execution_status",
)


def _csv_bytes(columns, rows):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            k: _safe_csv(row.get(k, "")) for k in columns
        })
    return buf.getvalue().encode("utf-8-sig")


def build_preflight():
    """Return a full 460-source census and frozen manual 18-source study."""
    sources = load_sources()
    if len(sources) != EXPECTED_TOTAL:
        raise ValueError("Full inventory requires unchanged 460-source manifest")
    if len({s["id"] for s in sources}) != len(sources):
        raise ValueError("Duplicate source ID in publisher manifest")
    count = Counter(s["category"] for s in sources)
    if dict(count) != EXPECTED:
        raise ValueError("Unexpected 194 docs / 177 pricing / 89 changelog mix")
    known = {s["id"]: s for s in sources}
    risky = {sid: reason for wave in WAVES for sid, reason in wave}
    selection = list(risky)
    if len(selection) != 2 * WAVE_SIZE or len(set(selection)) != len(selection):
        raise ValueError("Frozen cross-category wave IDs duplicate or changed")
    if set(selection) - set(known):
        raise ValueError("Frozen canary source IDs absent from current manifest")
    states = Counter()
    policies = Counter()
    category_approvals = Counter()
    monitor_approved, validation_technical, blocked = [], [], []
    all_source_rows = []
    for source in sources:
        sid = source["id"]
        lifecycle = source_lifecycle(source)
        validation, validation_reason = collection_decision(
            source, mode="validation",
        )
        monitoring, monitoring_reason = collection_decision(
            source, mode="monitor",
        )
        states[lifecycle["state"]] += 1
        policies[lifecycle["policy_status"]] += 1
        if monitoring:
            monitor_approved.append(sid)
            category_approvals[source["category"]] += 1
        if validation:
            validation_technical.append(sid)
        else:
            blocked.append({
                "source_id": sid,
                "category": source["category"],
                "source_url": source["url"],
                "lifecycle_reason": validation_reason,
            })
        next_action = (
            lifecycle["next_action"] if not validation
            else "Review ownership, terms, robots, scope and private retention per exact URL."
            if not monitoring else
            "Review two archival rounds and advisor-fact evidence separately."
        )
        all_source_rows.append({
            "source_id": sid,
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "source_lifecycle_state": lifecycle["state"],
            "publisher_policy_status": lifecycle["policy_status"],
            "validation_lifecycle_allows_request": validation,
            "monitor_collection_approved": monitoring,
            "risk_priority": risky.get(sid, "unreviewed_official_source"),
            "next_manual_action": next_action,
        })
    waves = []
    for i, wave in enumerate(WAVES, 1):
        ids = [sid for sid, _ in wave]
        src = [known[sid] for sid in ids]
        if (len(ids) != WAVE_SIZE
                or dict(Counter(s["category"] for s in src)) != {
                    "documentation": 3, "pricing": 3, "changelog": 3
                }
                or len({s["provider"] for s in src}) != len(src)):
            raise ValueError("Cross-category wave must include 3 distinct source labels per category")
        for source in src:
            if not collection_decision(source, "validation")[0]:
                raise ValueError(
                    "Previously selected source now policy-blocked: " + source["id"]
                )
        plan = build_canary_plan(ids)
        if (plan.get("execution_permitted") is not False
                or plan.get("approved_for_advisor") is not False
                or plan.get("total_expected_jobs") != 18
                or plan.get("source_ids") != ids):
            raise ValueError("Underlying manual canary planner contract changed")
        for job in plan["jobs"]:
            args = job["spider_args"]
            if (job["execution_status"] !=
                    "not_scheduled_requires_operator_authorization"
                    or args.get("cohort") != "all"
                    or args.get("source_ids") != job["source_id"]
                    or args.get("collection_mode") != "validation"
                    or "confirm_full_inventory" in args
                    or job["zyte_job_id"] is not None
                    or job["spider"] != SPIDERS[job["category"]]):
                raise ValueError("Canary job widened scope or impersonated execution")
        waves.append({
            "wave_id": "wave_" + str(i).zfill(2),
            "review_focus": [
                {"source_id": sid, "historical_or_hypothetical_risk": reason}
                for sid, reason in wave
            ],
            "canary_plan": plan,
            "manual_jobs": plan["total_expected_jobs"],
            "must_check_publisher_policy_for_every_source": True,
            "network_requests_performed": 0,
        })
    all_selected = [s for wave in waves for s in wave["canary_plan"]["sources"]]
    if (len(all_selected) != 18
            or len({x["source_id"] for x in all_selected}) != 18
            or len({x["provider"] for x in all_selected}) != 18):
        raise ValueError("Across-wave provider/source overlap undermines holdout")
    ready = {
        "source_inventory_exact_accounting": len(all_source_rows) == EXPECTED_TOTAL,
        "all_source_publisher_policy_review": False,
        # This is not an inference that real work was never done: no
        # verifiable source-specific evidence was PROVIDED to this command.
        "independent_policy_evidence_supplied_to_this_command": False,
        "current_registry_allows_unattended_all_sources":
            len(monitor_approved) == EXPECTED_TOTAL,
        "archived_two_round_real_zyte_canaries_supplied": False,
        "real_200_plus_archived_pricing_gold_verified": False,
        "real_100_plus_archived_date_gold_verified": False,
        "blind_dual_review_publisher_gold_verified": False,
        "full_original_changelog_html_census_verified": False,
        "documentation_product_scope_human_verified": False,
        "human_crawl_authorization_given": False,
    }
    # Separate permission to perform one supervised DIAGNOSTIC from
    # permission to trust its numbers for production monitoring/advice.
    # Human-gold thresholds are deliberately NOT prerequisites just to
    # COLLECT a finite, nonpublishing diagnostic baseline: those numbers
    # can be derived from the diagnostic's immutable real evidence.
    diagnostic_blockers = []
    if not ready["all_source_publisher_policy_review"]:
        diagnostic_blockers.append(
            "Per-URL human access/terms/robots/retention reviews for all attempted publishers not supplied"
        )
    if not ready["archived_two_round_real_zyte_canaries_supplied"]:
        diagnostic_blockers.append(
            "Two independently archived, source-pinned live canary rounds across docs/pricing/changelogs not supplied"
        )
    diagnostic_blockers.append(
        "Exact package revision in Zyte, proposed run budget, and operator's one-shot approval not verified here"
    )
    monitoring_blockers = list(diagnostic_blockers)
    if not ready["real_200_plus_archived_pricing_gold_verified"]:
        monitoring_blockers.append(
            "200+ distinct actual first-party pricing amount+model+unit+region cases not reviewed"
        )
    if not ready["real_100_plus_archived_date_gold_verified"]:
        monitoring_blockers.append(
            "100+ real publisher-owned release-date cases not reviewed"
        )
    if not ready["blind_dual_review_publisher_gold_verified"]:
        monitoring_blockers.append(
            "Two independent real-evidence review rounds have not been reconciled"
        )
    if not ready["full_original_changelog_html_census_verified"]:
        monitoring_blockers.append(
            "15-25-provider original-HTML whole-page changelog census not supplied"
        )
    if not ready["documentation_product_scope_human_verified"]:
        monitoring_blockers.append(
            "Documentation child-page scope and product identity not independently reviewed"
        )
    if len(monitor_approved) != EXPECTED_TOTAL:
        monitoring_blockers.append(
            "0/460 current unattended-monitor approvals" if not monitor_approved
            else "Not every monitored URL is approved by the source registry"
        )
    blockers = sorted(set(diagnostic_blockers + monitoring_blockers))
    outcome = {
        "schema_version": VERSION,
        "kind": KIND,
        "source_manifest_sha256": manifest_sha256(sources),
        "source_registry_sha256": registry_revision_sha256(),
        "configured_sources": len(sources),
        "category_counts": dict(sorted(count.items())),
        "lifecycle_counts": dict(sorted(states.items())),
        "policy_status_counts": dict(sorted(policies.items())),
        "technically_validation_allowed_by_local_guard_count":
            len(validation_technical),
        "individually_reviewed_publisher_permission_count_verified_here": 0,
        "unattended_collection_approved_count": len(monitor_approved),
        "unattended_collection_approved_by_category":
            dict(sorted(category_approvals.items())),
        "locally_blocked_sources": blocked,
        "risk_informed_canary_waves": [
            {
                "wave_id": w["wave_id"],
                "source_ids": w["canary_plan"]["source_ids"],
                "manual_one_source_jobs_two_rounds": w["manual_jobs"],
                "provider_label_count": w["canary_plan"]["source_count"],
                "risks": w["review_focus"],
                "publisher_policy_review_required": True,
                "scheduled": False,
            } for w in waves
        ],
        "total_planned_manual_canary_jobs": sum(w["manual_jobs"] for w in waves),
        "full_inventory_one_time_diagnostic_crawl": "NO_GO_PENDING_EVIDENCE",
        "full_inventory_automatic_monitoring": "NO_GO_PENDING_PER_SOURCE_APPROVAL",
        "diagnostic_collection_requires_completed_gold_benchmarks": False,
        "trusted_monitoring_requires_real_human_gold": True,
        "source_ids_held_and_not_fetched_under_current_policy": [
            b["source_id"] for b in blocked
        ],
        "real_accuracy_measured_by_this_preflight": False,
        "preflight_checks": ready,
        "diagnostic_run_blockers": diagnostic_blockers,
        "trusted_monitoring_blockers": monitoring_blockers,
        "blockers": blockers,
        "suggested_operator_sequence": [
            "Review policy/ownership and product for all Wave 1 sources; preserve blocked source IDs.",
            "Run two separate source-pinned, manually approved Zyte canary rounds; archive Items, Requests, Logs.",
            "Inspect real docs scope, pricing units, release date ownership and deployment fingerprint.",
            "Run Wave 2's preselected 9-source canaries after its own policy review; do not resample denials.",
            "Review each publisher URL that the broad diagnostic would actually request, while holding prohibited URLs.",
            "ONLY AFTER clean safe canaries, verified deployment and explicit budget/operator approval, run one supervised 460-ID diagnostic with no data publishing or schedules.",
            "Use those authentic full-run archives and P19A6 captured original HTML to build independently reviewed pricing, release and documentation gold.",
            "Pass strict P08/P15B quality gates and per-source Git-reviewed monitoring permissions before any trusted recurring full monitoring.",
        ],
        "published_release_facts_independently_verified": False,
        "advisor_fact_approvals": 0,
        "new_source_permissions": 0,
        "new_zyte_jobs": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }
    outcome["report_sha256"] = _digest(outcome)
    return outcome, all_source_rows, waves


def write_preflight(report, source_rows, waves, out_dir):
    """New-only owner-private immutable review artifacts, no side effects."""
    root = _private_new_directory(out_dir)
    try:
        _write_private(root / "full_inventory_readiness.json", (
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8"))
        _write_private(
            root / "all_460_source_review_queue.csv",
            _csv_bytes(CSV_SOURCE_FIELDS, source_rows),
        )
        for wave in waves:
            folder = _mkdir(root, wave["wave_id"])
            _write_private(folder / "manual_canary_plan.json", (
                json.dumps(wave["canary_plan"], indent=2, ensure_ascii=False) +
                "\n"
            ).encode("utf-8"))
            rows = []
            for job in wave["canary_plan"]["jobs"]:
                args = job["spider_args"]
                rows.append({
                    "wave": wave["wave_id"],
                    "round": job["round"],
                    "source_id": job["source_id"],
                    "category": job["category"],
                    "spider": job["spider"],
                    "source_url": job["source_url"],
                    "cohort": args["cohort"],
                    "spider_source_ids": args["source_ids"],
                    "collection_mode": args["collection_mode"],
                    "expected_manifest_sha256": args["expected_manifest_sha256"],
                    "expected_selection_ids_sha256":
                        args["expected_selection_ids_sha256"],
                    "expected_source_registry_sha256":
                        args["expected_source_registry_sha256"],
                    "execution_status": job["execution_status"],
                })
            _write_private(
                folder / "manual_canary_job_args.csv",
                _csv_bytes(CSV_JOB_FIELDS, rows),
            )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, required=True,
        help="NEW private folder: no requests and no permission changes",
    )
    args = parser.parse_args()
    report, rows, waves = build_preflight()
    result = write_preflight(report, rows, waves, args.out_dir)
    print(json.dumps({
        "report": str(result / "full_inventory_readiness.json"),
        "source_review_queue": str(result / "all_460_source_review_queue.csv"),
        "full_inventory_diagnostic": report[
            "full_inventory_one_time_diagnostic_crawl"
        ],
        "unattended_monitoring": report["full_inventory_automatic_monitoring"],
        "preplanned_cross_category_sources": 18,
        "preplanned_live_manual_canary_jobs": report[
            "total_planned_manual_canary_jobs"
        ],
        "publisher_policy_review_complete": False,
        "new_zyte_jobs": 0,
        "network_requests_performed": 0,
        "advisor_fact_approvals": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
