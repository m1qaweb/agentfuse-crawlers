"""P22C1: synthetic-only full production-parser same-snapshot row replay.

All pages are invented, no publisher access is authorized or performed.
"""
import copy
import json
import os
from pathlib import Path

import pytest

from agentfuse_crawlers.run_context import manifest_sha256, package_fingerprint
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.p22c_same_snapshot_replay import (
    MAX_HTML, _read, _write_new, assemble, plan_source,
    run_all, run_window, sha,
)

SRC = next(s for s in load_sources() if s["id"] == "openai_api_pricing")


def fake_html(rows=400, *, amount="USD 0.50 / 1M tokens"):
    chunks = [
        "<html><head><title>Fictional pricing example only</title></head>"
        "<body><main><h1>Fictional source example</h1>"
        "<p>All prices are in USD.</p><p>Region: Global</p>"
        "<p>Tier: Standard</p><p>Prices per 1M tokens.</p>"
        "<table><caption>USD per 1M tokens</caption><thead><tr>"
        "<th>Model</th><th>Input price</th></tr></thead><tbody>"
    ]
    chunks += [
        f"<tr><th>Mock Sample Model {i:04}</th>"
        f"<td>{amount}</td></tr>"
        for i in range(rows)
    ]
    chunks.append("</tbody></table></main></body></html>")
    return "".join(chunks).encode("utf-8")


def make_plan(raw, *, rows=64):
    return plan_source(
        raw, source_id=SRC["id"], expected_sha256=sha(raw),
        rows_per_window=rows,
    )


def test_400_original_rows_replay_with_real_parser_and_absolute_coordinates():
    raw = fake_html(400)
    plan = make_plan(raw)
    assert plan["source_id"] == SRC["id"]
    assert plan["source_url"] == SRC["url"]
    assert plan["source_manifest_sha256"] == manifest_sha256()
    assert plan["source_lifecycle_sha256"] == registry_revision_sha256()
    assert plan["parser_package_sha256"] == package_fingerprint()
    assert plan["inventory"]["relevant_tables"] == 1
    assert plan["inventory"]["relevant_original_rows"] == 401
    assert plan["inventory"]["row_windows"] == 7
    assert [
        (w["row_start"], w["row_end"]) for w in plan["windows"]
    ] == [(1, 65), (65, 129), (129, 193), (193, 257),
          (257, 321), (321, 385), (385, 401)]
    receipts = run_all(raw, plan)
    assert len(receipts) == 7
    assert all(
        x["status"] == "processed_recognized_static_table_rows" for x in receipts
    ), [x["hold_reasons"] for x in receipts]
    assert all(x["approved_for_advisor"] is False for x in receipts)
    result = assemble(raw, plan, receipts)
    report = result["report"]
    assert report["recognized_original_table_rows"] == 401
    assert report["validated_windows"] == 7
    assert report["expected_windows"] == 7
    assert report["recognized_row_window_coverage_complete"] is True
    assert report["publisher_catalog_complete"] is False
    assert report["human_gold_present"] is False
    assert report["price_accuracy_measured"] is False
    assert report["network_requests_performed"] == 0
    assert report["zyte_jobs_created"] == 0
    assert report["approved_for_advisor"] is False
    items = result["unverified_observations"]
    assert len(items) >= 400
    assert {item["original_row_index"] for item in items} == set(range(1, 401))
    assert len({i["observation_id"] for i in items}) == len(items)
    assert all(
        i["source_id"] == SRC["id"]
        and i["source_url"] == SRC["url"]
        and i["normalized_amount_decimal"] in ("0.5", "0.50", None)
        and i["review_status"] == "unverified"
        and i["approved_for_advisor"] is False
        for i in items
    )
    assert plan == make_plan(raw)
    assert receipts == run_all(raw, plan)



