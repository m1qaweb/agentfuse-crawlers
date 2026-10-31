#!/usr/bin/env python3
"""Offline versioned evidence export + review queue. No database or LLM writes.

python -m scripts.compare_exports --current output/today/*.jsonl --previous output/yesterday/*.jsonl --out-dir output/review
python -m scripts.compare_exports --current output/changelogs.jsonl --out-dir output/review

The first snapshot is ONLY a baseline; page/section changes are NOT verified releases.
"""

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agentfuse_crawlers.sources import load_sources, load_proven_source_ids, select_sources
from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256

STATUS_FIELDS = [
    'source_id', 'provider', 'category', 'source_cohort', 'status',
    'http_status', 'fetched_at_utc', 'source_url', 'final_url',
    'word_count', 'content_sha256', 'text_truncated',
    'sections_truncated', 'tables_truncated', 'review_status', 'error',
]
CHANGE_FIELDS = [
    'source_id', 'provider', 'category', 'change_type', 'previous_hash',
    'current_hash', 'fetched_at_utc', 'source_url', 'review_status',
]
SECTION_FIELDS = [
    'source_id', 'provider', 'category', 'change_type', 'section_id',
    'heading', 'date_candidate', 'section_url', 'importance_hint',
    'review_status',
]
IMPORTANT_TERMS = re.compile(
    r'\b(deprecat\w*|sunset|retir\w*|security|vulnerabilit\w*|generally available|'
    r'price|pricing|rate limit|new model|model release|API breaking|mcp|'
    r'context window|compatibility|migration)\b', re.I
)


def read_jsonl(paths):
    """Read both Zyte Dashboard JSON-array downloads and JSON Lines exports.

    Keep the latest record, including failures, rather than hiding them behind
    an older successful snapshot. JSON-array support is necessary because the
    Zyte UI defaults to JSON, not JSONL.
    """
    rows = {}
    for path in paths:
        with open(path, encoding='utf-8-sig') as handle:
            first = handle.read(1)
            while first and first.isspace():
                first = handle.read(1)
            handle.seek(0)
            if first == '[':
                items = json.load(handle)
                if not isinstance(items, list):
                    raise ValueError(f'Invalid JSON array in {path}')
            else:
                items = []
                for line_no, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise ValueError(f'Invalid JSON at {path}:{line_no}') from exc
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get('source_id'), str):
                    raise ValueError(f'Invalid item in {path}: no source_id')
                source_id = item['source_id']
                old_item = rows.get(source_id)
                if old_item and item.get('run_started_at_utc'):
                    # Repeating an Item within one job must be visible rather
                    # than silently hiding an exporter/crawler duplicate.
                    same_run_start = (
                        old_item.get('run_started_at_utc')
                        == item.get('run_started_at_utc')
                    )
                    same_job = (
                        old_item.get('zyte_job_id')
                        == item.get('zyte_job_id')
                    )
                    if same_run_start and same_job:
                        raise ValueError(
                            f'Duplicate source Item in one Zyte job: {source_id}'
                        )
                if (source_id not in rows or item.get('fetched_at_utc', '') >=
                        rows[source_id].get('fetched_at_utc', '')):
                    rows[source_id] = item
    return rows



def _declared_run_cohort(current):
    """Use actual requested job cohort, never historical source membership."""
    declarations = {
        row.get("requested_cohort") for row in current.values()
        if "requested_cohort" in row
    }
    if not declarations:
        return None
    if any("requested_cohort" not in row for row in current.values()):
        raise ValueError("Mixed versioned and legacy Items; separate jobs")
    if len(declarations) != 1 or not declarations <= {"all", "proven", "candidate"}:
        raise ValueError("Mixed or invalid requested_cohort; compare jobs separately")
    return next(iter(declarations))


