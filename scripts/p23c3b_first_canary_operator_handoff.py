"""P23C3B: first real-canary human handoff, zero publisher/Zyte network.

This one-off packet selects EXACT frozen P20A wave-1 IDs (one per category)
and reuses the production P23B single-source access decision and existing
P20A exact-job planner. It is NOT an access approval, a deploy attestation,
a Zyte job scheduler, a live HTML capture, or a product-quality evaluation.

DO NOT use synthetic test fixtures as actual publisher-access reviews.
"""
import argparse
import csv
import io
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.validation_access import (
    load_access_registry, validate_access_registry,
    validation_access_decision, validation_access_revision_sha256, digest,
)
from scripts.accession_cross_category_html import frozen_plan
from scripts.canary_rollout import build_canary_plan
from scripts.plan_documentation_children import (
    _private_new_directory, _safe_csv, _write_private,
)

VERSION = "1.0"
KIND = "p23c3b_exact_first_real_canary_operator_handoff_NOT_AUTHORIZED"
# Pre-registered wave-1 first-per-category sources: do not silently swap
# a source for a more convenient or apparently friendly publisher.
PILOT_SOURCE_IDS = (
    "kiro_docs", "gemini_api_pricing", "openai_api_changelog",
)
CATEGORIES = ("documentation", "pricing", "changelog")
WORKLIST_FIELDS = (
    "source_id", "category", "publisher", "source_url", "robots_candidate_url",
    "publisher_access_registry_status", "local_single_scope_record_present",
    "human_owner_verification", "human_robots_review", "human_terms_review",
    "human_private_retention_review", "human_operator_decision",
    "next_operator_action",
)
JOB_FIELDS = (
    "round", "source_id", "category", "spider", "source_url",
    "cohort", "source_ids", "collection_mode",
    "expected_manifest_sha256", "expected_selection_ids_sha256",
    "expected_source_registry_sha256", "source_policy_gate",
    "operator_canary_authorization", "zyte_job_id",
)

REVIEW_CHECKS = (
    "Human reviewer independently confirms the exact manifest URL's current owner and product",
    "Human reviewer checks actual first-party robots.txt for the crawler user agent and intended path",
    "Human reviewer identifies applicable public-site/crawler terms, not only API usage terms",
    "Human reviewer confirms private HTML retention, attribution and legal collection rights",
    "Human reviewer records actual evidence and source-scoped single_validation decision in reviewed registry",
    "Git review and deploy actual revised package, then verify Zyte installed package fingerprint",
    "Operator explicitly approves per-job budget and manually starts one exact source with job units 1",
    "Review Requests/Logs/Items and original publisher HTML; record two DISTINCT real rounds",
    "Never bypass 403/429/captcha, never replace a denied frozen source",
)


def _aware(now):
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise ValueError("Operator readiness clock must be timezone aware")
    return clock.astimezone(timezone.utc)


def _pilot_sources(plan, sources):
    if plan["selected_source_count"] != 18 or plan[
            "source_round_denominator"] != 36:
        raise ValueError("Original frozen 18-source / 36-round canary changed")
    known = {s["id"]: s for s in sources}
    rows = [r for r in plan["sources"] if r["source_id"] in PILOT_SOURCE_IDS]
    if (len(rows) != 3 or tuple(r["source_id"] for r in rows)
            != PILOT_SOURCE_IDS or any(r["wave"] != 1 for r in rows)
            or tuple(r["category"] for r in rows) != CATEGORIES
            or any(known[r["source_id"]]["url"] != r["source_url"]
                   for r in rows)):
        raise ValueError("Exact first-wave three-category source selection changed")
    return [known[sid] for sid in PILOT_SOURCE_IDS]


