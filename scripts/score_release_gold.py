"""P19A2: independent FULL-PAGE changelog release census and conservative scoring.

Only previously captured, immutable, publisher-ORIGIN-UNVERIFIED HTML.
Reviewers inventory ALL visible releases without viewing parser candidates.
Exact reviewed release-owned URLs make TP/FP/FN possible (unlike P19A1's
candidate-only review); disagreements, unknown owners and incomplete page
review BLOCK metrics. Even two agreeing humans do not authenticate the origin.

No HTTP requests, new spiders, source permission promotion, release alerts,
automated advisor approvals, model recommendations or production DB writes.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lxml import html

from agentfuse_crawlers.provider_profiles import load_provider_profiles
from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)
from scripts.replay_release_snapshots import (
    _capture_time, _digest, _valid_replay, replay_changelog_html,
    validate_capture_manifest,
)

VERSION = "1.0"
PACKET_KIND = "p19a2_blind_full_source_release_census_not_gold"
REVIEW_KIND = "p19a2_independent_full_source_human_census"
REPORT_KIND = "p19a2_dual_review_release_owner_date_accuracy_diagnostic"
MAX_EVENTS_PER_SOURCE = 100
MAX_REVIEW_BYTES = 4_000_000
MAX_NOTE = 1200
MAX_QUOTE = 450
MAX_REVIEW_TASKS = 5
SOURCE_FIELDS = frozenset({
    "task_id", "reviewed_full_visible_html", "event_list_complete",
    "unattributed_release_count", "release_count_observed",
    "census_note", "reviewed_at_utc", "events", "approved_for_advisor",
})
EVENT_FIELDS = frozenset({
    "owner_url", "publisher_title", "version", "date_status", "published_at",
    "date_evidence_text", "publisher_evidence_quote", "review_note",
    "approved_for_advisor",
})
REVIEW_FIELDS = frozenset({
    "schema_version", "kind", "reviewer_id", "packet_sha256",
    "independent_blind_review_attested", "source_reviews",
    "approved_for_advisor",
})
DATE_STATES = frozenset({
    "explicit_publication_day", "explicitly_undated", "ambiguous",
})
SAFE_PATH = re.compile(r"^/[a-zA-Z0-9/_~.-]+$")
SAFE_ANCHOR = re.compile(r"^[a-zA-Z0-9_.:-]{1,120}$")
REVIEWER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_ .@-]{3,79}$")
DAY = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
HOLDOUT_KEY_MIN = 32
MIN_PROVIDER_GROUPS_FOR_EVALUATION = 5
MIN_CONSENSUS_EVENTS_FOR_EVALUATION = 25
MIN_HOLDOUT_GROUPS_FOR_EVALUATION = 2
MIN_HOLDOUT_EVENTS_FOR_EVALUATION = 10


def _text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _bounded(value, *, label, minimum=1, maximum=500):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError("Invalid or missing " + label)
    return value.strip()


def _split_key(key):
    if (not isinstance(key, str) or not HOLDOUT_KEY_MIN <= len(key) <= 256
            or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise ValueError("HMAC split key must be 32-256 printable ASCII characters")
    return key.encode("ascii")


def _ratio(top, bottom):
    return top / bottom if bottom else None


def _pin_and_recompute(replay, manifest, snapshot_root):
    """Reject self-hashed forged replay and check exact archived source bytes."""
    sources = _valid_replay(replay)
    known = validate_capture_manifest(manifest)
    if (replay.get("capture_manifest_sha256") != _digest(manifest)
            or set(sources) != {e["source_id"] for e in manifest["snapshots"]}):
        raise ValueError("Publisher snapshot and P19A1 replay binding differs")
    refreshed = replay_changelog_html(manifest, snapshot_root)
    if replay != refreshed:
        raise ValueError("Current package replay differs from actual original HTML bytes")
    raw = {}
    for entry in manifest["snapshots"]:
        sid = entry["source_id"]
        raw[sid] = _snapshot_bytes(
            entry["snapshot"], snapshot_root, expected_url=known[sid]["url"],
            method="static_html",
        )
        if (entry["snapshot"]["sha256"] != sources[sid]["snapshot_sha256"]
                or _capture_time(entry["snapshot"]["captured_at_utc"]) !=
                    _capture_time(sources[sid]["captured_at_utc"])):
            raise ValueError("Review snapshot hash/capture-time mismatch")
    return sources, raw


def _group(source_id, row, profiles):
    profile = profiles.get(source_id)
    if profile:
        return "profile_provider:" + profile["provider_id"]
    # Fallback manifest label is a tentative grouping ONLY, not ownership.
    return "manifest_provider:" + _text(row["provider"])


def prepare_census_packet(replay, manifest, snapshot_root, *,
                          split_key, holdout_percent=25):
    """Separate independent *source-wide* human page census from predictions."""
    key = _split_key(split_key)
    if (type(holdout_percent) is not int or not 10 <= holdout_percent <= 40):
        raise ValueError("Holdout percent must be an integer from 10 to 40")
    sources, _ = _pin_and_recompute(replay, manifest, snapshot_root)
    if len(sources) > MAX_REVIEW_TASKS:
        raise ValueError("Review packet exceeds maximum source count")
    profiles = load_provider_profiles()
    tasks = []
    for sid, row in sorted(sources.items()):
        group = _group(sid, row, profiles)
        score = int.from_bytes(
            hmac.new(key, ("p19a2-provider-holdout-v1|" + group).encode(),
                     hashlib.sha256).digest()[:8], "big",
        ) % 100
        tasks.append({
            "task_id": hashlib.sha256(
                ("p19a2|full-html|" + sid + "|" + row["snapshot_sha256"] +
                 "|" + replay["replay_sha256"]).encode()
            ).hexdigest()[:24],
            "source_id": sid,
            "source_url": row["source_url"],
            "snapshot_sha256": row["snapshot_sha256"],
            "captured_at_utc": row["captured_at_utc"],
            "provisional_provider_group": group,
            "evaluation_split": (
                "holdout" if score < holdout_percent else "development"
            ),
            "census_scope": "entire_original_frozen_html_page",
            "predicted_release_ids_prefilled": False,
            "predicted_titles_prefilled": False,
            "predicted_dates_prefilled": False,
            "independent_owner_and_date_gold_verified": False,
            "approved_for_advisor": False,
        })
    packet = {
        "schema_version": VERSION,
        "kind": PACKET_KIND,
        "replay_sha256": replay["replay_sha256"],
        "capture_manifest_sha256": replay["capture_manifest_sha256"],
        "source_manifest_sha256": replay["source_manifest_sha256"],
        "source_registry_sha256": replay["source_registry_sha256"],
        "local_package_sha256": replay["local_package_sha256"],
        "split_key_commitment_sha256": hashlib.sha256(
            b"p19a2-split-key-commitment-v1|" + key
        ).hexdigest(),
        "holdout_percent": holdout_percent,
        "provider_group_count": len({
            task["provisional_provider_group"] for task in tasks
        }),
        "tasks": tasks,
        "sampling": "all_configured_frozen_sources_no_parser_candidate_sampling",
        "reviewers_required": 2,
        "human_source_censuses_completed": 0,
        "independently_verified_publisher_releases": 0,
        "benchmark_approval": False,
        "approved_for_advisor": False,
    }
    packet["packet_sha256"] = _digest(packet)
    return packet


def reviewer_template(packet, reviewer_letter):
    """Blank source inventory: never prefill parser-predicted events or dates."""
    if reviewer_letter not in {"a", "b"}:
        raise ValueError("Reviewer template must be A or B")
    return {
        "schema_version": VERSION,
        "kind": REVIEW_KIND,
        "reviewer_id": "REPLACE_WITH_DISTINCT_REVIEWER_" + reviewer_letter.upper(),
        "packet_sha256": packet["packet_sha256"],
        "independent_blind_review_attested": False,
        "source_reviews": [{
            "task_id": task["task_id"],
            "reviewed_full_visible_html": False,
            "event_list_complete": False,
            "unattributed_release_count": 0,
            "release_count_observed": 0,
            "census_note": "",
            "reviewed_at_utc": None,
            "events": [],
            "approved_for_advisor": False,
        } for task in packet["tasks"]],
        "approved_for_advisor": False,
    }


def _full_day(text):
    """Independent full-year reference parsing; never infer a missing year."""
    raw = re.sub(
        r"^(published|released)(?:\s+on)?\s*[:—-]?\s*", "",
        text.strip(), flags=re.I,
    )
    raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", raw, flags=re.I)
    formats = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y",
               "%d %B %Y", "%d %b %Y")
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _owner_node(source_url, owner_url, root):
    """Require publisher-owned in-document ID or exactly linked nested release."""
    if (not isinstance(owner_url, str) or not 1 <= len(owner_url) <= 800
            or not owner_url.isascii() or any(
                bad in owner_url for bad in ("\\", "%", "?")
            ) or any(ord(c) <= 32 or ord(c) == 127 for c in owner_url)):
        raise ValueError("Unsafe or absent manually labeled release owner URL")
    try:
        base, ref = urlsplit(source_url), urlsplit(owner_url)
        if (ref.scheme != "https" or ref.netloc != base.netloc
                or ref.username is not None or ref.password is not None
                or ref.port not in (None, 443)
                or not SAFE_PATH.fullmatch(ref.path)
                or "//" in ref.path or any(
                    part in {".", ".."} for part in ref.path.split("/")
                )):
            raise ValueError("Release owner URL differs from pinned publisher")
    except ValueError as exc:
        raise ValueError("Release owner URL is unsafe or malformed") from exc
    candidates = []
    if ref.path.rstrip("/") == base.path.rstrip("/"):
        if not SAFE_ANCHOR.fullmatch(ref.fragment):
            raise ValueError("A shared changelog index is NOT a release owner")
        candidates = root.xpath("//*[@id=$anchor]", anchor=ref.fragment)
    elif (ref.path.startswith(base.path.rstrip("/") + "/")
          and (not ref.fragment or SAFE_ANCHOR.fullmatch(ref.fragment))):
        candidates = [
            node for node in root.xpath("//a[@href]")
            if urljoin(source_url, node.get("href", "")) == owner_url
        ]
    else:
        raise ValueError("Release URL must be a page anchor or nested release path")
    if len(candidates) != 1:
        raise ValueError("Publisher release owner absent or duplicated in original HTML")
    node = candidates[0]
    # Expand a heading to its unique release card, never to a multi-event
    # parent that could make another entry's quote/date seem attributable.
    for ancestor in [node, *list(node.iterancestors())[:6]]:
        if (ancestor.tag in {"article", "section", "li", "div"}
                and len(ancestor.xpath(".//h2|.//h3|.//h4|.//h5")) == 1
                and len(_text(" ".join(ancestor.itertext()))) <= 16000):
            return ancestor
    return node


def _visible(root):
    return _text(" ".join(
        part for part in root.itertext() if isinstance(part, str) and part.strip()
    ))


def _review_label(event, task, root, whole_text):
    if (not isinstance(event, dict) or set(event) != EVENT_FIELDS
            or event.get("approved_for_advisor") is not False):
        raise ValueError("Review label must have exact unprivileged fields")
    owner = event.get("owner_url")
    card = _owner_node(task["source_url"], owner, root)
    card_text = _visible(card)
    title = _bounded(event.get("publisher_title"), label="publisher release title",
                     minimum=6, maximum=180)
    if _text(title) not in card_text:
        raise ValueError("Reviewed title missing from exact release-owned DOM node")
    quote = _bounded(event.get("publisher_evidence_quote"),
                     label="independent original publisher quote",
                     minimum=24, maximum=MAX_QUOTE)
    quoted = _text(quote)
    if quoted not in card_text or whole_text.count(quoted) != 1:
        raise ValueError("Release quote must uniquely identify its original card")
    _bounded(event.get("review_note"), label="reviewer release evidence note",
             minimum=24, maximum=MAX_NOTE)
    version = event.get("version")
    if (version is not None and (not isinstance(version, str)
            or not 1 <= len(version.strip()) <= 80)):
        raise ValueError("Invalid human-review version")
    state = event.get("date_status")
    if state not in DATE_STATES:
        raise ValueError("Date must be explicit, undated or unresolved")
    declared = event.get("published_at")
    date_text = event.get("date_evidence_text")
    if not isinstance(date_text, str) or len(date_text) > 100:
        raise ValueError("Malformed explicit publication evidence")
    if state == "explicit_publication_day":
        if not isinstance(declared, str) or not DAY.fullmatch(declared):
            raise ValueError("Full human-labeled ISO publication day required")
        try:
            date.fromisoformat(declared)
        except ValueError as exc:
            raise ValueError("Impossible human-labeled publication day") from exc
        if _full_day(date_text) != declared:
            raise ValueError("Day cannot be inferred from ambiguous or partial text")
        # The exact independently recorded date must appear visibly in its
        # specific release card or as its original explicit <time datetime>.
        match_visible = _text(date_text) in card_text
        match_time = any(
            (node.get("datetime") or "")[:10] == declared and not any(
                marker in " ".join(str(node.get(k, "")) for k in (
                    "itemprop", "class", "aria-label"
                )).casefold()
                for marker in ("modified", "updated", "edited")
            ) for node in card.xpath(".//time")
        )
        if not (match_visible or match_time):
            raise ValueError("Publication date evidence is not in release-owned card")
    elif declared is not None or date_text.strip():
        raise ValueError("Unknown/undated gold cannot invent publication day")
    return {
        "owner_url": owner,
        "publisher_title": _text(title),
        "version": version.strip() if version is not None else None,
        "date_status": state,
        "published_at": declared,
    }


def _validate_reviewer(reviewer, packet, raw):
    if (not isinstance(reviewer, dict) or set(reviewer) != REVIEW_FIELDS
            or reviewer["schema_version"] != VERSION
            or reviewer["kind"] != REVIEW_KIND
            or reviewer["approved_for_advisor"] is not False
            or reviewer["packet_sha256"] != packet["packet_sha256"]
            or reviewer["independent_blind_review_attested"] is not True
            or not isinstance(reviewer["reviewer_id"], str)
            or not REVIEWER.fullmatch(reviewer["reviewer_id"])
            or reviewer["reviewer_id"].startswith("REPLACE_WITH_")
            or not isinstance(reviewer["source_reviews"], list)
            or len(reviewer["source_reviews"]) != len(packet["tasks"])):
        raise ValueError("Missing complete independent reviewer census or attestation")
    tasks = {t["task_id"]: t for t in packet["tasks"]}
    recorded = {}
    for source in reviewer["source_reviews"]:
        if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
            raise ValueError("Malformed source-wide reviewer record")
        tid = source["task_id"]
        if tid not in tasks or tid in recorded:
            raise ValueError("Reviewer source census task missing or duplicated")
        task = tasks[tid]
        if (source["approved_for_advisor"] is not False
                or type(source["reviewed_full_visible_html"]) is not bool
                or type(source["event_list_complete"]) is not bool):
            raise ValueError("Reviewer cannot promote facts or infer page completeness")
        for count in ("unattributed_release_count", "release_count_observed"):
            if type(source[count]) is not int or not 0 <= source[count] <= 1000:
                raise ValueError("Reviewer must account for all visible release candidates")
        if (not isinstance(source["events"], list)
                or len(source["events"]) > MAX_EVENTS_PER_SOURCE
                or source["release_count_observed"] !=
                   len(source["events"]) + source["unattributed_release_count"]):
            raise ValueError("Human census is oversized or hides unowned releases")
        _bounded(source["census_note"], label="whole-page human review note",
                 minimum=40, maximum=MAX_NOTE)
        reviewed = _capture_time(source["reviewed_at_utc"])
        captured = _capture_time(task["captured_at_utc"])
        if reviewed < captured:
            raise ValueError("Reviewer observation predates original HTML snapshot")
        root = html.fromstring(raw[task["source_id"]])
        for node in list(root.xpath("//script|//style|//noscript")):
            node.drop_tree()
        whole = _visible(root)
        gold = {}
        for value in source["events"]:
            checked = _review_label(value, task, root, whole)
            owner_url = checked["owner_url"]
            if owner_url in gold:
                raise ValueError("Duplicate independently reviewed publisher release owner")
            gold[owner_url] = checked
        recorded[tid] = {
            "complete": (source["reviewed_full_visible_html"] is True
                         and source["event_list_complete"] is True),
            "unattributed": source["unattributed_release_count"],
            "census_size": source["release_count_observed"],
            "events": gold,
        }
    return recorded


def score_census(replay, manifest, snapshot_root, packet,
                 reviewer_a, reviewer_b, *, split_key,
                 holdout_percent=25):
    """Census-derived owner TP/FP/FN; unknown and disagreement are NOT zeroes."""
    sources, raw = _pin_and_recompute(replay, manifest, snapshot_root)
    expected = prepare_census_packet(
        replay, manifest, snapshot_root, split_key=split_key,
        holdout_percent=holdout_percent,
    )
    if packet != expected:
        raise ValueError("Blind packet/split differs from original source-bound replay")
    if (not isinstance(reviewer_a, dict) or not isinstance(reviewer_b, dict)
            or reviewer_a.get("reviewer_id", "").strip().casefold()
               == reviewer_b.get("reviewer_id", "").strip().casefold()):
        raise ValueError("Independent reviewers must have distinct identities")
    left = _validate_reviewer(reviewer_a, packet, raw)
    right = _validate_reviewer(reviewer_b, packet, raw)
    output = []
    overall = Counter()
    splits = {"development": Counter(), "holdout": Counter()}
    groups = {"development": set(), "holdout": set()}
    group_sources = {"development": set(), "holdout": set()}
    for task in packet["tasks"]:
        tid = task["task_id"]
        sid = task["source_id"]
        split = task["evaluation_split"]
        old = left[tid]
        new = right[tid]
        row = sources[sid]
        holds = []
        if not old["complete"] or not new["complete"]:
            holds.append("whole_original_page_not_fully_reviewed")
        if old["unattributed"] or new["unattributed"]:
            holds.append("publisher_release_owner_unattributed")
        if old["census_size"] != new["census_size"]:
            holds.append("reviewer_visible_release_counts_disagree")
        if old["events"] != new["events"]:
            holds.append("independent_reviewer_owner_title_date_or_version_disagreement")
        if row.get("capture_status") != "captured":
            holds.append("parser_capture_not_healthy")
        if row.get("source_product_title_conflict"):
            holds.append("expected_source_product_owner_unresolved")
        if row.get("release_events_omitted"):
            holds.append("parser_recent_window_omits_visible_releases")
        if row.get("release_recent_body_loss_count"):
            holds.append("parser_recent_event_body_truncated")
        if not row.get("release_window_complete"):
            holds.append("parser_recognized_window_incomplete")
        if row.get("release_event_identity_collision"):
            holds.append("parser_release_owner_identity_collision")
        if row.get("release_event_count_detected") != len(row["events"]):
            holds.append("parser_reported_release_count_not_full_page")
        parsed_urls = {}
        if not holds:
            doc = html.fromstring(raw[sid])
            for event in row["events"]:
                candidate = event["permalink"]
                if (event["identity_basis"] == "date_scoped_generic_heading_review_only"
                        or event.get("release_identity_requires_manual_review")):
                    holds.append("date_scoped_or_generic_parser_identity")
                    break
                try:
                    node = _owner_node(row["source_url"], candidate, doc)
                    if _text(event["title"]) not in _visible(node):
                        holds.append("parser_release_title_not_in_owned_card")
                        break
                except ValueError:
                    holds.append("parser_release_owner_unattributable")
                    break
                if candidate in parsed_urls:
                    holds.append("two_predicted_releases_claim_same_owner")
                    break
                parsed_urls[candidate] = event
        metrics = None
        if not holds:
            gold = old["events"]
            match = set(parsed_urls) & set(gold)
            tp = len(match)
            fp = len(parsed_urls) - tp
            fn = len(gold) - tp
            date_total = 0
            date_exact = 0
            date_unresolved = 0
            title_exact = 0
            version_total = 0
            version_exact = 0
            for url in match:
                expected_event = gold[url]
                observed = parsed_urls[url]
                title_exact += _text(observed["title"]) == expected_event["publisher_title"]
                if expected_event["version"] is not None:
                    version_total += 1
                    version_exact += observed.get("version") == expected_event["version"]
                date_state = expected_event["date_status"]
                if date_state == "ambiguous":
                    date_unresolved += 1
                    continue
                date_total += 1
                if date_state == "explicit_publication_day":
                    date_exact += observed.get("published_at") == expected_event["published_at"]
                else:
                    date_exact += observed.get("published_at") is None
            metrics = {
                "release_owner_tp": tp, "release_owner_fp": fp,
                "release_owner_fn": fn,
                "owner_precision": _ratio(tp, tp + fp),
                "owner_recall": _ratio(tp, tp + fn),
                "title_exact_matches": title_exact,
                "title_checked_matches": tp,
                "version_exact_matches": version_exact,
                "version_checked_matches": version_total,
                "publication_date_exact_matches": date_exact,
                "publication_date_checked_matches": date_total,
                "publication_date_unresolved_reference_matches": date_unresolved,
                "publication_date_exact_rate": _ratio(date_exact, date_total),
            }
            totals = splits[split]
            for key in (
                "release_owner_tp", "release_owner_fp", "release_owner_fn",
                "publication_date_exact_matches",
                "publication_date_checked_matches",
            ):
                totals[key] += metrics[key]
            totals["gold_event_count"] += len(gold)
            totals["scored_source_count"] += 1
            groups[split].add(task["provisional_provider_group"])
            group_sources[split].add(sid)
            overall["source_census_scored_diagnostic_only"] += 1
        else:
            overall["source_held_unscorable"] += 1
            for reason in sorted(set(holds)):
                overall[reason] += 1
        output.append({
            "source_id": sid,
            "source_url": task["source_url"],
            "snapshot_sha256": task["snapshot_sha256"],
            "source_wide_census_task_id": tid,
            "evaluation_split": split,
            "provisional_provider_group": task["provisional_provider_group"],
            "reviewer_a_visible_release_count": old["census_size"],
            "reviewer_b_visible_release_count": new["census_size"],
            "parser_retained_release_count": len(row["events"]),
            "status": "dual_review_agreed_snapshot_diagnostic" if metrics else
                      "held_no_accuracy_claim",
            "hold_reasons": sorted(set(holds)),
            "diagnostic_only_metrics": metrics,
            "publisher_release_facts_authenticated": False,
            "new_release_alerts": 0,
            "approved_for_advisor": False,
        })
    development = splits["development"]
    holdout = splits["holdout"]
    provider_groups_total = len(groups["development"] | groups["holdout"])
    total_gold = development["gold_event_count"] + holdout["gold_event_count"]
    coverage = bool(
        provider_groups_total >= MIN_PROVIDER_GROUPS_FOR_EVALUATION
        and total_gold >= MIN_CONSENSUS_EVENTS_FOR_EVALUATION
        and len(groups["holdout"]) >= MIN_HOLDOUT_GROUPS_FOR_EVALUATION
        and holdout["gold_event_count"] >= MIN_HOLDOUT_EVENTS_FOR_EVALUATION
        and development["scored_source_count"] > 0
        and holdout["scored_source_count"] > 0
    )
    summaries = {}
    for split in ("development", "holdout"):
        counter = splits[split]
        tp, fp, fn = (counter["release_owner_tp"], counter["release_owner_fp"],
                       counter["release_owner_fn"])
        summaries[split] = {
            "scored_sources": counter["scored_source_count"],
            "scored_provider_groups": len(groups[split]),
            "gold_events": counter["gold_event_count"],
            "owner_tp": tp, "owner_fp": fp, "owner_fn": fn,
            "diagnostic_owner_precision": _ratio(tp, tp + fp),
            "diagnostic_owner_recall": _ratio(tp, tp + fn),
            "date_exact": counter["publication_date_exact_matches"],
            "date_checked": counter["publication_date_checked_matches"],
            "diagnostic_date_exact_rate": _ratio(
                counter["publication_date_exact_matches"],
                counter["publication_date_checked_matches"],
            ),
            "verified_publisher_accuracy": False,
        }
    return {
        "schema_version": VERSION,
        "kind": REPORT_KIND,
        "capture_manifest_sha256": replay["capture_manifest_sha256"],
        "replay_sha256": replay["replay_sha256"],
        "blind_census_packet_sha256": packet["packet_sha256"],
        "source_manifest_sha256": replay["source_manifest_sha256"],
        "local_package_sha256": replay["local_package_sha256"],
        "reviewer_ids_distinct": True,
        "reviewer_independence_operator_attested_not_cryptographically_proven": True,
        "source_count": len(output),
        "outcome_counts": dict(sorted(overall.items())),
        "sources": output,
        "splits": summaries,
        "sample_diversity_thresholds_met": coverage,
        "independently_authenticated_publisher_origin": False,
        "publisher_truth_verified": False,
        "generalizable_release_accuracy_established": False,
        "benchmark_or_adapter_rollout_authorized": False,
        "new_release_alerts": 0,
        "advisor_fact_approvals": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }


def _load(path):
    if (not isinstance(path, Path) or path.is_symlink()
            or not path.is_file() or path.stat().st_size > MAX_REVIEW_BYTES):
        raise ValueError("Missing/symlinked/oversized private release gold JSON")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(root, name, value):
    _write_private(
        root / name,
        (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--score", action="store_true")
    p.add_argument("--replay", type=Path, required=True)
    p.add_argument("--capture-manifest", type=Path, required=True)
    p.add_argument("--snapshot-root", type=Path, required=True)
    p.add_argument("--packet", type=Path)
    p.add_argument("--reviewer-a", type=Path)
    p.add_argument("--reviewer-b", type=Path)
    p.add_argument("--holdout-percent", type=int, default=25)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    key = os.environ.get("AGENTFUSE_RELEASE_GOLD_SPLIT_KEY", "")
    if not key:
        p.error("AGENTFUSE_RELEASE_GOLD_SPLIT_KEY must be private and set")
    replay = _load(args.replay)
    manifest = _load(args.capture_manifest)
    if args.prepare:
        result = prepare_census_packet(
            replay, manifest, args.snapshot_root,
            split_key=key, holdout_percent=args.holdout_percent,
        )
    else:
        if not args.packet or not args.reviewer_a or not args.reviewer_b:
            p.error("--score requires --packet --reviewer-a --reviewer-b")
        result = score_census(
            replay, manifest, args.snapshot_root, _load(args.packet),
            _load(args.reviewer_a), _load(args.reviewer_b),
            split_key=key, holdout_percent=args.holdout_percent,
        )
    root = _private_new_directory(args.out_dir)
    try:
        filename = "blind_source_census_packet.json" if args.prepare else (
            "dual_review_release_gold_diagnostics.json"
        )
        _write(root, filename, result)
        if args.prepare:
            _write(root, "reviewer_a_template.json", reviewer_template(result, "a"))
            _write(root, "reviewer_b_template.json", reviewer_template(result, "b"))
    except Exception:
        shutil.rmtree(root)
        raise
    print(json.dumps({
        "private_result": str(root / filename),
        "publisher_truth_verified": False,
        "advisor_fact_approvals": 0,
        "new_release_alerts": 0,
        "network_requests_performed": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
