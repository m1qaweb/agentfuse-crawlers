"""P17A offline pre/post price model-label risk triage over all 177 pricing IDs.

Input: existing historical Zyte Dashboard pricing Items array. A model
label containing marketing prose is *not* a trustworthy rate identity.
This tool does not reconstruct lost DOM markup, rerun the spider, certify
vendors, or publish facts. Full original HTML fixtures are required to
measure improvement from the P17A parser update.
"""
import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path

from agentfuse_crawlers.model_labels import suspected_model_description_join
from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import select_sources

MAX_ITEMS_BYTES = 40_000_000
FIELDS = (
    "source_id", "provider", "source_status", "observations_retained",
    "quote_candidates", "risky_observations", "risky_quote_candidates",
    "missing_model_identity", "suspected_model_labels_example",
    "recommended_review", "publisher_facts_verified",
)


def _safe_csv(value):
    value = "" if value is None else str(value)
    return "'" + value if value.lstrip().startswith(("=", "-", "+", "@")) else value


def audit_pricing_model_identity(items):
    if not isinstance(items, list) or len(items) != 177:
        raise ValueError("Exactly 177 current pricing source Items required")
    expected = select_sources("pricing", "all")
    src = {s["id"]: s for s in expected}
    known = set()
    sources = []
    stats = Counter()
    sha = set()
    job_ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Malformed pricing Item")
        sid = item.get("source_id")
        ref = src.get(sid) if isinstance(sid, str) else None
        if ref is None or sid in known:
            raise ValueError("Duplicate/unknown pricing source ID")
        known.add(sid)
        if (item.get("provider") != ref["provider"]
                or item.get("category") != "pricing"
                or item.get("source_url") != ref["url"]
                or item.get("spider_name") != "official_pricing"
                or item.get("approved_for_advisor") is not False
                or item.get("requested_cohort") != "all"
                or item.get("collection_mode") != "validation"
                or item.get("run_scope_explicit") is not True
                or item.get("manifest_sha256") != manifest_sha256()
                or item.get("source_registry_sha256") !=
                    registry_revision_sha256()
                or item.get("selection_ids_sha256") !=
                    selection_ids_sha256(expected)
                or item.get("selection_source_count") != 177):
            raise ValueError("Pricing source/provenance/manifest is not pinned: " + sid)
        fingerprint = item.get("deployment_revision")
        if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                or item.get("deployment_revision_kind") !=
                   "package_py_json_sha256_v1"):
            raise ValueError("Pricing crawler revision cannot be verified")
        sha.add(fingerprint)
        job_ids.add(item.get("zyte_job_id"))
        observations = item.get("pricing_observations") or []
        if not isinstance(observations, list) or any(
            not isinstance(o, dict) or
            o.get("approved_for_advisor") is not False
            for o in observations
        ):
            raise ValueError("Observed pricing evidence invalid or pre-approved")
        suspect = [
            o for o in observations
            if suspected_model_description_join(o.get("model_or_service") or "")
        ]
        quote = [o for o in observations if o.get("review_quote_candidate") is True]
        risky_quote = [
            o for o in quote
            if suspected_model_description_join(o.get("model_or_service") or "")
        ]
        missing = [
            o for o in observations if not (o.get("model_or_service") or "").strip()
        ]
        stats["retained_observations"] += len(observations)
        stats["review_quote_candidates"] += len(quote)
        stats["suspicious_model_labels"] += len(suspect)
        stats["suspicious_review_quotes"] += len(risky_quote)
        stats["missing_model_labels"] += len(missing)
        stats["comparable_candidates"] += sum(
            o.get("comparable_candidate") is True for o in observations
        )
        examples = sorted({
            str(o.get("model_or_service"))[:140] for o in risky_quote + suspect
        })
        action = (
            "recover_exact_model_from_original_html_strictly" if risky_quote
            else "review_model_label_and_product_scope" if suspect or missing
            else "no_dom_proof_do_not_approve_pricing"
        )
        sources.append({
            "source_id": sid, "provider": ref["provider"],
            "source_status": item.get("status") or "",
            "observations_retained": len(observations),
            "quote_candidates": len(quote),
            "risky_observations": len(suspect),
            "risky_quote_candidates": len(risky_quote),
            "missing_model_identity": len(missing),
            "suspected_model_labels_example": "; ".join(examples[:2])[:290],
            "recommended_review": action,
            "publisher_facts_verified": False,
        })
    if len(known) != 177 or len(sha) != 1 or len(job_ids) != 1:
        raise ValueError("Pricing source or deployment job accounting incomplete")
    sources.sort(key=lambda s: (
        -s["risky_quote_candidates"], -s["risky_observations"],
        -s["observations_retained"], s["source_id"],
    ))
    return {
        "summary": {
            "report_kind": "historical_post_extraction_model_identity_risks_not_truth",
            "source_count": len(known),
            "deployment_revision": next(iter(sha)),
            "job_id": next(iter(job_ids)),
            "parser_change_replayed_on_raw_publisher_html": False,
            "results_from_old_existing_items_not_new_spider_run": True,
            "observed_counts": dict(sorted(stats.items())),
            "source_ids_with_risky_review_quotes": [
                s["source_id"] for s in sources
                if s["risky_quote_candidates"]
            ],
            "publisher_fact_accuracy_verified": False,
            "advisor_fact_approvals": 0,
            "network_requests_performed": 0,
            "deployment_authorized": False,
        },
        "sources": sources,
    }


def write_triage(report, out_dir):
    out = Path(out_dir)
    if out.is_symlink():
        raise ValueError("Private output cannot be a symlink")
    out.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(out, 0o700)
    summary = out / "pricing_model_identity_risks.json"
    summary.write_text(
        json.dumps(report["summary"], indent=2) + "\n", encoding="utf-8",
    )
    path = out / "pricing_model_identity_review_queue.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in report["sources"]:
            writer.writerow({
                key: _safe_csv(row.get(key, "")) for key in FIELDS
            })
    os.chmod(path, 0o600)
    os.chmod(summary, 0o600)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pricing-items", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path,
                    default=Path("output/private/p17a-pricing-identity"))
    args = ap.parse_args()
    if args.pricing_items.stat().st_size > MAX_ITEMS_BYTES:
        ap.error("Unexpectedly large pricing Items export")
    data = json.loads(args.pricing_items.read_text(encoding="utf-8-sig"))
    report = audit_pricing_model_identity(data)
    folder = write_triage(report, args.out_dir)
    print(json.dumps({
        "sources": 177,
        "suspected_review_quote_identity_risks": report["summary"][
            "observed_counts"]["suspicious_review_quotes"],
        "publisher_accuracy_verified": False,
        "full_html_reparse_performed": False,
        "out_dir": str(folder),
    }, indent=2))


if __name__ == "__main__":
    main()