def _validate_run_provenance(current, manifest, cohort, categories,
                             source_ids=None, limit=None, offset=0):
    """Fail closed when an exported job does not match this manifest and CLI scope.

    For full multi-spider archives, per-category run IDs may differ. Within a
    category, every source-summary Item must identify the same specific job.
    Legacy Items lacking provenance remain readable but are *not* verified.
    """
    if not any("manifest_sha256" in row for row in current.values()):
        return "legacy_unverified"
    required = (
        "manifest_sha256", "selection_ids_sha256",
        "selection_source_count", "requested_cohort",
        "spider_name", "run_started_at_utc",
    )
    for row in current.values():
        if any(row.get(k) in (None, "") for k in required):
            raise ValueError("Missing run provenance in versioned Items")
    actual_manifest = manifest_sha256(manifest)
    for category in categories:
        items = [x for x in current.values() if x.get("category") == category]
        if not items:
            continue
        # Every Item in one category must have identical job-level scope.
        job_keys = (
            "requested_cohort", "selection_ids_sha256",
            "selection_source_count", "manifest_sha256",
            "spider_name", "run_started_at_utc", "zyte_job_id",
            "deployment_revision",
        )
        if any(tuple(row.get(k) for k in job_keys) !=
               tuple(items[0].get(k) for k in job_keys) for row in items[1:]):
            raise ValueError(f"Mixed Zyte jobs in {category}; compare separately")
        row = items[0]
        if row["requested_cohort"] != cohort:
            raise ValueError("Requested cohort differs from CLI scope")
        if row["manifest_sha256"] != actual_manifest:
            raise ValueError("Manifest fingerprint mismatch: use matching manifest revision")
        selected = select_sources(
            category, cohort=cohort, source_ids=source_ids, limit=limit, offset=offset,
        )
        if (row["selection_ids_sha256"] != selection_ids_sha256(selected)
                or row["selection_source_count"] != len(selected)):
            raise ValueError(
                "Selection fingerprint mismatch; supply exact --cohort, "
                "--source-ids, --limit and --offset from the Zyte job"
            )
        if row["spider_name"] != {
            "documentation": "official_documentation",
            "pricing": "official_pricing",
            "changelog": "official_changelogs",
        }[category]:
            raise ValueError("Spider identity does not match category")
    return "verified_against_current_manifest_and_args"

def _healthy(row):
    """A successful HTTP response or legacy 'captured' flag is insufficient."""
    if row.get('category') == 'pricing' and row.get('pricing_evidence_schema') == '1.0':
        return bool(
            row.get('status') == 'captured'
            and row.get('content_sha256')
            and row.get('pricing_inventory_complete')
            and row.get('pricing_comparable_candidate_count', 0) > 0
            and not row.get('pricing_evidence_lost_to_item_budget')
        )
    return (
        row.get('status') == 'captured'
        and bool(row.get('content_sha256'))
        and not row.get('text_truncated')
        and not (row.get('category') == 'pricing' and row.get('tables_truncated'))
        and not (row.get('category') in {'documentation', 'changelog'}
                 and row.get('sections_truncated'))
        and not any(x.get('excerpt_truncated') for x in row.get('sections', []))
    )


def compare(current, previous):
    """Conservative page-level diff, preserving legacy change categories."""
    changes = []
    for source_id, item in sorted(current.items()):
        old = previous.get(source_id)
        new_hash = item.get('content_sha256') or ''
        old_hash = (old.get('content_sha256') or '') if old else ''
        if not _healthy(item):
            kind = 'not_captured'
        elif not old or not _healthy(old):
            kind = 'new_baseline'
        elif (old.get('source_url') and item.get('source_url') and
              old['source_url'] != item['source_url']):
            # URL migrations start a new baseline: do not call a moved feed
            # a newly announced feature or a content update.
            kind = 'new_baseline'
        elif old_hash != new_hash:
            kind = 'page_text_changed'
        else:
            kind = 'unchanged'
        changes.append({
            'source_id': source_id,
            'provider': item.get('provider', ''),
            'category': item.get('category', ''),
            'change_type': kind,
            'previous_hash': old_hash,
            'current_hash': new_hash,
            'fetched_at_utc': item.get('fetched_at_utc', ''),
            'source_url': item.get('source_url', ''),
            'review_status': 'unverified',
        })
    return changes