def build_handoff(*, access_registry=None, now=None):
    clock = _aware(now)
    frozen = frozen_plan()
    manifest = load_sources()
    if len(manifest) != 460:
        raise ValueError("Original source manifest changed")
    selected = _pilot_sources(frozen, manifest)
    # The actual deployed policy file is the only local review input.
    access = load_access_registry() if access_registry is None else access_registry
    validate_access_registry(access, now=clock)
    plan = build_canary_plan(list(PILOT_SOURCE_IDS))
    if plan["total_expected_jobs"] != 6 or plan["execution_permitted"]:
        raise ValueError("Bounded manual two-round canary contract changed")
    worklist, jobs, policy_counts = [], [], Counter()
    allowed_by_local_registry = set()
    for source in selected:
        sid = source["id"]
        reviewed, reason = validation_access_decision(
            source, scope="single_validation", registry=access, now=clock,
        )
        policy_counts[reason] += 1
        if reviewed:
            allowed_by_local_registry.add(sid)
        host = urlsplit(source["url"]).hostname
        worklist.append({
            "source_id": sid,
            "category": source["category"],
            "publisher": source["provider"],
            "source_url": source["url"],
            "robots_candidate_url": "https://" + host + "/robots.txt",
            # Candidate URL is NOT proof that robots exists or permits this crawl.
            "publisher_access_registry_status": reason,
            "local_single_scope_record_present": reviewed,
            "human_owner_verification": "NOT_ATTESTED_BY_THIS_PACKET",
            "human_robots_review": "NOT_ATTESTED_BY_THIS_PACKET",
            "human_terms_review": "NOT_ATTESTED_BY_THIS_PACKET",
            "human_private_retention_review": "NOT_ATTESTED_BY_THIS_PACKET",
            "human_operator_decision": "PENDING_INDEPENDENT_HUMAN_REVIEW",
            "next_operator_action": (
                "Verify real terms/robots/rights and Git-review exact source access"
                if not reviewed else
                "Independently verify publisher permission, Zyte deployment and operator budget"
            ),
        })
    for job in plan["jobs"]:
        if job["source_id"] not in PILOT_SOURCE_IDS or job["round"] not in (1, 2):
            raise ValueError("Canary planner emitted out-of-scope source or round")
        args = job["spider_args"]
        if (set(args) != {
                "cohort", "source_ids", "collection_mode",
                "expected_manifest_sha256", "expected_selection_ids_sha256",
                "expected_source_registry_sha256",
            } or args["source_ids"] != job["source_id"]
                or args["collection_mode"] != "validation"
                or args["cohort"] != "all"):
            raise ValueError("Canary job args could broaden publisher scope")
        jobs.append({
            "round": job["round"],
            "source_id": job["source_id"],
            "category": job["category"],
            "spider": job["spider"],
            "source_url": job["source_url"],
            "spider_args": args,
            "source_policy_gate": (
                "local_p23b_attestation_NOT_EXTERNAL_PERMISSION"
                if job["source_id"] in allowed_by_local_registry
                else "HELD_BY_P23B_SOURCE_POLICY"
            ),
            "operator_canary_authorization": "NOT_AUTHORIZED_BY_PACKET",
            "zyte_job_id": None,
            "advisor_approved": False,
        })
    if len(worklist) != 3 or len(jobs) != 6 or dict(
            Counter(s["category"] for s in selected)
    ) != {c: 1 for c in CATEGORIES}:
        raise ValueError("Exact 3-source / 6-round first pilot accounting failed")
    result = {
        "schema_version": VERSION,
        "kind": KIND,
        "status": "NO_GO_PENDING_REAL_SOURCE_REVIEW_AND_OPERATOR",
        "execution_permitted": False,
        "publisher_permission_independently_authenticated": False,
        "remote_zyte_deployment_independently_verified": False,
        "operator_cost_budget_approved": False,
        "canary_jobs_started": 0,
        "publisher_network_requests_performed": 0,
        "source_access_registry_edited": False,
        "monitoring_enabled": False,
        "approved_for_advisor": False,
        "original_frozen_source_count": 18,
        "original_frozen_source_round_denominator": 36,
        "original_plan_sha256": frozen["plan_sha256"],
        "source_manifest_sha256": manifest_sha256(manifest),
        "source_lifecycle_registry_sha256": registry_revision_sha256(),
        "installed_source_access_registry_sha256": validation_access_revision_sha256(access),
        "local_package_sha256_NOT_REMOTE_PROOF": package_fingerprint(),
        "initial_pilot_source_ids": list(PILOT_SOURCE_IDS),
        "initial_pilot_sources": 3,
        "initial_pilot_manual_job_specs": 6,
        "local_reviewed_single_validation_sources_NOT_PERMISSION": len(
            allowed_by_local_registry
        ),
        "source_policy_status_counts": dict(sorted(policy_counts.items())),
        "sources": worklist,
        "jobs": jobs,
        "required_human_checks": list(REVIEW_CHECKS),
        "next_action": (
            "Independent publisher rights/robots/terms/retention review. "
            "Do not launch jobs without genuine Git-reviewed source policies, "
            "verified Zyte deploy and explicit operator approval."
        ),
    }
    result["report_sha256"] = digest(result)
    return result


