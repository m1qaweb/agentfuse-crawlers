"""Conservative pricing table inventory and independent rate evidence.

All rate observations are unverified. A table scan being complete means only
that recognized relevant TABLE elements on the fetched page were inspected,
NOT that dynamic tabs, regional variants or vendor prices are exhaustive.
"""

import hashlib
import json
import re

from agentfuse_crawlers.rate_units import (
    PRICE_MARKER, analyze_cell, clean,
)
from agentfuse_crawlers.pricing_scope import table_declarations, scoped_text
from agentfuse_crawlers.pricing_cards import extract_card_evidence
from agentfuse_crawlers.model_labels import inspect_model_cell, visible_cell_text
from agentfuse_crawlers.pricing_adapters import (
    family_for_source, explicit_inline_components, REVISION as ADAPTER_REVISION,
)

MAX_SCAN_TABLES = 700
MAX_SELECTED_TABLES = 64
MAX_ROW_SCAN = 250
MAX_COL_SCAN = 28
MAX_OBSERVATIONS = 300
MAX_RAW_TABLES = 14
MAX_RAW_ROWS = 12
MAX_CONTEXT = 550
MAX_FOOTNOTES = 700
MAX_ITEM_BYTES = 720_000

PRICE_CELL_HEADER = re.compile(
    r"\b(?:price|rate|cost|charge|free tier|paid tier|input|output|"
    r"tokens?|monthly|hourly|unit)\b", re.I,
)
GENAI_SCOPE = re.compile(
    r"\b(?:generative AI|gen AI|language models?|inference models?)\b", re.I,
)
MODEL_ROW = re.compile(
    r"\b(?:input (?:price|cost|rate)|output (?:price|cost|rate)|"
    r"cached input (?:price|cost|rate)|context caching|"
    r"cache (?:write|read)|batch input|batch output|storage price|"
    r"rate per|price per|monthly price|hourly rate)\b", re.I,
)
GENERIC_ROW_LABEL = re.compile(
    r"^(?:(?:monthly|annual|hourly|subscription)\s+)?"
    r"(?:prices?|rates?|costs?|charges?|models?|pricing|tiers?|plans?)$",
    re.I,
)
GENERIC_MODEL_SECTION = re.compile(
    r"^(?:models?|model prices?|model pricing|pricing|billing|"
    r"api pricing|gemini api pricing|claude pricing|plans|"
    r"on.demand pricing|standard prices?|rate card)$",
    re.I,
)


def _tag(node):
    return node.tag.lower() if isinstance(node.tag, str) else ""


def _contexts(main):
    """Map each top-level table to the closest preceding h2/h3/h4 context."""
    headings = {}
    tables = {}
    for node in main.iter():
        tag = _tag(node)
        if tag in {"h2", "h3", "h4"}:
            level = int(tag[1])
            headings[level] = clean(node.text_content(), 170)
            for deeper in (level + 1, 4):
                headings.pop(deeper, None)
        elif tag == "table" and not any(_tag(x) == "table" for x in node.iterancestors()):
            tables[id(node)] = tuple(headings.get(i, "") for i in (2, 3, 4))
    return tables


def _positive_span(raw, *, max_span):
    if not raw or not str(raw).isdigit():
        return 1
    value = int(raw)
    return value if 1 <= value <= max_span else 1


