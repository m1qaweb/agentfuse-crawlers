"""P22A2: dual-blind whole-visible-page human consensus, offline only.

Source-wide sampling: EXACT P20A 18 publisher source IDs x two rounds (36).
Recompute P22A1 original HTML byte hashes, policy validity and parser
diagnostics; two *distinct* independently attesting human reviewers inspect
the publisher-visible page without parser predictions. Validate evidence
quotes against the exact original HTML; release owner/date against P19A2.

Agreement + quote grounding is NOT publisher-origin authentication, proof
of reviewer independence, or a parser accuracy score. No precision/recall
until separately human-adjudicated parser-to-reference identity mapping.
No network, Zyte, source permission promotion, DB writes or advisor facts.
"""
import argparse
import json
import re
import shutil
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import html

from agentfuse_crawlers.documentation_scope import TOPIC_PATTERNS
from scripts.accession_cross_category_html import (
    _load as _p22_load, stage_data, validate_plan,
)
from scripts.compare_acquisition_snapshots import _snapshot_bytes
from scripts.plan_documentation_children import (
    _private_new_directory, _write_private,
)
from scripts.replay_release_snapshots import _digest
from scripts.score_release_gold import _review_label as validate_release_owner

VERSION = "1.0"
BUNDLE_KIND = "p22a2_blind_whole_visible_page_tasks_not_gold"
REVIEW_KIND = "p22a2_two_independent_private_whole_page_reviews"
REPORT_KIND = "p22a2_dual_human_visible_page_consensus_not_parser_accuracy"
REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{3,79}$")
ALLOWED_PAGE_SCOPE = {
    "not_reviewed", "sufficient_visible_static_page",
    "insufficient_js_or_challenge", "ambiguous_product_scope",
    "incomplete_review",
}
TASK_META = (
    "task_id", "source_id", "source_url", "category", "wave", "round",
    "raw_html_sha256", "raw_html_private_file", "captured_at_utc",
)
TASK_FIELDS = frozenset(TASK_META) | {
    "reviewed_at_utc", "page_scope", "whole_visible_page_review_complete",
    "exact_product_scope_reviewed", "no_relevant_evidence_observed",
    "evidence_inventory", "review_note", "parser_predictions_hidden",
    "approved_for_advisor",
}
ROOT_FIELDS = {
    "schema_version", "kind", "reviewer_letter", "reviewer_id",
    "task_bundle_sha256", "frozen_plan_sha256",
    "independent_blind_review_attested", "source_reviews",
    "approved_for_advisor",
}
EVIDENCE_FIELDS = {
    "evidence_type", "publisher_evidence_quote", "publisher_evidence_url",
    "reviewed_value", "review_note", "approved_for_advisor",
}
PRICE_FIELDS = {
    "amount_decimal", "currency", "billing_unit", "price_dimension",
    "model_or_service", "region", "region_applicability",
    "tier_or_plan", "tier_applicability", "conditions",
}
APPLICABILITY = {"explicit", "unknown", "reviewed_not_applicable", "conditional"}
RELEASE_FIELDS = {
    "event_owner_url", "publisher_title", "version", "date_status",
    "published_at", "date_evidence_text",
}
DOCS_FIELDS = {
    "topic", "support_state", "capability_statement",
    "conditions", "product_id",
}
EVIDENCE_TYPES = {
    "pricing": "pricing_rate", "changelog": "release_event",
    "documentation": "documentation_claim",
}
MAX_SOURCE_LABELS = 200
MAX_TOTAL_LABELS = 1800
MAX_REVIEW_JSON = 6_000_000


