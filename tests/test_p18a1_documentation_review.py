"""P18A1 offline docs review: all fixtures invented, no network access."""
import csv
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from agentfuse_crawlers.sources import load_sources
from scripts.plan_documentation_children import (
    _strict_child_url, build_review_packet, write_review_packet,
)

ALL = {source["id"]: source for source in load_sources()}
SOURCE_ID = "openai_api_docs"
SOURCE = ALL[SOURCE_ID]
BASE = SOURCE["url"]


def _child(url, label="Structured outputs"):
    return {
        "candidate_id": hashlib.sha256(
            (SOURCE_ID + "|docs-child|" + url).encode("utf-8")
        ).hexdigest()[:24],
        "source_id": SOURCE_ID,
        "candidate_url": url,
        "anchor_text": label,
        "found_in": "navigation_or_sidebar",
        "relationship": "same_host_path_family_unverified",
        "review_status": "pending_human_url_and_policy_review",
        "approved_for_crawl": False,
        "approved_for_advisor": False,
    }


def _item(*urls, label="Structured outputs"):
    item = {
        "source_id": SOURCE_ID,
        "category": "documentation",
        "provider": SOURCE["provider"],
        "source_url": BASE,
        "status": "captured",
        "approved_for_advisor": False,
        "source_product_title_conflict": False,
        "content_sha256": "a" * 64,
        "documentation_nav_candidates": [_child(u, label=label) for u in urls],
        "documentation_canonical_relation": "missing",
        "documentation_canonical_review_url": None,
        "documentation_nav_candidate_omitted": 0,
    }
    return item


def _url(name):
    return BASE.rstrip("/") + "/guides/" + name


def test_original_manifest_unchanged_and_product_identity_only_candidate():
    packet = build_review_packet([_item(_url("structured-outputs"))])
    assert len(load_sources()) == 460
    assert packet["expected_documentation_source_count"] == 194
    assert packet["input_documentation_source_count"] == 1
    assert packet["input_manifest_complete"] is False
    assert packet["review_task_count"] == 1
    assert packet["new_network_requests"] == 0
    assert packet["new_fetch_permissions"] == 0
    assert packet["human_publisher_policy_approvals"] == 0
    assert packet["verified_product_owners"] == 0
    assert packet["advisor_approved_facts"] == 0
    assert packet["approved_for_crawl"] is False
    task = packet["tasks"][0]
    assert task["source_url"] == BASE
    assert task["product_id_unverified"] == "openai_api"
    assert task["parent_snapshot_sha256_unverified"] == "a" * 64
    assert task["review_status"] == "pending_independent_policy_and_product_review"
    assert task["product_ownership_independently_verified"] is False
    assert len(task["required_human_checks"]) == 5
    assert task["approved_for_crawl"] is False
    assert task["approved_for_advisor"] is False
    assert len(packet["packet_sha256"]) == 64


def test_packet_is_deterministic_and_source_round_robin_bounded():
    a, b, c = (_url(x) for x in ("alpha", "bravo", "charlie"))
    first = build_review_packet([_item(c, a, b)], per_source=2)
    second = build_review_packet([_item(b, c, a)], per_source=2)
    assert first == second
    assert [t["candidate_url"] for t in first["tasks"]] == [a, b]
    assert first["held_candidate_reasons"]["bounded_selection_omitted"] == 1
    small = build_review_packet([_item(c, a, b)], max_total=1)
    assert len(small["tasks"]) == 1
    assert small["held_candidate_reasons"]["bounded_selection_omitted"] == 2


@pytest.mark.parametrize("bad_url", [
    "http://developers.openai.com/api/docs/guides/unsafe",
    "https://evil.example/api/docs/guides/unsafe",
    "https://developers.openai.com.evil.example/api/docs/guides/unsafe",
    "https://developers.openai.com/api/docs",
    "https://developers.openai.com/codex/docs/guides/unsafe",
    "https://developers.openai.com/api/docs/../codex",
    "https://developers.openai.com/api/docs/./quickstart",
    "https://developers.openai.com/api/docs//quickstart",
    "https://developers.openai.com/api/docs/%2e%2e/codex",
    "https://developers.openai.com/api/docs/page?token=secret",
    "https://developers.openai.com/api/docs/page#fragment",
    "https://developers.openai.com/api/docs/page\\malicious",
    "https://developers.openai.com:444/api/docs/page",
    "https://user@developers.openai.com/api/docs/page",
    "https://developers.openai.com./api/docs/page",
    "https://developers.openai.com/api/docs/💡",
])
def test_refuse_off_origin_parent_path_traversal_and_query(bad_url):
    with pytest.raises(ValueError):
        _strict_child_url(SOURCE, bad_url)