def _grid(table):
    """Expand declared HTML spans without guessing unlabeled columns.

    Span collisions or excessive dimensions make the table partial, never a
    verified normalized rate.
    """
    rows = table.xpath(".//tr[not(ancestor::table[2])]")
    truncated = len(rows) > MAX_ROW_SCAN
    occupied = {}
    matrix = []
    for r, row in enumerate(rows[:MAX_ROW_SCAN]):
        cells = []
        position = 0
        for cell in row.xpath("./th|./td"):
            while (r, position) in occupied:
                cells.append(occupied[(r, position)])
                position += 1
            colspan = _positive_span(cell.get("colspan"), max_span=MAX_COL_SCAN)
            rowspan = _positive_span(cell.get("rowspan"), max_span=MAX_ROW_SCAN)
            # Invalid, zero and out-of-range HTML spans cannot be silently
            # treated as single-cell spans in a financial rate table.
            for attr, maximum in (("colspan", MAX_COL_SCAN),
                                  ("rowspan", MAX_ROW_SCAN)):
                declared = cell.get(attr)
                if declared is not None and (
                    not declared.isdigit() or not 1 <= int(declared) <= maximum
                ):
                    truncated = True
            if position >= MAX_COL_SCAN or position + colspan > MAX_COL_SCAN:
                truncated = True
                break
            value = {
                "text": visible_cell_text(cell),
                "model_cell": inspect_model_cell(cell) if position == 0 else None,
                "header": _tag(cell) == "th",
                "origin_row": r,
                "origin_col": position,
            }
            for c in range(position, position + colspan):
                cells.append(value)
                for rr in range(r + 1, min(MAX_ROW_SCAN, r + rowspan)):
                    if (rr, c) in occupied:
                        truncated = True
                    occupied[(rr, c)] = value
            position += colspan
        while (r, position) in occupied and position < MAX_COL_SCAN:
            cells.append(occupied[(r, position)])
            position += 1
        if len(row.xpath("./th|./td")) > MAX_COL_SCAN:
            truncated = True
        matrix.append(cells)
    if occupied and any(row_idx >= len(matrix) for row_idx, col_idx in occupied):
        truncated = True
    return matrix, truncated, rows


def _header_count(table, matrix, rows):
    if not matrix:
        return 0
    count = 0
    for i, row in enumerate(rows[:len(matrix)]):
        if row.xpath("ancestor::thead"):
            count = i + 1
    if count:
        return min(count, 4)
    # HTML price tables often use <th> only for the header, and <th> in the
    # first column of all subsequent data rows. Require multiple header cells.
    for i, row in enumerate(rows[:min(3, len(matrix))]):
        headers = row.xpath("./th")
        if len(headers) >= 2 and i == count:
            count += 1
        else:
            break
    if count:
        return count
    first = " ".join(x["text"] for x in matrix[0])
    if PRICE_CELL_HEADER.search(first) and not PRICE_MARKER.search(first):
        return 1
    return 0


def _column_heading(matrix, column, header_rows):
    chunks = []
    for row in matrix[:header_rows]:
        if column >= len(row):
            continue
        text = row[column]["text"]
        if text and text not in chunks:
            chunks.append(text)
    return " | ".join(chunks)[:500]


def _table_info(table, index, headings):
    caption = table.xpath("./caption[1]")
    caption = clean(caption[0].text_content(), 230) if caption else ""
    label = clean(table.get("aria-label") or table.get("data-title"), 150)
    context = " > ".join(x for x in headings if x)[:MAX_CONTEXT]
    footer = " ".join(x.text_content() for x in table.xpath("./tfoot|.//small|.//sup")[:20])
    footnotes = clean(footer, MAX_FOOTNOTES)
    return {
        "table_id": f"table-{index+1}",
        "table_index": index,
        "caption": caption,
        "label": label,
        "heading_context": context,
        "footnotes": footnotes,
    }


def _is_relevant(table, info, source_id):
    if source_id == "oracle_oci_generative_ai_pricing":
        # The linked Oracle URL is a cross-product CLOUD price list.
        # Do not attribute Data Science jobs or arbitrary compute prices to
        # generative AI; require an explicit nearby product-scope signal.
        if not GENAI_SCOPE.search(
            " ".join((info["heading_context"], info["caption"], info["label"]))
        ):
            return False
    sample = clean(table.text_content(), 2600)
    headers = " ".join(
        clean(n.text_content(), 150) for n in table.xpath(".//tr[1]//th")[:20]
    )
    caption_and_headers = " ".join(
        (info["caption"], info["label"], headers)
    )
    combined = " ".join((info["heading_context"], caption_and_headers, sample))
    if PRICE_MARKER.search(combined):
        return True
    # "Not a price" in an unrelated description is NOT a priced table.
    # Only actual labeled column headers/captions make a table worth scanning.
    return bool(
        PRICE_CELL_HEADER.search(caption_and_headers)
        and re.search(r"\b(?:price|rate|cost|billing|USD|EUR|GBP)\b",
                      caption_and_headers, re.I)
    )


