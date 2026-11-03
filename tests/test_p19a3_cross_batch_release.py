"""P19A3 source-wide cross-batch gold aggregation: synthetic publisher HTML.

Tests use only invented release cards and self-authored synthetic reviewers.
They NEVER prove publisher origin, human independence or parser field accuracy.
"""
import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.aggregate_release_pilot import (
    _batch_inputs, _safe_member, aggregate_release_pilot,
    main as pilot_cli,
)
from scripts.replay_release_snapshots import (
    _digest, replay_changelog_html,
)
from scripts.score_release_gold import (
    prepare_census_packet, reviewer_template,
)

KNOWN = {s["id"]: s for s in load_sources()}
OPENAI = "openai_api_changelog"
KIRO = "kiro_changelog"
KEY = "p19a3-only-synthetic-split-key-not-a-real-secret-2026"
CAPTURE = "2026-11-02T10:00:00Z"
REVIEW = "2026-11-02T12:00:00Z"
NOTE = (
    "I independently reviewed every visible release card on the frozen "
    "synthetic HTML page, identified their publisher anchors and checked "
    "each date evidence and possible missing release."
)
LONG = (
    "This synthetic example reports no genuine release. It describes "
    "imaginary developer model improvements, configuration options, "
    "documentation enhancements, version compatibility, validation "
    "details, migration notes, reliability behavior, an explanatory "
    "technical workflow and expected product support boundaries. "
    "All information is invented solely for deterministic tests."
)


def brand(sid):
    return "OpenAI API" if sid == OPENAI else "Kiro"


def release_title(sid, n, *, missed=False):
    if missed:
        return brand(sid) + " private synthetic improvement " + str(n)
    return brand(sid) + " test release v2." + str(n) + ".0"


def release_body(sid, n):
    return (
        "Unique release " + brand(sid) + " number " + str(n) + ". " + LONG
    )


def day(n):
    return "2026-10-" + str(n + 20).zfill(2)


def card(sid, n, *, missed=False, when=None):
    title = release_title(sid, n, missed=missed)
    date_string = "" if missed else (when or day(n))
    stamp = ('<time datetime="' + date_string + 'T10:00:00Z">' +
             date_string + '</time>') if date_string else ""
    return (
        '<article><header><h2 id="r' + str(n) + '">' + title + '</h2>'
        + stamp + '</header><p>' + release_body(sid, n) + '</p></article>'
    )


def source_html(sid, *, recognized=(2, 1), missed=()):
    if sid not in KNOWN or KNOWN[sid]["category"] != "changelog":
        raise AssertionError("Not a real configured changelog source")
    doc = (
        "<!doctype html><html><head><title>" + brand(sid) +
        " Changelog</title></head><body><main><h1>" + brand(sid) +
        " Changelog</h1>"
    )
    for n in recognized:
        doc += card(sid, n)
    for n in missed:
        doc += card(sid, n, missed=True)
    return doc + "</main></body></html>"


def review_label(sid, n, *, missed=False, explicit=None):
    title = release_title(sid, n, missed=missed)
    value = None if missed else (explicit or day(n))
    quote = (title + (" " + value if value else "") +
             " " + "Unique release " + brand(sid) + " number " + str(n) +
             ". This synthetic example reports no genuine release.")
    return {
        "owner_url": KNOWN[sid]["url"] + "#r" + str(n),
        "publisher_title": title,
        "version": None if missed else "2." + str(n) + ".0",
        "date_status": "explicitly_undated" if missed else "explicit_publication_day",
        "published_at": value,
        "date_evidence_text": value or "",
        "publisher_evidence_quote": quote,
        "review_note": (
            "The unique release card, exact pinned source anchor and "
            "the visible publication dateline were checked independently."
        ),
        "approved_for_advisor": False,
    }


