"""P19A1: operator-attested original public changelog HTML capture (manual).

Default is an offline plan for 1-5 exact 460-source manifest changelog IDs.
Actual network requests require --capture --policy-reviewed and a private
publisher-policy research/retention note. Robots are checked fail closed.
No redirects, retries, access evasion, new spiders, schedules or approvals.
"""
import argparse
import hashlib
import json
import os
import shutil
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.sources import load_sources
from scripts.capture_pricing_html import (
    NoRedirect, AGENT, _fetch_exact, _host, _private_exclusive_directory,
    _robots_check, _robots_url, _write_new_private_file,
)
from scripts.replay_release_snapshots import (
    MANIFEST_KIND, VERSION, source_pins, validate_capture_manifest,
)

MAX_POLICY_NOTE = 500


def capture_plan(source_ids):
    pins = source_pins(source_ids)
    known = {s["id"]: s for s in load_sources()}
    return {
        "schema_version": VERSION,
        "kind": "p19a1_read_only_manual_changelog_capture_plan",
        "expected_manifest_sha256": pins["expected_manifest_sha256"],
        "expected_source_registry_sha256":
            pins["expected_source_registry_sha256"],
        "sources": [{
            **entry,
            "robots_url": _robots_url(known[entry["source_id"]]),
            "capture_method": "static_html_exact_original",
        } for entry in pins["sources"]],
        "max_exact_changelog_urls": 5,
        "publisher_policy_review_required": True,
        "network_requests_performed": 0,
        "new_spider_sources": 0,
        "approved_for_advisor": False,
    }