def _pricing_rate_diffs(current, previous):
    """Compare only fully scoped same-identity rate observations.

    A vendor's first observed price is NOT necessarily an effective-today
    price. Missing a price from one page is NOT a price removal or free tier.
    """
    candidates = []
    for source_id, curr in sorted(current.items()):
        old = previous.get(source_id)
        if not old or curr.get("category") != "pricing":
            continue
        if (curr.get("pricing_evidence_schema") != "1.0"
                or old.get("pricing_evidence_schema") != "1.0"
                or not _healthy(curr) or not _healthy(old)
                or curr.get("source_url") != old.get("source_url")
                or curr.get("provider") != old.get("provider")):
            continue

        def comparable_map(row):
            found = {}
            for x in row.get("pricing_observations", []):
                if not x.get("comparable_candidate"):
                    continue
                if not x.get("normalized_amount_decimal") or not x.get("observation_id"):
                    return None
                key = x["observation_id"]
                if key in found:
                    return None  # Ambiguous repeated identity; fail closed.
                found[key] = x
            return found

        before = comparable_map(old)
        after = comparable_map(curr)
        if before is None or after is None:
            continue
        for key, observation in sorted(after.items()):
            earlier = before.get(key)
            if earlier and (
                observation["normalized_amount_decimal"] ==
                    earlier.get("normalized_amount_decimal")
                and observation.get("source_evidence_sha256") ==
                    earlier.get("source_evidence_sha256")
            ):
                continue
            if earlier and (
                observation["normalized_amount_decimal"] ==
                    earlier.get("normalized_amount_decimal")
            ):
                # Text or footnote changed without an actual comparable rate
                # change; keep it in the unclassified page review, not alert
                # a false price increase/decrease.
                continue
            kind = ("rate_first_observed_candidate" if earlier is None
                    else "rate_value_changed_candidate")
            candidates.append({
                "source_id": source_id,
                "provider": curr.get("provider", ""),
                "category": "pricing",
                "change_type": kind,
                "observation_id": key,
                "model_or_service": observation.get("model_or_service"),
                "price_dimension": observation.get("price_dimension"),
                "billing_unit": observation.get("billing_unit"),
                "currency": observation.get("currency"),
                "region": observation.get("region"),
                "tier_or_plan": observation.get("tier_or_plan"),
                "previous_amount_decimal": (
                    earlier.get("normalized_amount_decimal") if earlier else None
                ),
                "current_amount_decimal": observation.get("normalized_amount_decimal"),
                "raw_displayed_price": observation.get("raw_displayed_price"),
                "table_id": observation.get("table_id"),
                "row_index": observation.get("row_index"),
                "column_index": observation.get("column_index"),
                "section_id": "",
                "heading": observation.get("model_or_service", ""),
                "date_candidate": "",
                "section_url": curr.get("source_url", ""),
                "importance_hint": "review_first",
                "review_status": "pending_human_verification",
                "approved_for_advisor": False,
                "evidence_excerpt": observation.get("raw_displayed_price", "")[:280],
                "interpretation_warning": (
                    "Observed official pricing snapshot difference; no "
                    "vendor effective date or advisor approval is inferred."
                ),
            })
    return candidates


def _section_diffs(current, previous):
    """Compare sections only when both complete captures exist.

    Truncated sections/text can suggest removals that never happened: suppress.
    Historical sections on the first crawl are never called fresh news.
    """
    changes = []
    for source_id, curr in sorted(current.items()):
        old = previous.get(source_id)
        if curr.get('category') == 'pricing' and (
            curr.get('pricing_evidence_schema') == '1.0'
            or (old and old.get('pricing_evidence_schema') == '1.0')
        ):
            # Structural price observations supersede generic headings.
            continue
        if not old or not _healthy(curr) or not _healthy(old):
            continue
        if (old.get('source_url') and curr.get('source_url') and
                old['source_url'] != curr['source_url']):
            continue
        if any(x.get('sections_truncated') for x in (curr, old)):
            continue
        old_sections = {s['section_id']: s for s in old.get('sections', [])}
        new_sections = {s['section_id']: s for s in curr.get('sections', [])}
        if not old_sections or not new_sections:
            continue
        for key, section in sorted(new_sections.items()):
            was = old_sections.get(key)
            if was is None:
                kind = 'section_added'
            elif section.get('sha256') != was.get('sha256'):
                kind = 'section_modified'
            else:
                continue
            changes.append(_section_record(curr, section, kind))
        for key, section in sorted(old_sections.items()):
            if key not in new_sections:
                changes.append(_section_record(curr, section, 'section_removed'))
    return changes


def _section_record(record, section, kind):
    words = section.get('heading', '') + ' ' + section.get('excerpt', '')[:800]
    return {
        'source_id': record['source_id'],
        'provider': record.get('provider', ''),
        'category': record.get('category', ''),
        'change_type': kind,
        'section_id': section['section_id'],
        'heading': section.get('heading', ''),
        'date_candidate': section.get('date_candidate', ''),
        'section_url': section.get('section_url') or record.get('source_url', ''),
        'importance_hint': 'review_first' if IMPORTANT_TERMS.search(words) else 'normal',
        'review_status': 'pending_human_verification',
        'evidence_excerpt': section.get('excerpt', '')[:450],
        'approved_for_advisor': False,
    }