def _csv_bytes(fields, rows):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            name: _safe_csv(row.get(name, "")) for name in fields
        })
    return buf.getvalue().encode("utf-8-sig")


def write_handoff(report, out_dir):
    if (report.get("kind") != KIND
            or report.get("execution_permitted") is not False
            or report.get("status") != "NO_GO_PENDING_REAL_SOURCE_REVIEW_AND_OPERATOR"
            or report.get("initial_pilot_sources") != 3
            or report.get("initial_pilot_manual_job_specs") != 6
            or report.get("report_sha256") != digest({
                k: v for k, v in report.items() if k != "report_sha256"
            })):
        raise ValueError("Unreviewed/malformed first canary handoff is not publishable")
    root = _private_new_directory(out_dir)
    try:
        _write_private(
            root / "first_3_source_canary_handoff_NO_GO.json",
            (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        _write_private(
            root / "human_first_source_review_queue_NOT_APPROVED.csv",
            _csv_bytes(WORKLIST_FIELDS, report["sources"]),
        )
        rows = [{
            **job, **job["spider_args"],
        } for job in report["jobs"]]
        _write_private(
            root / "six_manual_zyte_job_specs_NOT_AUTHORIZED.csv",
            _csv_bytes(JOB_FIELDS, rows),
        )
        _write_private(
            root / "READ_ME_NO_CRAWL.txt",
            (
                "This packet issues ZERO requests and ZERO access approvals.\n"
                "Three original wave-1 sources, six possible MANUAL job specs.\n"
                "It DOES NOT independently authenticate permissions or remote Zyte deployment.\n"
                "The sources may remain blocked in the actual deployed spider.\n"
                "Never infer permission from source_url, robots candidate or an API/terms link.\n"
                "Complete actual P23B publisher-specific reviews and manual operator signoff.\n"
                "Keep filled private policy records, publisher correspondence, real job logs\n"
                "and original HTML OUT of GitHub Actions / public artifacts.\n"
                "Preserve all 18 original scientific source IDs and 36 rounds.\n"
            ).encode("utf-8"),
        )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_handoff()
    path = write_handoff(report, args.out_dir)
    print(json.dumps({
        "status": report["status"],
        "initial_source_ids": report["initial_pilot_source_ids"],
        "local_reviewed_sources_NOT_EXTERNAL_PERMISSIONS": report[
            "local_reviewed_single_validation_sources_NOT_PERMISSION"
        ],
        "job_specs_NOT_AUTHORIZED": report["initial_pilot_manual_job_specs"],
        "network_requests": 0, "zyte_jobs": 0, "out_dir": str(path),
    }, indent=2))


if __name__ == "__main__":
    main()