def _model_label(row_label, context, caption):
    label = clean(row_label, 180)
    if (label and not MODEL_ROW.search(label)
            and not GENERIC_ROW_LABEL.fullmatch(label)
            and not PRICE_MARKER.search(label)
            and not re.fullmatch(r"[\d.,%/\-\s]+", label)):
        return label
    # For model-by-rate tables, the row identifies INPUT/OUTPUT and a
    # *specific* model must be named in a nearby heading. "Model pricing",
    # "Gemini API pricing" and similar section titles are NOT model names.
    for raw_part in reversed(context.split(" > ")):
        part = clean(raw_part, 180)
        if not part or GENERIC_MODEL_SECTION.fullmatch(part):
            continue
        if re.match(r"^Model\s*:\s*[A-Za-z][A-Za-z0-9_. -]{2,}$", part, re.I):
            return part
        if re.search(
            r"\b(?:gemini|claude|gpt|grok|llama|command|mistral|cohere)\b",
            part, re.I,
        ) and not re.search(r"\b(?:pricing|billing|rates?)\b", part, re.I):
            return part
    return ""


def extract_pricing_evidence(main, source_url, source_id, *,
                             table_offset=0, table_limit=MAX_SELECTED_TABLES):
    """Scan relevant table inventory and capture one explicitly bounded window.

    A window with omitted relevant tables is ALWAYS partial, even if all
    retained numeric cells have clear dimensions. Adjacent windows must be
    assembled offline from the same immutable page hash and extractor revision.
    """
    if (type(table_offset) is not int or table_offset < 0
            or table_offset > MAX_SCAN_TABLES
            or type(table_limit) is not int
            or not 1 <= table_limit <= MAX_SELECTED_TABLES):
        raise ValueError("pricing table window must be offset=0..700, limit=1..64")
    all_tables = main.xpath(".//table[not(ancestor::table)]")
    table_context = _contexts(main)
    # P09A: strictly bounded declarations with original text provenance.
    # Never assume publisher-wide USD, a global region, or a default tier.
    table_scope = table_declarations(main)
    family_profile = family_for_source(source_id, source_url)
    scan_truncated = len(all_tables) > MAX_SCAN_TABLES
    relevant = []
    for index, table in enumerate(all_tables[:MAX_SCAN_TABLES]):
        info = _table_info(table, index, table_context.get(id(table), ()))
        if _is_relevant(table, info, source_id):
            relevant.append((table, info))
    relevant_total = len(relevant)
    selected = relevant[table_offset:table_offset + table_limit]
    # Only the first window includes non-table pricing cards. Repeating them
    # across windows would create duplicate independent price observations.
    if table_offset == 0:
        card_evidence = extract_card_evidence(main, source_url, source_id)
    else:
        card_evidence = {
            "card_total": 0, "card_selected": 0, "card_omitted": 0,
            "card_oversized": 0, "card_entries_examined": 0,
            "card_entries_omitted": 0, "card_scan_truncated": False,
            "card_observations": [], "card_evidence_excerpts": [],
        }

    observations = []
    legacy_tables = []
    rows_examined = 0
    rows_incomplete = False
    potential_rate_cells = 0
    ambiguous_table_cells = 0
    inline_cells_split = 0
    inline_component_extras = 0
    inline_unlabeled_multi_amount_cells = 0
    model_label_recovered_rows = 0
    model_identity_review_rows = 0

    for table, info in selected:
        matrix, clipped, rows = _grid(table)
        header_rows = _header_count(table, matrix, rows)
        rows_incomplete = rows_incomplete or clipped
        label = " ".join((info["heading_context"], info["caption"], info["label"]))
        if len(legacy_tables) < MAX_RAW_TABLES:
            legacy_tables.append({
                "table_id": info["table_id"],
                "caption": info["caption"],
                "heading_context": info["heading_context"],
                "footnotes": info["footnotes"],
                "rows": [[{"text": x["text"], "header": x["header"]}
                          for x in line[:12]]
                         for line in matrix[:MAX_RAW_ROWS]],
                "rows_truncated": len(matrix) > MAX_RAW_ROWS or clipped,
                "raw_excerpt_only": True,
            })

        for row_num, cells in enumerate(matrix[header_rows:], start=header_rows):
            if not cells:
                continue
            rows_examined += 1
            first = cells[0]["text"]
            row_label = first
            model_cell = cells[0].get("model_cell") or {}
            model_status = model_cell.get("status", "unresolved_plain_row_cell")
            model_risk = model_cell.get("requires_review") is True
            if model_risk:
                # An ambiguous model owner cannot become a stable rate key.
                # A section heading must not silently rescue a bad row label.
                model = ""
                model_identity_review_rows += 1
            elif model_cell.get("label"):
                model = model_cell["label"]
                if model_status == "explicit_leading_dom_label_with_description":
                    model_label_recovered_rows += 1
            else:
                model = _model_label(first, info["heading_context"], info["caption"])
            # Other columns may explicitly identify units for THIS row.
            row_unit = " ".join(
                cell["text"] for col, cell in enumerate(cells[1:], start=1)
                if re.search(r"\b(?:unit|billing unit|measure)\b",
                             _column_heading(matrix, col, header_rows), re.I)
            )[:250]
            for col, cell in enumerate(cells[1:], start=1):
                header = _column_heading(matrix, col, header_rows)
                if not PRICE_CELL_HEADER.search(header) and not PRICE_MARKER.search(cell["text"]):
                    continue
                # Distinguish an explicitly labeled row's Unit column from
                # the monetary value; no guessed numeric amount.
                if re.search(r"^\s*unit\s*$", header, re.I):
                    continue
                if cell["origin_row"] != row_num or cell["origin_col"] != col:
                    # A row/colspan carried forward is the SAME displayed
                    # amount; never duplicate it as another independent rate.
                    continue
                potential_rate_cells += 1
                raw = cell["text"]
                caption = " ".join((
                    info["caption"], row_unit,
                    scoped_text(table_scope.get(id(table), ())),
                ))
                explicit_parts = explicit_inline_components(
                    raw, model_label=model, row_header=row_label,
                    table_caption=caption,
                    table_context=info["heading_context"],
                    footnotes=info["footnotes"],
                    family_profile=family_profile,
                )
                if explicit_parts:
                    inline_cells_split += 1
                    inline_component_extras += len(explicit_parts) - 1
                    candidates = explicit_parts
                else:
                    if len(PRICE_MARKER.findall(raw)) > 1:
                        inline_unlabeled_multi_amount_cells += 1
                    candidates = [analyze_cell(
                        raw, model_label=model, column_header=header,
                        row_header=row_label,
                        table_context=info["heading_context"],
                        table_caption=caption, footnotes=info["footnotes"],
                    )]
                for part_index, candidate in enumerate(candidates):
                    if model_cell.get("price_scope_qualifier_requires_review"):
                        candidate["normalized_amount_decimal"] = None
                        candidate["review_quote_amount_decimal"] = None
                        candidate["review_quote_candidate"] = False
                        candidate["comparable_candidate"] = False
                        candidate["normalization_blockers"] = list(dict.fromkeys([
                            *candidate["normalization_blockers"],
                            "model_row_price_scope_qualifier_unresolved",
                        ]))
                    if candidate["price_state"] == "unparsed":
                        ambiguous_table_cells += 1
                    descriptor = "|".join(
                        str(candidate.get(k) or "") for k in (
                            "model_or_service", "price_dimension", "billing_unit",
                            "currency", "region", "tier_or_plan",
                        )
                    )
                    # Explicit subrates share one DOM cell but never share an
                    # observation ID. Rate keys stay non-comparable until gold.
                    structured_key = (
                        source_id + "|" + descriptor
                        if candidate["comparable_candidate"]
                        else source_id + "|" + info["table_id"] +
                             f"|{row_num}|{col}|{part_index}"
                             if explicit_parts
                        else source_id + "|" + info["table_id"] +
                             f"|{row_num}|{col}"
                    )
                    candidate["observation_id"] = hashlib.sha256(
                        structured_key.encode("utf-8")
                    ).hexdigest()[:32]
                    candidate["source_id"] = source_id
                    candidate["source_url"] = source_url
                    candidate["scope_declarations"] = list(
                        table_scope.get(id(table), ())
                    )
                    candidate["scope_provenance_verified"] = False
                    candidate["evidence_kind"] = (
                        "structured_table_labeled_inline_component"
                        if explicit_parts else "structured_table"
                    )
                    candidate["model_label_provenance"] = (
                        "explicit_dom_primary_label" if model_cell.get("label")
                        else "row_first_cell" if model and first
                            and not MODEL_ROW.search(first)
                        else "scoped_heading" if model else "unresolved"
                    )
                    candidate["model_label_hygiene_status"] = model_status
                    candidate["model_label_requires_review"] = model_risk
                    candidate["model_row_price_scope_qualifier_requires_review"] = bool(
                        model_cell.get("price_scope_qualifier_requires_review")
                    )
                    candidate["model_label_description_present"] = bool(
                        model_cell.get("description_present")
                    )
                    candidate["table_id"] = info["table_id"]
                    candidate["row_index"] = row_num
                    candidate["column_index"] = col
                    candidate["row_label"] = clean(row_label, 200)
                    candidate["column_label"] = (
                        candidate["inline_component_label"] if explicit_parts
                        else header
                    )
                    candidate["table_caption"] = info["caption"]
                    candidate["heading_context"] = info["heading_context"]
                    candidate["footnotes"] = info["footnotes"]
                    evidence_key = (
                        raw + "|" + header + "|" + row_label + "|" + label
                    )
                    if explicit_parts:
                        evidence_key += "|" + str(part_index)
                    candidate["source_evidence_sha256"] = hashlib.sha256(
                        evidence_key.encode("utf-8")
                    ).hexdigest()
                    candidate["review_status"] = "unverified"
                    candidate["approved_for_advisor"] = False
                    if len(observations) < MAX_OBSERVATIONS:
                        observations.append(candidate)

    # Tables retain priority. A repeated equivalent rate in a styled card is
    # one vendor observation, not two independent price changes. Conflicting
    # amounts under the same fully scoped identity invalidate comparability.
    prior = {
        x["observation_id"]: x for x in observations
        if x.get("comparable_candidate")
    }
    card_duplicates = 0
    card_conflict = False
    for card in card_evidence["card_observations"]:
        old = prior.get(card["observation_id"]) if card["comparable_candidate"] else None
        if old:
            if old.get("normalized_amount_decimal") == card.get("normalized_amount_decimal"):
                card_duplicates += 1
                continue
            card_conflict = True
        if len(observations) < MAX_OBSERVATIONS:
            observations.append(card)
        if card.get("comparable_candidate"):
            prior[card["observation_id"]] = card

    total_detected = (
        potential_rate_cells + inline_component_extras +
        card_evidence["card_entries_examined"] - card_duplicates
    )
    obs_overflow = total_detected > MAX_OBSERVATIONS
    card_incomplete = card_evidence["card_scan_truncated"]
    # Ambiguous repeated typed keys across tables/cards are never safe rate
    # comparisons. The source stays partial, even if both amounts are equal,
    # until the model/region/plan attribution is independently checked.
    ids = [
        x["observation_id"] for x in observations
        if x.get("comparable_candidate")
    ]
    rate_id_collision_count = len(ids) - len(set(ids))
    inventory_complete = bool(
        table_offset == 0
        and not scan_truncated and relevant_total == len(selected)
        and not rows_incomplete and not obs_overflow
        and not card_incomplete and not card_conflict
        and not rate_id_collision_count
    )
    scope_unresolved = bool(
        source_id == "oracle_oci_generative_ai_pricing" and relevant_total == 0
    )
    comparable = [x for x in observations if x["comparable_candidate"]]
    states = sorted(set(x["price_state"] for x in observations))
    status = (
        "source_product_scope_unresolved" if scope_unresolved
        else "no_recognized_pricing_tables"
             if relevant_total == 0 and card_evidence["card_total"] == 0
        else "recognized_pricing_inventory_partial" if not inventory_complete
        else "recognized_pricing_tables_and_cards_scanned"
             if relevant_total and card_evidence["card_total"]
        else "recognized_pricing_cards_scanned"
             if card_evidence["card_total"] else "recognized_pricing_tables_scanned"
    )

    return {
        "pricing_evidence_schema": "1.0",
        # Adding structurally different evidence changes typed rate inventory.
        # New parser revision must be baselined, not mistaken for a vendor rate
        # launch or price increase relative to old archives.
        "pricing_parser_revision": "evidence_quote_v5_inline_labeled_components",
        "pricing_inline_adapter_revision": ADAPTER_REVISION,
        "pricing_inline_adapter_family": (
            family_profile["page_family_candidate"] if family_profile else None
        ),
        "pricing_inline_adapter_owner_review_status": (
            family_profile["family_review_status"] if family_profile else None
        ),
        "pricing_table_window_start": table_offset,
        "pricing_table_window_limit": table_limit,
        "pricing_table_window_end": table_offset + len(selected),
        "pricing_table_window_selected_indices": [
            info["table_index"] for _, info in selected
        ],
        "pricing_table_window_cards_included": table_offset == 0,
        "pricing_table_total": len(all_tables),
        "pricing_table_scanned": min(len(all_tables), MAX_SCAN_TABLES),
        "pricing_table_relevant": relevant_total,
        "pricing_table_selected": len(selected),
        "pricing_table_omitted_relevant": relevant_total - len(selected),
        "pricing_table_scan_truncated": scan_truncated,
        "pricing_table_rows_incomplete": rows_incomplete,
        "pricing_observation_limit_reached": obs_overflow,
        "pricing_observation_total_detected": total_detected,
        "pricing_card_total": card_evidence["card_total"],
        "pricing_card_selected": card_evidence["card_selected"],
        "pricing_card_omitted": card_evidence["card_omitted"],
        "pricing_card_oversized_count": card_evidence["card_oversized"],
        "pricing_card_scan_truncated": card_incomplete,
        "pricing_card_price_entries_examined": card_evidence["card_entries_examined"],
        "pricing_card_price_entries_omitted": card_evidence["card_entries_omitted"],
        "pricing_card_duplicate_rate_count": card_duplicates,
        "pricing_card_rate_identity_conflict": card_conflict,
        "pricing_rate_identity_collision_count": rate_id_collision_count,
        "pricing_card_observation_count": sum(
            x.get("evidence_kind") == "structured_card" for x in observations
        ),
        "pricing_card_evidence_excerpts": card_evidence["card_evidence_excerpts"],
        "pricing_inventory_complete": inventory_complete,
        "pricing_coverage_status": status,
        "pricing_product_scope_unresolved": scope_unresolved,
        "pricing_price_cells_examined": potential_rate_cells,
        "pricing_inline_rate_cells_split": inline_cells_split,
        "pricing_inline_component_extra_observations": inline_component_extras,
        "pricing_inline_multi_amount_cells_unresolved":
            inline_unlabeled_multi_amount_cells,
        "pricing_rows_examined": rows_examined,
        "pricing_observation_count": len(observations),
        "pricing_comparable_candidate_count": len(comparable),
        "pricing_review_quote_candidate_count": sum(
            bool(x.get("review_quote_candidate")) for x in observations
        ),
        "pricing_observed_single_amount_count": sum(
            x.get("observed_single_amount_decimal") is not None
            for x in observations
        ),
        "pricing_unscoped_review_quote_count": sum(
            bool(x.get("review_quote_candidate"))
            and not bool(x.get("comparable_candidate"))
            for x in observations
        ),
        "pricing_non_numeric_states": states,
        "pricing_unparsed_candidate_count": ambiguous_table_cells,
        "pricing_model_label_recovered_rows": model_label_recovered_rows,
        "pricing_model_identity_review_rows": model_identity_review_rows,
        "pricing_scoped_table_count": sum(
            bool(table_scope.get(id(table))) for table, _ in selected
        ),
        "pricing_scope_declaration_count": sum(
            len(table_scope.get(id(table), ())) for table, _ in selected
        ),
        "pricing_observations": observations,
        "pricing_table_evidence": [
            {k: v for k, v in info.items() if k != "label"}
            for _, info in selected
        ],
        "pricing_legacy_table_excerpts": legacy_tables,
        "pricing_publisher_completeness_verified": False,
        "approved_for_advisor": False,
    }