def review_queue(current, previous, changes):
    """Non-authoritative candidate queue. Never an approved recommendations feed."""
    pricing_changes = _pricing_rate_diffs(current, previous)
    section_changes = _section_diffs(current, previous)
    queue = list(pricing_changes) + list(section_changes)
    detailed_sources = {x['source_id'] for x in queue}
    # Only generate page-level tasks if no section-level diff is available.
    for item in changes:
        if item['change_type'] != 'page_text_changed' or item['source_id'] in detailed_sources:
            continue
        record = current[item['source_id']]
        prior = previous.get(item['source_id'])
        if record.get('category') == 'pricing' and (
            record.get('pricing_evidence_schema') !=
            (prior or {}).get('pricing_evidence_schema')
        ):
            # Parser-schema migration is a new evidence baseline, not a
            # vendor rate change or a general "price changed" announcement.
            continue
        # Typed pricing can change text without a comparable numeric price
        # change. This must be reviewed as a page edit, not a rate alert.
        queue.append({
            'source_id': record['source_id'],
            'provider': record.get('provider', ''),
            'category': record.get('category', ''),
            'change_type': 'page_changed_unclassified',
            'section_id': '',
            'heading': record.get('title', ''),
            'date_candidate': '',
            'section_url': record.get('source_url', ''),
            'importance_hint': 'review_first' if record.get('category') == 'pricing' else 'normal',
            'review_status': 'pending_human_verification',
            'evidence_excerpt': (record.get('text') or '')[:450],
            'approved_for_advisor': False,
        })
    return queue