def capture_changelog_html(source_ids, out_dir, *, policy_review_note,
                           opener=None, sleep_fn=None, clock=None,
                           source_policy_preflight=None):
    """Capture one *explicit* authorized research batch, or fail atomically."""
    plan = capture_plan(source_ids)
    # Real network capture must be preceded by exact per-source policy review.
    # An injected test opener preserves P19A1's fully synthetic regressions.
    if opener is None and source_policy_preflight is None:
        raise ValueError("Live publisher capture requires source-specific policy preflight")
    if source_policy_preflight is not None:
        waves = source_policy_preflight.get("batches") if isinstance(
            source_policy_preflight, dict
        ) else None
        def _allows(wave):
            if not isinstance(wave, dict):
                return False
            planned = wave.get("planned_source_ids")
            eligible = wave.get("operator_attested_capture_eligible_source_ids")
            if not isinstance(planned, list) or not isinstance(eligible, list):
                return False
            # Retain full preregistration; only a reviewed ordered subset
            # of ONE wave can be fetched by an explicit operator invocation.
            return (
                [sid for sid in planned if sid in source_ids] == source_ids
                and set(source_ids) <= set(eligible)
            )
        if (not isinstance(source_policy_preflight, dict)
                or source_policy_preflight.get("kind") !=
                    "p19a5_offline_policy_preflight_not_permission"
                or source_policy_preflight.get("approved_for_advisor") is not False
                or not isinstance(waves, list)
                or sum(_allows(wave) for wave in waves) != 1):
            raise ValueError("No matching source-specific reviewed pilot wave subset")
    if (not isinstance(policy_review_note, str)
            or not 30 <= len(policy_review_note.strip()) <= MAX_POLICY_NOTE):
        raise ValueError("Manual publisher policy note must be 30-500 chars")
    dest = Path(out_dir)
    if (dest.exists() or dest.is_symlink()
            or any(parent.is_symlink() for parent in dest.parents)):
        raise ValueError("Choose a NEW private non-symlink output directory")
    checkout = Path(__file__).resolve().parents[1]
    absolute = dest.resolve(strict=False)
    if absolute.is_relative_to(checkout) and not absolute.is_relative_to(
        checkout / "output"
    ):
        raise ValueError("Captured publisher HTML must stay in gitignored output/")
    current = clock if clock is not None else lambda: datetime.now(timezone.utc)
    op = opener if opener is not None else urllib.request.build_opener(NoRedirect)
    sleeper = sleep_fn if sleep_fn is not None else time.sleep
    known = {s["id"]: s for s in load_sources()}
    robots = {}
    # Every exact publisher path must be allowed BEFORE any original HTML GET.
    for sid in source_ids:
        source = known[sid]
        host = _host(source)
        if host not in robots:
            robots[host] = _robots_check(source, op)
        if not robots[host]["parser"].can_fetch(AGENT, source["url"]):
            raise ValueError("Publisher robots denies exact changelog source: " + sid)
    target = _private_exclusive_directory(dest)
    captures, receipts = [], []
    try:
        for sid in source_ids:
            source = known[sid]
            robot = robots[_host(source)]
            sleeper(robot["delay_seconds"])
            raw, response, original_html = _fetch_exact(
                source["url"], op, robots=False,
            )
            evidence = extract_evidence(
                original_html, source["url"], category="changelog", source_id=sid,
            )
            state, reason = assess_capture(
                "changelog", evidence, evidence.get("text", ""),
            )
            if state == "blocked":
                raise ValueError("Publisher HTML indicates access challenge; abort capture")
            digest = hashlib.sha256(raw).hexdigest()
            file_name = sid + "-" + digest[:20] + ".html"
            _write_new_private_file(target / file_name, raw)
            captured = current()
            if not isinstance(captured, datetime) or captured.tzinfo is None:
                raise ValueError("Capture clock must include timezone")
            timestamp = captured.astimezone(timezone.utc).isoformat()
            captures.append({
                "source_id": sid,
                "snapshot": {
                    "file": file_name,
                    "sha256": digest,
                    "request_url": source["url"],
                    "final_url": source["url"],
                    "http_status": 200,
                    "media_type": "text/html",
                    "capture_method": "static_html",
                    "captured_at_utc": timestamp,
                    "capture_origin_review_status":
                        "operator_supplied_unverified",
                },
            })
            receipts.append({
                "source_id": sid,
                "official_source_url": source["url"],
                "raw_html_sha256": digest,
                "raw_html_bytes": len(raw),
                "robots_url": robot["robots_url"],
                "robots_sha256": robot["robots_sha256"],
                "robots_allowed_for_agent": True,
                "robots_delay_seconds": robot["delay_seconds"],
                "http_date_unverified": response["date"],
                "last_modified_not_publication_date": response["last_modified"],
                "parser_capture_status": state,
                "parser_capture_reason": reason,
                "publisher_origin_independently_authenticated": False,
                "published_release_facts_independently_verified": False,
                "approved_for_advisor": False,
            })
        manifest = {
            "schema_version": VERSION,
            "kind": MANIFEST_KIND,
            "expected_manifest_sha256": plan["expected_manifest_sha256"],
            "expected_source_registry_sha256":
                plan["expected_source_registry_sha256"],
            "approved_for_advisor": False,
            "snapshots": captures,
        }
        validate_capture_manifest(manifest)
        audit = {
            "schema_version": VERSION,
            "kind": "p19a1_manual_original_changelog_capture_audit",
            "capture_count": len(captures),
            "source_ids": list(source_ids),
            "publisher_policy_review_operator_attested": True,
            "publisher_policy_independently_verified": False,
            "policy_review_note": policy_review_note.strip(),
            "source_specific_policy_review_receipt_sha256": (
                source_policy_preflight["receipt_sha256"]
                if source_policy_preflight is not None else None
            ),
            "source_specific_policy_review_completed": (
                source_policy_preflight is not None
            ),
            "robots_checks": len(robots),
            "network_requests_performed": len(robots) + len(captures),
            "receipts": receipts,
            "new_spider_sources": 0,
            "zyte_jobs_created": 0,
            "automatic_schedules_enabled": False,
            "new_release_alerts": 0,
            "advisor_approved_facts": 0,
            "approved_for_advisor": False,
        }
        for filename, obj in (
            ("frozen_release_snapshots.json", manifest),
            ("capture_audit.json", audit),
        ):
            _write_new_private_file(
                target / filename,
                (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            )
        return manifest, audit
    except Exception:
        shutil.rmtree(target)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-ids", required=True,
                   help="1-5 exact configured changelog source IDs, comma-separated")
    p.add_argument("--capture", action="store_true",
                   help="Allow manual publisher requests; default NO network")
    p.add_argument("--policy-reviewed", action="store_true",
                   help="Operator independently checked publisher policy and terms")
    p.add_argument("--policy-review-note", default="",
                   help="Private 30-500 character publisher access/retention note")
    p.add_argument("--pilot-plan", type=Path,
                   help="Frozen P19A4 plan required for every real manual capture")
    p.add_argument("--policy-ledger", type=Path,
                   help="Filled P19A5 per-publisher policy reviews, private")
    p.add_argument("--out-dir", type=Path, default=Path(
        "output/private/p19a1-changelog-html"
    ))
    args = p.parse_args()
    ids = [x.strip() for x in args.source_ids.split(",")]
    plan = capture_plan(ids)
    if not args.capture:
        if (args.policy_reviewed or args.policy_review_note
                or args.pilot_plan or args.policy_ledger):
            p.error("Policy flags require explicit --capture")
        print(json.dumps(plan, indent=2))
        return
    if not args.policy_reviewed:
        p.error("--capture requires --policy-reviewed")
    if not args.pilot_plan or not args.policy_ledger:
        p.error("--capture requires --pilot-plan and --policy-ledger")
    selection_key = os.environ.get("AGENTFUSE_RELEASE_PILOT_SELECTION_KEY", "")
    if not selection_key:
        p.error("Private AGENTFUSE_RELEASE_PILOT_SELECTION_KEY required")
    from scripts.prepare_release_pilot import _read_plan
    from scripts.review_release_pilot_policy import require_batch_capture_review
    policy_receipt = require_batch_capture_review(
        _read_plan(args.pilot_plan), _read_plan(args.policy_ledger),
        source_ids=ids, selection_key=selection_key,
    )
    manifest, audit = capture_changelog_html(
        ids, args.out_dir, policy_review_note=args.policy_review_note,
        source_policy_preflight=policy_receipt,
    )
    print(json.dumps({
        "status": "original_changelog_html_saved_privately_unverified",
        "sources_captured": len(manifest["snapshots"]),
        "network_requests_performed": audit["network_requests_performed"],
        "private_capture_directory": str(args.out_dir),
        "advisor_approved_facts": 0, "new_release_alerts": 0,
        "zyte_jobs_created": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
