"""P22A3 — offline independent source-visible evidence-to-parser adjudication.

Every P20A source/round is accounted for. Actual page bytes, individual
operator policy reviews and P22A2 dual-blind A/B consensus are recomputed.
Only AFTER their review, an independent third adjudicator sees parser
predictions and human quote-backed reference identities and must disposition
EVERY predicted and EVERY human reference observation exactly once.

Metrics describe the strictly adjudicated, static, preselected pages ONLY.
Held pages remain missing, NOT negative test examples. Real publisher
ownership, human independence and population representativeness remain
unverified. No network requests, source policy/DB writes, release alerts,
recommendations or model training inputs are generated.
"""
import argparse
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.provider_profiles import identify_source_product
from agentfuse_crawlers.run_context import package_fingerprint
from agentfuse_crawlers.sources import load_sources
from scripts.accession_cross_category_html import _load as load_accession
from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.plan_documentation_children import _private_new_directory, _write_private
from scripts.reconcile_cross_category_reviews import reconcile
from scripts.replay_release_snapshots import _digest
from scripts.score_release_gold import _owner_node

VERSION = "1.0"
PACKET_KIND = "p22a3_adjudicator_only_publisher_snapshot_parser_reference_cases"
REVIEW_KIND = "p22a3_independent_candidate_identity_adjudication_not_approval"
REPORT_KIND = "p22a3_source_qualified_diagnostic_precision_recall_not_global_truth"
PERSON = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{3,79}$")
MAX_INPUT_BYTES = 6_000_000
MAX_PREDICTIONS = 300
MAX_EVIDENCE = 200
MAPPING_FIELDS = frozenset({
    "prediction_id", "reference_id", "same_visible_evidence_note",
})
REVIEW_FIELDS = frozenset({
    "case_id", "source_id", "round", "category", "review_completed",
    "adjudicated_at_utc", "adjudication_note", "matches",
    "unmatched_prediction_ids", "missed_reference_ids",
    "approved_for_advisor",
})
REVIEW_ROOT_FIELDS = frozenset({
    "schema_version", "kind", "frozen_packet_sha256",
    "adjudicator_id", "independent_of_a_and_b_attested",
    "cases", "approved_for_advisor",
})