def serialized_size(record):
    return len(json.dumps(record, ensure_ascii=False, separators=(",", ":"),
                          default=str).encode("utf-8"))


def compact_pricing_record(record, raw_text):
    """Bound Zyte Items while preserving source identity and explicit loss."""
    record["text_total_characters"] = len(raw_text)
    record["text_retained_characters"] = min(len(raw_text), 16000)
    record["text_truncated"] = len(raw_text) > 16000
    record["historical_text_truncated"] = record["text_truncated"]
    record["text"] = raw_text[:16000]
    record.pop("text_sample", None)
    # The generic parser's first-40 tables are superseded by scoped evidence;
    # never use its truncated excerpts as proof of price completeness.
    record["tables"] = record.pop("pricing_legacy_table_excerpts", [])
    record["pricing_raw_table_excerpt_truncated"] = bool(
        record.get("pricing_table_selected", 0) > len(record["tables"])
        or any(x.get("rows_truncated") for x in record["tables"])
    )
    record["serialized_item_bytes"] = 0
    for _ in range(6):
        size = serialized_size(record)
        record["serialized_item_bytes"] = size
        if serialized_size(record) <= MAX_ITEM_BYTES:
            return record
        if record.get("sections"):
            record["sections"] = []
            record["sections_truncated"] = True
        elif record.get("tables"):
            record["tables"] = []
            record["pricing_raw_table_excerpt_truncated"] = True
        elif record.get("text"):
            record["text"] = record["text"][:400]
            record["text_truncated"] = True
        else:
            break
    # Do not silently remove numeric candidates to get below the limit.
    record["pricing_observation_count_before_budget"] = record.get("pricing_observation_count", 0)
    record["pricing_observations"] = []
    record["pricing_evidence_lost_to_item_budget"] = True
    record["pricing_inventory_complete"] = False
    record["status"] = "partial_capture"
    record["error"] = "pricing_item_budget_exceeded"
    record["tables"] = []
    record["sections"] = []
    record["text"] = record.get("text", "")[:250]
    record["serialized_item_bytes"] = serialized_size(record)
    if record["serialized_item_bytes"] > MAX_ITEM_BYTES:
        raise ValueError("Unable to fit pricing source summary within safe Zyte budget")
    return record
