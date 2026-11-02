"""P15B: blind, dual-review, snapshot-bound gold for pricing, dates and docs.

This offline module intentionally requires an *independent* publisher snapshot
for each reviewed case. The original Zyte Item or a crawler-generated excerpt
does not become ground truth by passing tests. Archive binding verifies the
crawler observation, NOT that a human reading the publisher snapshot is right.

No network, live fetching, source policy promotion, approvals, or DB writes.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from lxml import html

from agentfuse_crawlers.sources import load_sources
from scripts.quality_gates import RATE_FIELDS
from scripts.real_gold_binding import (
    _sha_json, prepare_review_candidates,
)

SHA = re.compile(r"^[a-f0-9]{64}$")
PRICE_ID = re.compile(r"^[a-f0-9]{32}$")
CASE_RE = re.compile(r"^[a-f0-9]{24}$")
MAX_SNAPSHOT_BYTES = 2_000_000
MAX_CACHED_SNAPSHOTS = 8
MAX_TASKS = 3600
MIN_SPLIT_KEY_BYTES = 16
MIN_REVIEW_NOTE = 24
MAX_REVIEW_NOTE = 1200
MIN_QUOTE = 24
MAX_QUOTE = 450
MAX_SNAPSHOT_AGE_HOURS = 24
SCHEMA = "1.0"
SOURCE_BY_ID = {x["id"]: x for x in load_sources()}
KINDS = {"pricing", "release_dates", "documentation"}
RESOLUTIONS = {
    "pricing": {"established", "incomplete", "unresolved"},
    "release_dates": {"published_date", "explicitly_undated", "unresolved"},
    "documentation": {"topic_relevant", "topic_irrelevant", "unresolved"},
}
SUPPORT_STATES = {"supported", "unsupported", "conditional", "unknown"}


def _normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Review/snapshot timestamp must be ISO 8601")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid review/snapshot timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError("Review/snapshot timestamp needs a timezone")
    return dt.astimezone(timezone.utc)


def _same_official_host(url, official):
    if not isinstance(url, str) or not isinstance(official, str) or len(url) > 900:
        return False
    try:
        a, b = urlsplit(url), urlsplit(official)
        return bool(
            a.scheme == b.scheme == "https" and a.hostname and
            a.hostname == b.hostname and a.port in (None, 443)
            and not a.username and not a.password and not a.query
            and not a.fragment and not a.path.startswith("//")
        )
    except (ValueError, TypeError):
        return False


def _required_key(key):
    if isinstance(key, str):
        key = key.encode("utf-8")
    if not isinstance(key, bytes) or len(key) < MIN_SPLIT_KEY_BYTES:
        raise ValueError("Private split key must be at least 16 UTF-8 bytes")
    return key


def _blind_hint(raw):
    """Keep non-factual navigation cues but redact numeric price/date leaks."""
    if not isinstance(raw, str):
        return ""
    text = raw[:300]
    # Publisher headings can themselves embed publication dates. They may
    # orient the reviewer, but cannot silently prefill the gold answer.
    text = re.sub(r"\b20\d\d[-/]\d{1,2}[-/]\d{1,2}\b",
                  "[DATE REDACTED]", text)
    text = re.sub(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
        r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
        r"\d{1,2}(?:,?\s+20\d\d)?\b",
        "[DATE REDACTED]", text, flags=re.I,
    )
    text = re.sub(
        r"(?:[$€£]\s*\d[\d,.]*|\b(?:USD|EUR|GBP)\s+\d[\d,.]*)",
        "[PRICE REDACTED]", text, flags=re.I,
    )
    return text[:150]


def _case_id(kind, sample):
    ident = {
        "pricing": "observation_id", "release_dates": "event_id",
        "documentation": "candidate_id",
    }[kind]
    return hashlib.sha256((
        kind + "|" + sample["source_id"] + "|" + sample["job_id"]
        + "|" + str(sample[ident])
    ).encode("utf-8")).hexdigest()[:24]


def _check_candidate_packet(packet):
    if (not isinstance(packet, dict)
            or packet.get("kind") !=
               "unreviewed_offline_publisher_evidence_candidates_not_gold"
            or packet.get("human_review_completed") is not False
            or packet.get("not_for_release_quality_gates") is not True
            or packet.get("advisor_fact_approvals") != 0
            or packet.get("independently_verified_vendor_facts") != 0
            or not isinstance(packet.get("package_sha256"), str)
            or not SHA.fullmatch(packet["package_sha256"])
            or not isinstance(packet.get("samples"), dict)
            or set(packet["samples"]) != KINDS):
        raise ValueError("Input must be the P14A unreviewed, archive-derived candidate packet")


def prepare_blind_bundle(packet, *, split_key, holdout_percent=25):
    """Build cases and reviewer templates WITHOUT prices, dates or claims.

    Every product/provider is allocated to one partition, not split by row:
    near-identical sources therefore cannot leak from training to holdout.
    Private HMAC split key is never serialized into a report.
    """
    _check_candidate_packet(packet)
    key = _required_key(split_key)
    if (type(holdout_percent) is not int or
            not 10 <= holdout_percent <= 50):
        raise ValueError("Holdout percent must be an integer from 10 to 50")
    seen_identities = set()
    tasks = []
    for kind in sorted(KINDS):
        examples = packet["samples"][kind]
        if not isinstance(examples, list):
            raise ValueError("Malformed unreviewed candidates")
        for sample in examples:
            if (not isinstance(sample, dict)
                    or sample.get("approved_for_advisor") is not False):
                raise ValueError("Candidate cannot authorize a publisher fact")
            sid = sample.get("source_id")
            known = SOURCE_BY_ID.get(sid) if isinstance(sid, str) else None
            category = {"pricing": "pricing", "release_dates": "changelog",
                        "documentation": "documentation"}[kind]
            ident = {"pricing": "observation_id", "release_dates": "event_id",
                     "documentation": "candidate_id"}[kind]
            val = sample.get(ident)
            if (not known or known["category"] != category
                    or known["url"] != sample.get("source_url")
                    or not re.fullmatch(r"\d+/\d+/\d+", str(sample.get("job_id")))
                    or (kind == "pricing" and
                        (not isinstance(val, str) or not PRICE_ID.fullmatch(val)))
                    or (kind == "documentation" and
                        (not isinstance(val, str) or not CASE_RE.fullmatch(val)))
                    or (kind == "release_dates" and
                        (not isinstance(val, str) or
                         not val.startswith(sid + ":")))
                    or not isinstance(sample.get("content_sha256"), str)
                    or not SHA.fullmatch(sample["content_sha256"])):
                raise ValueError("Candidate source or typed observation identity is not pinned")
            identity = (kind, sid, str(val))
            if identity in seen_identities:
                raise ValueError("Repeated publisher observation cannot inflate reviewed gold")
            seen_identities.add(identity)
            evidence_url = sample.get("evidence_url") or known["url"]
            # Original page may carry a fragment; separate offline snapshot
            # URLs never accept query secrets or arbitrary external hosts.
            if not _same_official_host(evidence_url.split("#", 1)[0], known["url"]):
                raise ValueError("Review candidate points to a foreign publisher")
            task = {
                "case_id": _case_id(kind, sample),
                "kind": kind,
                "source_id": sid,
                "provider": known["provider"],
                "job_id": sample["job_id"],
                "source_url": known["url"],
                "publisher_evidence_url": evidence_url.split("#", 1)[0],
                "archived_extracted_content_sha256": sample["content_sha256"],
                "observation_identity": str(val),
                # These are unverified *navigation cues*, not proposed truth.
                "target_title_hint": _blind_hint(
                    sample.get("title") if kind == "release_dates" else
                    sample.get("topic_hint") if kind == "documentation" else
                    sample.get("observed", {}).get("model_or_service")
                ),
                "target_dimension_hint": (
                    sample.get("observed", {}).get("price_dimension")
                    if kind == "pricing" else ""
                ) or "",
                "review_status": "unreviewed",
                "original_page_snapshot_required": True,
                "approved_for_advisor": False,
            }
            # Only text labels, never price amount, date, blockers or
            # "supported" statuses, enter the blind annotation view.
            tasks.append(task)
    if len(tasks) > MAX_TASKS:
        raise ValueError("Unreviewed packet exceeds bounded blind case count")
    providers = sorted({t["provider"].strip().casefold() for t in tasks})
    ranked = sorted(
        providers, key=lambda p: (
            hmac.new(key, ("p15b-provider|" + p).encode(), hashlib.sha256).digest(),
            p,
        )
    )
    held = set(ranked[:max(1, round(len(providers) * holdout_percent / 100))]
               ) if len(providers) >= 2 else set()
    for task in tasks:
        task["partition"] = (
            "holdout" if task["provider"].strip().casefold() in held
            else "train"
        )
    tasks.sort(key=lambda r: (r["kind"], r["source_id"], r["case_id"]))
    basis = {
        "schema_version": SCHEMA,
        "kind": "blind_source_grouped_review_tasks_not_publisher_truth",
        "candidate_packet_sha256": _sha_json(packet),
        "package_sha256": packet["package_sha256"],
        "split_scheme": "private_hmac_sha256_by_provider_v1",
        "split_key_sha256_commitment": hashlib.sha256(key).hexdigest(),
        "holdout_percent": holdout_percent,
        "tasks": tasks,
        "synthetic_only": False,
        "independent_publisher_truth_confirmed": False,
        "advisor_fact_approvals": 0,
        "network_requests_performed": 0,
    }
    basis["task_bundle_sha256"] = _sha_json(basis)
    return basis


def reviewer_template(bundle, reviewer_id):
    if not isinstance(reviewer_id, str) or not 3 <= len(reviewer_id.strip()) <= 80:
        raise ValueError("Reviewer identifier required")
    return {
        "schema_version": SCHEMA,
        "kind": "independent_blind_publisher_review_annotations",
        "reviewer_id": reviewer_id,
        "task_bundle_sha256": bundle["task_bundle_sha256"],
        "synthetic_only": False,
        "approved_for_advisor": False,
        "labels": [],  # No proposed expected truth; human must fill this.
    }


def _publisher_snapshot_text(snap, root, task, archived, *, cache):
    """Verify the bytes and temporal context of a separately collected page.

    A checked snapshot SHA does not authenticate who downloaded it. The human
    reviewers remain responsible for checking publisher ownership and facts.
    """
    sid, case_id = task["source_id"], task["case_id"]
    if (not isinstance(snap, dict) or snap.get("case_id") != case_id
            or snap.get("source_id") != sid
            or snap.get("approved_for_advisor") is not False):
        raise ValueError("Publisher snapshot case/source identity mismatch")
    relative = snap.get("file")
    if (not isinstance(relative, str) or not relative
            or Path(relative).is_absolute() or
            not all(part not in {"..", ".", ""} for part in Path(relative).parts)):
        raise ValueError("Publisher snapshot must have a safe relative path")
    if not _same_official_host(snap.get("publisher_url"), task["source_url"]):
        raise ValueError("Publisher snapshot URL must match original first-party host")
    # A page on the same host can document a completely different
    # product or release. The pinned task permalink/path is binding.
    original = urlsplit(task["publisher_evidence_url"])
    actual = urlsplit(snap["publisher_url"])
    if actual.path.rstrip("/") != original.path.rstrip("/"):
        raise ValueError("Publisher snapshot path differs from reviewed source page")
    if snap.get("media_type") not in {
        "text/html", "text/plain", "text/markdown", "application/json"
    }:
        raise ValueError("Unsupported publisher evidence snapshot media type")
    digest = snap.get("sha256")
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("Publisher evidence requires a real SHA-256")
    capture = _timestamp(snap.get("captured_at_utc"))
    item_stamp = _timestamp(archived.get("fetched_at_utc"))
    if abs((capture - item_stamp).total_seconds()) > MAX_SNAPSHOT_AGE_HOURS * 3600:
        raise ValueError("Publisher snapshot is not contemporaneous with the crawler Item")
    base = Path(root).resolve(strict=True)
    path = base.joinpath(relative)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
        raise ValueError("Snapshot path missing, a symlink, or outside private root")
    size = path.stat().st_size
    if not 1 <= size <= MAX_SNAPSHOT_BYTES:
        raise ValueError("Publisher snapshot exceeds bounded size or is empty")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Publisher evidence snapshot SHA-256 mismatch")
    cache_key = (str(path), digest)
    if cache_key not in cache:
        if len(cache) >= MAX_CACHED_SNAPSHOTS:
            cache.pop(next(iter(cache)))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Publisher snapshot requires UTF-8") from exc
        if snap["media_type"] == "text/html":
            try:
                root_html = html.fromstring(text)
                for noise in root_html.xpath("//script|//style|//noscript"):
                    noise.drop_tree()
                text = root_html.text_content()
            except (ValueError, TypeError) as exc:
                raise ValueError("Unreadable publisher HTML") from exc
        cache[cache_key] = _normalized(text)
    return cache[cache_key]


def _check_expected(kind, label):
    status = label.get("resolution")
    if status not in RESOLUTIONS[kind]:
        raise ValueError("Review label uses an unknown outcome/status")
    value = label.get("expected")
    if kind == "pricing":
        if status == "established":
            if not isinstance(value, dict) or not all(
                isinstance(value.get(f), str) and value[f].strip()
                for f in RATE_FIELDS[:7]
            ):
                raise ValueError("Established pricing gold requires exact typed dimensions")
            try:
                amount = Decimal(value["amount"])
                if not amount.is_finite() or amount < 0:
                    raise ValueError("Nonfinite or negative gold price")
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("Invalid manually reviewed decimal price") from exc
            if value.get("service_mode") is not None and not isinstance(
                value.get("service_mode"), str
            ):
                raise ValueError("Invalid optional reviewed service mode")
        elif value is not None:
            raise ValueError("Incomplete/unresolved price may not invent a normalized rate")
    elif kind == "release_dates":
        if status == "published_date":
            if not isinstance(value, str):
                raise ValueError("Known date requires exact ISO day")
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError("Noncanonical publication date")
            except ValueError as exc:
                raise ValueError("Invalid official release publication day") from exc
        elif value is not None:
            raise ValueError("Undated/unresolved release label must have null expected day")
    else:
        if not isinstance(value, dict) or set(value) != {
            "support_state", "capability_statement", "conditions"
        } or value["support_state"] not in SUPPORT_STATES:
            raise ValueError("Docs label needs support status and explicit claim/conditions")
        claim, conditions = value["capability_statement"], value["conditions"]
        if not isinstance(claim, str) or not isinstance(conditions, str):
            raise ValueError("Docs claim and conditions must be strings")
        if status != "topic_relevant" and value["support_state"] != "unknown":
            raise ValueError("Irrelevant/unresolved docs cannot prove capability support")
        if (value["support_state"] in {"supported", "conditional", "unsupported"}
                and not 15 <= len(claim.strip()) <= 450):
            raise ValueError("Docs support status needs a concrete scoped claim")
        if (value["support_state"] == "conditional"
                and len(conditions.strip()) < 15):
            raise ValueError("Conditional capability requires documented conditions")
    return status, value


def _review_labels(bundle, reviewer, snapshots, by_id, root, archived, cache):
    if (not isinstance(reviewer, dict)
            or reviewer.get("kind") != "independent_blind_publisher_review_annotations"
            or reviewer.get("schema_version") != SCHEMA
            or reviewer.get("synthetic_only") is not False
            or reviewer.get("approved_for_advisor") is not False
            or reviewer.get("task_bundle_sha256") != bundle["task_bundle_sha256"]
            or not isinstance(reviewer.get("reviewer_id"), str)
            or len(reviewer["reviewer_id"].strip()) < 3
            or not isinstance(reviewer.get("labels"), list)):
        raise ValueError("Invalid blinded reviewer file or bundle digest")
    mapped = {}
    for label in reviewer["labels"]:
        if not isinstance(label, dict):
            raise ValueError("Invalid reviewer label")
        case_id = label.get("case_id")
        if case_id not in by_id or case_id in mapped:
            raise ValueError("Reviewer supplied unknown or duplicate case")
        task = by_id[case_id]
        if label.get("approved_for_advisor") is not False:
            raise ValueError("Reviewer cannot authorize advisor claim")
        if "observed" in label or "crawler_prediction" in label:
            raise ValueError("Blind reviewer file cannot contain crawler predictions")
        stamp = _timestamp(label.get("reviewed_at_utc"))
        if (not isinstance(label.get("review_note"), str)
                or not MIN_REVIEW_NOTE <= len(label["review_note"].strip())
                       <= MAX_REVIEW_NOTE):
            raise ValueError("Reviewer needs substantive independent review notes")
        quote = label.get("publisher_evidence_quote")
        if (not isinstance(quote, str) or
                not MIN_QUOTE <= len(quote.strip()) <= MAX_QUOTE):
            raise ValueError("Reviewer needs a substantial exact publisher quote")
        snapshot = snapshots.get(case_id)
        if not snapshot:
            raise ValueError("No immutable publisher snapshot for reviewed case")
        item = archived.get((task["source_id"], task["job_id"]))
        if not item:
            raise ValueError("Reviewer case does not match immutable Zyte archive")
        page = _publisher_snapshot_text(
            snapshot, root, task, item, cache=cache,
        )
        normalized_quote = _normalized(quote)
        if page.count(normalized_quote) != 1:
            raise ValueError("Publisher evidence quote absent or ambiguous in pinned snapshot")
        if not _same_official_host(label.get("publisher_evidence_url"),
                                   task["source_url"]):
            raise ValueError("Reviewer evidence URL is not first-party")
        if label["publisher_evidence_url"] != snapshot["publisher_url"]:
            raise ValueError("Reviewer evidence locator disagrees with frozen page")
        if stamp < _timestamp(snapshot["captured_at_utc"]):
            raise ValueError("Review timestamp predates the referenced publisher snapshot")
        resolution, expected = _check_expected(task["kind"], label)
        mapped[case_id] = {
            "resolution": resolution,
            "expected": expected,
            "snapshot_sha256": snapshot["sha256"],
            "reviewer_id": reviewer["reviewer_id"].strip(),
        }
    return mapped


def _rate_equal(expected, observed):
    if (not isinstance(expected, dict) or not isinstance(observed, dict)
            or observed.get("comparable_candidate") is not True):
        return False
    try:
        a, b = Decimal(expected["amount"]), Decimal(observed["amount"])
        if not (a.is_finite() and b.is_finite() and a == b):
            return False
    except (TypeError, InvalidOperation, KeyError):
        return False
    return all(expected.get(f) == observed.get(f) for f in RATE_FIELDS[1:])


def _metric(numerator, denominator):
    return numerator / denominator if denominator else None


def score_dual_review(candidate_packet, reviewer_a, reviewer_b, snapshot_manifest,
                      *, snapshot_root, split_key, archive_paths,
                      full_inventory_plan=None, holdout_percent=25):
    """Recompute archive provenance, blind tasks and independent publisher quotes.

    Even consensus does NOT authenticate who captured publisher bytes or
    establish truth of reviewer assertions. Everything remains human QA.
    """
    if not archive_paths:
        raise ValueError("Original immutable Zyte archives are mandatory")
    # Recompute packet from every archived Item; never trust a forged JSON
    # packet that asserts a crawler observed a price/date it did not observe.
    genuine = prepare_review_candidates(
        archive_paths, full_inventory_plan=full_inventory_plan,
    )
    if _sha_json(candidate_packet) != _sha_json(genuine):
        raise ValueError("Review packet is not the checksum-bound archived source inventory")
    from scripts.real_gold_binding import load_bound_archives
    archived, jobs, package_sha = load_bound_archives(
        archive_paths, full_inventory_plan=full_inventory_plan,
    )
    bundle = prepare_blind_bundle(
        candidate_packet, split_key=split_key,
        holdout_percent=holdout_percent,
    )
    if not isinstance(snapshot_manifest, dict) or not isinstance(
        snapshot_manifest.get("snapshots"), list
    ) or snapshot_manifest.get("approved_for_advisor") is not False:
        raise ValueError("Invalid publisher snapshot manifest")
    snapshots = {}
    by_id = {x["case_id"]: x for x in bundle["tasks"]}
    for snap in snapshot_manifest["snapshots"]:
        if not isinstance(snap, dict) or snap.get("case_id") not in by_id:
            raise ValueError("Snapshot manifest has an unknown case")
        if snap["case_id"] in snapshots:
            raise ValueError("Duplicate snapshot for one review case")
        snapshots[snap["case_id"]] = snap
    if not isinstance(reviewer_a, dict) or not isinstance(reviewer_b, dict):
        raise ValueError("Two full independent reviewer records are required")
    if reviewer_a.get("reviewer_id", "").strip().casefold() == reviewer_b.get(
        "reviewer_id", "").strip().casefold():
        raise ValueError("Independent review requires two distinct reviewers")
    cache = {}
    first = _review_labels(
        bundle, reviewer_a, snapshots, by_id, snapshot_root, archived, cache
    )
    second = _review_labels(
        bundle, reviewer_b, snapshots, by_id, snapshot_root, archived, cache
    )
    counters = {partition: {kind: Counter() for kind in KINDS}
                for partition in ("train", "holdout")}
    provider_groups = defaultdict(set)
    disagreements = []
    for task in bundle["tasks"]:
        cid = task["case_id"]
        metric = counters[task["partition"]][task["kind"]]
        metric["candidates"] += 1
        if cid not in first or cid not in second:
            metric["missing_dual_review"] += 1
            continue
        a, b = first[cid], second[cid]
        if (a["resolution"] != b["resolution"] or
                a["expected"] != b["expected"] or
                a["snapshot_sha256"] != b["snapshot_sha256"]):
            metric["disagreed"] += 1
            disagreements.append({
                "case_id": cid, "source_id": task["source_id"],
                "partition": task["partition"], "kind": task["kind"],
                "reason": "independent_expected_labels_disagree",
            })
            continue
        metric["consensus"] += 1
        provider_groups[(task["partition"], task["kind"])].add(
            task["provider"].casefold()
        )
        kind, status, expected = task["kind"], a["resolution"], a["expected"]
        ident = task["observation_identity"]
        # Only use P14A verified crawler observations; no reviewer-supplied
        # observed value can change the numerator or denominator.
        packet_items = candidate_packet["samples"][kind]
        candidate = next(
            r for r in packet_items
            if _case_id(kind, r) == cid
        )
        if kind == "pricing":
            observed = candidate["observed"]
            if status == "established":
                metric["evaluable"] += 1
                if _rate_equal(expected, observed):
                    metric["correct"] += 1
                else:
                    metric["incorrect_or_not_comparable"] += 1
            elif status == "incomplete":
                metric["negative_examples"] += 1
                if observed.get("comparable_candidate") is True:
                    metric["false_comparable"] += 1
            else:
                metric["unresolved"] += 1
        elif kind == "release_dates":
            observed = candidate.get("observed_day")
            if status != "unresolved":
                metric["evaluable"] += 1
                actual = expected if status == "published_date" else None
                if actual == observed:
                    metric["correct"] += 1
                else:
                    metric["incorrect"] += 1
                    if actual is None and observed is not None:
                        metric["invented_publication_date"] += 1
            else:
                metric["unresolved"] += 1
        else:
            if status != "unresolved":
                metric["evaluable"] += 1
                if status == "topic_relevant":
                    metric["correct"] += 1
                    support = expected["support_state"]
                    metric["reviewed_" + support] += 1
                else:
                    metric["irrelevant_topic"] += 1
            else:
                metric["unresolved"] += 1

    summary = {}
    for split, kinds in counters.items():
        summary[split] = {}
        for kind, metric in kinds.items():
            summary[split][kind] = {
                **dict(metric),
                "precision_or_date_accuracy": _metric(
                    metric["correct"], metric["evaluable"],
                ),
                "source_provider_count": len(provider_groups[(split, kind)]),
            }
    required = {
        "pricing": {"total": 200, "holdout": 50, "providers_holdout": 3,
                    "min_precision": 0.99},
        "release_dates": {"total": 100, "holdout": 25,
                          "providers_holdout": 2, "min_precision": 0.99},
        "documentation": {"total": 50, "holdout": 15,
                          "providers_holdout": 2, "min_precision": 0.98},
    }
    gates = {}
    for kind, thresholds in required.items():
        all_evaluable = sum(counters[split][kind]["evaluable"]
                            for split in ("train", "holdout"))
        holdout = summary["holdout"][kind]
        gates[kind] = bool(
            all_evaluable >= thresholds["total"]
            and holdout.get("evaluable", 0) >= thresholds["holdout"]
            and holdout["source_provider_count"] >=
                thresholds["providers_holdout"]
            and holdout["precision_or_date_accuracy"] is not None
            and holdout["precision_or_date_accuracy"] >=
                thresholds["min_precision"]
        )
    no_false_scope = sum(
        counters[p]["pricing"]["false_comparable"]
        for p in ("train", "holdout")
    ) == 0
    no_invented_dates = sum(
        counters[p]["release_dates"]["invented_publication_date"]
        for p in ("train", "holdout")
    ) == 0
    all_dual_reviewed = all(
        not metric["missing_dual_review"] and not metric["disagreed"]
        for kinds in counters.values() for metric in kinds.values()
    )
    permitted = bool(
        all(gates.values()) and no_false_scope and no_invented_dates
        and all_dual_reviewed
        and all(summary["holdout"][kind]["evaluable"] > 0 for kind in KINDS)
    )
    return {
        "schema_version": SCHEMA,
        "report_kind": "blind_dual_review_snapshot_bounded_gold_assessment",
        "task_bundle_sha256": bundle["task_bundle_sha256"],
        "candidate_packet_sha256": bundle["candidate_packet_sha256"],
        "verified_archive_job_count": len(jobs),
        "package_sha256": package_sha,
        "source_group_split": "private_hmac_by_provider",
        "reviewer_count": 2,
        "publisher_snapshot_count": len(snapshots),
        "case_count": len(bundle["tasks"]),
        "training_and_holdout": summary,
        "unresolved_disagreements": disagreements,
        "checks": {
            **{kind + "_holdout_accuracy": value for kind, value in gates.items()},
            "no_false_comparable_negative_rates": no_false_scope,
            "no_invented_publication_dates": no_invented_dates,
            "all_cases_dual_reviewed_and_agreed": all_dual_reviewed,
        },
        "eligible_for_human_accuracy_signoff": permitted,
        "status": ("eligible_for_separate_manual_accuracy_signoff" if permitted
                   else "blocked_pending_publisher_gold_and_consensus"),
        "documentation_supported_feature_accuracy": None,
        "documentation_support_state_is_not_a_verified_capability_claim": True,
        "independent_publisher_truth_confirmed": False,
        "publisher_snapshot_origin_externally_authenticated": False,
        "advisor_fact_approvals": 0,
        "source_policy_promotions": 0,
        "network_requests_performed": 0,
        "deployment_authorized": False,
    }


def _write_private_json(path, data):
    file = Path(path)
    file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if file.is_symlink():
        raise ValueError("Refusing symlink reviewer output file")
    file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    os.chmod(file, 0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-packet", type=Path, required=True)
    parser.add_argument("--split-key-env", default="AGENTFUSE_GOLD_SPLIT_KEY")
    parser.add_argument("--holdout-percent", type=int, default=25)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/private/p15b"))
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument("--prepare", action="store_true")
    option.add_argument("--score", action="store_true")
    parser.add_argument("--reviewer-a", type=Path)
    parser.add_argument("--reviewer-b", type=Path)
    parser.add_argument("--snapshots", type=Path)
    parser.add_argument("--snapshot-root", type=Path)
    parser.add_argument("--archives", type=Path, nargs="+")
    parser.add_argument("--full-inventory-plan", type=Path)
    args = parser.parse_args()
    key = os.environ.get(args.split_key_env)
    if not key:
        raise ValueError("Private split key environment variable is required")
    packet = json.loads(args.candidate_packet.read_text(encoding="utf-8"))
    if args.prepare:
        bundle = prepare_blind_bundle(
            packet, split_key=key, holdout_percent=args.holdout_percent,
        )
        _write_private_json(args.out_dir / "blind_tasks.json", bundle)
        _write_private_json(args.out_dir / "reviewer_a_template.json",
                            reviewer_template(bundle, "REVIEWER_A"))
        _write_private_json(args.out_dir / "reviewer_b_template.json",
                            reviewer_template(bundle, "REVIEWER_B"))
        print(json.dumps({
            "task_count": len(bundle["tasks"]),
            "reviewers_needed": 2, "holdout_grouping": "by_provider",
            "expected_truth_prefilled": False, "network_requests": 0,
        }))
    else:
        if not (args.reviewer_a and args.reviewer_b and args.snapshots
                and args.snapshot_root and args.archives):
            raise ValueError(
                "Scoring needs two reviewer files, publisher snapshots, "
                "a snapshot root and verified Zyte job archives"
            )
        plan = (json.loads(args.full_inventory_plan.read_text(encoding="utf-8"))
                if args.full_inventory_plan else None)
        def read(path):
            return json.loads(path.read_text(encoding="utf-8"))
        result = score_dual_review(
            packet, read(args.reviewer_a), read(args.reviewer_b),
            read(args.snapshots), snapshot_root=args.snapshot_root,
            split_key=key, archive_paths=args.archives,
            full_inventory_plan=plan,
            holdout_percent=args.holdout_percent,
        )
        _write_private_json(args.out_dir / "dual_review_score.json", result)
        print(json.dumps({
            "status": result["status"],
            "cases": result["case_count"],
            "eligible_for_human_signoff": result[
                "eligible_for_human_accuracy_signoff"],
            "advisor_fact_approvals": 0,
        }))
        if not result["eligible_for_human_accuracy_signoff"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