def _norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def _utc(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 45:
        raise ValueError("Adjudicator must supply a timezone-aware time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Adjudication time needs UTC offset")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Invalid adjudication timestamp") from exc


def _note(text, label):
    if not isinstance(text, str) or not 24 <= len(text.strip()) <= 1200:
        raise ValueError("Substantive " + label + " required")
    return text.strip()


def _id(task, tag, value):
    return _digest({
        "task_id": task["task_id"], "kind": tag, "identity": value
    })[:24]


def _decimal(value):
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        parsed = Decimal(value)
        return format(parsed.normalize(), "f") if parsed.is_finite() and parsed >= 0 else None
    except InvalidOperation:
        return None


def _pricing_gold_complete(gold):
    required = ("amount_decimal", "currency", "billing_unit",
                "price_dimension", "model_or_service")
    return (
        all(gold.get(k) is not None for k in required)
        and gold.get("region_applicability") not in {"unknown", None}
        and gold.get("tier_applicability") not in {"unknown", None}
    )


def _eligible_parser(category, evidence, identity):
    """Physical extraction truncation/identity collision means metrics held.

    Zero comparable prices or missing release predictions can still reflect
    failures, not a reason to silently drop hard real publisher pages.
    """
    holds = []
    if identity.get("source_product_title_conflict"):
        holds.append("source_expected_product_identity_conflict")
    if category == "pricing":
        if evidence.get("pricing_inventory_complete") is not True:
            holds.append("pricing_page_inventory_incomplete")
        if evidence.get("pricing_observation_limit_reached") or (
            evidence.get("pricing_table_scan_truncated")
        ) or evidence.get("pricing_rate_identity_collision_count"):
            holds.append("pricing_truncation_or_identity_collision")
    elif category == "changelog":
        events = evidence.get("release_events") or []
        if (evidence.get("release_event_count", 0) != len(events)
                or evidence.get("release_historical_event_count_omitted", 0)
                or evidence.get("release_recent_body_loss_count", 0)
                or evidence.get("release_event_identity_collision")
                or evidence.get("release_events_truncated")
                or any(x.get("body_text_truncated") for x in events)):
            holds.append("release_page_events_omitted_truncated_or_colliding")
        if any(x.get("release_identity_requires_manual_review")
               or x.get("identity_basis") == "date_scoped_generic_heading_review_only"
               for x in events):
            holds.append("release_parser_owner_identity_unstable")
    else:
        if (evidence.get("documentation_topic_candidate_omitted", 0)
                or evidence.get("documentation_source_sections_truncated")
                or evidence.get("sections_truncated")
                or evidence.get("documentation_static_capture_status")
                   in {"javascript_shell_suspected", "insufficient_static_text"}
                or evidence.get("documentation_profile_status") == "profile_url_mismatch"
                or evidence.get("documentation_product_scope_signal")
                   in {"marker_not_found", "body_only_marker_requires_review"}
                or evidence.get("documentation_requires_product_review")):
            holds.append("documentation_page_topic_or_product_scope_incomplete")
    return sorted(set(holds))


def _predictions(task, evidence):
    category = task["category"]
    output = []
    all_unqualified = 0
    if category == "pricing":
        observations = evidence.get("pricing_observations") or []
        if not isinstance(observations, list):
            raise ValueError("Pricing observation inventory is not a list")
        all_unqualified = sum(o.get("comparable_candidate") is not True for o in observations)
        for i, obs in enumerate(observations):
            if obs.get("comparable_candidate") is not True:
                continue
            if (obs.get("approved_for_advisor") is not False
                    or obs.get("source_id") != task["source_id"]):
                raise ValueError("Source-crossed/privileged comparable price prediction")
            fields = {k: obs.get(k) for k in (
                "normalized_amount_decimal", "currency", "billing_unit",
                "price_dimension", "model_or_service", "region", "tier_or_plan",
            )}
            if _decimal(fields["normalized_amount_decimal"]) is None:
                raise ValueError("Comparable rate lacks normalized exact decimal")
            output.append({
                "prediction_id": _id(task, "pricing_rate",
                    [i, obs.get("observation_id"), obs.get("source_evidence_sha256")]),
                "category": category,
                "prediction_identity": obs.get("observation_id"),
                "physical_cell_hint": {
                    "table_id": obs.get("table_id"), "row_index": obs.get("row_index"),
                    "column_index": obs.get("column_index"),
                    "raw_parent_cell_text": str(
                        obs.get("raw_parent_cell_text")
                        or obs.get("raw_displayed_price") or ""
                    )[:500],
                },
                "observed_value": fields,
                "approved_for_advisor": False,
            })
    elif category == "changelog":
        events = evidence.get("release_events") or []
        if not isinstance(events, list):
            raise ValueError("Release events are not a list")
        for i, event in enumerate(events):
            if event.get("approved_for_advisor") is not False or (
                event.get("source_id") != task["source_id"]
            ):
                raise ValueError("Cross-owned/privileged release prediction")
            output.append({
                "prediction_id": _id(task, "release_event",
                    [i, event.get("event_id"), event.get("permalink")]),
                "category": category,
                "prediction_identity": event.get("event_id"),
                "physical_cell_hint": None,
                "observed_value": {
                    "event_owner_url": event.get("permalink"),
                    "publisher_title": event.get("title"),
                    "version": event.get("version"),
                    "published_at": event.get("published_at"),
                    "identity_basis": event.get("identity_basis"),
                },
                "approved_for_advisor": False,
            })
    else:
        topics = evidence.get("documentation_topic_candidates") or []
        if not isinstance(topics, list):
            raise ValueError("Documentation topics are not a list")
        by_topic = defaultdict(list)
        for item in topics:
            if item.get("approved_for_advisor") is not False or (
                item.get("source_id") != task["source_id"]
            ):
                raise ValueError("Cross-owned/privileged docs topic prediction")
            by_topic[item.get("topic_hint")].append(item)
        for topic, observations in sorted(by_topic.items()):
            if not isinstance(topic, str) or not topic:
                raise ValueError("Unknown documentation topic prediction")
            output.append({
                "prediction_id": _id(task, "documentation_topic", topic),
                "category": category, "prediction_identity": topic,
                "physical_cell_hint": {
                    "section_ids": sorted(set(str(x.get("section_id")) for x in observations)),
                    "section_excerpts": [str(x.get("excerpt") or "")[:520]
                                         for x in observations[:16]],
                    "multiple_sections_same_topic": len(observations) > 1,
                },
                "observed_value": {"topic": topic},
                "approved_for_advisor": False,
            })
    if len(output) > MAX_PREDICTIONS or len({
        x["prediction_id"] for x in output
    }) != len(output):
        raise ValueError("Parser prediction identity collision or unbounded inventory")
    return output, all_unqualified


def _references(task, consensus):
    category = task["category"]
    references = []
    if category == "documentation":
        # The deployed docs parser detects TOPICS; it never asserts technical
        # capability supported/unsupported. Multiple human claims under one
        # topic form a SINGLE topic unit, not several artificial false negatives.
        by_topic = defaultdict(list)
        for evidence in consensus["evidence"]:
            by_topic[evidence["reviewed_value"]["topic"]].append(evidence)
        for topic, entries in sorted(by_topic.items()):
            references.append({
                "reference_id": _id(task, "docs_ref_topic", topic),
                "category": category,
                "evidence_ids": sorted(x["evidence_id"] for x in entries),
                "reviewed_value": {"topic": topic},
                "publisher_evidence_quotes": [
                    x["publisher_evidence_quote"] for x in entries
                ],
                "support_state_inferred_by_parser": False,
                "approved_for_advisor": False,
            })
    else:
        for item in consensus["evidence"]:
            references.append({
                "reference_id": item["evidence_id"],
                "category": category,
                "evidence_ids": [item["evidence_id"]],
                "reviewed_value": item["reviewed_value"],
                "publisher_evidence_quotes": [item["publisher_evidence_quote"]],
                "approved_for_advisor": False,
            })
    if len(references) > MAX_EVIDENCE or len({
        ref["reference_id"] for ref in references
    }) != len(references):
        raise ValueError("Duplicate or unbounded human reference labels")
    return references


def build_packet(plan, ledger, capture_root, reviewer_a, reviewer_b, *, now=None):
    review, rounds, consensus = reconcile(
        plan, ledger, capture_root, reviewer_a, reviewer_b, now=now,
    )
    tasks_by_round = {(c["source_id"], c["round"]): c for c in ledger["rows"]
                      for _ in ()}  # no implicit source replacement
    # Source identity from the frozen accession, NOT parser contents.
    from scripts.accession_cross_category_html import stage_data
    _, cases, _ = stage_data(plan, ledger, capture_root, now=now)
    actual = {s["id"]: s for s in load_sources()}
    agreed = {(x["source_id"], x["round"]): x for x in consensus}
    packet_cases = []
    for origin, verdict in zip(cases, rounds):
        if (origin["source_id"] != verdict["source_id"]
                or origin["round"] != verdict["round"]
                or origin["category"] != verdict["category"]):
            raise ValueError("Original source identity differs from blinded census")
        key = (origin["source_id"], origin["round"])
        entry = {
            "source_id": origin["source_id"],
            "source_url": origin["source_url"],
            "category": origin["category"],
            "wave": origin["wave"], "round": origin["round"],
            "original_capture_state": origin["state"],
            "raw_html_sha256": origin.get("raw_html_sha256"),
            "review_status": verdict["dual_review_status"],
            "case_id": _id({
                "task_id": plan["plan_sha256"]
            }, "source_round", [origin["source_id"], origin["round"]]),
            "score_status": "held",
            "hold_reasons": [],
            "predictions": [], "references": [],
            "unqualified_rate_observations": 0,
            "parser_package_sha256": package_fingerprint(),
            "approved_for_advisor": False,
        }
        consensus_case = agreed.get(key)
        if not consensus_case:
            entry["hold_reasons"].append(verdict["dual_review_status"])
        else:
            source = actual[origin["source_id"]]
            snap = ledger["rows"][
                next(i for i, row in enumerate(ledger["rows"])
                     if row["source_id"] == source["id"])
            ]["rounds"][origin["round"] - 1]["snapshot"]
            raw = _snapshot_bytes(
                snap, capture_root, expected_url=source["url"],
                method="static_html",
            )
            evidence = extract_evidence(
                raw, source["url"], category=source["category"],
                source_id=source["id"],
            )
            identity = identify_source_product(source, evidence)
            holds = _eligible_parser(source["category"], evidence, identity)
            refs = _references(origin, consensus_case)
            if source["category"] == "pricing" and any(
                not _pricing_gold_complete(ref["reviewed_value"]) for ref in refs
            ):
                holds.append("human_price_scope_not_fully_established")
            if not holds:
                predictions, unqualified = _predictions(origin, evidence)
                entry["score_status"] = "requires_independent_adjudication"
                entry["predictions"] = predictions
                entry["references"] = refs
                entry["unqualified_rate_observations"] = unqualified
            else:
                entry["hold_reasons"] = sorted(set(holds))
        packet_cases.append(entry)
    if len(packet_cases) != 36:
        raise ValueError("Missing source rounds in adjudication packet")
    packet = {
        "schema_version": VERSION, "kind": PACKET_KIND,
        "frozen_plan_sha256": plan["plan_sha256"],
        "source_round_denominator": 36,
        "source_count_denominator": 18,
        "p22a2_review_report_sha256": review["report_sha256"],
        "p22a2_task_bundle_sha256": review["task_bundle_sha256"],
        "parser_package_sha256": package_fingerprint(),
        "adjudication_cases": packet_cases,
        "publisher_origin_independently_authenticated": False,
        "independent_review_real_world_truth_verified": False,
        "parser_predictions_not_shown_to_blinded_reviewers": True,
        "advisor_fact_approvals": 0, "approved_for_advisor": False,
    }
    packet["packet_sha256"] = _digest(packet)
    return packet


def blank_adjudicator(packet):
    return {
        "schema_version": VERSION, "kind": REVIEW_KIND,
        "frozen_packet_sha256": packet["packet_sha256"],
        "adjudicator_id": None,
        "independent_of_a_and_b_attested": False,
        "cases": [{
            "case_id": x["case_id"], "source_id": x["source_id"],
            "round": x["round"], "category": x["category"],
            "review_completed": False, "adjudicated_at_utc": None,
            "adjudication_note": "", "matches": [],
            "unmatched_prediction_ids": [], "missed_reference_ids": [],
            "approved_for_advisor": False,
        } for x in packet["adjudication_cases"]
        if x["score_status"] == "requires_independent_adjudication"],
        "approved_for_advisor": False,
    }


def _price_field_exact(observed, expected):
    checks = {}
    checks["amount_decimal"] = (
        _decimal(observed.get("normalized_amount_decimal"))
        == _decimal(expected.get("amount_decimal"))
    )
    for field in ("currency", "billing_unit", "price_dimension",
                  "model_or_service", "region", "tier_or_plan"):
        checks[field] = _norm(observed.get(field) or "") == _norm(expected.get(field) or "")
    # The crawler's existing normalizer has no explicit reviewed region/tier
    # applicability flags. Only compare their observed values, never claim
    # separate applicability understanding.
    return checks


def _match_valid(case, pred, ref, note):
    _note(note, "visible-source identity adjudication")
    category = case["category"]
    if category == "changelog":
        if (pred["observed_value"]["event_owner_url"] !=
                ref["reviewed_value"]["event_owner_url"]):
            raise ValueError("Release identity requires EXACT publisher-owned permalink")
    elif category == "documentation":
        if (pred["observed_value"]["topic"] !=
                ref["reviewed_value"]["topic"]):
            raise ValueError("Documentation identity requires same visible page topic")
    else:
        # A material cell snippet must be inside the human's independently
        # quoted ORIGINAL evidence. This is evidence overlap, not a reviewer's
        # assertion that a wrong monetary unit became correct.
        cell = _norm(pred["physical_cell_hint"]["raw_parent_cell_text"])
        quotes = [_norm(x) for x in ref["publisher_evidence_quotes"]]
        if (len(cell) < 5
                or not any(cell in q or q in cell for q in quotes)):
            raise ValueError("Price match not bound to same visible source cell evidence")


def score_packet(plan, ledger, capture_root, reviewer_a, reviewer_b,
                 frozen_packet, adjudicator, *, now=None):
    expected = build_packet(
        plan, ledger, capture_root, reviewer_a, reviewer_b, now=now,
    )
    if frozen_packet != expected:
        raise ValueError("Adjudication packet differs from CURRENT original HTML/parser")
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise ValueError("Adjudication clock must include timezone")
    clock = clock.astimezone(timezone.utc)
    if (not isinstance(adjudicator, dict)
            or set(adjudicator) != REVIEW_ROOT_FIELDS
            or adjudicator.get("schema_version") != VERSION
            or adjudicator.get("kind") != REVIEW_KIND
            or adjudicator.get("approved_for_advisor") is not False
            or adjudicator.get("frozen_packet_sha256") != expected["packet_sha256"]
            or adjudicator.get("independent_of_a_and_b_attested") is not True
            or not isinstance(adjudicator.get("adjudicator_id"), str)
            or not PERSON.fullmatch(adjudicator["adjudicator_id"])
            or adjudicator["adjudicator_id"].strip().casefold() in {
                reviewer_a["reviewer_id"].strip().casefold(),
                reviewer_b["reviewer_id"].strip().casefold(),
            }):
        raise ValueError("Separate human identity adjudicator required")
    cases = blank_adjudicator(expected)["cases"]
    actual = adjudicator.get("cases")
    if (not isinstance(actual, list) or len(actual) != len(cases)):
        raise ValueError("Missing or extra original source-round adjudication")
    case_index = {x["case_id"]: x for x in expected["adjudication_cases"]}
    total, cat = Counter(), {k: Counter() for k in (
        "pricing", "changelog", "documentation",
    )}
    qualified, all_outcomes = [], []
    for i, (task, reference) in enumerate(zip(actual, cases)):
        if (not isinstance(task, dict) or set(task) != REVIEW_FIELDS
                or any(task[k] != reference[k] for k in (
                    "case_id", "source_id", "round", "category"
                ))
                or task["approved_for_advisor"] is not False
                or task["review_completed"] is not True):
            raise ValueError("Each eligible source-round needs complete identity adjudication")
        info = case_index[task["case_id"]]
        ts = _utc(task["adjudicated_at_utc"])
        if ts > clock + timedelta(minutes=5):
            raise ValueError("Adjudicator timestamp claims the future")
        _note(task["adjudication_note"], "complete source-round disposition")
        if any(not isinstance(x, list) for x in (
            task.get("matches"), task.get("unmatched_prediction_ids"),
            task.get("missed_reference_ids"),
        )):
            raise ValueError("Missing explicit one-to-one prediction/gold dispositions")
        p_map = {x["prediction_id"]: x for x in info["predictions"]}
        r_map = {x["reference_id"]: x for x in info["references"]}
        used_p, used_r, matched = set(), set(), []
        for pair in task["matches"]:
            if (not isinstance(pair, dict) or set(pair) != MAPPING_FIELDS
                    or pair["prediction_id"] not in p_map
                    or pair["reference_id"] not in r_map):
                raise ValueError("Cross-source or unknown human identity pair")
            pid, rid = pair["prediction_id"], pair["reference_id"]
            if pid in used_p or rid in used_r:
                raise ValueError("Duplicate parser or human evidence identity pair")
            pred, ref = p_map[pid], r_map[rid]
            _match_valid(info, pred, ref, pair["same_visible_evidence_note"])
            used_p.add(pid)
            used_r.add(rid)
            matched.append((pred, ref))
        unmatched = task["unmatched_prediction_ids"]
        missed = task["missed_reference_ids"]
        if (any(not isinstance(x, str) for x in unmatched+missed)
                or len(unmatched) != len(set(unmatched))
                or len(missed) != len(set(missed))
                or set(unmatched) & used_p or set(missed) & used_r
                or set(unmatched) | used_p != set(p_map)
                or set(missed) | used_r != set(r_map)):
            raise ValueError("INCOMPLETE source-wide parser and human inventory disposition")
        correct, incorrect, field_totals, field_correct = 0, 0, Counter(), Counter()
        day_denom, day_exact = 0, 0
        for pred, ref in matched:
            if info["category"] == "pricing":
                fields = _price_field_exact(
                    pred["observed_value"], ref["reviewed_value"],
                )
                for field, equal in fields.items():
                    field_totals[field] += 1
                    field_correct[field] += bool(equal)
                equality = all(fields.values())
            elif info["category"] == "changelog":
                # Already required EXACT release owner permalink.
                expected_value = ref["reviewed_value"]
                observed_value = pred["observed_value"]
                equality = True  # owner recall/precision, independent of date
                state = expected_value["date_status"]
                if state != "ambiguous":
                    day_denom += 1
                    if state == "explicit_publication_day":
                        day_exact += (
                            observed_value.get("published_at") == expected_value.get("published_at")
                        )
                    else:
                        day_exact += observed_value.get("published_at") is None
            else:
                # Topic detections are all this parser claims. Its output
                # does NOT say feature_supported=true, so no support score.
                equality = True
            correct += int(equality)
            incorrect += int(not equality)
        # Incorrect matched price is ONE FP and ONE FN for strict
        # comparable-rate correctness, not a true positive.
        tp = correct
        fp = len(unmatched) + incorrect
        fn = len(missed) + incorrect
        stats = {
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "matched_wrong_typed_rate_count": incorrect,
            "predicate": {
                "pricing": "fully_qualified_exact_price_dimensions",
                "changelog": "unique_release_owner_permalink",
                "documentation": "topic_hint_on_this_exact_source_page",
            }[info["category"]],
            "precision": tp / (tp+fp) if tp+fp else None,
            "recall": tp / (tp+fn) if tp+fn else None,
            "day_exact_count": day_exact,
            "day_matched_reference_count": day_denom,
            "field_compared": dict(field_totals),
            "field_exact": dict(field_correct),
            "unqualified_rate_observations": info["unqualified_rate_observations"],
            "reviewer_identity_bound_not_cryptographically_independent": True,
            "source_origin_authenticated": False,
            "approved_for_advisor": False,
        }
        for dest in (total, cat[info["category"]]):
            for key in ("true_positives", "false_positives", "false_negatives",
                        "matched_wrong_typed_rate_count", "day_exact_count",
                        "day_matched_reference_count"):
                dest[key] += stats[key]
            dest["adjudicated_source_rounds"] += 1
            for k, v in field_totals.items():
                dest["fields_compared_" + k] += v
                dest["fields_exact_" + k] += field_correct[k]
        qualified.append({
            "case_id": info["case_id"], "source_id": info["source_id"],
            "category": info["category"], "round": info["round"],
            "adjudicator_score": stats,
            "not_representative_of_all_460_sources": True,
            "approved_for_advisor": False,
        })
    for item in expected["adjudication_cases"]:
        if item["score_status"] == "held":
            cat[item["category"]]["held_source_rounds"] += 1
            total["held_source_rounds"] += 1
        all_outcomes.append({
            "source_id": item["source_id"], "category": item["category"],
            "round": item["round"], "original_capture_state": item["original_capture_state"],
            "accuracy_state": (
                "diagnostic_from_adjudicated_human_evidence"
                if item["score_status"] == "requires_independent_adjudication"
                else "held_without_accuracy"
            ),
            "hold_reasons": item["hold_reasons"],
            "approved_for_advisor": False,
        })
    if len(all_outcomes) != 36:
        raise ValueError("Source-wide 36-round denominator unexpectedly changed")
    def summarize(stats):
        n = stats["adjudicated_source_rounds"]
        tp, fp, fn = (
            stats["true_positives"], stats["false_positives"],
            stats["false_negatives"],
        )
        return {
            "adjudicated_source_rounds": n,
            "held_source_rounds": stats["held_source_rounds"],
            "source_round_denominator": (
                36 if stats is total else 12
            ),
            "tp": tp if n else None, "fp": fp if n else None, "fn": fn if n else None,
            "precision": tp/(tp+fp) if n and tp+fp else None,
            "recall": tp/(tp+fn) if n and tp+fn else None,
            "date_exact": stats["day_exact_count"] if n else None,
            "date_checked": stats["day_matched_reference_count"] if n else None,
            "date_exact_rate": (
                stats["day_exact_count"] / stats["day_matched_reference_count"]
                if n and stats["day_matched_reference_count"] else None
            ),
            "field_exact_rate": {
                field[len("fields_compared_"):]:
                stats["fields_exact_" + field[len("fields_compared_"):]] / count
                for field, count in stats.items()
                if field.startswith("fields_compared_") and count
            },
            "diagnostic_only_nonrepresentative": True,
        }
    report = {
        "schema_version": VERSION, "kind": REPORT_KIND,
        "frozen_plan_sha256": plan["plan_sha256"],
        "adjudication_packet_sha256": expected["packet_sha256"],
        "source_denominator": 18, "source_round_denominator": 36,
        "overall": summarize(total),
        "by_category": {k: summarize(v) for k, v in cat.items()},
        "all_original_rounds_covered": len(all_outcomes) == 36,
        "adjudicator_distinct_identity_attested_not_independently_verified": True,
        "publisher_origin_independently_authenticated": False,
        "representative_production_accuracy_verified": False,
        "complete_frozen_study_accuracy_measurable": (
            total["adjudicated_source_rounds"] == 36
        ),
        "documentation_feature_support_accuracy": None,
        "documentation_corpus_coverage_accuracy": None,
        "advisor_fact_approvals": 0, "approved_for_advisor": False,
        "network_requests_performed": 0, "zyte_jobs_created": 0,
    }
    report["report_sha256"] = _digest({"report": report,
        "cases": qualified, "source_rounds": all_outcomes})
    return report, qualified, all_outcomes


def _write_json(root, filename, obj):
    _write_private(root / filename,
                   (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def write_packet(packet, root):
    out = _private_new_directory(root)
    try:
        _write_json(out, "adjudicator_only_parser_vs_human_packet_PRIVATE.json", packet)
        _write_json(out, "adjudicator_THIRD_HUMAN_BLANK.json", blank_adjudicator(packet))
    except Exception:
        shutil.rmtree(out)
        raise
    return out


def write_score(data, root):
    out = _private_new_directory(root)
    try:
        report, scored, rounds = data
        _write_json(out, "p22a3_accuracy_READINESS_and_diagnostics.json", report)
        _write_json(out, "source_round_diagnostic_scores_PRIVATE.json", scored)
        _write_json(out, "all_36_original_round_coverage.json", rounds)
    except Exception:
        shutil.rmtree(out)
        raise
    return out


def _load(path):
    file = Path(path)
    if (not file.is_file() or file.is_symlink()
            or any(x.is_symlink() for x in file.parents)
            or not 2 <= file.stat().st_size <= MAX_INPUT_BYTES):
        raise ValueError("P22A3 private file missing, oversized or unsafe")
    return json.loads(file.read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-adjudicator", action="store_true")
    mode.add_argument("--score", action="store_true")
    for flag in ("frozen-plan", "private-ledger", "capture-root",
                 "reviewer-a", "reviewer-b", "out-dir"):
        p.add_argument("--" + flag, required=True, type=Path)
    p.add_argument("--packet", type=Path)
    p.add_argument("--adjudicator", type=Path)
    args = p.parse_args()
    plan, ledger = _load(args.frozen_plan), _load(args.private_ledger)
    a, b = _load(args.reviewer_a), _load(args.reviewer_b)
    if args.prepare_adjudicator:
        if args.packet or args.adjudicator:
            p.error("Preparation cannot use a prefilled adjudicator packet")
        packet = build_packet(plan, ledger, args.capture_root, a, b)
        out = write_packet(packet, args.out_dir)
        result = {"private_packet": str(out),
                  "eligible_source_rounds": sum(
                      x["score_status"] == "requires_independent_adjudication"
                      for x in packet["adjudication_cases"])}
    else:
        if not args.packet or not args.adjudicator:
            p.error("Scoring needs BOTH frozen packet and independent adjudicator")
        result_data = score_packet(
            plan, ledger, args.capture_root, a, b,
            _load(args.packet), _load(args.adjudicator),
        )
        out = write_score(result_data, args.out_dir)
        result = {"private_scoring_output": str(out),
                  "adjudicated_rounds":
                      result_data[0]["overall"]["adjudicated_source_rounds"]}
    print(json.dumps({**result, "original_source_round_denominator": 36,
                      "new_publisher_requests": 0, "zyte_jobs": 0,
                      "advisor_fact_approvals": 0,
                      "full_460_source_accuracy_verified": False}, indent=2))


if __name__ == "__main__":
    main()
