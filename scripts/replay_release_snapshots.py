"""P19A1: offline exact-original-HTML changelog identity and date replay.

No website requests, publisher approvals, new spiders, change alerts,
price/capability verification or production database writes. A SHA-256
of captured bytes is integrity evidence, not publisher authentication.
Every emitted event remains an UNVERIFIED reviewer candidate.
"""
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.provider_profiles import identify_source_product
from agentfuse_crawlers.quality import assess_capture
from agentfuse_crawlers.run_context import manifest_sha256, package_fingerprint
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources
from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)

VERSION = "1.0"
MANIFEST_KIND = "frozen_original_changelog_html_manifest"
REPLAY_KIND = "p19a1_original_changelog_html_replay_unverified"
COMPARE_KIND = "p19a1_two_round_release_identity_review_not_alerts"
TASKS_KIND = "p19a1_blind_release_owner_date_tasks_unverified"
MAX_CAPTURE = 5
MAX_EVENTS = 80
MAX_REVIEW_PER_SOURCE = 15
MAX_TOTAL_REVIEW_TASKS = 120
MAX_INPUT_BYTES = 4_000_000
HEX64 = re.compile(r"^[a-f0-9]{64}$")
EVENT_ID = re.compile(r"^[a-z][a-z0-9_]{2,80}:[a-f0-9]{24}$")
MANIFEST_FIELDS = frozenset({
    "schema_version", "kind", "expected_manifest_sha256",
    "expected_source_registry_sha256", "approved_for_advisor", "snapshots",
})
SNAPSHOT_FIELDS = frozenset({"source_id", "snapshot"})


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _known():
    all_sources = load_sources()
    if len(all_sources) != 460:
        raise ValueError("P19A1 requires exactly the current 460-source manifest")
    changelogs = {
        source["id"]: source for source in all_sources
        if source["category"] == "changelog"
    }
    if len(changelogs) != 89:
        raise ValueError("P19A1 requires exactly 89 changelog sources")
    return changelogs


def source_pins(source_ids):
    """Read-only source pins for one to five specific changelog IDs."""
    if (not isinstance(source_ids, list)
            or not 1 <= len(source_ids) <= MAX_CAPTURE
            or any(not isinstance(sid, str) for sid in source_ids)
            or len(set(source_ids)) != len(source_ids)):
        raise ValueError("Choose 1-5 different exact changelog source IDs")
    known = _known()
    entries = []
    for sid in source_ids:
        source = known.get(sid)
        if source is None:
            raise ValueError("Unconfigured changelog source: " + sid)
        allowed, reason = collection_decision(source, "validation")
        if not allowed:
            raise ValueError("Publisher lifecycle blocks validation: " + sid)
        entries.append({
            "source_id": sid,
            "official_source_url": source["url"],
            "lifecycle_validation_status": reason,
            "publisher_policy_review_required": True,
        })
    return {
        "schema_version": VERSION,
        "kind": "p19a1_read_only_changelog_source_pins",
        "expected_manifest_sha256": manifest_sha256(),
        "expected_source_registry_sha256": registry_revision_sha256(),
        "sources": entries,
        "network_requests_performed": 0,
        "publisher_permissions_granted": 0,
        "approved_for_advisor": False,
    }


def validate_capture_manifest(manifest):
    if (not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS
            or manifest["schema_version"] != VERSION
            or manifest["kind"] != MANIFEST_KIND
            or manifest["approved_for_advisor"] is not False
            or manifest["expected_manifest_sha256"] != manifest_sha256()
            or manifest["expected_source_registry_sha256"] !=
                registry_revision_sha256()
            or not isinstance(manifest["snapshots"], list)
            or not 1 <= len(manifest["snapshots"]) <= MAX_CAPTURE):
        raise ValueError("Unpinned or privileged original changelog capture manifest")
    known = _known()
    seen = set()
    for entry in manifest["snapshots"]:
        if not isinstance(entry, dict) or set(entry) != SNAPSHOT_FIELDS:
            raise ValueError("Unexpected changelog capture entry")
        sid = entry.get("source_id")
        if not isinstance(sid, str) or sid in seen or sid not in known:
            raise ValueError("Duplicate, unknown or non-changelog source")
        seen.add(sid)
        allowed, _ = collection_decision(known[sid], "validation")
        if not allowed:
            raise ValueError("Publisher lifecycle blocks original changelog capture")
    return known