def test_old_250_row_parser_limit_is_detected_without_claiming_real_accuracy():
    from agentfuse_crawlers.extract import extract_evidence
    raw = fake_html(400)
    old = extract_evidence(
        raw, SRC["url"], category="pricing", source_id=SRC["id"],
    )
    assert old["pricing_table_rows_incomplete"] is True
    assert old["pricing_rows_examined"] == 249
    assert old["pricing_inventory_complete"] is False
    plan = make_plan(raw)
    new = assemble(raw, plan, run_all(raw, plan))
    assert new["report"]["recognized_row_window_coverage_complete"] is True
    assert len(new["unverified_observations"]) >= 400
    assert new["report"]["price_accuracy_measured"] is False
    assert old["approved_for_advisor"] is False


def test_per_window_observation_cap_is_a_hold_not_silent_300_candidate_loss():
    columns = ["<th>Model</th>"] + [
        f"<th>Input price {n}</th>" for n in range(5)
    ]
    body = "".join(
        "<tr><th>Mock model %03d</th>%s</tr>" % (
            row, "<td>USD 1.25 / 1M tokens</td>" * 5
        ) for row in range(80)
    )
    raw = (
        "<html><body><main><p>All prices are in USD.</p>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<table><thead><tr>" + "".join(columns) +
        "</tr></thead><tbody>" + body +
        "</tbody></table></main></body></html>"
    ).encode()
    plan = make_plan(raw, rows=80)
    assert len(plan["windows"]) == 1
    receipt = run_all(raw, plan)[0]
    assert receipt["status"] == "held"
    assert "parser_observation_budget_exceeded" in receipt["hold_reasons"]
    assert receipt["observations"] == []
    report = assemble(raw, plan, [receipt])["report"]
    assert report["recognized_row_window_coverage_complete"] is False
    assert report["unverified_observations"] == 0


def test_all_windows_remain_bound_to_one_original_html_sha256():
    raw = fake_html(70)
    plan = make_plan(raw, rows=32)
    receipts = run_all(raw, plan)
    assert len(receipts) == 3
    assert all(
        r["original_html_sha256"] == sha(raw) and
        r["plan_sha256"] == plan["plan_sha256"] and
        r["parser_package_sha256"] == plan["parser_package_sha256"]
        for r in receipts
    )
    assert assemble(raw, plan, receipts)["report"]["validated_windows"] == 3


@pytest.mark.parametrize("change,fragment", [
    ("missing", "Missing or extra"),
    ("duplicate", "Unknown/duplicate"),
    ("reorder_source", "Forged"),
    ("replace_amount", "Forged"),
    ("replace_row_locator", "Forged"),
    ("fake_receipt_sha", "Forged"),
    ("promote_fact", "Forged"),
    ("mark_held_complete", "Forged"),
])
def test_forged_or_incomplete_parser_receipts_never_assemble(change, fragment):
    raw = fake_html(72)
    plan = make_plan(raw, rows=32)
    receipts = run_all(raw, plan)
    forged = copy.deepcopy(receipts)
    if change == "missing":
        forged.pop()
    elif change == "duplicate":
        forged[1] = copy.deepcopy(forged[0])
    elif change == "reorder_source":
        forged[0]["source_id"] = "anthropic_api_pricing"
    elif change == "replace_amount":
        forged[0]["observations"][0]["normalized_amount_decimal"] = "999999"
    elif change == "replace_row_locator":
        forged[0]["observations"][0]["original_row_index"] = 7000
    elif change == "fake_receipt_sha":
        forged[0]["receipt_sha256"] = "0"*64
    elif change == "promote_fact":
        forged[0]["approved_for_advisor"] = True
    elif change == "mark_held_complete":
        forged[0]["status"] = "held"
        forged[0]["hold_reasons"] = ["operator_says_so"]
    with pytest.raises(ValueError, match=fragment):
        assemble(raw, plan, forged)