def test_candidate_forged_hash_and_duplicate_url_fail_closed():
    one = _item(_url("models"))
    one["documentation_nav_candidates"][0]["candidate_id"] = "0" * 24
    with pytest.raises(ValueError, match="candidate ID"):
        build_review_packet([one])
    two = _item(_url("models"), _url("models"))
    with pytest.raises(ValueError, match="Duplicate"):
        build_review_packet([two])


def test_cannot_promote_crawl_flags_from_source_item():
    one = _item(_url("models"))
    one["documentation_nav_candidates"][0]["approved_for_crawl"] = True
    with pytest.raises(ValueError, match="Unsafe/unapproved"):
        build_review_packet([one])
    two = _item(_url("models"))
    two["approved_for_advisor"] = True
    with pytest.raises(ValueError, match="must not authorize"):
        build_review_packet([two])


def test_title_conflict_blocks_links_without_asserting_ownership():
    one = _item(_url("models"))
    one["source_product_title_conflict"] = True
    packet = build_review_packet([one])
    assert packet["review_task_count"] == 0
    assert packet["held_candidate_reasons"]["product_title_conflict"] == 1
    assert packet["sources"][0]["eligible_for_review"] is False


def test_quarantined_source_cannot_be_requested_even_with_empty_links():
    source = ALL["v0_docs"]
    data = {
        "category": "documentation",
        "source_id": "v0_docs",
        "provider": source["provider"],
        "source_url": source["url"],
        "approved_for_advisor": False,
        "documentation_nav_candidates": [],
    }
    with pytest.raises(ValueError, match="policy blocked"):
        build_review_packet([data], source_ids=["v0_docs"])


def test_invalid_selection_or_source_ownership_rejected():
    with pytest.raises(ValueError, match="absent"):
        build_review_packet([_item()], source_ids=["anthropic_api_docs"])
    with pytest.raises(ValueError, match="distinct"):
        build_review_packet([_item()], source_ids=[SOURCE_ID, SOURCE_ID])
    with pytest.raises(ValueError, match="Invalid bounded"):
        build_review_packet([_item()], per_source=0)
    with pytest.raises(ValueError, match="Invalid bounded"):
        build_review_packet([_item()], max_total=100000)
    with pytest.raises(ValueError, match="mismatched"):
        malicious = _item()
        malicious["source_url"] = "https://evil.example/documentation"
        build_review_packet([malicious])


def test_snapshot_hash_invalid_is_unknown_not_fabricated():
    item = _item(_url("models"))
    item["content_sha256"] = "unknown_from_zyte"
    packet = build_review_packet([item])
    assert packet["tasks"][0]["parent_snapshot_sha256_unverified"] is None


def test_private_files_csv_formula_safety_and_no_overwrite(tmp_path):
    packet = build_review_packet([_item(
        _url("models"), label='=HYPERLINK("https://evil.example")',
    )])
    target = tmp_path / "not-committed"
    created = write_review_packet(packet, target)
    assert created == target
    assert (created / "child_review_packet.json").exists()
    assert (created / "human_review_notes_template.json").exists()
    report = json.loads((created / "child_review_packet.json").read_text())
    assert report == packet
    template = json.loads(
        (created / "human_review_notes_template.json").read_text()
    )
    assert template["manual_review_records"] == []
    assert template["approved_for_crawl"] is False
    with (created / "child_review_tasks.csv").open(encoding="utf-8-sig",
                                                    newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["anchor_text"].startswith("'=HYPERLINK")
    assert rows[0]["approved_for_crawl"] == "False"
    if os.name == "posix":
        assert created.stat().st_mode & 0o777 == 0o700
        assert all(p.stat().st_mode & 0o777 == 0o600
                   for p in created.iterdir())
    with pytest.raises(ValueError, match="NEW"):
        write_review_packet(packet, target)


def test_no_private_review_exports_into_repo_tracked_folders():
    # Validation must fail before an accidental tracked docs directory write.
    packet = build_review_packet([_item(_url("models"))])
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="must stay in output"):
        write_review_packet(packet, repository / "docs" / "untracked-human-review")


def test_duplicate_source_items_and_bad_pin_do_not_create_review():
    item = _item(_url("models"))
    with pytest.raises(ValueError, match="Duplicate source Item"):
        build_review_packet([item, deepcopy(item)])
    changed = deepcopy(item)
    changed["provider"] = "Unrelated Provider"
    with pytest.raises(ValueError, match="mismatched"):
        build_review_packet([changed])
