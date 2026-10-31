"""Fail-closed PR08 evidence-quality scorecard and human release checklist.

Synthetic fixture tests are NOT independent evidence. No input can authorize
advisor facts, run Zyte jobs, or automatically deploy code. Release readiness
is a *recommendation for additional manual review*, not approval.
"""

import argparse
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.source_lifecycle import collection_decision, registry_revision_sha256
from agentfuse_crawlers.run_context import manifest_sha256

MIN_REVIEWED_PRICES = 200
MIN_REVIEWED_DATES = 100
MIN_DATE_ACCURACY = 0.99
MIN_RATE_ACCURACY = 0.99
MIN_CANARY_USABLE_RATE = 0.95
MEMORY_ADVISORY_BYTES = 400 * 1024 * 1024
JOB_ID_RE = re.compile(r"^[0-9]+/[0-9]+/[0-9]+$")
RATE_FIELDS = (
    "amount", "currency", "billing_unit", "model_or_service", "region",
    "tier_or_plan", "price_dimension", "service_mode",
    "effective_from", "effective_until",
)


def _iso_day(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Golden release date must be ISO day or null")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("Invalid reviewed golden publication date") from exc


def _same_official_locator(url, official):
    if not isinstance(url, str):
        return False
    try:
        a, b = urlsplit(url), urlsplit(official)
        return bool(
            a.scheme == "https" and b.scheme == "https" and a.hostname == b.hostname
            and a.port in (None, 443) and not a.username and not a.password
            and not a.query
        )
    except (TypeError, ValueError):
        return False


def _check_gold_source(row, known, seen, name):
    if not isinstance(row, dict):
        raise ValueError(f"Invalid {name} golden record")
    case_id = row.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
        raise ValueError(f"Missing or repeated {name} case ID")
    seen.add(case_id)
    source_id = row.get("source_id")
    src = known.get(source_id)
    if (src is None or row.get("source_url") != src["url"]
            or not _same_official_locator(row.get("evidence_url"), src["url"])
            or not isinstance(row.get("job_id"), str)
            or not JOB_ID_RE.fullmatch(row["job_id"])):
        raise ValueError(f"{name} does not cite an official manifest source and job")
    if row.get("approved_for_advisor") is not False:
        raise ValueError("Reviewed examples must not be advisor-approved")


def _comparison(row):
    expected = row.get("expected")
    observed = row.get("observed")
    if not isinstance(expected, dict) or not isinstance(observed, dict):
        raise ValueError("Reviewed rate row needs expected and observed evidence")
    for field in RATE_FIELDS[:7]:
        if not isinstance(expected.get(field), str) or not expected[field].strip():
            raise ValueError("Reviewed rate labels need full rate dimensions")
    try:
        expected_amount = Decimal(expected["amount"])
        observed_amount = Decimal(observed["amount"])
        if not (expected_amount.is_finite() and observed_amount.is_finite()
                and expected_amount >= 0 and observed_amount >= 0):
            return False
    except (InvalidOperation, ValueError, TypeError, KeyError):
        return False
    return bool(
        expected_amount == observed_amount
        and all(expected.get(field) == observed.get(field) for field in RATE_FIELDS[1:])
        and observed.get("comparable_candidate") is True
    )


def score_human_gold(gold):
    """Validate self-attested human annotation format; never trust its truth."""
    if not isinstance(gold, dict):
        raise ValueError("Human golden evidence must be a JSON object")
    if (gold.get("schema_version") != "1.0"
            or gold.get("origin") != "human_annotated_official_source_evidence"
            or gold.get("synthetic_only") is not False
            or gold.get("approved_for_advisor") is not False):
        raise ValueError("Missing independently annotated gold provenance")
    reviewer = gold.get("reviewed_by")
    if not isinstance(reviewer, str) or len(reviewer.strip()) < 3:
        raise ValueError("Human golden report needs a named reviewer")
    stamp = gold.get("reviewed_at_utc")
    try:
        reviewed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if reviewed.tzinfo is None:
            raise ValueError("Date must be timezone-aware")
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Gold review date must be timezone-aware ISO") from exc
    known = {source["id"]: source for source in load_sources()}
    pricing = gold.get("pricing_rows")
    dating = gold.get("date_rows")
    negative = gold.get("negative_rate_rows")
    change_cases = gold.get("change_safety_rows")
    if not all(isinstance(v, list) for v in (pricing, dating, negative, change_cases)):
        raise ValueError("Human gold must supply all four annotated case lists")
    seen = set()
    price_correct = 0
    observed_rates = set()
    for row in pricing:
        _check_gold_source(row, known, seen, "pricing")
        if known[row["source_id"]]["category"] != "pricing":
            raise ValueError("Pricing gold source has wrong spider category")
        oid = row.get("observation_id")
        if not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{32}", oid):
            raise ValueError("Human pricing gold must cite a real typed observation ID")
        identity = row["source_id"], row["job_id"], oid
        if identity in observed_rates:
            raise ValueError("Repeated pricing observation cannot inflate 200 reviewed examples")
        observed_rates.add(identity)
        price_correct += bool(_comparison(row))
    date_correct, false_latest = 0, 0
    reviewed_events = set()
    for row in dating:
        _check_gold_source(row, known, seen, "release_date")
        if known[row["source_id"]]["category"] != "changelog":
            raise ValueError("Date gold source has wrong spider category")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id.startswith(row["source_id"] + ":"):
            raise ValueError("Reviewed publication dates require a typed event ID")
        identity = row["source_id"], row["job_id"], event_id
        if identity in reviewed_events:
            raise ValueError("Repeated event cannot inflate publication-date accuracy")
        reviewed_events.add(identity)
        expected = _iso_day(row.get("expected_day"))
        observed = _iso_day(row.get("observed_day"))
        if expected == observed:
            date_correct += 1
        if expected is None and observed is not None:
            false_latest += 1
    unscoped_false = 0
    for row in negative:
        _check_gold_source(row, known, seen, "negative_rate")
        if known[row["source_id"]]["category"] != "pricing":
            raise ValueError("Negative-rate gold source must be pricing")
        if row.get("expected_comparable") is not False:
            raise ValueError("Negative-rate gold case must be explicitly noncomparable")
        unscoped_false += int(row.get("observed_comparable") is True)
    false_new = 0
    for row in change_cases:
        _check_gold_source(row, known, seen, "change_safety")
        if known[row["source_id"]]["category"] != "changelog":
            raise ValueError("Change gold case must be an official changelog")
        if row.get("scenario") not in {"first_baseline", "reordered_same_events"}:
            raise ValueError("Unexpected change-safety scenario")
        false_new += int(row.get("observed_new_release_alert") is True)
    return {
        "pricing_examples": len(pricing),
        "pricing_correct": price_correct,
        "pricing_accuracy": (price_correct / len(pricing) if pricing else None),
        "date_examples": len(dating),
        "date_correct": date_correct,
        "date_accuracy": (date_correct / len(dating) if dating else None),
        "false_latest_date_count": false_latest,
        "negative_rate_examples": len(negative),
        "unscoped_rate_false_comparable": unscoped_false,
        "change_safety_examples": len(change_cases),
        "false_new_release_alerts": false_new,
        "review_provenance": "self_attested_requires_operator_cross_check",
        "approved_for_advisor": False,
    }


def _canary_report_consistent(report):
    """Do not treat a forged summary flag as publisher-approved evidence."""
    if not isinstance(report, dict) or report.get("report_kind") != "offline_two_round_canary_score":
        raise ValueError("Invalid offline canary scorer report")
    from collections import Counter
    from agentfuse_crawlers.sources import load_sources

    catalog = load_sources()
    known = {x["id"]: x for x in catalog}
    if (report.get("manifest_sha256") != manifest_sha256(catalog)
            or report.get("source_registry_sha256") != registry_revision_sha256()):
        return False
    entries = report.get("outcomes")
    if not isinstance(entries, list) or not entries:
        return False
    if (report.get("expected_jobs") != len(entries)
            or report.get("source_count", 0) * 2 != len(entries)
            or report.get("observed_archives") != len(entries)):
        return False
    seen = set()
    approved_sources = set()
    for row in entries:
        if not isinstance(row, dict):
            return False
        key = row.get("source_id"), row.get("round")
        if key in seen or key[1] not in (1, 2) or key[0] not in known:
            return False
        seen.add(key)
        actual_reviewed = collection_decision(known[key[0]], "monitor")[0]
        if row.get("reviewed_collection_eligible") is not actual_reviewed:
            return False
        if actual_reviewed:
            approved_sources.add(key[0])
        if (not row.get("job_id") or not row.get("job_identity_valid")
                or row.get("policy_violation") or row.get("unapproved_fact_count")):
            return False
    if not all((sid, 1) in seen and (sid, 2) in seen for sid, _ in seen):
        return False
    eligible = [row for row in entries if row["reviewed_collection_eligible"]]
    if (report.get("reviewed_collection_eligible_sources") != len(approved_sources)
            or report.get("reviewed_eligible_rounds") != len(eligible)
            or len(eligible) != 2 * len(approved_sources)):
        return False
    computed = sum(row.get("usable") is True for row in eligible) / len(eligible) if eligible else None
    return bool(
        computed is not None
        and report.get("reviewed_eligible_usable_rate") == round(computed, 5)
        and report.get("source_accounting_complete") is True
        and report.get("archive_mapping_complete") is True
        and report.get("strict_round_order") is True
        and report.get("duplicate_job_id") is False
        and report.get("policy_violation_count") == 0
        and report.get("advisor_approval_anomaly_count") == 0
        and report.get("approved_for_advisor") is False
        and len(approved_sources) > 0
    )


def grade_release(*, synthetic=None, canaries=None, human_gold=None):
    """Return actionable blockers. Missing evidence NEVER counts as passed."""
    blockers, warnings, criteria = [], [], {}

    def check(name, ok, message):
        criteria[name] = bool(ok)
        if not ok:
            blockers.append(message)

    if synthetic is None:
        check("synthetic_replay", False, "Synthetic offline golden regression not provided")
    else:
        if (not isinstance(synthetic, dict)
                or synthetic.get("synthetic_only") is not True
                or synthetic.get("independently_human_reviewed") is not False):
            raise ValueError("Synthetic regression report must identify itself as synthetic")
        check(
            "synthetic_replay",
            synthetic.get("pass") is True
            and synthetic.get("date_cases", 0) >= 24
            and synthetic.get("rate_cases", 0) >= 240
            and synthetic.get("false_latest_date_errors") == 0
            and synthetic.get("unscoped_rate_false_comparable") == 0
            and synthetic.get("approved_for_advisor") is False,
            "Synthetic regression failed or is incomplete",
        )
    if canaries is None:
        check("two_repeat_canaries", False, "No two-round archived Zyte canary evidence provided")
    else:
        if not isinstance(canaries, dict) or canaries.get("report_kind") != "offline_two_round_canary_score":
            raise ValueError("Invalid offline canary scorer report")
        check(
            "two_repeat_canaries",
            _canary_report_consistent(canaries)
            and canaries.get("two_round_95pct_gate") is True
            and canaries.get("source_accounting_complete") is True
            and canaries.get("strict_round_order") is True
            and canaries.get("duplicate_job_id") is False
            and canaries.get("reviewed_collection_eligible_sources", 0) > 0
            and canaries.get("reviewed_eligible_usable_rate", 0) >= MIN_CANARY_USABLE_RATE
            and canaries.get("policy_violation_count") == 0
            and canaries.get("advisor_approval_anomaly_count") == 0
            and canaries.get("approved_for_advisor") is False,
            "Insufficient reviewed-eligible, accurate two-round canary evidence",
        )
        memory = canaries.get("max_memory_peak_bytes")
        if memory is None:
            warnings.append("Zyte peak memory was not recorded; inspect job stats")
        elif memory >= MEMORY_ADVISORY_BYTES:
            warnings.append("Canary peak memory >=400 MiB: investigate before scaling")
    if human_gold is None:
        check("independent_pricing_gold", False,
              "Missing 200 independently reviewed real first-party pricing cases")
        check("independent_date_gold", False,
              "Missing 100 independently reviewed release-date examples")
        check("no_false_gold_alerts", False,
              "Missing human-reviewed negative rate and baseline/reorder cases")
        reviewed = None
    else:
        reviewed = score_human_gold(human_gold)
        check(
            "independent_pricing_gold",
            reviewed["pricing_examples"] >= MIN_REVIEWED_PRICES
            and reviewed["pricing_accuracy"] is not None
            and reviewed["pricing_accuracy"] >= MIN_RATE_ACCURACY,
            "Reviewed pricing amount+currency+unit+scope precision below 99% "
            "or fewer than 200 independently labeled real cases",
        )
        check(
            "independent_date_gold",
            reviewed["date_examples"] >= MIN_REVIEWED_DATES
            and reviewed["date_accuracy"] is not None
            and reviewed["date_accuracy"] >= MIN_DATE_ACCURACY
            and reviewed["false_latest_date_count"] == 0,
            "Reviewed date accuracy below 99%, false latest date, or "
            "fewer than 100 independently labeled examples",
        )
        check(
            "no_false_gold_alerts",
            reviewed["negative_rate_examples"] > 0
            and reviewed["unscoped_rate_false_comparable"] == 0
            and reviewed["change_safety_examples"] > 0
            and reviewed["false_new_release_alerts"] == 0,
            "A missing unit/tier/region was normalized, a baseline generated "
            "false news, or negative human gold has not been supplied",
        )
        warnings.append("Human labeling is self-attested; source and reviewer must be independently audited")
    return {
        "schema_version": "1.0",
        "report_kind": "manual_release_quality_check",
        "status": "eligible_for_human_release_review" if not blockers
                  else "blocked_pending_evidence_or_quality",
        "checks": criteria, "blockers": blockers, "warnings": warnings,
        "independent_gold_summary": reviewed,
        "hard_gate_count": len(criteria),
        "hard_gates_passed": sum(criteria.values()),
        "advisor_fact_approvals": 0,
        "deployment_authorized": False,
        "network_requests_performed": 0,
        "notice": (
            "A passing software scorecard is not source permissions, provider "
            "fact truth, deployment approval, or user authorization. "
            "Manual publisher and deployment signoff remains mandatory."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-report", type=Path)
    parser.add_argument("--canary-score", type=Path)
    parser.add_argument("--reviewed-gold", type=Path,
                        help="Separate human-annotated official evidence JSON")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/release-gates"))
    parser.add_argument("--strict", action="store_true",
                        help="Exit nonzero unless independently reviewed release gates pass")
    args = parser.parse_args()

    def load(path):
        return json.loads(path.read_text(encoding="utf-8")) if path else None

    result = grade_release(
        synthetic=load(args.synthetic_report),
        canaries=load(args.canary_score),
        human_gold=load(args.reviewed_gold),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "quality_gate_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": result["status"],
        "hard_gates_passed": result["hard_gates_passed"],
        "hard_gate_count": result["hard_gate_count"],
        "advisor_fact_approvals": 0,
    }, indent=2))
    if args.strict and result["status"] != "eligible_for_human_release_review":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
