"""G3 synthetic tests: never put historical publisher Items in git/CI."""

import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest

from agentfuse_crawlers.sources import load_sources
from scripts import g3_historical_items_triage as g3


def _fixtures():
    sources = load_sources()
    assert len(sources) == 460
    items = {}
    within = {"documentation": 0, "pricing": 0, "changelog": 0}
    for source in sources:
        category = source["category"]
        within[category] += 1
        rank = within[category]
        status = (
            "captured" if (category == "documentation" and rank <= 51)
            or (category == "changelog" and rank <= 14)
            else "partial_capture" if category == "pricing" and rank == 1
            else "needs_review"
        )
        items[source["id"]] = {
            "source_id": source["id"],
            "category": category,
            "source_url": source["url"],
            "provider": source["provider"],
            "status": status,
            "http_status": 200,
            "approved_for_advisor": False,
            "error": "" if status == "captured" else "unverified",
            "diagnostic_reason_codes": [],
            "pricing_observation_count": 12 if category == "pricing" else 0,
            "pricing_inventory_complete": category == "pricing",
            "release_recent_event_count": 9 if category == "changelog" else 0,
            "release_window_complete": category == "changelog",
            "documentation_scope_status":
                "scoped_page" if category == "documentation" else None,
            "original_publisher_html_SECRET_NOT_TO_EXPORT":
                "G3_NON_PUBLIC_RAW_PUBLISHER_BODY_DO_NOT_OUTPUT",
        }
    checksums = {name: "a" * 64 for name in g3.SUFFIX.values()}
    return sources, items, checksums


def test_counts_460_300_24_and_no_permissions_or_new_zyte_jobs():
    report, rows, top, shortlist = g3.build_triage(*_fixtures())
    assert report["status"] == "NO_GO_HISTORICAL_EVIDENCE_ONLY"
    assert report["source_count"] == 460
    assert report["selected_300_review_only"] == 300
    assert report["supplemental_canary_review_24_not_authorized"] == 24
    assert report["frozen_original_source_count"] == 18
    assert report["frozen_study_round_denominator_unchanged"] == 36
    assert report["new_zyte_jobs"] == report["publisher_requests_now"] == 0
    assert report["new_source_approvals"] == 0
    assert report["approved_for_advisor"] is False
    assert report["historical_items_are_current_accurate_or_licensed"] is False
    assert report["historical_status_counts"]["captured"] == 65
    assert report["historical_pricing_http200"] == 177
    assert len(rows) == 460 and len(top) == 300 and len(shortlist) == 24
    assert len({r["source_id"] for r in rows}) == 460
    assert all(r["publisher_permission_independently_verified"] is False
               and r["approved_for_advisor"] is False for r in rows)
    assert {
        c: sum(r["category"] == c for r in top)
        for c in g3.CATEGORIES
    } == g3.CATEGORY_QUOTAS
    assert {c: sum(r["category"] == c for r in shortlist)
            for c in g3.CATEGORIES} == {
                "documentation": 8, "pricing": 8, "changelog": 8,
            }
    assert not any(r["source_id"] in g3.G1_ELEVATED_TERMS_REVIEW
                   for r in shortlist)
    assert not any(r["original_frozen_18_source_ID"] for r in shortlist)
    assert all(r["supplemental_24_source_human_review_NOT_A_RUN_LIST"]
               for r in shortlist)
    assert [r["historical_review_rank"] for r in rows] == list(range(1, 461))


@pytest.mark.parametrize("field,value", [
    ("status", "trusted"), ("approved_for_advisor", True),
    ("source_url", "https://evil.invalid"), ("category", "pricing"),
    ("source_id", "unrecognized_source_id"),
])
def test_mutated_synthetic_source_item_rejected(field, value):
    sources, items, digests = _fixtures()
    one = sources[0]["id"]
    items[one][field] = value
    with pytest.raises(ValueError):
        g3.build_triage(sources, items, digests)


@pytest.mark.parametrize("field,value", [
    ("diagnostic_reason_codes", ["=BAD_SHEET_FORMULA"]),
    ("diagnostic_reason_codes", ["bad reason"]),
    ("pricing_observation_count", 999999),
    ("http_status", True),
    ("http_status", 999),
])
def test_unexpected_historical_diagnostics_fail_closed(field, value):
    sources, items, checksums = _fixtures()
    items[sources[0]["id"]][field] = value
    with pytest.raises(ValueError):
        g3.build_triage(sources, items, checksums)


def test_bounded_redacted_csv_never_exports_scraped_text(tmp_path):
    result = g3.build_triage(*_fixtures())
    directory = tmp_path / "original_zyte_items_review"
    assert g3.write_triage(*result, directory) == directory
    summary = json.loads(
        (directory / "g3_historical_empirical_summary_NO_GO.json").read_text()
    )
    assert summary == result[0]
    files = sorted(p.name for p in directory.iterdir())
    assert files == [
        "g3_historical_empirical_summary_NO_GO.json",
        "g3_historical_shortlist24_NOT_AUTHORIZED.csv",
        "g3_historical_top300_NOT_RUN_LIST.csv",
        "g3_historical_triage_all460_REVIEW_ONLY.csv",
    ]
    for file in directory.iterdir():
        text = file.read_text(encoding="utf-8-sig")
        assert "G3_NON_PUBLIC_RAW_PUBLISHER_BODY_DO_NOT_OUTPUT" not in text
        assert "PRIVATE" not in text
    for filename, expected in (
        ("g3_historical_triage_all460_REVIEW_ONLY.csv", 460),
        ("g3_historical_top300_NOT_RUN_LIST.csv", 300),
        ("g3_historical_shortlist24_NOT_AUTHORIZED.csv", 24),
    ):
        with (directory / filename).open(encoding="utf-8-sig", newline="") as f:
            assert len(list(csv.DictReader(f))) == expected
    with pytest.raises(ValueError, match="NEW non-symlink"):
        g3.write_triage(*result, directory)


def test_wrong_historic_exports_rejected_before_untrusted_processing(tmp_path):
    filenames = list(g3.SUFFIX.values())
    for filename in filenames:
        (tmp_path / filename).write_bytes(b"[]")
    with pytest.raises(ValueError, match="SHA mismatch"):
        g3.read_pinned_items(tmp_path)
    with pytest.raises(ValueError):
        g3.read_pinned_items(tmp_path / "not-exists")
