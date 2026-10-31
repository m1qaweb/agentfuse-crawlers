"""Offline, replayable, unverified release/pricing/docs comparison across Zyte jobs.

Failing or incompatible observations never replace the latest healthy
comparable source baseline. No job scheduling, DB writes or vendor facts.
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from scripts.archive_jobs import load_archive
from scripts.compare_exports import _healthy

REVIEW_STATUS = "pending_human_verification"
CSV_COLUMNS = (
    "source_id", "provider", "category", "change_type", "event_id",
    "observation_id", "section_id", "source_url", "evidence_url",
    "prior_value", "current_value", "observed_at_utc", "review_status",
)


def _source_identity(row):
    """A changed parser, URL, manifest or product means a fresh baseline."""
    return (
        row.get("source_id"), row.get("provider"), row.get("category"),
        row.get("source_url"), row.get("manifest_sha256"),
        row.get("source_registry_sha256"),
        row.get("schema_version"),
        row.get("release_events_schema"),
        row.get("release_identity_revision"),
        row.get("pricing_evidence_schema"),
        row.get("pricing_parser_revision"),
        row.get("documentation_evidence_schema"),
        row.get("documentation_product_scope"),
        row.get("source_format"),
    )


def _run_eligible(envelope):
    """A captured Item cannot cure an incomplete/aborted Zyte job."""
    scope = envelope.get("source_scope") or {}
    return bool(scope.get("safe_for_semantic_diff"))


def _healthy_for_typed_diffs(row):
    if not _healthy(row):
        return False
    if row.get("source_policy_status") in {"unresolved", "prohibited_reviewed"}:
        return False
    if row.get("source_lifecycle_state") in {"quarantined", "retired"}:
        return False
    if row.get("freshness_warnings"):
        return False
    age = row.get("reported_cache_age_seconds")
    if isinstance(age, (int, float)) and age > 86_400:
        return False
    flags = row.get("scrapy_response_flags") or []
    if any("cache" in str(flag).lower() for flag in flags):
        return False
    code = row.get("http_status")
    if code is not None and (not isinstance(code, int) or not 200 <= code < 300):
        return False
    if row.get("category") == "documentation" and row.get(
        "documentation_evidence_schema"
    ):
        return bool(
            row.get("documentation_scope_status") == "scoped_page"
            and row.get("documentation_profile_status")
            == "curated_pending_live_validation"
            and not row.get("documentation_source_sections_truncated")
            and not row.get("documentation_item_budget_truncated")
            and not row.get("documentation_topic_candidate_omitted")
        )
    return True


def _safe_locator(locator, official):
    """Never export an arbitrary URL scraped from an HTML page."""
    if not isinstance(locator, str) or not isinstance(official, str):
        return ""
    try:
        a, b = urlsplit(locator), urlsplit(official)
        if (a.scheme != "https" or a.hostname != b.hostname or
                a.username or a.password or a.port not in (None, 443) or
                not b.hostname):
            return ""
        # Preserve a bounded fragment for heading navigation but no tokens.
        fragment = a.fragment if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", a.fragment) else ""
        return urlunsplit(("https", a.hostname, a.path[:800] or "/",
                           "", fragment))
    except (TypeError, ValueError):
        return ""


def _change(row, kind, *, locator="", **extra):
    return {
        "source_id": row["source_id"],
        "provider": row.get("provider", ""),
        "category": row.get("category", ""),
        "source_url": row.get("source_url", ""),
        "evidence_url": _safe_locator(locator, row.get("source_url", ""))
                        or row.get("source_url", ""),
        "change_type": kind,
        "observed_at_utc": row.get("fetched_at_utc", ""),
        "review_status": REVIEW_STATUS,
        "approved_for_advisor": False,
        **extra,
    }


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _release_delta(current, previous, older_healthy=()):
    """Explicit event identity and content hashes; never infer removals."""
    if (current.get("release_events_schema") != "1.1"
            or previous.get("release_events_schema") != "1.1"
            or current.get("release_identity_revision")
                != previous.get("release_identity_revision")
            or not current.get("release_window_complete")
            or not previous.get("release_window_complete")):
        return []
    before = {e.get("event_id"): e for e in previous.get("release_events", [])
              if isinstance(e, dict) and e.get("event_id")}
    earlier = set()
    for old in older_healthy:
        if _source_identity(old) == _source_identity(current):
            earlier.update(e.get("event_id") for e in old.get("release_events", [])
                           if isinstance(e, dict))
    seen = set()
    result = []
    old_fetch = _date(str(previous.get("fetched_at_utc", ""))[:10])
    current_fetch = _date(str(current.get("fetched_at_utc", ""))[:10])
    for event in current.get("release_events", []):
        if not isinstance(event, dict):
            continue
        identity = event.get("event_id")
        if not isinstance(identity, str) or not identity or identity in seen:
            return [_change(current, "needs_review",
                            reason="duplicate_or_missing_release_event_identity")]
        seen.add(identity)
        if not isinstance(event.get("body_sha256"), str) or not event["body_sha256"]:
            continue
        prior = before.get(identity)
        if prior and all(event.get(k) == prior.get(k) for k in (
            "body_sha256", "published_at", "published_date_provenance", "version"
        )):
            continue
        release_date = _date(event.get("published_at"))
        if prior:
            kind = "edited_event"
        elif identity in earlier:
            kind = "restored_event"
        elif (release_date is None or old_fetch is None
              or current_fetch is None or release_date > current_fetch):
            kind = "needs_review"
        elif release_date < old_fetch:
            kind = "backfilled_event"
        else:
            kind = "new_event_candidate"
        locator = event.get("permalink") or current["source_url"]
        result.append(_change(
            current, kind, locator=locator,
            event_id=identity,
            title=event.get("title", ""),
            version=event.get("version"),
            published_date_candidate=event.get("published_at"),
            published_date_provenance=event.get("published_date_provenance"),
            evidence_excerpt=str(event.get("excerpt") or "")[:400],
            current_value=event.get("body_sha256"),
            prior_value=prior.get("body_sha256") if prior else None,
            reason=("date_missing_future_or_unverifiable" if kind == "needs_review"
                    else "historic_event_first_observed" if kind == "backfilled_event"
                    else "unverified_release_evidence_delta"),
        ))
    return result


RATE_DIMENSIONS = (
    "model_or_service", "region", "tier_or_plan", "service_mode",
    "price_dimension", "billing_unit", "currency",
    "effective_from", "effective_until",
)


def _priced_map(row):
    """Require a unique fully scoped typed identity; no imputed USD or units."""
    found = {}
    seen_ids = set()
    for obs in row.get("pricing_observations", []):
        if not isinstance(obs, dict) or not obs.get("comparable_candidate"):
            continue
        if any(not obs.get(field) for field in (
            "model_or_service", "region", "tier_or_plan",
            "price_dimension", "billing_unit", "currency",
            "observation_id", "raw_displayed_price", "normalized_amount_decimal",
        )):
            return None
        key = tuple(obs.get(field) for field in RATE_DIMENSIONS)
        if key in found or obs["observation_id"] in seen_ids:
            return None
        try:
            amount = Decimal(obs["normalized_amount_decimal"])
            if not amount.is_finite() or amount < 0:
                return None
        except (TypeError, ValueError, InvalidOperation):
            return None
        seen_ids.add(obs["observation_id"])
        found[key] = obs
    return found


def _pricing_delta(current, previous):
    if not (current.get("pricing_evidence_schema") == "1.0"
            and previous.get("pricing_evidence_schema") == "1.0"
            and current.get("pricing_inventory_complete")
            and previous.get("pricing_inventory_complete")):
        return []
    old, new = _priced_map(previous), _priced_map(current)
    if old is None or new is None:
        return [_change(current, "needs_review",
                        reason="pricing_rate_identity_ambiguous")]
    changes = []
    for key, price in sorted(new.items(), key=lambda p: str(p[0])):
        prev = old.get(key)
        # New table rows are first-observed evidence, not a price increase
        # or a proof a newly introduced product was launched today.
        kind = ("rate_first_seen_candidate" if prev is None
                else "rate_change_candidate" if Decimal(
                    price["normalized_amount_decimal"]
                ) != Decimal(prev["normalized_amount_decimal"]) else None)
        if kind is None:
            if (prev and price.get("source_evidence_sha256")
                    and prev.get("source_evidence_sha256")
                    and price["source_evidence_sha256"]
                        != prev["source_evidence_sha256"]):
                changes.append(_change(
                    current, "needs_review", locator=price.get("source_url"),
                    observation_id=price["observation_id"],
                    reason="pricing_evidence_changed_but_numeric_rate_unchanged",
                    rate_dimensions=dict(zip(RATE_DIMENSIONS, key)),
                    raw_current_price=price.get("raw_displayed_price"),
                    raw_prior_price=prev.get("raw_displayed_price"),
                ))
            continue
        changes.append(_change(
            current, kind, locator=price.get("source_url"),
            observation_id=price.get("observation_id"),
            rate_dimensions=dict(zip(RATE_DIMENSIONS, key)),
            current_value=price["normalized_amount_decimal"],
            prior_value=prev.get("normalized_amount_decimal") if prev else None,
            raw_current_price=price.get("raw_displayed_price"),
            raw_prior_price=prev.get("raw_displayed_price") if prev else None,
            table_id=price.get("table_id"),
            row_index=price.get("row_index"),
            column_index=price.get("column_index"),
            reason="unverified_publisher_rate_observation",
        ))
    return changes


def _docs_delta(current, previous):
    if not (current.get("documentation_evidence_schema") == "1.0"
            and previous.get("documentation_evidence_schema") == "1.0"
            and current.get("documentation_scope_status") == "scoped_page"
            and previous.get("documentation_scope_status") == "scoped_page"):
        return []
    old = {s.get("section_id"): s for s in previous.get("sections", [])
           if isinstance(s, dict) and s.get("section_id")}
    seen = set()
    results = []
    for section in current.get("sections", []):
        sid = section.get("section_id")
        if not sid or sid in seen:
            return [_change(current, "needs_review",
                            reason="duplicate_or_missing_documentation_section")]
        seen.add(sid)
        prior = old.get(sid)
        sha = section.get("sha256")
        if not sha or (prior and prior.get("sha256") == sha):
            continue
        results.append(_change(
            current, "docs_section_changed",
            locator=section.get("section_url"), section_id=sid,
            section_change_kind="modified" if prior else "added",
            heading=section.get("heading", ""),
            evidence_excerpt=str(section.get("excerpt") or "")[:400],
            current_value=sha, prior_value=prior.get("sha256") if prior else None,
            reason="semantic_section_digest_delta_not_feature_support",
        ))
    # A missing section can be a moved heading or bounded index, not a removed
    # capability. Never infer discontinued model/features from absence.
    return results


def _archive_moment(envelope):
    job = envelope["job"]
    ms = job.get("finished_time_ms")
    if isinstance(ms, (int, float)) and ms > 0:
        return (float(ms), job["job_id"])
    raise ValueError("Cannot order job archive without official finished_time_ms")


def evaluate(current_archive, history=()):
    """Verify archives, compute latest-observed vs latest-healthy per source."""
    current_env, current_rows = load_archive(current_archive)
    histories = []
    nowkey = _archive_moment(current_env)
    for path in history:
        env, rows = load_archive(path)
        if env["job"]["job_id"] == current_env["job"]["job_id"]:
            if env["integrity"] != current_env["integrity"]:
                raise ValueError("Conflicting copies of identical Zyte job")
            continue
        if _archive_moment(env) >= nowkey:
            raise ValueError("Historical archive must precede current finished job")
        histories.append((env, rows))
    histories.sort(key=lambda x: _archive_moment(x[0]))
    earlier = defaultdict(list)
    observed = {}
    for env, rows in histories:
        for row in rows:
            earlier[row["source_id"]].append((env, row))
    for row in current_rows:
        observed[row["source_id"]] = row
    changes, states = [], []
    for sid in sorted(set(observed) | set(earlier)):
        current = observed.get(sid)
        previous_all = earlier.get(sid, [])
        latest_observed = current if current is not None else (
            previous_all[-1][1] if previous_all else None)
        latest_observed_job = current_env["job"]["job_id"] if current is not None else (
            previous_all[-1][0]["job"]["job_id"] if previous_all else None)
        healthy_history = [(env, row) for env, row in previous_all
                           if _run_eligible(env) and _healthy_for_typed_diffs(row)]
        baseline = healthy_history[-1][1] if healthy_history else None
        baseline_job = healthy_history[-1][0]["job"]["job_id"] if healthy_history else None
        current_healthy = bool(
            current is not None and _run_eligible(current_env)
            and _healthy_for_typed_diffs(current)
        )
        final_healthy = current if current_healthy else baseline
        final_good_job = current_env["job"]["job_id"] if current_healthy else baseline_job
        if current is None:
            # Historic-only sources were outside this current job scope.
            # They are not outages and do not become item loss alerts.
            continue
        if not current_healthy:
            if not _run_eligible(current_env):
                changes.append(_change(
                    current, "needs_review", reason="job_scope_or_finish_incomplete"
                ))
            else:
                changes.append(_change(
                    current, "source_unavailable",
                    reason=current.get("error") or current.get("status")
                ))
        elif baseline is None:
            changes.append(_change(current, "historical_baseline",
                                   reason="no_compatible_healthy_previous_capture"))
        elif _source_identity(current) != _source_identity(baseline):
            changes.append(_change(current, "source_migrated",
                                   reason="manifest_url_scope_or_parser_revision_changed"))
        else:
            recent = previous_all[-1][1] if previous_all else None
            if recent is not None and not _healthy_for_typed_diffs(recent):
                changes.append(_change(current, "source_restored",
                                       reason="current_healthy_after_unhealthy_observation"))
            old_before = [row for env, row in healthy_history[:-1]]
            if current.get("category") == "changelog":
                changes.extend(_release_delta(current, baseline, old_before))
            elif current.get("category") == "pricing":
                changes.extend(_pricing_delta(current, baseline))
            elif current.get("category") == "documentation":
                changes.extend(_docs_delta(current, baseline))
        states.append({
            "source_id": sid, "category": current.get("category"),
            "latest_observed_job_id": latest_observed_job,
            "latest_observed_status": latest_observed.get("status") if latest_observed else None,
            "latest_healthy_job_id": final_good_job,
            "latest_healthy_content_sha256": (
                final_healthy.get("content_sha256") if final_healthy else None
            ),
            "latest_healthy_schema": (
                final_healthy.get("release_events_schema")
                or final_healthy.get("pricing_evidence_schema")
                or final_healthy.get("documentation_evidence_schema")
                if final_healthy else None
            ),
            "healthy_current_capture": bool(current_healthy),
            "source_url": current.get("source_url"),
            "approved_for_advisor": False,
        })
    summary = {
        "evaluation_schema": "1.0",
        "current_job_id": current_env["job"]["job_id"],
        "current_job_finished_time_ms": current_env["job"]["finished_time_ms"],
        "history_jobs_considered": [env["job"]["job_id"] for env, _ in histories],
        "source_summary_count": len(current_rows),
        "metadata_item_count_matches": (
            len(current_rows) == current_env["job"]["expected_item_count"]
        ),
        "run_scope_consistent": _run_eligible(current_env),
        "close_reason": current_env["job"]["close_reason"],
        "healthy_current_sources": sum(s["healthy_current_capture"] for s in states),
        "unhealthy_current_sources": sum(not s["healthy_current_capture"] for s in states),
        "change_counts": dict(sorted(Counter(x["change_type"] for x in changes).items())),
        "advisor_approved_fact_count": 0,
        "all_results_unverified": True,
        "interpretation": (
            "The newest observation is not the last comparable baseline. "
            "First captures never generate vendor announcements. "
            "Missing list entries do not prove removals."
        ),
    }
    return {"summary": summary, "states": states,
            "changes": changes, "current": current_rows}


def _jsonl(path, entries):
    with path.open("w", encoding="utf-8") as f:
        for row in entries:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def write_evaluation(result, out_dir):
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    changes = result["changes"]
    with (root / "status.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=(
            "source_id", "category", "source_url", "latest_observed_job_id",
            "latest_observed_status", "latest_healthy_job_id",
            "latest_healthy_content_sha256", "healthy_current_capture",
            "approved_for_advisor",
        ), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["states"])
    with (root / "changes.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(changes)
    _jsonl(root / "review_queue.jsonl", changes)
    _jsonl(root / "release_events.jsonl", [
        dict(change) for change in changes if change["category"] == "changelog"
        and change["change_type"] in {
            "new_event_candidate", "edited_event", "restored_event",
            "backfilled_event", "needs_review",
        }
    ])
    _jsonl(root / "pricing_observations.jsonl", [
        dict(observation, archive_source_id=row["source_id"],
             approved_for_advisor=False, review_status=REVIEW_STATUS)
        for row in result["current"] if row.get("category") == "pricing"
        for observation in row.get("pricing_observations", [])
    ])
    _jsonl(root / "latest_state.jsonl", result["states"])
    (root / "run_quality.json").write_text(
        json.dumps(result["summary"], sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result["summary"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path,
                        help="Verified immutable archive job directory")
    parser.add_argument("--history", type=Path, nargs="*", default=[])
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(args.current, args.history)
    print(json.dumps(write_evaluation(result, args.out_dir), indent=2))


if __name__ == "__main__":
    main()