def _write(folder, filename, payload):
    dest = folder / filename
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def make_batch(root, sid, batch_id, *, recognized=(2, 1),
               missed=(), gold=None, wrong_b=None, fake_html=None):
    directory = root / batch_id
    directory.mkdir()
    raw = fake_html if fake_html is not None else source_html(
        sid, recognized=recognized, missed=missed,
    )
    (directory / "source.html").write_text(raw, encoding="utf-8")
    meta = {
        "schema_version": "1.0",
        "kind": "frozen_original_changelog_html_manifest",
        "expected_manifest_sha256": manifest_sha256(),
        "expected_source_registry_sha256": registry_revision_sha256(),
        "approved_for_advisor": False,
        "snapshots": [{
            "source_id": sid,
            "snapshot": {
                "file": "source.html",
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "request_url": KNOWN[sid]["url"],
                "final_url": KNOWN[sid]["url"],
                "http_status": 200,
                "media_type": "text/html",
                "capture_method": "static_html",
                "captured_at_utc": CAPTURE,
                "capture_origin_review_status": "operator_supplied_unverified",
            },
        }],
    }
    replay = replay_changelog_html(meta, directory)
    packet = prepare_census_packet(
        replay, meta, directory, split_key=KEY,
    )
    if gold is None:
        gold = [review_label(sid, n) for n in recognized] + [
            review_label(sid, n, missed=True) for n in missed
        ]
    for who in ("a", "b"):
        template = reviewer_template(packet, who)
        template["reviewer_id"] = "Synthetic Reviewer " + who.upper()
        template["independent_blind_review_attested"] = True
        source = template["source_reviews"][0]
        labels = deepcopy(gold if who == "a" or wrong_b is None else wrong_b)
        source.update({
            "reviewed_full_visible_html": True,
            "event_list_complete": True,
            "unattributed_release_count": 0,
            "release_count_observed": len(labels),
            "census_note": NOTE,
            "reviewed_at_utc": REVIEW,
            "events": labels,
        })
        _write(directory, "reviewer_" + who + ".json", template)
    for name, value in (
        ("replay.json", replay), ("manifest.json", meta),
        ("packet.json", packet),
    ):
        _write(directory, name, value)
    return {
        "batch_id": batch_id,
        "replay": batch_id + "/replay.json",
        "capture_manifest": batch_id + "/manifest.json",
        "snapshot_root": batch_id,
        "blind_packet": batch_id + "/packet.json",
        "reviewer_a": batch_id + "/reviewer_a.json",
        "reviewer_b": batch_id + "/reviewer_b.json",
    }


def cohort(*batches):
    return {
        "schema_version": "1.0",
        "kind": "p19a3_reviewed_release_source_batch_cohort",
        "approved_for_advisor": False,
        "holdout_percent": 25,
        "batches": list(batches),
    }


def two_batches(tmp_path):
    b1 = make_batch(tmp_path, OPENAI, "batch_openai")
    b2 = make_batch(tmp_path, KIRO, "batch_kiro")
    return cohort(b1, b2)


def test_real_source_manifest_pinned_and_cross_batch_micro_macro(tmp_path):
    assert len(load_sources()) == 460
    inputs = two_batches(tmp_path)
    result = aggregate_release_pilot(inputs, tmp_path, split_key=KEY)
    assert result["batch_count"] == 2
    assert result["source_count"] == 2
    assert result["provisional_publisher_group_count"] == 2
    assert result["pilot_sample_coverage_diagnostic_ready"] is False
    assert "need_at_least_3_independently_reviewed_small_batches" in (
        result["pilot_coverage_blockers"]
    )
    assert result["all_selected_sources"]["diagnostic_scored_source_count"] == 2
    assert result["all_selected_sources"]["held_source_count"] == 0
    assert result["all_selected_sources"]["reference_releases_scored"] == 4
    assert result["all_selected_sources"]["owner_tp"] == 4
    assert result["all_selected_sources"]["owner_fn"] == 0
    assert result["all_selected_sources"][
        "micro_owner_precision_on_scored_sources_only"] == 1
    assert result["all_selected_sources"][
        "macro_owner_recall_on_complete_providers_only"] == 1
    assert len(result["report_sha256"]) == 64
    assert result["local_package_sha256"] == (
        result["input_manifest_batches"][0]["replay_sha256"]
        and result["local_package_sha256"]
    )
    assert result["source_manifest_sha256"] == manifest_sha256()
    for field in (
        "publisher_truth_verified", "generalizable_release_accuracy_established",
        "reviewer_independence_cryptographically_verified",
        "approval_of_provider_specific_adapters", "deployment_authorized",
    ):
        assert result[field] is False
    assert result["advisor_fact_approvals"] == 0
    assert result["new_release_alerts"] == 0
    assert result["zyte_jobs_created"] == 0
    assert result["network_requests_performed"] == 0
    assert all("excerpt" not in str(x) for x in result["sources"])


def test_cross_batch_genuine_false_negative_and_provider_weighting(tmp_path):
    b1 = make_batch(tmp_path, OPENAI, "batch_openai",
                    recognized=(2, 1), missed=(3,))
    b2 = make_batch(tmp_path, KIRO, "batch_kiro", recognized=(1,))
    result = aggregate_release_pilot(cohort(b1, b2), tmp_path, split_key=KEY)
    all_ = result["all_selected_sources"]
    assert all_["owner_tp"] == 3
    assert all_["owner_fp"] == 0
    assert all_["owner_fn"] == 1
    assert all_["micro_owner_recall_on_scored_sources_only"] == pytest.approx(.75)
    assert all_["macro_owner_recall_on_complete_providers_only"] == pytest.approx(
        (2/3 + 1) / 2,
    )
    assert all_["reference_releases_scored"] == 4
    assert not result["pilot_sample_coverage_diagnostic_ready"]


