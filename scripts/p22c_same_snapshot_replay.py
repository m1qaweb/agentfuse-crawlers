"""P22C1: original-byte-pinned OFFLINE pricing row windows using the LIVE parser.

No publisher requests. The operator must independently verify exact publisher
access and HTML retention; a SHA is not publisher authentication. Every window
is derived from ONE source HTML byte stream and replayed with the existing
pricing extractor, not a second price recognizer. All outputs are unverified.
A row-window receipt is NOT a Zyte table-window Item and must never be passed
to the old independent-job assemble_pricing_windows.py tool.
"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from lxml import html

from agentfuse_crawlers.extract import _clean, extract_evidence
from agentfuse_crawlers.model_labels import visible_cell_text
from agentfuse_crawlers.pricing_evidence import (
    _contexts, _grid, _header_count, _is_relevant, _table_info,
    MAX_SCAN_TABLES, MAX_ROW_SCAN, MAX_OBSERVATIONS,
)
from agentfuse_crawlers.run_context import manifest_sha256, package_fingerprint
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources

VERSION = "p22c1_same_original_snapshot_row_windows_v1"
MAX_HTML = 8 * 1024 * 1024
MAX_PLAN = 6 * 1024 * 1024
MAX_RECEIPTS = 12 * 1024 * 1024
MAX_ROWS = 24000
MAX_WINDOWS = 160
MAX_RECEIPT = 280000
MAX_ROWS_PER_WINDOW = min(128, MAX_ROW_SCAN - 4)
HEX = re.compile(r"^[0-9a-f]{64}$")


def sha(obj):
    raw = (bytes(obj) if isinstance(obj, (bytes, bytearray)) else
           json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return hashlib.sha256(raw).hexdigest()


def _tag(node):
    return node.tag.casefold() if isinstance(node.tag, str) else ""


def _rows(table):
    # Excludes nested-table rows from direct parent table inventory.
    return [row for row in table.iter("tr")
            if row.xpath("ancestor::table")
            and row.xpath("ancestor::table")[-1] is table]


def _cell_sha(cell):
    return sha(html.tostring(cell, encoding="utf-8", with_tail=False))


def _main(raw):
    parser = html.HTMLParser(encoding="utf-8", recover=True, no_network=True)
    document = html.document_fromstring(raw, parser=parser)
    choices = document.xpath("//main | //*[@role='main']")
    if not choices:
        choices = document.xpath("//article")
    if not choices:
        choices = document.xpath("//body")
    node = max(choices, key=lambda el: len(el.text_content())) if choices else document
    # Do NOT reinterpret the production pricing visibility/noise rules.
    _clean(node, category="pricing")
    return document, node


def _tables(main):
    return main.xpath(".//table[not(ancestor::table)]")


def _source(sid):
    sources = [s for s in load_sources() if s["id"] == sid]
    if len(sources) != 1 or sources[0]["category"] != "pricing":
        raise ValueError("Only exact pinned official pricing source IDs allowed")
    return sources[0]


def plan_source(raw, *, source_id, expected_sha256, rows_per_window=64):
    if (not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_HTML
            or not isinstance(expected_sha256, str)
            or not HEX.fullmatch(expected_sha256)
            or sha(raw) != expected_sha256):
        raise ValueError("P22C immutable original HTML byte SHA-256 mismatch")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Original HTML must be UTF-8; manual review required") from exc
    if (type(rows_per_window) is not int
            or not 1 <= rows_per_window <= MAX_ROWS_PER_WINDOW):
        raise ValueError("Bounded row window must contain 1..128 data rows")
    source = _source(source_id)
    _, main = _main(raw)
    tables = _tables(main)
    if len(tables) > MAX_SCAN_TABLES:
        raise ValueError("Live pricing table scan exceeds source inventory budget")
    context = _contexts(main)
    relevant, meta, windows, total_rows, risky_tables = [], [], [], 0, 0
    for all_index, table in enumerate(tables):
        info = _table_info(table, all_index, context.get(id(table), ()))
        if not _is_relevant(table, info, source_id):
            continue
        rows = _rows(table)
        total_rows += len(rows)
        if total_rows > MAX_ROWS:
            raise ValueError("Source recognized table rows exceed offline safety budget")
        matrix, _, rows_again = _grid(table)
        header_count = _header_count(table, matrix, rows_again)
        # A span can affect a row in a DIFFERENT chunk. Conservatively hold
        # the entire table until a grid-safe row-window method is reviewed.
        span = any(
            cell.get("rowspan", "1") != "1" or cell.get("colspan", "1") != "1"
            for row in rows for cell in row.xpath("./th|./td")
        )
        nested = bool(table.xpath(".//table"))
        if span or nested:
            risky_tables += 1
        entry = {
            "table_id": info["table_id"],
            "all_table_index": all_index,
            "relevant_table_index": len(relevant),
            "header_rows": header_count,
            "original_row_count": len(rows),
            "original_row_sha256": [
                sha(html.tostring(row, encoding="utf-8", with_tail=False))
                for row in rows
            ],
            "span_or_nested_table_hold": span or nested,
        }
        relevant.append(table)
        meta.append(entry)
        for start in range(header_count, len(rows), rows_per_window):
            end = min(start + rows_per_window, len(rows))
            identity = [source_id, expected_sha256, entry["table_id"],
                        start, end, header_count]
            windows.append({
                "window_id": sha(identity)[:24], "table_id": entry["table_id"],
                "all_table_index": all_index,
                "relevant_table_index": entry["relevant_table_index"],
                "row_start": start, "row_end": end,
                "header_rows": header_count,
                "span_or_nested_table_hold": span or nested,
            })
            if len(windows) > MAX_WINDOWS:
                raise ValueError("Source row-window count exceeds offline safety budget")
    inventory = {
        "all_visible_tables": len(tables),
        "relevant_tables": len(meta),
        "relevant_original_rows": total_rows,
        "row_windows": len(windows),
        "structural_hold_tables": risky_tables,
        "source_without_recognized_rates_not_a_negative": not bool(meta),
        "cards_not_in_row_window_scope": True,
        "dynamic_or_hidden_pricing_not_exhaustively_collected": True,
    }
    result = {
        "schema_version": VERSION,
        "kind": "offline_single_original_html_pricing_row_window_plan",
        "source_id": source_id,
        "source_url": source["url"],
        "original_html_sha256": expected_sha256,
        "source_manifest_sha256": manifest_sha256(),
        "source_lifecycle_sha256": registry_revision_sha256(),
        "parser_package_sha256": package_fingerprint(),
        "pricing_parser_revision":
            "evidence_quote_v5_inline_labeled_components",
        "rows_per_window": rows_per_window,
        "inventory": inventory,
        "tables": meta, "windows": windows,
        "capture_authorization_independently_verified": False,
        "publisher_origin_authenticated": False,
        "human_gold_supplied": False,
        "approved_for_advisor": False,
    }
    result["plan_sha256"] = sha(result)
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_PLAN:
        raise ValueError("Original row inventory plan exceeds private 6 MiB budget")
    return result


def _assert_plan(raw, plan):
    if not isinstance(plan, dict):
        raise ValueError("Missing frozen row-window plan")
    expected = plan_source(
        raw, source_id=plan.get("source_id"),
        expected_sha256=plan.get("original_html_sha256"),
        rows_per_window=plan.get("rows_per_window"),
    )
    if expected != plan:
        raise ValueError("Frozen row-window plan stale or modified vs original bytes/package")
    return expected


def run_window(raw, plan, window):
    _assert_plan(raw, plan)
    matches = [x for x in plan["windows"] if x["window_id"] == window]
    if len(matches) != 1:
        raise ValueError("Unknown or duplicate original row window")
    w = matches[0]
    table_meta = next(x for x in plan["tables"] if x["table_id"] == w["table_id"])
    receipt = {
        "schema_version": VERSION,
        "kind": "offline_live_parser_original_row_window_receipt",
        "window_id": w["window_id"], "plan_sha256": plan["plan_sha256"],
        "source_id": plan["source_id"], "source_url": plan["source_url"],
        "original_html_sha256": plan["original_html_sha256"],
        "parser_package_sha256": plan["parser_package_sha256"],
        "status": "held", "hold_reasons": [],
        "observations": [],
        "approved_for_advisor": False,
    }
    if w["span_or_nested_table_hold"]:
        receipt["hold_reasons"].append("rowspan_colspan_or_nested_grid_requires_review")
    else:
        doc, main = _main(raw)
        all_tables = _tables(main)
        table = all_tables[w["all_table_index"]]
        original_rows = _rows(table)
        if len(original_rows) != table_meta["original_row_count"]:
            raise ValueError("Window source HTML table inventory changed")
        keep = list(range(w["header_rows"])) + list(
            range(w["row_start"], w["row_end"])
        )
        # Modifying a VIEW, not captured original HTML; all other original
        # table context/visible currency declarations remain intact.
        for index in range(len(original_rows) - 1, -1, -1):
            if index not in keep:
                original_rows[index].drop_tree()
        # The price classifier is the REAL deployed extractor, not custom
        # recognition logic. Its original row indexes in this bounded VIEW
        # are immediately mapped back to absolute original positions.
        view = html.tostring(doc, encoding="utf-8")
        replay = extract_evidence(
            view, plan["source_url"], category="pricing",
            source_id=plan["source_id"],
            pricing_table_window={
                "table_offset": w["relevant_table_index"], "table_limit": 1,
            },
        )
        blockers = (
            ("parser_table_scan_truncated", replay.get("pricing_table_scan_truncated")),
            ("parser_row_window_truncated", replay.get("pricing_table_rows_incomplete")),
            ("parser_observation_budget_exceeded", replay.get("pricing_observation_limit_reached")),
            ("parser_rate_identity_collision", replay.get("pricing_rate_identity_collision_count")),
        )
        receipt["hold_reasons"].extend(k for k, value in blockers if value)
        rows = _rows(_tables(_main(raw)[1])[w["all_table_index"]])
        records = []
        for obs in replay.get("pricing_observations", []):
            if not str(obs.get("evidence_kind", "")).startswith("structured_table"):
                continue  # Cards are deliberately separate, never repeated.
            i, j = obs.get("row_index"), obs.get("column_index")
            if (type(i) is not int or type(j) is not int
                    or i not in range(len(keep))
                    or i < w["header_rows"]):
                receipt["hold_reasons"].append("parser_row_coordinate_unmappable")
                break
            abs_index = keep[i]
            if not w["row_start"] <= abs_index < w["row_end"]:
                receipt["hold_reasons"].append("parser_row_outside_window")
                break
            cells = rows[abs_index].xpath("./th|./td")
            if j >= len(cells):
                receipt["hold_reasons"].append("parser_cell_coordinate_unmappable")
                break
            cell = cells[j]
            quote = visible_cell_text(cell)
            key = [w["window_id"], abs_index, j,
                   obs.get("inline_component_index"), obs.get("source_evidence_sha256")]
            records.append({
                "observation_id": sha(key)[:32],
                "source_id": plan["source_id"],
                "source_url": plan["source_url"],
                "window_id": w["window_id"],
                "table_id": w["table_id"],
                "original_row_index": abs_index,
                "original_column_index": j,
                "original_cell_sha256": _cell_sha(cell),
                "raw_cell_text": quote[:380],
                "parser_evidence_kind": obs.get("evidence_kind"),
                "parser_observation_id": obs.get("observation_id"),
                "price_state": obs.get("price_state"),
                "normalized_amount_decimal": obs.get("normalized_amount_decimal"),
                "currency": obs.get("currency"),
                "billing_unit": obs.get("billing_unit"),
                "price_dimension": obs.get("price_dimension"),
                "model_or_service": obs.get("model_or_service"),
                "region": obs.get("region"), "tier_or_plan": obs.get("tier_or_plan"),
                "comparable_candidate_unverified": obs.get("comparable_candidate") is True,
                "normalization_blockers": obs.get("normalization_blockers", []),
                "review_status": "unverified", "approved_for_advisor": False,
            })
        if not receipt["hold_reasons"]:
            receipt["observations"] = records
            receipt["status"] = "processed_recognized_static_table_rows"
    receipt["hold_reasons"] = sorted(set(receipt["hold_reasons"]))
    receipt["receipt_sha256"] = sha(receipt)
    if len(json.dumps(receipt, ensure_ascii=False).encode()) > MAX_RECEIPT:
        raise ValueError("Window receipt exceeds bounded 280 KB output budget")
    return receipt


def run_all(raw, plan):
    _assert_plan(raw, plan)
    return [run_window(raw, plan, w["window_id"]) for w in plan["windows"]]


def assemble(raw, plan, receipts):
    _assert_plan(raw, plan)
    if (not isinstance(receipts, list)
            or len(receipts) != len(plan["windows"])):
        raise ValueError("Missing or extra original row windows")
    by_window = {w["window_id"]: w for w in plan["windows"]}
    if len(by_window) != len(plan["windows"]):
        raise ValueError("Frozen original row window identity collision")
    seen, ids, candidates, holds = set(), set(), [], []
    for rec in receipts:
        if (not isinstance(rec, dict)
                or rec.get("window_id") not in by_window
                or rec["window_id"] in seen):
            raise ValueError("Unknown/duplicate source-bound row-window receipt")
        seen.add(rec["window_id"])
        # Re-run CURRENT parser against ORIGINAL bytes, not a caller's
        # self-declared window_complete flag. This guards against fake
        # empty receipts, changed source HTML, and stale parser builds.
        expected = run_window(raw, plan, rec["window_id"])
        if rec != expected:
            raise ValueError("Forged, stale or source-mixed row-window receipt")
        if rec["status"] != "processed_recognized_static_table_rows":
            holds.extend([rec["window_id"] + ":" + x
                          for x in rec["hold_reasons"]])
        for row in rec["observations"]:
            identity = row["observation_id"]
            if identity in ids:
                raise ValueError("Duplicate/overlapping row evidence identity")
            ids.add(identity)
            candidates.append(row)
    if seen != set(by_window):
        raise ValueError("Gaps in same-original-snapshot row coverage")
    if plan["inventory"]["structural_hold_tables"]:
        holds.append("complex_table_grid_not_qualified")
    if not plan["windows"]:
        holds.append("no_recognized_static_rate_row_windows_not_vendor_negative")
    report = {
        "schema_version": VERSION,
        "kind": "offline_same_snapshot_pricing_row_assembly_NOT_GOLD",
        "source_id": plan["source_id"],
        "source_url": plan["source_url"],
        "original_html_sha256": plan["original_html_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "parser_package_sha256": plan["parser_package_sha256"],
        "expected_windows": len(plan["windows"]),
        "validated_windows": len(seen),
        "recognized_original_table_rows": plan["inventory"]["relevant_original_rows"],
        "unverified_observations": len(candidates),
        "holds": sorted(set(holds)),
        "recognized_row_window_coverage_complete": not bool(holds),
        "publisher_catalog_complete": False,
        "publisher_access_legal_review_verified_by_this_tool": False,
        "publisher_origin_authenticated": False,
        "human_gold_present": False,
        "price_accuracy_measured": False,
        "network_requests_performed": 0,
        "zyte_jobs_created": 0, "approved_for_advisor": False,
    }
    report["report_sha256"] = sha({"report": report, "observations": candidates})
    return {"report": report, "unverified_observations": candidates}


def _read(path, limit, *, json_input=False):
    p = Path(path)
    if (not p.is_file() or p.is_symlink() or
            any(parent.is_symlink() for parent in p.parents)
            or not 1 <= p.stat().st_size <= limit):
        raise ValueError("Missing, unsafe or oversized private input")
    data = p.read_bytes()
    if json_input:
        return json.loads(data.decode("utf-8"))
    return data


def _write_new(path, value):
    p = Path(path)
    if p.exists() or p.is_symlink() or any(
        ancestor.is_symlink() for ancestor in p.parents
    ):
        raise ValueError("Output must be NEW private path, never overwrite")
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with p.open("xb") as out:
        out.write(raw)
    p.chmod(0o600)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    choices = ap.add_mutually_exclusive_group(required=True)
    choices.add_argument("--plan", action="store_true")
    choices.add_argument("--run-offline", action="store_true")
    choices.add_argument("--assemble", action="store_true")
    ap.add_argument("--original-html", type=Path, required=True)
    ap.add_argument("--source-id")
    ap.add_argument("--expected-html-sha256")
    ap.add_argument("--rows-per-window", type=int, default=64)
    ap.add_argument("--frozen-plan", type=Path)
    ap.add_argument("--receipts", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    raw = _read(args.original_html, MAX_HTML)
    if args.plan:
        if not args.source_id or not args.expected_html_sha256:
            ap.error("--plan requires exact source ID and HTML SHA-256")
        if args.frozen_plan or args.receipts:
            ap.error("--plan does not accept prefilled plan or receipts")
        result = plan_source(
            raw, source_id=args.source_id,
            expected_sha256=args.expected_html_sha256,
            rows_per_window=args.rows_per_window,
        )
    else:
        if not args.frozen_plan or args.source_id or args.expected_html_sha256:
            ap.error("--run-offline/--assemble require only frozen plan")
        plan = _read(args.frozen_plan, MAX_PLAN, json_input=True)
        if args.run_offline:
            if args.receipts:
                ap.error("--run-offline generates actual parser receipts")
            result = run_all(raw, plan)
        else:
            if not args.receipts:
                ap.error("--assemble needs parser-generated window receipts")
            result = assemble(
                raw, plan, _read(args.receipts, MAX_RECEIPTS, json_input=True),
            )
    _write_new(args.out, result)
    print(json.dumps({
        "new_private_output": str(args.out), "publisher_fetches": 0,
        "zyte_jobs": 0, "approved_for_advisor": False,
    }, indent=2))


if __name__ == "__main__":
    main()