def test_unchanged_plan_refuses_original_bytes_or_pinned_parser_fingerprint():
    raw = fake_html(16)
    plan = make_plan(raw)
    wrong_bytes = raw.replace(b"0.50", b"0.51", 1)
    with pytest.raises(ValueError, match="SHA-256"):
        assemble(wrong_bytes, plan, run_all(raw, plan))
    tampered = copy.deepcopy(plan)
    tampered["parser_package_sha256"] = "a"*64
    with pytest.raises(ValueError, match="stale"):
        run_all(raw, tampered)
    tampered = copy.deepcopy(plan)
    tampered["source_url"] = "https://wrong.invalid/pricing"
    with pytest.raises(ValueError, match="stale"):
        run_all(raw, tampered)
    with pytest.raises(ValueError, match="official pricing"):
        plan_source(
            raw, source_id="bogus_publisher", expected_sha256=sha(raw)
        )


def test_hidden_table_excluded_before_window_planning():
    source = (
        "<html><body><main><div hidden>"
        + fake_html(10).decode().split("<table>", 1)[1].split("</table>", 1)[0]
        .join(["<table>", "</table>"])
        + "</div>"
        + fake_html(2).decode().split("<table>", 1)[1].split("</table>", 1)[0]
        .join(["<table>", "</table>"])
        + "</main></body></html>"
    ).encode()
    plan = make_plan(source)
    assert plan["inventory"]["all_visible_tables"] == 1
    assert plan["inventory"]["relevant_tables"] == 1
    assert plan["inventory"]["relevant_original_rows"] == 3


def test_unsafe_spans_are_held_not_declared_complete():
    original = fake_html(6).decode()
    original = original.replace(
        "<td>USD 0.50 / 1M tokens</td>",
        "<td rowspan='2'>USD 0.50 / 1M tokens</td>", 1,
    ).encode()
    plan = make_plan(original)
    assert plan["inventory"]["structural_hold_tables"] == 1
    receipts = run_all(original, plan)
    assert receipts and all(r["status"] == "held" for r in receipts)
    report = assemble(original, plan, receipts)["report"]
    assert report["recognized_row_window_coverage_complete"] is False
    assert "complex_table_grid_not_qualified" in report["holds"]
    assert report["unverified_observations"] == 0


def test_unrecognized_or_empty_source_is_not_negative_evidence():
    raw = b"<html><body><main><p>JavaScript mount only.</p></main></body></html>"
    plan = make_plan(raw)
    assert plan["windows"] == []
    result = assemble(raw, plan, [])
    report = result["report"]
    assert report["recognized_row_window_coverage_complete"] is False
    assert report["publisher_catalog_complete"] is False
    assert report["price_accuracy_measured"] is False
    assert "no_recognized_static_rate_row_windows_not_vendor_negative" in report["holds"]


def test_private_io_never_overwrites_exposes_symlink_or_network(tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **kw: pytest.fail("NO publisher network in P22C1"),
    )
    raw = fake_html(8)
    plan = make_plan(raw)
    got = assemble(raw, plan, run_all(raw, plan))
    path = tmp_path / "private" / "report.json"
    _write_new(path, got)
    assert json.loads(path.read_text()) == got
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="NEW"):
        _write_new(path, got)
    assert _read(path, 12*1024*1024, json_input=True) == got
    link = tmp_path / "link.json"
    try:
        link.symlink_to(path)
    except OSError:
        return
    with pytest.raises(ValueError, match="unsafe"):
        _read(link, 1000000, json_input=True)


@pytest.mark.parametrize("budget", [0, -1, 129, "64", True])
def test_unbounded_row_window_budget_fails_closed(budget):
    raw = fake_html(6)
    with pytest.raises(ValueError, match="Bounded row"):
        make_plan(raw, rows=budget)


def test_large_source_byte_budget_is_bounded():
    raw = b"x" * (MAX_HTML+1)
    with pytest.raises(ValueError, match="SHA-256"):
        plan_source(
            raw, source_id=SRC["id"],
            expected_sha256=sha(raw),
        )