def write_csv(path, rows, fields):
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def export(current, previous, out_dir, category='auto', cohort='auto', source_ids=None, limit=None, offset=0):
    if category not in {'auto', 'all', 'documentation', 'pricing', 'changelog'}:
        raise ValueError('Invalid category filter')
    categories = ({x.get('category') for x in current.values()}
                  if category == 'auto' else
                  {category} if category != 'all' else {'documentation', 'pricing', 'changelog'})
    categories = categories.intersection({'documentation', 'pricing', 'changelog'})
    if not categories:
        raise ValueError('No recognized categories in current exports; pass --category')
    catalog = load_sources()
    known = {s['id']: s for s in catalog}
    # A Zyte job with cohort=proven emits only three items for a spider.
    # Never pretend that 26 changelogs failed because 23 were intentionally skipped.
    if cohort not in {'auto', 'all', 'proven', 'candidate'}:
        raise ValueError('Invalid cohort')
    declared_cohort = _declared_run_cohort(current)
    if cohort == 'auto':
        if declared_cohort is not None:
            cohort = declared_cohort
        else:
            # Legacy Items have only historical source-cohort membership.
            # Auto-inference here is explicitly unverified, never job proof.
            observed_cohorts = {x.get('source_cohort') for x in current.values()}
            cohort = (next(iter(observed_cohorts)) if observed_cohorts in
                      ({'proven'}, {'candidate'}) else 'all')
    elif declared_cohort is not None and declared_cohort != cohort:
        raise ValueError("Explicit cohort contradicts Zyte requested_cohort")
    proven = load_proven_source_ids()
    if source_ids is not None:
        if isinstance(source_ids, str):
            source_ids = {x.strip() for x in source_ids.split(',')}
        else:
            source_ids = set(source_ids)
        if not source_ids or not source_ids <= set(known):
            raise ValueError('Unknown or empty --source-ids selection')
    if limit is not None:
        if isinstance(limit, bool) or not str(limit).isdigit() or not 1 <= int(limit) <= 500:
            raise ValueError('limit must be between 1 and 500')
        limit = int(limit)
    manifest = [
        s for s in catalog
        if s['category'] in categories
        and (cohort == 'all' or (s['id'] in proven) == (cohort == 'proven'))
        and (source_ids is None or s['id'] in source_ids)
    ]
    if isinstance(offset, bool) or not str(offset).isdigit() or not 0 <= int(offset) <= 100000:
        raise ValueError('offset must be between 0 and 100000')
    offset = int(offset)
    if offset or limit is not None:
        by_category = Counter()
        limited = []
        for s in manifest:
            index = by_category[s['category']]
            by_category[s['category']] += 1
            if index < offset:
                continue
            if limit is None or index < offset + limit:
                limited.append(s)
        manifest = limited
    if not manifest:
        raise ValueError('Expected source selection is empty')
    ids = {s['id'] for s in manifest}
    provenance_validation = _validate_run_provenance(
        current, catalog, cohort, categories, source_ids, limit, offset,
    )
    # V2.1 records carry a fixed source identity. Reject files that attempt
    # to reattribute an official URL to a different provider/category.
    for source_id, row in current.items():
        expected = known.get(source_id)
        if row.get('schema_version') == '2.1' and expected and (
            row.get('provider') != expected['provider']
            or row.get('category') != expected['category']
            or row.get('source_url') != expected['url']
        ):
            raise ValueError('Export has a mismatched source identity')
    unknown = set(current) - {s['id'] for s in load_sources()}
    if unknown:
        raise ValueError(f'Unknown source IDs not in trusted manifest: {sorted(unknown)}')
    current = {k: v for k, v in current.items() if k in ids}
    previous = {k: v for k, v in previous.items() if k in ids}
    for s in manifest:
        if s['id'] not in current:
            current[s['id']] = {
                'source_id': s['id'], 'provider': s['provider'],
                'category': s['category'], 'source_url': s['url'],
                'source_cohort': 'proven' if s['id'] in proven else 'candidate',
                'status': 'not_in_export',
                'error': 'Missing record; job may not have run or robots may have denied access',
                'review_status': 'unverified',
            }
    changes = compare(current, previous)
    queue = review_queue(current, previous, changes)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / 'status.csv', [current[k] for k in sorted(current)], STATUS_FIELDS)
    write_csv(out_dir / 'changes.csv', changes, CHANGE_FIELDS)
    write_csv(out_dir / 'section_changes.csv', queue, SECTION_FIELDS)
    with open(out_dir / 'snapshots.jsonl', 'w', encoding='utf-8') as f:
        for k in sorted(current):
            f.write(json.dumps(current[k], ensure_ascii=False) + '\n')
    with open(out_dir / 'review_queue.jsonl', 'w', encoding='utf-8') as f:
        for entry in queue:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    with open(out_dir / 'pricing_observations.jsonl', 'w', encoding='utf-8') as f:
        for row in current.values():
            for observation in row.get('pricing_observations', []):
                f.write(json.dumps(observation, ensure_ascii=False) + '\n')
    with open(out_dir / 'pricing_rate_changes.jsonl', 'w', encoding='utf-8') as f:
        for entry in queue:
            if entry.get('change_type') in {
                'rate_first_observed_candidate', 'rate_value_changed_candidate',
            }:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    statuses = Counter(x.get('status', 'unknown') for x in current.values())
    summary = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'categories': sorted(categories),
        'cohort_scope': cohort,
        'cohort_source': 'requested_job' if declared_cohort is not None else 'legacy_inference_or_explicit',
        'run_provenance_validation': provenance_validation,
        'manifest_sha256': manifest_sha256(catalog),
        'source_ids_explicit': source_ids is not None,
        'limit_per_category': limit,
        'offset_per_category': offset,
        'sources_expected': len(manifest),
        'sources_captured': statuses['captured'],
        'sources_comparable': sum(bool(_healthy(row)) for row in current.values()),
        'legacy_truncated_captures': sum(row.get('status') == 'captured' and bool(row.get('text_truncated')) for row in current.values()),
        'capture_rate': round(statuses['captured'] / len(manifest), 4) if manifest else 0,
        'statuses': dict(sorted(statuses.items())),
        'change_counts': dict(sorted(Counter(c['change_type'] for c in changes).items())),
        'review_candidates': len(queue),
        'approved_for_advisor': 0,
        'pricing_observation_count': sum(
            len(row.get('pricing_observations', []))
            for row in current.values()
        ),
        'pricing_inventory_incomplete_sources': sum(
            row.get('pricing_evidence_schema') == '1.0'
            and not row.get('pricing_inventory_complete')
            for row in current.values()
        ),
        'pricing_comparable_candidate_count': sum(
            sum(bool(x.get('comparable_candidate')) for x in
                row.get('pricing_observations', []))
            for row in current.values()
        ),
        'warning': 'All evidence and ranking hints are unverified; baselines are never new announcements.',
    }
    (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', nargs='+', required=True, type=Path)
    parser.add_argument('--previous', nargs='*', default=[], type=Path)
    parser.add_argument('--category', choices=['auto', 'all', 'documentation', 'pricing', 'changelog'], default='auto')
    parser.add_argument('--cohort', choices=['auto', 'all', 'proven', 'candidate'], default='auto')
    parser.add_argument('--source-ids', help='Comma-separated manifest IDs for a bounded Zyte job')
    parser.add_argument('--limit', type=int, help='Same per-spider limit used in Zyte')
    parser.add_argument('--offset', type=int, default=0, help='Same per-spider offset used in Zyte')
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    summary = export(read_jsonl(args.current), read_jsonl(args.previous), args.out_dir, args.category, args.cohort, args.source_ids, args.limit, args.offset)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