def test_held_reviewer_disagreement_is_visible_not_hidden_in_macro(tmp_path):
    b1 = make_batch(tmp_path, OPENAI, "batch_openai")
    b2 = make_batch(
        tmp_path, KIRO, "batch_kiro",
        wrong_b=[review_label(KIRO, 2)],
    )
    result = aggregate_release_pilot(cohort(b1, b2), tmp_path, split_key=KEY)
    all_ = result["all_selected_sources"]
    assert all_["diagnostic_scored_source_count"] == 1
    assert all_["held_source_count"] == 1
    assert all_["fully_scored_provisional_provider_groups"] == 1
    assert result["held_reason_counts"][
        "independent_reviewer_owner_title_date_or_version_disagreement"
    ] == 1
    assert "unattributable_colliding_clipped_or_disagreed_sources_remain" in (
        result["pilot_coverage_blockers"]
    )
    held = next(x for x in result["sources"] if x["source_id"] == KIRO)
    assert held["diagnostic_only_metrics"] is None
    assert held["approved_for_advisor"] is False


def test_duplicate_source_across_batches_is_rejected(tmp_path):
    a = make_batch(tmp_path, OPENAI, "batch_a")
    b = make_batch(tmp_path, OPENAI, "batch_b")
    with pytest.raises(ValueError, match="Duplicate source"):
        aggregate_release_pilot(cohort(a, b), tmp_path, split_key=KEY)


def test_unsafe_source_paths_symlink_and_manifest_shape_rejected(tmp_path):
    data = two_batches(tmp_path)
    for invalid in ("../escape.json", "/etc/passwd", "batch_openai//packet.json",
                    "batch_openai/./packet.json", "batch_openai\\packet.json"):
        altered = deepcopy(data)
        altered["batches"][0]["blind_packet"] = invalid
        with pytest.raises(ValueError, match="path|outside|root|escapes"):
            aggregate_release_pilot(altered, tmp_path, split_key=KEY)
    # Symlinked review inputs are not opened even if they point within root.
    original = tmp_path / "batch_openai" / "packet.json"
    linked = tmp_path / "batch_openai" / "linked_packet.json"
    try:
        linked.symlink_to(original)
    except OSError:
        pytest.skip("Symlinks not available on this filesystem")
    data["batches"][0]["blind_packet"] = "batch_openai/linked_packet.json"
    with pytest.raises(ValueError, match="symlink"):
        aggregate_release_pilot(data, tmp_path, split_key=KEY)
    data = two_batches_again_if_needed_not_called


def test_missing_or_incomplete_manifest_never_yields_pilot_approval(tmp_path):
    data = two_batches(tmp_path)
    for mutate in (
        lambda x: x.update(approved_for_advisor=True),
        lambda x: x.update(holdout_percent=True),
        lambda x: x.update(kind="forged_verified_changelog_gold"),
        lambda x: x["batches"][0].update(batch_id="batch_kiro"),
        lambda x: x["batches"][0].update(extra_untrusted_input="true"),
    ):
        altered = deepcopy(data)
        mutate(altered)
        with pytest.raises(ValueError):
            aggregate_release_pilot(altered, tmp_path, split_key=KEY)
    with pytest.raises(ValueError):
        aggregate_release_pilot(cohort(), tmp_path, split_key=KEY)