def _norm(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _timestamp(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 45:
        raise ValueError("Timestamped independent human review required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("Missing timezone")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid timezone-aware human review timestamp") from exc


def _bounded_note(text, label, minimum=24, maximum=1200):
    if not isinstance(text, str) or not minimum <= len(text.strip()) <= maximum:
        raise ValueError(label + " needs substantive human notes")
    return text.strip()


def _field(value, *, label, required=False, maximum=240):
    if value is None:
        if required:
            raise ValueError("Missing required independently reviewed " + label)
        return None
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= maximum):
        raise ValueError("Invalid independently reviewed " + label)
    return value.strip()


def _rate_scope(kind, amount):
    if not isinstance(amount, dict) or set(amount) != PRICE_FIELDS:
        raise ValueError("Human rate requires exact source-scope dimensions")
    raw = _field(amount["amount_decimal"], label="price amount", required=True)
    try:
        d = Decimal(raw)
        if not d.is_finite() or d < 0:
            raise ValueError("Negative/nonfinite human price")
        numeric = format(d.normalize(), "f")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid exact decimal rate amount") from exc
    values = {"amount_decimal": numeric}
    for key in (
        "currency", "billing_unit", "price_dimension", "model_or_service",
        "region", "tier_or_plan", "conditions",
    ):
        values[key] = _field(amount[key], label=key, maximum=300)
    # Unknown currency stays None. Never infer dollars from a $ symbol.
    if values["currency"] is not None and not re.fullmatch(
        r"[A-Z]{3}", values["currency"]
    ):
        raise ValueError("Currency must be explicit ISO-4217 code or null")
    for field, scope in (
        ("region", "region_applicability"),
        ("tier_or_plan", "tier_applicability"),
    ):
        status = amount[scope]
        if status not in APPLICABILITY:
            raise ValueError("Missing explicit/unknown/not-applicable scope review")
        if status == "explicit" and values[field] is None:
            raise ValueError("Explicit applicability cannot omit source value")
        if status in {"unknown", "reviewed_not_applicable"} and values[field] is not None:
            raise ValueError("Unknown/not-applicable scope cannot invent value")
        if status == "conditional" and not values["conditions"]:
            raise ValueError("Conditional applicability requires original conditions")
        values[scope] = status
    return values


def _release_scope(value, evidence, source, document, visible):
    if not isinstance(value, dict) or set(value) != RELEASE_FIELDS:
        raise ValueError("Release requires exact owner, title and publication state")
    raw = {
        "owner_url": value["event_owner_url"],
        "publisher_title": value["publisher_title"],
        "version": value["version"],
        "date_status": value["date_status"],
        "published_at": value["published_at"],
        "date_evidence_text": value["date_evidence_text"],
        "publisher_evidence_quote": evidence["publisher_evidence_quote"],
        "review_note": evidence["review_note"],
        "approved_for_advisor": False,
    }
    verified = validate_release_owner(
        raw, {"source_url": source["source_url"]}, document, visible,
    )
    return {
        "event_owner_url": verified["owner_url"],
        "publisher_title": verified["publisher_title"],
        "version": verified["version"],
        "date_status": verified["date_status"],
        "published_at": verified["published_at"],
        "date_evidence_text": value["date_evidence_text"],
    }


def _documentation_scope(value):
    if not isinstance(value, dict) or set(value) != DOCS_FIELDS:
        raise ValueError("Documentation review needs exact technical claim fields")
    topic = value["topic"]
    status = value["support_state"]
    if topic not in TOPIC_PATTERNS or status not in {
        "supported", "unsupported", "conditional", "unknown",
    }:
        raise ValueError("Invalid reviewed docs topic/support state")
    claim = _field(
        value["capability_statement"], label="capability claim",
        required=True, maximum=450,
    )
    if len(claim) < 20:
        raise ValueError("Docs support claim must be adequately scoped")
    cond = _field(value["conditions"], label="technical claim conditions",
                  maximum=450)
    if status == "conditional" and (cond is None or len(cond) < 15):
        raise ValueError("Conditional capability lacks documented conditions")
    pid = _field(value["product_id"], label="product ID", maximum=120)
    # This is a human opinion about original visible HTML, never approval.
    return {
        "topic": topic, "support_state": status,
        "capability_statement": claim, "conditions": cond,
        "product_id": pid,
    }


def build_bundle(plan, ledger, capture_root, *, now=None):
    validate_plan(plan)
    metrics, cases, _ = stage_data(plan, ledger, capture_root, now=now)
    tasks = []
    for case in cases:
        if case["state"] != "captured":
            continue
        identity = {
            "source_id": case["source_id"],
            "source_url": case["source_url"],
            "category": case["category"],
            "wave": case["wave"], "round": case["round"],
            "raw_html_sha256": case["raw_html_sha256"],
            "raw_html_private_file": case["raw_html_private_file"],
            "captured_at_utc": case["captured_at_utc"],
        }
        identity["task_id"] = _digest(identity)[:24]
        tasks.append(identity)
    packet = {
        "schema_version": VERSION, "kind": BUNDLE_KIND,
        "frozen_plan_sha256": plan["plan_sha256"],
        "accession_sha256": metrics["accession_sha256"],
        "source_round_denominator": 36,
        "human_review_tasks": tasks,
        "parser_predictions_in_reviewer_tasks": False,
        "publisher_original_html_origin_authenticated": False,
        "human_gold_established": False,
        "approved_for_advisor": False,
    }
    packet["task_bundle_sha256"] = _digest(packet)
    return packet, metrics, cases


def blank_reviewer(bundle, letter):
    if letter not in {"A", "B"}:
        raise ValueError("Reviewer letter must be A or B")
    return {
        "schema_version": VERSION, "kind": REVIEW_KIND,
        "reviewer_letter": letter, "reviewer_id": None,
        "task_bundle_sha256": bundle["task_bundle_sha256"],
        "frozen_plan_sha256": bundle["frozen_plan_sha256"],
        "independent_blind_review_attested": False,
        "source_reviews": [{
            **task,
            "reviewed_at_utc": None,
            "page_scope": "not_reviewed",
            "whole_visible_page_review_complete": False,
            "exact_product_scope_reviewed": False,
            "no_relevant_evidence_observed": None,
            "evidence_inventory": [],
            "review_note": "",
            "parser_predictions_hidden": True,
            "approved_for_advisor": False,
        } for task in bundle["human_review_tasks"]],
        "approved_for_advisor": False,
    }


def _visible_html(original):
    root = html.fromstring(original)
    for node in list(root.xpath(
        "//script|//style|//noscript|//template|//nav|//aside|//footer|"
        "//*[@aria-hidden='true']|//*[@hidden]"
    )):
        if node.getparent() is not None:
            node.drop_tree()
    text = _norm(" ".join(root.itertext()))
    return root, text


def _evidence(item, task, doc, visible, *, seen_quotes, seen_owners):
    if (not isinstance(item, dict) or set(item) != EVIDENCE_FIELDS
            or item["approved_for_advisor"] is not False
            or item["evidence_type"] != EVIDENCE_TYPES[task["category"]]
            or item["publisher_evidence_url"] != task["source_url"]):
        raise ValueError("Unknown, cross-owned or privileged source evidence")
    quote = _field(
        item["publisher_evidence_quote"], label="publisher evidence quote",
        required=True, maximum=450,
    )
    if len(quote) < 24:
        raise ValueError("Original evidence quote must be substantial")
    normalized = _norm(quote)
    if visible.count(normalized) != 1 or normalized in seen_quotes:
        raise ValueError("Original visible HTML quote absent, duplicated, or repeated")
    seen_quotes.add(normalized)
    _bounded_note(item["review_note"], "Publisher evidence")
    value = item["reviewed_value"]
    category = task["category"]
    if category == "pricing":
        normalized_value = _rate_scope(category, value)
    elif category == "changelog":
        normalized_value = _release_scope(value, item, task, doc, visible)
        owner = normalized_value["event_owner_url"]
        if owner in seen_owners:
            raise ValueError("Multiple release labels claim the same publisher owner")
        seen_owners.add(owner)
    else:
        normalized_value = _documentation_scope(value)
    return {
        "evidence_id": _digest({
            "task_id": task["task_id"], "quote": normalized,
            "evidence_type": item["evidence_type"],
        })[:24],
        "evidence_type": item["evidence_type"],
        "publisher_evidence_quote": quote,
        "publisher_evidence_url": task["source_url"],
        "reviewed_value": normalized_value,
        "approved_for_advisor": False,
    }


def _read_reviewer(reviewer, expected, bundle, capture_root, *, now):
    letter = expected["reviewer_letter"]
    if (not isinstance(reviewer, dict) or set(reviewer) != ROOT_FIELDS
            or reviewer.get("schema_version") != VERSION
            or reviewer.get("kind") != REVIEW_KIND
            or reviewer.get("reviewer_letter") != letter
            or reviewer.get("frozen_plan_sha256") != bundle["frozen_plan_sha256"]
            or reviewer.get("task_bundle_sha256") != bundle["task_bundle_sha256"]
            or reviewer.get("approved_for_advisor") is not False
            or reviewer.get("independent_blind_review_attested") is not True
            or not isinstance(reviewer.get("reviewer_id"), str)
            or not REVIEWER.fullmatch(reviewer["reviewer_id"])
            or reviewer["reviewer_id"].strip().upper().startswith("REPLACE")
            or not isinstance(reviewer.get("source_reviews"), list)
            or len(reviewer["source_reviews"]) != len(expected["source_reviews"])):
        raise ValueError("Missing complete distinct attested reviewer record")
    reviewer_id = reviewer["reviewer_id"].strip()
    outcomes = {}
    labels_total = 0
    for index, (entry, original) in enumerate(zip(
        reviewer["source_reviews"], expected["source_reviews"]
    )):
        if (not isinstance(entry, dict) or set(entry) != TASK_FIELDS
                or any(entry[key] != original[key] for key in TASK_META)
                or entry["parser_predictions_hidden"] is not True
                or entry["approved_for_advisor"] is not False
                or entry["page_scope"] not in ALLOWED_PAGE_SCOPE
                or type(entry["whole_visible_page_review_complete"]) is not bool
                or type(entry["exact_product_scope_reviewed"]) is not bool
                or not isinstance(entry["evidence_inventory"], list)
                or len(entry["evidence_inventory"]) > MAX_SOURCE_LABELS):
            raise ValueError("Forged/reordered/source-mixed reviewer task")
        task_id = original["task_id"]
        state = entry["page_scope"]
        note = entry["review_note"]
        complete = state == "sufficient_visible_static_page"
        if complete:
            if (entry["whole_visible_page_review_complete"] is not True
                    or entry["exact_product_scope_reviewed"] is not True
                    or type(entry["no_relevant_evidence_observed"]) is not bool):
                raise ValueError("Complete source review must verify page/product scope")
            _bounded_note(note, "Whole-visible-page review")
        else:
            if (entry["whole_visible_page_review_complete"] is not False
                    or entry["exact_product_scope_reviewed"] is not False
                    or entry["no_relevant_evidence_observed"] is not None
                    or entry["evidence_inventory"]):
                raise ValueError("Incomplete/unknown source cannot claim no evidence or labels")
            if state == "not_reviewed" and (entry["reviewed_at_utc"] is not None
                                            or note != ""):
                raise ValueError("Unreviewed task cannot claim human activity")
            if state != "not_reviewed":
                _bounded_note(note, "Incomplete/JS page review")
        stamp = entry["reviewed_at_utc"]
        if state == "not_reviewed":
            if stamp is not None:
                raise ValueError("Unreviewed source cannot have timestamp")
        else:
            stamp = _timestamp(stamp)
            captured = _timestamp(entry["captured_at_utc"])
            if stamp < captured or stamp > now + timedelta(minutes=5):
                raise ValueError("Source review predates HTML or claims future timestamp")
        result_labels = {}
        if complete:
            evidence = entry["evidence_inventory"]
            if entry["no_relevant_evidence_observed"] != (len(evidence) == 0):
                raise ValueError("Empty-page/negative claim conflicts with human inventory")
            original_html = _snapshot_bytes({
                "file": entry["raw_html_private_file"],
                "sha256": entry["raw_html_sha256"],
                "request_url": entry["source_url"],
                "final_url": entry["source_url"],
                "http_status": 200,
                "media_type": "text/html",
                "capture_method": "static_html",
                "captured_at_utc": entry["captured_at_utc"],
                "capture_origin_review_status": "operator_supplied_unverified",
            }, capture_root, expected_url=entry["source_url"], method="static_html")
            doc, visible = _visible_html(original_html)
            used_quotes, used_owners = set(), set()
            for e in evidence:
                result = _evidence(
                    e, entry, doc, visible,
                    seen_quotes=used_quotes, seen_owners=used_owners,
                )
                if result["evidence_id"] in result_labels:
                    raise ValueError("Duplicate publisher evidence ID")
                result_labels[result["evidence_id"]] = result
            labels_total += len(result_labels)
            if labels_total > MAX_TOTAL_LABELS:
                raise ValueError("Review exceeds bounded full study label cap")
        outcomes[task_id] = {
            "reviewer": reviewer_id,
            "scope": state,
            "complete": complete,
            "no_evidence_on_this_visible_page": (
                entry["no_relevant_evidence_observed"] if complete else None
            ),
            "labels": result_labels,
            "approved_for_advisor": False,
        }
    return outcomes


def reconcile(plan, ledger, capture_root, reviewer_a, reviewer_b, *, now=None):
    bundle, accession, cases = build_bundle(
        plan, ledger, capture_root, now=now,
    )
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise ValueError("Reviewer evaluation clock needs explicit timezone")
    clock = clock.astimezone(timezone.utc)
    reference_a = blank_reviewer(bundle, "A")
    reference_b = blank_reviewer(bundle, "B")
    a = _read_reviewer(reviewer_a, reference_a, bundle, capture_root, now=clock)
    b = _read_reviewer(reviewer_b, reference_b, bundle, capture_root, now=clock)
    if reviewer_a["reviewer_id"].strip().casefold() == reviewer_b[
        "reviewer_id"
    ].strip().casefold():
        raise ValueError("Independent reviewers must have distinct named identities")
    source_rounds = []
    consensus = []
    totals, categories = Counter(), {x: Counter() for x in (
        "pricing", "changelog", "documentation",
    )}
    for case in cases:
        key = _digest({
            "source_id": case["source_id"], "source_url": case["source_url"],
            "category": case["category"], "wave": case["wave"],
            "round": case["round"], "raw_html_sha256": case.get("raw_html_sha256"),
            "raw_html_private_file": case.get("raw_html_private_file"),
            "captured_at_utc": case.get("captured_at_utc"),
        })[:24] if case["state"] == "captured" else None
        status = "held_no_original_html"
        hold_reasons = []
        if key is not None:
            if key not in a or key not in b:
                raise ValueError("Reviewer task is missing frozen original source round")
            left, right = a[key], b[key]
            if not left["complete"] or not right["complete"]:
                status = "held_incomplete_blind_page_review"
                hold_reasons += [
                    "reviewer_a_" + left["scope"],
                    "reviewer_b_" + right["scope"],
                ]
            elif (left["no_evidence_on_this_visible_page"] !=
                  right["no_evidence_on_this_visible_page"] or
                  {k: e["reviewed_value"] for k, e in left["labels"].items()}
                  != {k: e["reviewed_value"] for k, e in right["labels"].items()}):
                status = "held_two_reviewers_disagree_on_page_evidence"
                hold_reasons.append("human_census_or_typed_value_disagreement")
            else:
                status = "agreed_two_reviewers_visible_page_inventory"
                evidence = [left["labels"][x] for x in sorted(left["labels"])]
                consensus.append({
                    "source_id": case["source_id"],
                    "source_url": case["source_url"],
                    "category": case["category"],
                    "round": case["round"],
                    "raw_html_sha256": case["raw_html_sha256"],
                    "task_id": key,
                    "evidence": evidence,
                    "visible_page_no_relevant_evidence": len(evidence) == 0,
                    "reviewer_independence_operator_attested_not_proven": True,
                    "publisher_origin_authenticated": False,
                    "approved_for_advisor": False,
                })
                totals["agreed_quote_grounded_labels"] += len(evidence)
                categories[case["category"]]["agreed_labels"] += len(evidence)
        totals[status] += 1
        categories[case["category"]][status] += 1
        source_rounds.append({
            "source_id": case["source_id"],
            "category": case["category"],
            "round": case["round"], "state": case["state"],
            "original_html_sha256": case.get("raw_html_sha256"),
            "dual_review_status": status,
            "hold_reasons": hold_reasons,
            "source_wide_agreement_not_parser_accuracy": True,
            "approved_for_advisor": False,
        })
    if len(source_rounds) != 36:
        raise ValueError("All originally sampled 36 source rounds must remain visible")
    report = {
        "schema_version": VERSION, "kind": REPORT_KIND,
        "frozen_plan_sha256": plan["plan_sha256"],
        "task_bundle_sha256": bundle["task_bundle_sha256"],
        "accession_sha256": accession["accession_sha256"],
        "source_denominator": 18, "source_round_denominator": 36,
        "original_html_rounds": accession["source_rounds_with_valid_byte_sha256"],
        "source_round_outcome_counts": dict(sorted(totals.items())),
        "by_category": {k: dict(sorted(v.items())) for k,v in categories.items()},
        "agreed_visible_page_census_rounds":
            totals["agreed_two_reviewers_visible_page_inventory"],
        "disputed_visible_page_census_rounds":
            totals["held_two_reviewers_disagree_on_page_evidence"],
        "not_reviewed_or_insufficient_page_rounds":
            totals["held_incomplete_blind_page_review"],
        "human_agreed_quote_bound_evidence_labels":
            totals["agreed_quote_grounded_labels"],
        "publisher_origin_independently_authenticated": False,
        "reviewer_independence_cryptographically_verified": False,
        "agreement_does_not_prove_fact_truth": True,
        "precision": None, "recall": None, "false_positives": None,
        "false_negatives": None,
        "parser_evidence_identity_matching_completed": False,
        "accuracy_measurable": False,
        "no_publisher_permissions_granted": True,
        "new_network_requests": 0, "new_zyte_jobs": 0,
        "advisor_fact_approvals": 0, "approved_for_advisor": False,
    }
    report["report_sha256"] = _digest({
        "report": report, "source_rounds": source_rounds,
        "consensus": consensus,
    })
    return report, source_rounds, consensus


def _private_json(root, filename, data):
    _write_private(
        root / filename,
        (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(),
    )


def write_templates(bundle, out_dir):
    root = _private_new_directory(out_dir)
    try:
        _private_json(root, "cross_category_blind_task_bundle.json", bundle)
        for letter in ("A", "B"):
            _private_json(
                root, "independent_reviewer_" + letter + "_BLANK.json",
                blank_reviewer(bundle, letter),
            )
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def write_consensus(scored, out_dir):
    report, rounds, consensus = scored
    root = _private_new_directory(out_dir)
    try:
        _private_json(root, "cross_category_review_readiness_NOT_ACCURACY.json", report)
        _private_json(root, "all_36_source_round_review_status.json", rounds)
        _private_json(root, "agreed_quote_grounded_evidence_PRIVATE.json", {
            "schema_version": VERSION,
            "kind": "p22a2_private_two_human_evidence_inventory",
            "source_rounds": consensus,
            "verified_publisher_facts": 0,
            "advisor_fact_approvals": 0,
            "parser_accuracy_established": False,
        })
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def _read_json(path, maximum=MAX_REVIEW_JSON):
    p = Path(path)
    if (not p.is_file() or p.is_symlink()
            or any(x.is_symlink() for x in p.parents)
            or not 2 <= p.stat().st_size <= maximum):
        raise ValueError("Private P22A2 input missing, oversized or symlinked")
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-reviewers", action="store_true")
    mode.add_argument("--reconcile", action="store_true")
    p.add_argument("--frozen-plan", type=Path, required=True)
    p.add_argument("--private-ledger", type=Path, required=True)
    p.add_argument("--capture-root", type=Path, required=True)
    p.add_argument("--reviewer-a", type=Path)
    p.add_argument("--reviewer-b", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    plan = _read_json(args.frozen_plan)
    ledger = _read_json(args.private_ledger)
    if args.prepare_reviewers:
        if args.reviewer_a or args.reviewer_b:
            p.error("Blind preparation cannot inspect filled reviewers")
        bundle, _, _ = build_bundle(plan, ledger, args.capture_root)
        root = write_templates(bundle, args.out_dir)
        result = {"private_blind_review_templates": str(root),
                  "review_tasks": len(bundle["human_review_tasks"])}
    else:
        if not args.reviewer_a or not args.reviewer_b:
            p.error("Independent reviewer A and B files both required")
        a = _read_json(args.reviewer_a)
        b = _read_json(args.reviewer_b)
        scored = reconcile(plan, ledger, args.capture_root, a, b)
        root = write_consensus(scored, args.out_dir)
        result = {"private_consensus": str(root),
                  "source_round_denominator": 36,
                  "visible_page_rounds_agreed":
                     scored[0]["agreed_visible_page_census_rounds"]}
    print(json.dumps({
        **result, "publisher_fetches": 0, "zyte_jobs": 0,
        "human_gold_claimed_automatically": False,
        "parser_precision_recall_measurable": False,
    }, indent=2))


if __name__ == "__main__":
    main()
