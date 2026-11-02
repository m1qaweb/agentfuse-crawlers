"""P19A2 synthetic, source-wide blinded release owner/date gold scoring.

Invented HTML + fake distinct reviewer labels. No publisher requests,
no real review or confidence claim. The source-wide census MUST catch
missed release cards the P19A1 event-derived tasks could never present.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from agentfuse_crawlers.sources import load_sources
from scripts.replay_release_snapshots import (
    _digest, replay_changelog_html,
)
from scripts.score_release_gold import (
    PACKET_KIND, _full_day, _owner_node, _split_key,
    prepare_census_packet, reviewer_template, score_census,
)

SID = "openai_api_changelog"
KNOWN = {s["id"]: s for s in load_sources()}
URL = KNOWN[SID]["url"]
KEY = "example-key-for-synthetic-gold-tests-only-2026-11-02"
CAPTURED = "2026-11-02T10:00:00Z"
REVIEWED = "2026-11-02T11:00:00Z"
NOTE = (
    "I independently inspected the entire original frozen HTML page, "
    "including release cards, owners, publication labels, and negative cases."
)


def title(n):
    return "Imaginary model release v2." + str(n) + ".0"


def body(n):
    return (
        "Release " + str(n) + " has a unique synthetic technical announcement "
        "and documentation evidence about imaginary developer API changes. "
        "This card discusses a fake model capability, settings, predictable "
        "execution, safer workflows, documentation improvements, migration "
        "considerations, clear boundaries, and product compatibility, "
        "all created exclusively for test coverage."
    )


def release(n, day, *, heading_version=True):
    name = title(n) if heading_version else "Synthetic parser-missed adjustment " + str(n)
    time_markup = (
        '<time datetime="' + day + 'T09:00:00Z">' + day + '</time>'
        if day else ""
    )
    return (
        '<article><header><h2 id="r' + str(n) + '">' + name + '</h2>'
        + time_markup + '</header><p>' + body(n) + '</p></article>'
    )


def html_page(records):
    return (
        "<!doctype html><html><head><title>OpenAI API Changelog</title>"
        "</head><body><main><h1>OpenAI API Changelog</h1>"
        + "".join(records) + "</main></body></html>"
    )


BASE_HTML = html_page([
    release(2, "2026-10-28"),
    release(1, "2026-10-26"),
])


def fixture(tmp_path, raw_html=BASE_HTML):
    p = tmp_path / "publisher.html"
    p.write_text(raw_html, encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "kind": "frozen_original_changelog_html_manifest",
        "expected_manifest_sha256": __import__(
            "agentfuse_crawlers.run_context", fromlist=["manifest_sha256"]
        ).manifest_sha256(),
        "expected_source_registry_sha256": __import__(
            "agentfuse_crawlers.source_lifecycle",
            fromlist=["registry_revision_sha256"]
        ).registry_revision_sha256(),
        "approved_for_advisor": False,
        "snapshots": [{
            "source_id": SID,
            "snapshot": {
                "file": p.name,
                "sha256": hashlib.sha256(raw_html.encode()).hexdigest(),
                "request_url": URL, "final_url": URL, "http_status": 200,
                "media_type": "text/html",
                "capture_method": "static_html",
                "captured_at_utc": CAPTURED,
                "capture_origin_review_status": "operator_supplied_unverified",
            },
        }],
    }
    replay = replay_changelog_html(manifest, tmp_path)
    packet = prepare_census_packet(
        replay, manifest, tmp_path, split_key=KEY,
    )
    return manifest, replay, packet


def entry(n, day, *, state="explicit_publication_day",
          version=None, quote=None, date_text=None, heading_version=True):
    name = title(n) if heading_version else (
        "Synthetic parser-missed adjustment " + str(n)
    )
    date_value = day if state == "explicit_publication_day" else None
    actual_quote = (name + (" " + day if day else "") + " " +
                    "Release " + str(n) + " has a unique synthetic technical announcement")
    return {
        "owner_url": URL + "#r" + str(n),
        "publisher_title": name,
        "version": version,
        "date_status": state,
        "published_at": date_value,
        "date_evidence_text": (
            date_text if date_text is not None
            else day if date_value else ""
        ),
        "publisher_evidence_quote": quote or actual_quote,
        "review_note": (
            "I found the unique release-owned heading, inspected its full "
            "original card and recorded the visible publisher evidence."
        ),
        "approved_for_advisor": False,
    }


def reviewer(packet, who, labels, *, complete=True, unattributed=0,
             note=NOTE):
    x = reviewer_template(packet, who)
    x["reviewer_id"] = "Independent Reviewer " + who.upper()
    x["independent_blind_review_attested"] = True
    assert len(x["source_reviews"]) == 1
    record = x["source_reviews"][0]
    record.update({
        "reviewed_full_visible_html": complete,
        "event_list_complete": complete,
        "unattributed_release_count": unattributed,
        "release_count_observed": len(labels) + unattributed,
        "census_note": note,
        "reviewed_at_utc": REVIEWED,
        "events": labels,
    })
    return x


def score_fixture(tmp_path, raw_html=BASE_HTML, a=None, b=None):
    manifest, replay, packet = fixture(tmp_path, raw_html)
    default = [entry(2, "2026-10-28"), entry(1, "2026-10-26")]
    left = reviewer(packet, "a", deepcopy(default if a is None else a))
    right = reviewer(packet, "b", deepcopy(default if b is None else b))
    result = score_census(replay, manifest, tmp_path, packet, left, right,
                          split_key=KEY)
    return result, manifest, replay, packet, left, right


def test_packet_is_source_wide_not_leaked_parser_candidate_list(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    assert len(load_sources()) == 460
    assert replay["source_count"] == 1
    assert packet["kind"] == PACKET_KIND
    assert packet["provider_group_count"] == 1
    assert len(packet["tasks"]) == 1
    task = packet["tasks"][0]
    assert task["census_scope"] == "entire_original_frozen_html_page"
    assert task["predicted_release_ids_prefilled"] is False
    assert task["predicted_titles_prefilled"] is False
    assert task["predicted_dates_prefilled"] is False
    assert "events" not in task and "published_at" not in task
    assert not packet["approved_for_advisor"]
    a = reviewer_template(packet, "a")
    b = reviewer_template(packet, "b")
    assert a["source_reviews"][0]["events"] == []
    assert b["source_reviews"][0]["events"] == []
    assert not a["independent_blind_review_attested"]
    assert a["reviewer_id"] != b["reviewer_id"]
    assert packet == prepare_census_packet(
        replay, manifest, tmp_path, split_key=KEY,
    )
    assert packet["split_key_commitment_sha256"] != KEY


def test_dual_agreed_full_census_yields_provisional_metrics_but_no_approval(tmp_path):
    result, _, replay, packet, _, _ = score_fixture(tmp_path)
    source = result["sources"][0]
    assert source["status"] == "dual_review_agreed_snapshot_diagnostic"
    m = source["diagnostic_only_metrics"]
    assert m["release_owner_tp"] == 2
    assert m["release_owner_fp"] == 0
    assert m["release_owner_fn"] == 0
    assert m["owner_precision"] == 1
    assert m["owner_recall"] == 1
    assert m["publication_date_exact_matches"] == 2
    assert m["publication_date_checked_matches"] == 2
    assert m["publication_date_exact_rate"] == 1
    assert source["parser_retained_release_count"] == 2
    assert not result["sample_diversity_thresholds_met"]
    assert result["generalizable_release_accuracy_established"] is False
    assert result["independently_authenticated_publisher_origin"] is False
    assert result["publisher_truth_verified"] is False
    assert result["benchmark_or_adapter_rollout_authorized"] is False
    assert result["new_release_alerts"] == 0
    assert result["advisor_fact_approvals"] == 0
    assert result["network_requests_performed"] == 0
    assert result["capture_manifest_sha256"] == replay["capture_manifest_sha256"]
    assert result["blind_census_packet_sha256"] == packet["packet_sha256"]
    assert result["sources"][0]["evaluation_split"] in {"development", "holdout"}


def test_true_false_negative_not_covered_by_parser_candidate_sampling(tmp_path):
    raw = html_page([
        release(2, "2026-10-28"),
        release(1, "2026-10-26"),
        release(3, None, heading_version=False),
    ])
    manual = [
        entry(2, "2026-10-28"), entry(1, "2026-10-26"),
        entry(3, None, state="explicitly_undated", heading_version=False),
    ]
    result, _, replay, _, _, _ = score_fixture(
        tmp_path, raw, a=manual, b=manual,
    )
    assert len(replay["sources"][0]["events"]) == 2
    metrics = result["sources"][0]["diagnostic_only_metrics"]
    assert metrics["release_owner_tp"] == 2
    assert metrics["release_owner_fp"] == 0
    assert metrics["release_owner_fn"] == 1
    assert metrics["owner_recall"] == pytest.approx(2 / 3)
    assert metrics["publication_date_exact_rate"] == 1


def test_parser_false_positive_is_explicitly_counted_not_publication(tmp_path):
    result, _, _, _, _, _ = score_fixture(
        tmp_path, a=[entry(1, "2026-10-26")],
        b=[entry(1, "2026-10-26")],
    )
    m = result["sources"][0]["diagnostic_only_metrics"]
    assert m["release_owner_tp"] == 1
    assert m["release_owner_fp"] == 1
    assert m["release_owner_fn"] == 0
    assert m["owner_precision"] == pytest.approx(0.5)
    assert not result["publisher_truth_verified"]


def test_human_explicit_undated_but_parser_date_is_date_error(tmp_path):
    label = [entry(2, "2026-10-28", state="explicitly_undated"),
             entry(1, "2026-10-26")]
    result, _, _, _, _, _ = score_fixture(tmp_path, a=label, b=label)
    m = result["sources"][0]["diagnostic_only_metrics"]
    assert m["publication_date_exact_matches"] == 1
    assert m["publication_date_checked_matches"] == 2
    assert m["publication_date_exact_rate"] == 0.5


def test_ambiguous_reference_date_is_excluded_not_scored_as_correct(tmp_path):
    label = [entry(2, "2026-10-28", state="ambiguous"),
             entry(1, "2026-10-26")]
    result, _, _, _, _, _ = score_fixture(tmp_path, a=label, b=label)
    m = result["sources"][0]["diagnostic_only_metrics"]
    assert m["publication_date_checked_matches"] == 1
    assert m["publication_date_unresolved_reference_matches"] == 1
    assert m["publication_date_exact_rate"] == 1


def test_disagreement_and_unowned_release_never_claim_accuracy(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    a = reviewer(packet, "a", [entry(2, "2026-10-28"), entry(1, "2026-10-26")])
    b = reviewer(packet, "b", [entry(2, "2026-10-28")])
    held = score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)
    assert held["sources"][0]["status"] == "held_no_accuracy_claim"
    assert "independent_reviewer_owner_title_date_or_version_disagreement" in (
        held["sources"][0]["hold_reasons"]
    )
    assert held["sources"][0]["diagnostic_only_metrics"] is None
    assert sum(x["scored_sources"] for x in held["splits"].values()) == 0
    b = reviewer(packet, "b", [entry(2, "2026-10-28"),
                                entry(1, "2026-10-26")], unattributed=1)
    held = score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)
    assert "publisher_release_owner_unattributed" in held["sources"][0]["hold_reasons"]


def test_not_full_page_census_cannot_score_as_zero_false_negative(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    a = reviewer(packet, "a", [], complete=False)
    b = reviewer(packet, "b", [], complete=False)
    report = score_census(replay, manifest, tmp_path, packet, a, b,
                          split_key=KEY)
    assert report["sources"][0]["diagnostic_only_metrics"] is None
    assert "whole_original_page_not_fully_reviewed" in (
        report["sources"][0]["hold_reasons"]
    )
    assert report["splits"]["development"]["diagnostic_owner_precision"] is None or (
        report["splits"]["holdout"]["diagnostic_owner_precision"] is None
    )


def test_manually_referenced_release_owner_must_exist_in_frozen_dom(tmp_path):
    for bad in (
        "https://evil.example/api/docs/changelog#r2",
        URL, URL + "?secret=abc#r2", URL + "#not-in-html",
        URL + "#r2%2E", URL + "/release-fake",
        URL + "/../pricing#r2",
    ):
        manifest, replay, packet = fixture(tmp_path)
        a = reviewer(packet, "a", [entry(2, "2026-10-28"),
                                   entry(1, "2026-10-26")])
        b = reviewer(packet, "b", deepcopy(a["source_reviews"][0]["events"]))
        a["source_reviews"][0]["events"][0]["owner_url"] = bad
        with pytest.raises(ValueError, match="owner|URL|release"):
            score_census(replay, manifest, tmp_path, packet, a, b,
                         split_key=KEY)


@pytest.mark.parametrize("change", [
    lambda x: x.update(approved_for_advisor=True),
    lambda x: x["source_reviews"][0]["events"][0].update(
        approved_for_advisor=True),
    lambda x: x["source_reviews"][0]["events"][0].update(
        publisher_evidence_quote="a hallucinated quote that is missing"),
    lambda x: x["source_reviews"][0]["events"][0].update(
        publisher_title="Product that is not present in frozen HTML"),
    lambda x: x["source_reviews"][0]["events"][0].update(
        published_at="2026-10-29"),
    lambda x: x["source_reviews"][0]["events"][0].update(
        date_evidence_text="Oct 28"),
    lambda x: x["source_reviews"][0]["events"][0].update(
        date_evidence_text="2026-10-27"),
    lambda x: x["source_reviews"][0].update(release_count_observed=50),
    lambda x: x["source_reviews"][0].update(
        reviewed_at_utc="2026-11-01T01:00:00Z"),
    lambda x: x.update(packet_sha256="f" * 64),
])
def test_false_human_evidence_or_privilege_flags_rejected(tmp_path, change):
    manifest, replay, packet = fixture(tmp_path)
    a = reviewer(packet, "a", [entry(2, "2026-10-28"),
                               entry(1, "2026-10-26")])
    b = reviewer(packet, "b", deepcopy(a["source_reviews"][0]["events"]))
    change(a)
    with pytest.raises(ValueError):
        score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)


def test_duplicate_gold_owner_cannot_create_new_release(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    labels = [entry(2, "2026-10-28"), entry(2, "2026-10-28")]
    a, b = reviewer(packet, "a", labels), reviewer(packet, "b", labels)
    with pytest.raises(ValueError, match="Duplicate"):
        score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)


def test_reviewer_id_and_independence_attestation_are_mandatory(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    labels = [entry(2, "2026-10-28"), entry(1, "2026-10-26")]
    a = reviewer(packet, "a", labels)
    b = deepcopy(a)
    with pytest.raises(ValueError, match="distinct"):
        score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)
    b["reviewer_id"] = "Independent Reviewer B"
    a["independent_blind_review_attested"] = False
    with pytest.raises(ValueError, match="attestation"):
        score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)


def test_wrong_snapshot_bytes_and_self_forged_replay_never_score(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    labels = [entry(2, "2026-10-28"), entry(1, "2026-10-26")]
    a, b = reviewer(packet, "a", labels), reviewer(packet, "b", labels)
    fake = deepcopy(replay)
    fake["sources"][0]["events"][0]["published_at"] = "2026-10-30"
    fake["replay_sha256"] = _digest({
        k: v for k, v in fake.items() if k != "replay_sha256"
    })
    with pytest.raises(ValueError, match="actual original HTML"):
        score_census(fake, manifest, tmp_path, packet, a, b, split_key=KEY)
    path = tmp_path / "publisher.html"
    path.write_text(path.read_text().replace("Release 1", "Altered 1"),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)


def test_packet_HMAC_split_tampering_is_rejected(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    labels = [entry(2, "2026-10-28"), entry(1, "2026-10-26")]
    a, b = reviewer(packet, "a", labels), reviewer(packet, "b", labels)
    for wrong_key in (
        "this-is-another-different-private-synthetic-split-key",
        "too short",
    ):
        with pytest.raises(ValueError, match="packet/split|HMAC"):
            score_census(replay, manifest, tmp_path, packet, a, b,
                         split_key=wrong_key)
    changed = deepcopy(packet)
    changed["tasks"][0]["evaluation_split"] = (
        "development" if changed["tasks"][0]["evaluation_split"] == "holdout"
        else "holdout"
    )
    with pytest.raises(ValueError, match="packet/split"):
        score_census(replay, manifest, tmp_path, changed, a, b, split_key=KEY)
    with pytest.raises(ValueError, match="Holdout percent"):
        prepare_census_packet(replay, manifest, tmp_path,
                              split_key=KEY, holdout_percent=0)


def test_duplicate_OR_unresolved_human_source_reviews_rejected(tmp_path):
    manifest, replay, packet = fixture(tmp_path)
    labels = [entry(2, "2026-10-28"), entry(1, "2026-10-26")]
    a, b = reviewer(packet, "a", labels), reviewer(packet, "b", labels)
    a["source_reviews"].append(deepcopy(a["source_reviews"][0]))
    with pytest.raises(ValueError):
        score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)
    a = reviewer(packet, "a", labels)
    a["source_reviews"][0]["task_id"] = "0" * 24
    with pytest.raises(ValueError, match="task"):
        score_census(replay, manifest, tmp_path, packet, a, b, split_key=KEY)


def test_independent_day_parser_requires_full_year_and_valid_date():
    assert _full_day("Oct 28, 2026") == "2026-10-28"
    assert _full_day("Published on: October 28, 2026") == "2026-10-28"
    assert _full_day("2026-10-28") == "2026-10-28"
    assert _full_day("Oct 28") is None
    assert _full_day("2026-02-30") is None
    with pytest.raises(ValueError):
        _split_key("short")


def test_parser_omission_of_more_than_80_release_cards_holds_accuracy(tmp_path):
    html_text = html_page([
        release(i, "2026-10-28") for i in range(90, 9, -1)
    ])
    # 81 publisher-visible synthetic release cards; 80-event extractor limit.
    manifest, replay, packet = fixture(tmp_path, html_text)
    assert replay["sources"][0]["release_events_omitted"] > 0
    events = [entry(i, "2026-10-28") for i in range(90, 9, -1)]
    a, b = reviewer(packet, "a", deepcopy(events)), reviewer(packet, "b", deepcopy(events))
    result = score_census(replay, manifest, tmp_path, packet, a, b,
                          split_key=KEY)
    assert result["sources"][0]["status"] == "held_no_accuracy_claim"
    assert "parser_recent_window_omits_visible_releases" in (
        result["sources"][0]["hold_reasons"]
    )
    assert result["sources"][0]["diagnostic_only_metrics"] is None