def test_forged_replay_package_or_exact_raw_html_detected(tmp_path):
    data = two_batches(tmp_path)
    file = tmp_path / "batch_openai" / "replay.json"
    forged = json.loads(file.read_text())
    forged["local_package_sha256"] = "a" * 64
    forged["replay_sha256"] = _digest({
        k: v for k, v in forged.items() if k != "replay_sha256"
    })
    _write(file.parent, file.name, forged)
    with pytest.raises(ValueError, match="actual original HTML"):
        aggregate_release_pilot(data, tmp_path, split_key=KEY)
    # Restore replay and corrupt only the private bytes.
    manifest = json.loads((file.parent / "manifest.json").read_text())
    _write(file.parent, file.name, replay_changelog_html(
        manifest, file.parent,
    ))
    (file.parent / "source.html").write_text(
        "<html><body>changed original bytes</body></html>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="SHA-256"):
        aggregate_release_pilot(data, tmp_path, split_key=KEY)


def test_wrong_private_holdout_key_or_tampered_split_fail_closed(tmp_path):
    data = two_batches(tmp_path)
    with pytest.raises(ValueError, match="packet/split"):
        aggregate_release_pilot(
            data, tmp_path,
            split_key="different-long-private-test-key-for-p19a3",
        )
    with pytest.raises(ValueError, match="HMAC"):
        aggregate_release_pilot(data, tmp_path, split_key="short")
    file = tmp_path / "batch_kiro" / "packet.json"
    pkt = json.loads(file.read_text())
    pkt["tasks"][0]["evaluation_split"] = (
        "holdout" if pkt["tasks"][0]["evaluation_split"] == "development"
        else "development"
    )
    _write(file.parent, file.name, pkt)
    with pytest.raises(ValueError, match="packet/split"):
        aggregate_release_pilot(data, tmp_path, split_key=KEY)


def test_future_scheduled_publication_is_not_historical_gold(tmp_path):
    b1 = make_batch(tmp_path, OPENAI, "batch_openai",
                    recognized=(2, 1))
    b2 = make_batch(tmp_path, KIRO, "batch_kiro")
    # Explicit future card in immutable original HTML, beyond UTC+14 tolerance.
    folder = tmp_path / "batch_openai"
    raw = source_html(OPENAI, recognized=(2, 1))
    future = raw.replace(day(2), "2026-11-05")
    # Recreate same-source manifest and original replay pins.
    (folder / "source.html").write_text(future, encoding="utf-8")
    meta = json.loads((folder / "manifest.json").read_text())
    meta["snapshots"][0]["snapshot"]["sha256"] = hashlib.sha256(
        future.encode(),
    ).hexdigest()
    replay = replay_changelog_html(meta, folder)
    packet = prepare_census_packet(replay, meta, folder, split_key=KEY)
    _write(folder, "manifest.json", meta)
    _write(folder, "replay.json", replay)
    _write(folder, "packet.json", packet)
    for who in "ab":
        ref = reviewer_template(packet, who)
        ref["reviewer_id"] = "Synthetic Reviewer " + who.upper()
        ref["independent_blind_review_attested"] = True
        ref["source_reviews"][0].update({
            "reviewed_full_visible_html": True, "event_list_complete": True,
            "unattributed_release_count": 0, "release_count_observed": 2,
            "census_note": NOTE, "reviewed_at_utc": REVIEW,
            "events": [review_label(OPENAI, 2, explicit="2026-11-05"),
                       review_label(OPENAI, 1)],
        })
        _write(folder, "reviewer_" + who + ".json", ref)
    with pytest.raises(ValueError, match="Future scheduled publication"):
        aggregate_release_pilot(cohort(b1, b2), tmp_path, split_key=KEY)


def test_cli_offline_report_private_and_contains_blockers(tmp_path, monkeypatch,
                                                            capsys):
    data = two_batches(tmp_path)
    _write(tmp_path, "cohort.json", data)
    monkeypatch.setenv("AGENTFUSE_RELEASE_GOLD_SPLIT_KEY", KEY)
    out = tmp_path / "output" / "pilot-result"
    monkeypatch.setattr(sys, "argv", [
        "aggregate_release_pilot", "--input-root", str(tmp_path),
        "--cohort-manifest", "cohort.json",
        "--out-dir", str(out),
    ])
    pilot_cli()
    printed = json.loads(capsys.readouterr().out)
    assert printed["network_requests_performed"] == 0
    assert printed["publisher_truth_verified"] is False
    assert printed["sample_coverage_diagnostic_ready"] is False
    report = json.loads((out / "release_pilot_diagnostics.json").read_text())
    assert report["source_count"] == 2
    assert report["network_requests_performed"] == 0
    assert report["advisor_fact_approvals"] == 0
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o700
        assert (out / "release_pilot_diagnostics.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(Exception):
        pilot_cli()  # private outputs are new-only; no overwrite


def test_empty_source_or_untrusted_scorecard_cannot_be_used(tmp_path):
    data = two_batches(tmp_path)
    altered = deepcopy(data)
    altered["batches"][0]["self_reported_accuracy"] = 1.0
    with pytest.raises(ValueError, match="exact"):
        aggregate_release_pilot(altered, tmp_path, split_key=KEY)
    assert _safe_member(tmp_path, "batch_openai/source.html").is_file()
    with pytest.raises(ValueError):
        _safe_member(tmp_path, "batch_openai/source.html", directory=True)
