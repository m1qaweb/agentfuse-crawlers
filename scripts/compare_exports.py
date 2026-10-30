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

from agentfuse_crawlers.sources import load_sources, load_proven_source_ids

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
                if (source_id not in rows or item.get('fetched_at_utc', '') >=
                        rows[source_id].get('fetched_at_utc', '')):
                    rows[source_id] = item
    return rows


def _healthy(row):
    return row.get('status') == 'captured' and row.get('content_sha256') and not row.get('text_truncated')


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


def _section_diffs(current, previous):
    """Compare sections only when both complete captures exist.

    Truncated sections/text can suggest removals that never happened: suppress.
    Historical sections on the first crawl are never called fresh news.
    """
    changes = []
    for source_id, curr in sorted(current.items()):
        old = previous.get(source_id)
        if not old or not _healthy(curr) or not _healthy(old):
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
    section_changes = _section_diffs(current, previous)
    queue = list(section_changes)
    detailed_sources = {x['source_id'] for x in section_changes}
    # Only generate page-level tasks if no section-level diff is available.
    for item in changes:
        if item['change_type'] != 'page_text_changed' or item['source_id'] in detailed_sources:
            continue
        record = current[item['source_id']]
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


def export(current, previous, out_dir, category='auto'):
    if category not in {'auto', 'all', 'documentation', 'pricing', 'changelog'}:
        raise ValueError('Invalid category filter')
    categories = ({x.get('category') for x in current.values()}
                  if category == 'auto' else
                  {category} if category != 'all' else {'documentation', 'pricing', 'changelog'})
    categories = categories.intersection({'documentation', 'pricing', 'changelog'})
    if not categories:
        raise ValueError('No recognized categories in current exports; pass --category')
    manifest = [s for s in load_sources() if s['category'] in categories]
    ids = {s['id'] for s in manifest}
    unknown = set(current) - {s['id'] for s in load_sources()}
    if unknown:
        raise ValueError(f'Unknown source IDs not in trusted manifest: {sorted(unknown)}')
    current = {k: v for k, v in current.items() if k in ids}
    previous = {k: v for k, v in previous.items() if k in ids}
    proven = load_proven_source_ids()
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
    statuses = Counter(x.get('status', 'unknown') for x in current.values())
    summary = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'categories': sorted(categories),
        'sources_expected': len(manifest),
        'sources_captured': statuses['captured'],
        'sources_comparable': sum(bool(_healthy(row)) for row in current.values()),
        'legacy_truncated_captures': sum(row.get('status') == 'captured' and bool(row.get('text_truncated')) for row in current.values()),
        'capture_rate': round(statuses['captured'] / len(manifest), 4) if manifest else 0,
        'statuses': dict(sorted(statuses.items())),
        'change_counts': dict(sorted(Counter(c['change_type'] for c in changes).items())),
        'review_candidates': len(queue),
        'approved_for_advisor': 0,
        'warning': 'All evidence and ranking hints are unverified; baselines are never new announcements.',
    }
    (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', nargs='+', required=True, type=Path)
    parser.add_argument('--previous', nargs='*', default=[], type=Path)
    parser.add_argument('--category', choices=['auto', 'all', 'documentation', 'pricing', 'changelog'], default='auto')
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    summary = export(read_jsonl(args.current), read_jsonl(args.previous), args.out_dir, args.category)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