def _capture_time(value):
    if not isinstance(value, str):
        raise ValueError("Capture timestamp must be ISO8601 UTC")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Malformed changelog capture time") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Changelog timestamp must include timezone")
    return stamp.astimezone(timezone.utc)


def _event_record(event, sid, source_url):
    """Review-only structured evidence; truncate body to a short excerpt."""
    if (not isinstance(event, dict) or event.get("approved_for_advisor") is not False
            or event.get("source_id") != sid
            or not isinstance(event.get("event_id"), str)
            or not EVENT_ID.fullmatch(event["event_id"])
            or not event["event_id"].startswith(sid + ":")
            or not isinstance(event.get("body_sha256"), str)
            or not HEX64.fullmatch(event["body_sha256"])):
        raise ValueError("Malformed, cross-owned or privileged release event")
    permalink = event.get("permalink")
    if not isinstance(permalink, str) or len(permalink) > 800:
        raise ValueError("Missing or oversized release evidence link")
    owner = urlsplit(source_url)
    url = urlsplit(permalink)
    if (url.scheme != "https" or url.hostname != owner.hostname
            or url.username or url.password or url.port not in (None, 443)
            or url.query):
        raise ValueError("Non-publisher or credential-bearing event link")
    published = event.get("published_at")
    if published is not None:
        if (not isinstance(published, str)
                or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", published)):
            raise ValueError("Invalid publisher date candidate")
        try:
            date.fromisoformat(published)
        except ValueError as exc:
            raise ValueError("Impossible publisher date candidate") from exc
    locator = event.get("evidence_locator") or {}
    return {
        "event_id": event["event_id"],
        "source_id": sid,
        "title": str(event.get("title") or "")[:180],
        "version": event.get("version"),
        "published_at": published,
        "date_evidence_text": str(event.get("date_evidence_text") or "")[:80],
        "published_date_provenance": str(event.get("published_date_provenance") or "")[:80],
        "permalink": permalink,
        "identity_basis": str(event.get("identity_basis") or "")[:90],
        "release_identity_requires_manual_review":
            event.get("release_identity_requires_manual_review") is True,
        "body_sha256": event["body_sha256"],
        "excerpt": str(event.get("excerpt") or "")[:300],
        "excerpt_truncated": bool(event.get("excerpt_truncated")),
        "body_text_truncated": bool(event.get("body_text_truncated")),
        "heading_id": str(locator.get("heading_id") or "")[:120],
        "publisher_event_verified": False,
        "approved_for_advisor": False,
    }


def replay_changelog_html(manifest, snapshot_root):
    """Replay the production HTML extractor without any HTTP requests."""
    known = validate_capture_manifest(manifest)
    results = []
    for entry in sorted(manifest["snapshots"], key=lambda x: x["source_id"]):
        sid = entry["source_id"]
        source = known[sid]
        snapshot = entry["snapshot"]
        raw = _snapshot_bytes(
            snapshot, snapshot_root, expected_url=source["url"],
            method="static_html",
        )
        evidence = extract_evidence(
            raw, source["url"], category="changelog", source_id=sid,
        )
        identity = identify_source_product(source, evidence)
        capture_status, reason = assess_capture(
            "changelog", evidence, evidence.get("text", ""),
        )
        events = evidence.get("release_events")
        if (not isinstance(events, list) or len(events) > MAX_EVENTS):
            raise ValueError("Malformed or unbounded changelog release events")
        records = [_event_record(e, sid, source["url"]) for e in events]
        actual_collision = len({e["event_id"] for e in records}) != len(records)
        results.append({
            "source_id": sid,
            "provider": source["provider"],
            "source_url": source["url"],
            "snapshot_sha256": snapshot["sha256"],
            "captured_at_utc": snapshot["captured_at_utc"],
            "capture_status": capture_status,
            "capture_reason": reason,
            "source_expected_product_id": identity["source_expected_product_id"],
            "source_product_title_conflict":
                identity["source_product_title_conflict"],
            "source_product_ownership_verified": False,
            "release_events_schema": evidence.get("release_events_schema"),
            "release_identity_revision": evidence.get("release_identity_revision"),
            "release_window_complete": evidence.get("release_window_complete") is True,
            "release_event_count_detected": evidence.get("release_event_count", 0),
            "release_events_omitted": evidence.get(
                "release_historical_event_count_omitted", 0,
            ),
            "release_recent_body_loss_count": evidence.get(
                "release_recent_body_loss_count", 0,
            ),
            "release_event_identity_collision": bool(
                evidence.get("release_event_identity_collision")
                or actual_collision
            ),
            "release_order_direction": evidence.get("release_order_direction"),
            "release_order_basis": evidence.get("release_order_basis"),
            "release_window_coverage_status":
                evidence.get("release_window_coverage_status"),
            "latest_publication_verified": False,
            "events": records,
            "approved_for_advisor": False,
        })
    report = {
        "schema_version": VERSION,
        "kind": REPLAY_KIND,
        "capture_manifest_sha256": _digest(manifest),
        "source_manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "local_package_sha256": package_fingerprint(),
        "source_count": len(results),
        "sources": results,
        "human_truth_review_completed": False,
        "verified_release_events": 0,
        "new_release_alerts": 0,
        "network_requests_performed": 0,
        "advisor_approved_facts": 0,
        "deployment_authorized": False,
    }
    report["replay_sha256"] = _digest(report)
    return report


def _valid_replay(report):
    if (not isinstance(report, dict)
            or report.get("schema_version") != VERSION
            or report.get("kind") != REPLAY_KIND
            or report.get("human_truth_review_completed") is not False
            or report.get("verified_release_events") != 0
            or report.get("new_release_alerts") != 0
            or report.get("network_requests_performed") != 0
            or report.get("advisor_approved_facts") != 0
            or report.get("deployment_authorized") is not False
            or not isinstance(report.get("sources"), list)
            or not isinstance(report.get("replay_sha256"), str)
            or not HEX64.fullmatch(report["replay_sha256"])):
        raise ValueError("Malformed, privileged or unbounded changelog replay")
    unsigned = dict(report)
    original = unsigned.pop("replay_sha256")
    if _digest(unsigned) != original:
        raise ValueError("Changelog replay checksum mismatch")
    known = _known()
    if (report.get("source_manifest_sha256") != manifest_sha256()
            or report.get("source_registry_sha256") != registry_revision_sha256()
            or not isinstance(report.get("local_package_sha256"), str)
            or not HEX64.fullmatch(report["local_package_sha256"])
            or report.get("source_count") != len(report["sources"])
            or not 1 <= len(report["sources"]) <= MAX_CAPTURE):
        raise ValueError("Replay source/provenance mismatch")
    seen = set()
    for row in report["sources"]:
        sid = row.get("source_id") if isinstance(row, dict) else None
        source = known.get(sid) if isinstance(sid, str) else None
        if (not source or sid in seen or row.get("source_url") != source["url"]
                or row.get("provider") != source["provider"]
                or row.get("approved_for_advisor") is not False
                or row.get("latest_publication_verified") is not False
                or not isinstance(row.get("events"), list)
                or len(row["events"]) > MAX_EVENTS):
            raise ValueError("Changelog replay source invalid")
        seen.add(sid)
        for event in row["events"]:
            _event_record(event, sid, source["url"])
    return {row["source_id"]: row for row in report["sources"]}


def compare_replays(before, after):
    """Two-round structural comparison, never a publication/new-release alert."""
    b, a = _valid_replay(before), _valid_replay(after)
    pins = ("source_manifest_sha256", "source_registry_sha256",
            "local_package_sha256")
    if (b.keys() != a.keys() or any(before.get(k) != after.get(k) for k in pins)):
        raise ValueError("Two-round release comparison needs same source and parser build")
    out = []
    counts = Counter()
    for sid in sorted(a):
        old, current = b[sid], a[sid]
        if (old["source_url"] != current["source_url"]
                or old.get("release_identity_revision") !=
                   current.get("release_identity_revision")
                or old.get("release_events_schema") !=
                   current.get("release_events_schema")):
            raise ValueError("Changelog parser/identity revision must reset baseline")
        old_when = _capture_time(old["captured_at_utc"])
        new_when = _capture_time(current["captured_at_utc"])
        if new_when <= old_when:
            raise ValueError("Second publisher snapshot must be captured later")
        reasons = []
        for row, label in ((old, "baseline"), (current, "current")):
            if row.get("source_product_title_conflict"):
                reasons.append(label + "_product_title_conflict")
            if row.get("capture_status") != "captured":
                reasons.append(label + "_capture_not_healthy")
            if not row.get("release_window_complete"):
                reasons.append(label + "_recognized_window_incomplete")
            if row.get("release_event_identity_collision"):
                reasons.append(label + "_event_identity_collision")
            if row.get("release_recent_body_loss_count"):
                reasons.append(label + "_recent_body_clipped")
            if not row.get("events"):
                reasons.append(label + "_no_release_events")
            if len({x["event_id"] for x in row["events"]}) != len(row["events"]):
                reasons.append(label + "_duplicate_event_id")
        status = "held_for_review" if reasons else "bounded_structural_review_only"
        counts[status] += 1
        changes = []
        if not reasons:
            previous = {x["event_id"]: x for x in old["events"]}
            for event in current["events"]:
                old_event = previous.get(event["event_id"])
                if old_event:
                    if old_event["published_at"] != event["published_at"]:
                        kind = "date_or_publication_evidence_edited_review"
                    elif (old_event["body_sha256"] != event["body_sha256"]
                          or old_event["published_date_provenance"] !=
                             event["published_date_provenance"]):
                        kind = "existing_release_content_or_provenance_edited_review"
                    else:
                        continue
                elif (event["identity_basis"]
                      == "date_scoped_generic_heading_review_only"):
                    kind = "ambiguous_generic_date_or_identity_review"
                elif not event["published_at"]:
                    kind = "first_observed_undated_review"
                elif date.fromisoformat(event["published_at"]) > new_when.date():
                    kind = "future_publication_date_review"
                else:
                    kind = "first_observed_release_identity_review"
                changes.append({
                    "event_id": event["event_id"],
                    "review_change_kind": kind,
                    "publisher_owned_permalink_candidate": event["permalink"],
                    "source_id": sid,
                    "first_observed_not_published_today": True,
                    "human_owner_and_date_review_required": True,
                    "new_release_alert": False,
                    "approved_for_advisor": False,
                })
                counts[kind] += 1
        out.append({
            "source_id": sid,
            "source_url": current["source_url"],
            "baseline_snapshot_sha256": old["snapshot_sha256"],
            "current_snapshot_sha256": current["snapshot_sha256"],
            "release_identity_revision": current["release_identity_revision"],
            "baseline_events_retained": len(old["events"]),
            "current_events_retained": len(current["events"]),
            "status": status,
            "hold_reasons": reasons,
            "review_deltas": changes,
            "new_release_alerts": 0,
            "approved_for_advisor": False,
        })
    return {
        "schema_version": VERSION,
        "kind": COMPARE_KIND,
        "source_count": len(out),
        "before_replay_sha256": before["replay_sha256"],
        "after_replay_sha256": after["replay_sha256"],
        "source_manifest_sha256": before["source_manifest_sha256"],
        "local_package_sha256": before["local_package_sha256"],
        "outcome_counts": dict(sorted(counts.items())),
        "sources": out,
        "independently_verified_publication_dates": 0,
        "new_release_alerts": 0,
        "approved_for_advisor": False,
        "network_requests_performed": 0,
    }


def prepare_blind_release_review(report):
    """Source-balanced human cases with NO inferred dates/titles prefilled."""
    sources = _valid_replay(report)
    queue = []
    per_source = {}
    omitted = 0
    for sid in sorted(sources):
        row = sources[sid]
        # Without owner/location or a trustworthy capture, do not
        # manufacture a reviewer task or claim a matched release.
        if row.get("capture_status") == "blocked":
            continue
        ids = sorted({e["event_id"] for e in row["events"]})
        omitted += max(0, len(ids) - MAX_REVIEW_PER_SOURCE)
        per_source[sid] = ids[:MAX_REVIEW_PER_SOURCE]
    for index in range(MAX_REVIEW_PER_SOURCE):
        for sid, ids in sorted(per_source.items()):
            if index >= len(ids):
                continue
            if len(queue) >= MAX_TOTAL_REVIEW_TASKS:
                omitted += 1
                continue
            row = sources[sid]
            eid = ids[index]
            queue.append({
                "task_id": hashlib.sha256(
                    (sid + "|" + row["snapshot_sha256"] + "|" + eid).encode()
                ).hexdigest()[:24],
                "source_id": sid,
                "source_url": row["source_url"],
                "snapshot_sha256": row["snapshot_sha256"],
                "event_id_for_matching_only": eid,
                "expected_owner_id_prefilled": False,
                "expected_publication_date_prefilled": False,
                "reviewer_fact_approved": False,
            })
    packet = {
        "schema_version": VERSION,
        "kind": TASKS_KIND,
        "replay_sha256": report["replay_sha256"],
        "tasks": queue,
        "omitted_by_bounded_sampling": omitted,
        "sampling": "source_round_robin_max_15_per_source",
        "human_reviewers_required": 2,
        "human_reviewed_cases": 0,
        "publisher_facts_verified": 0,
        "approved_for_advisor": False,
    }
    packet["packet_sha256"] = _digest(packet)
    return packet


def _load(path):
    if (not isinstance(path, Path) or path.is_symlink()
            or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES):
        raise ValueError("Missing, symlinked or oversized private replay metadata")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _private_json(root, name, payload):
    _write_private(
        root / name,
        (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_mutually_exclusive_group(required=True)
    actions.add_argument("--source-pins", action="store_true")
    actions.add_argument("--replay", action="store_true")
    actions.add_argument("--compare", action="store_true")
    actions.add_argument("--blind-review-tasks", action="store_true")
    p.add_argument("--source-ids", help="Exact changelog IDs, comma-separated")
    p.add_argument("--manifest", type=Path)
    p.add_argument("--snapshot-root", type=Path)
    p.add_argument("--before", type=Path)
    p.add_argument("--after", type=Path)
    p.add_argument("--out-dir", type=Path, default=Path(
        "output/private/p19a1-release-replay"
    ))
    args = p.parse_args()
    if args.source_pins:
        if not args.source_ids:
            p.error("--source-pins needs --source-ids")
        print(json.dumps(source_pins(
            [x.strip() for x in args.source_ids.split(",")]
        ), indent=2))
        return
    if args.replay:
        if not args.manifest or not args.snapshot_root:
            p.error("--replay needs --manifest and --snapshot-root")
        output = replay_changelog_html(_load(args.manifest), args.snapshot_root)
        name = "changelog_html_replay.json"
    elif args.compare:
        if not args.before or not args.after:
            p.error("--compare needs --before and --after")
        output = compare_replays(_load(args.before), _load(args.after))
        name = "changelog_two_round_review.json"
    else:
        if not args.after:
            p.error("--blind-review-tasks needs --after")
        output = prepare_blind_release_review(_load(args.after))
        name = "blind_release_owner_date_tasks.json"
    root = _private_new_directory(args.out_dir)
    try:
        _private_json(root, name, output)
        if args.blind_review_tasks:
            for reviewer in ("reviewer_a", "reviewer_b"):
                _private_json(root, reviewer + "_template.json", {
                    "schema_version": VERSION,
                    "kind": "p19a1_independent_release_review_notes_unsubmitted",
                    "reviewer_id": reviewer.upper(),
                    "packet_sha256": output["packet_sha256"],
                    "labels": [],
                    "approved_for_advisor": False,
                })
    except Exception:
        import shutil
        shutil.rmtree(root)
        raise
    print(json.dumps({
        "result": str(root / name),
        "network_requests_performed": 0,
        "new_release_alerts": 0,
        "advisor_approved_facts": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
