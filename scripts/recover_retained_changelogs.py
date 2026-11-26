"""Bounded, review-only recovery of explicitly dated retained changelog evidence."""
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

SHA = re.compile(r'[0-9a-f]{64}')
MONTHS = 'January February March April May June July August September October November December'.split()
MONTH = '(?:' + '|'.join(MONTHS + [x[:3] for x in MONTHS]) + ')'
DAY = rf'{MONTH} [0-9]{{1,2}}, 20[0-9]{{2}}'
ISO = r'20[0-9]{2}-[0-9]{2}-[0-9]{2}'
# Source-specific page scopes are not verified catalog product IDs. In particular,
# the PostHog and Sentry pages are publisher-wide, not AI-only changelogs.
SCOPES = {
    'deepseek_changelog': 'DeepSeek API changelog',
    'gemini_cli_changelog': 'Gemini CLI announcements',
    'warp_changelog': 'Warp release notes',
    'posthog_ai_observability_changelog': 'PostHog publisher-wide changelog',
    'sentry_seer_changelog': 'Sentry publisher-wide changelog',
    'hyper3d_rodin_changelog': 'Rodin API documentation notices',
    'prime_intellect_changelog': 'Prime Intellect blog announcement index',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def normalize(value):
    return ' '.join(value.replace('\u200b', '').split()).casefold()


def explicit_day(value):
    try:
        if re.fullmatch(ISO, value):
            return date.fromisoformat(value).isoformat()
        m = re.fullmatch(r'([A-Za-z]+) ([0-9]{1,2}), (20[0-9]{2})', value)
        if m:
            month = next(i for i, name in enumerate(MONTHS, 1)
                         if m[1].casefold() in {name.casefold(), name[:3].casefold()})
            return date(int(m[3]), month, int(m[2])).isoformat()
    except (ValueError, StopIteration):
        pass
    return None


def patterns(sid, text):
    """Yield a heading/date/body locator, never infer a year from crawl time."""
    if sid == 'deepseek_changelog':
        pattern = rf'^Date: (?P<day>{ISO})\u200b?\n(?P<title>[^\n\u200b]{{3,180}})\u200b\n(?P<body>[^\n]{{15,2400}})'
        for m in re.finditer(pattern, text, re.M):
            yield m, explicit_day(m['day']), 'day', 'dated_release_note', m['title'], None
    elif sid in {'gemini_cli_changelog', 'warp_changelog'}:
        if sid == 'gemini_cli_changelog':
            pattern = rf'^(?P<title>Announcements: (?P<version>v[0-9]+\.[0-9]+\.[0-9]+) - (?P<day>{ISO}))\nSection titled “(?P=title)”\n(?P<body>[^\n]{{8,1000}})'
            kind = 'dated_announcement_heading'
        else:
            pattern = r'^(?P<title>(?P<day>20[0-9]{2}\.[0-9]{2}\.[0-9]{2}) \((?P<version>v0\.[0-9.]+)\))\nSection titled “(?P=title)”\n(?:Improvements|Bug fixes|Features|Fixes)\n(?P<body>[^\n]{8,1800})'
            kind = 'dated_release_note'
        for m in re.finditer(pattern, text, re.M):
            yield m, explicit_day(m['day'].replace('.', '-')), 'day', kind, m['title'], m['version']
    elif sid == 'posthog_ai_observability_changelog':
        pattern = rf'^(?P<title>[^\n]{{3,180}})\n(?P<day>{DAY}) · [^\n]{{1,100}} Team\n(?P<body>[^\n]{{15,2400}})'
        for m in re.finditer(pattern, text, re.M | re.I):
            yield m, explicit_day(m['day']), 'day', 'dated_changelog_card', m['title'], None
    elif sid == 'sentry_seer_changelog':
        pattern = rf'^(?P<title>[^\n]{{3,180}})\n(?P<body>[^\n]{{15,2000}})\n(?P<day>{DAY})Read On →$'
        for m in re.finditer(pattern, text, re.M | re.I):
            yield m, explicit_day(m['day']), 'day', 'dated_changelog_card', m['title'], None
    elif sid == 'hyper3d_rodin_changelog':
        # Explicit month headers plus known notice labels, no fabricated day.
        group = re.compile(rf'^(?P<month>{MONTH}) (?P<year>20[0-9]{{2}})\n', re.M)
        notice = re.compile(r'^(?:New docs|Docs update|New parameter|Parameter update|Refinement|Removed parameter|New feature)[:：][^\n]{3,900}[.!?]$', re.M | re.I)
        groups = list(group.finditer(text))
        for i, m in enumerate(groups):
            end = groups[i+1].start() if i+1 < len(groups) else len(text)
            # Stop at the first non-notice line, e.g. footer/navigation.
            cursor = m.end()
            while cursor < end:
                n = notice.match(text, cursor, end)
                if not n:
                    break
                month = explicit_day(m['month']+' 1, '+m['year'])
                yield (m, n), month[:7] if month else None, 'month', 'month_scoped_notice', n[0], None
                cursor = n.end()+1
    elif sid == 'prime_intellect_changelog':
        pattern = rf'^(?P<day>{DAY})/Announcements(?P<title>[^\n]{{3,180}})$'
        for m in re.finditer(pattern, text, re.M | re.I):
            yield m, explicit_day(m['day']), 'day', 'announcement_index_entry', m['title'], None


def old_events(item):
    events = item['release_events']
    if not isinstance(events, list) or len(events) > 80:
        raise ValueError('Malformed retained release event array')
    for e in events:
        if (e.get('source_id') != item['source_id'] or e.get('approved_for_advisor') is not False
                or e.get('review_status') != 'unverified'
                or not re.fullmatch(re.escape(item['source_id'])+r':[a-f0-9]{24}', str(e.get('event_id', '')))
                or not SHA.fullmatch(str(e.get('body_sha256', '')))
                or not isinstance(e.get('title'), str)
                or (e.get('published_at') is not None and explicit_day(e['published_at']) != e['published_at'])):
            raise ValueError('Malformed or privileged retained event')
    return events


def link_old(events, title, observed_date):
    hits = [(i, e) for i, e in enumerate(events) if normalize(e['title']) == normalize(title)]
    if not hits:
        return 'no_exact_title_match', None
    if len(hits) != 1 or sum(e['event_id'] == hits[0][1]['event_id'] for e in events) != 1:
        return 'ambiguous_title_or_identity', None
    i, event = hits[0]
    if event['published_at'] is None:
        state = 'unique_undated_title'
    elif event['published_at'] == observed_date:
        state = 'unique_already_dated_title'
    else:
        return 'date_conflict', None
    return state, {'event_index': i, 'event_id': event['event_id'], 'event_sha256': digest(event)}


def recover_item(item):
    events = old_events(item)
    sid = item['source_id']
    if item.get('source_product_title_conflict') or item.get('release_ui_contamination_requires_review'):
        return 'identity_or_ui_review_required', []
    if item.get('freshness_warnings') or item.get('error') == 'server_cached_response_over_one_day':
        return 'freshness_review_required', []
    if sid not in SCOPES:
        return 'layout_not_selected', []
    if item.get('quality_axes', {}).get('content_capture_status') != 'text_observed_unverified':
        return 'insufficient_text', []
    source = urlsplit(item['source_url'])
    canonical = urlsplit(item.get('canonical_url') or item['source_url'])
    if (canonical.scheme != 'https' or canonical.netloc != source.netloc
            or canonical.path.rstrip('/') != source.path.rstrip('/') or canonical.query or canonical.fragment):
        return 'canonical_review_required', []
    text = item.get('text', '')
    if not isinstance(text, str) or len(text) > 24000:
        raise ValueError('Unexpected retained text size')
    stamp = datetime.fromisoformat(item['fetched_at_utc'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Naive observation time')
    asof = stamp.astimezone(timezone.utc).date().isoformat()
    eligible = []
    for match, when, precision, kind, title, version in patterns(sid, text):
        if not when or when > asof[:len(when)]:
            continue
        parts = match if isinstance(match, tuple) else (match,)
        if any(p.end() == len(text) for p in parts) and item.get('text_truncated'):
            continue
        if not isinstance(match, tuple) and match.end() < len(text) and text[match.end()] != '\n':
            continue
        eligible.append((parts, when, precision, kind, title, version))
    title_counts = Counter(normalize(t) for _, _, _, _, t, _ in eligible)
    key_counts = Counter((k, d, normalize(t)) for _, d, _, k, t, _ in eligible)
    records = []
    for parts, when, precision, kind, title, version in eligible:
        key = (kind, when, normalize(title))
        # Identical displayed title/date rows can have different bodies. Do
        # not discard one arbitrarily or count either as an independent event.
        if key_counts[key] != 1:
            continue
        locators = [{'field': 'text', 'start': p.start(), 'end': p.end(), 'evidence_text': p[0],
                     'evidence_sha256': digest(p[0])} for p in parts]
        state, link = link_old(events, title, when) if precision == 'day' and kind != 'announcement_index_entry' else ('not_release_identity_match', None)
        if link and title_counts[normalize(title)] != 1:
            state, link = 'ambiguous_title_or_identity', None
        blockers = ['independent_event_and_date_review_required', 'canonical_product_mapping_review_required',
                    'publisher_reuse_review_required', 'single_snapshot_not_change_detection',
                    'excerpt_not_complete_event_body']
        if precision == 'month':
            blockers.append('day_precision_unavailable')
        if kind == 'announcement_index_entry':
            blockers.append('article_body_not_observed_not_release_proof')
        if sid in {'posthog_ai_observability_changelog', 'sentry_seer_changelog'}:
            blockers.append('publisher_wide_not_ai_product_attribution')
        if state in {'ambiguous_title_or_identity', 'date_conflict'} or item.get('release_event_identity_collision'):
            blockers.append('event_identity_review_required')
        r = {'source_id': sid, 'page_scope_label': SCOPES[sid], 'title': title, 'version_label': version,
             'record_kind': kind, 'displayed_date_candidate': when, 'date_precision': precision,
             'evidence_locators': locators, 'existing_event_link_state': state, 'existing_event_reference': link,
             'source_content_sha256': item.get('content_sha256'), 'expected_product_id': item.get('source_expected_product_id'),
             'normalization_blockers': blockers,
             'review_status': 'unverified', 'approved_for_advisor': False, 'publication_date_verified': False,
             'product_identity_verified': False, 'alert_eligible': False}
        r['candidate_id'] = digest({'source_id': sid, 'key': key, 'locators': locators})
        records.append(r)
    return ('review_candidates' if records else 'no_eligible_explicit_date_layout'), records


def recover(observations):
    candidates, coverage, seen = [], [], set()
    for entry in observations:
        item, evidence = entry['item'], entry['evidence']
        if item.get('category') != 'changelog' or item.get('http_status') != 200:
            continue
        sid = item['source_id']
        if (sid in seen or entry.get('source_id') != sid or entry.get('approved_for_advisor') is not False
                or item.get('approved_for_advisor') is not False or item.get('review_status') != 'unverified'
                or any(item.get(k) is not False for k in ('public_diagnostic_publisher_rights_independently_verified',
                       'latest_publication_verified', 'source_product_ownership_verified'))
                or evidence.get('http_status') != 200 or evidence.get('job_id') != item.get('zyte_job_id')
                or any(not SHA.fullmatch(str(evidence.get(k, ''))) for k in ('items_sha256', 'requests_sha256'))
                or any(type(evidence.get(k)) is not int or evidence[k] < 0 for k in ('item_index', 'request_index'))):
            raise ValueError('Invalid or duplicate historical changelog evidence')
        seen.add(sid)
        events = old_events(item)
        state, rr = recover_item(item)
        for r in rr:
            r.update(source_url=item['source_url'], observed_at_utc=item['fetched_at_utc'], primary_evidence=evidence)
        candidates.extend(rr)
        coverage.append({'source_id': sid, 'state': state, 'original_error': item.get('error'),
                         'retained_event_records': len(events), 'retained_day_date_candidates': sum(e['published_at'] is not None for e in events),
                         'retained_identity_collision': len({e['event_id'] for e in events}) != len(events),
                         'original_window_complete_indicator': item.get('release_window_complete') is True,
                         'recovered_observations': len(rr), 'approved_for_advisor': False})
    if len({r['candidate_id'] for r in candidates}) != len(candidates):
        raise ValueError('Duplicate recovered observation identity')
    report = {'kind': 'retained_changelog_recovery_NOT_VERIFIED', 'source_count': len(coverage),
              'retained_event_records': sum(r['retained_event_records'] for r in coverage),
              'retained_day_date_candidates': sum(r['retained_day_date_candidates'] for r in coverage),
              'retained_identity_collision_sources': sum(r['retained_identity_collision'] for r in coverage),
              'sources_with_recovered_observations': sum(bool(r['recovered_observations']) for r in coverage),
              'recovered_observations': len(candidates), 'record_kinds': dict(Counter(r['record_kind'] for r in candidates)),
              'existing_event_link_states': dict(Counter(r['existing_event_link_state'] for r in candidates)),
              'coverage': coverage, 'approved_for_advisor': False, 'independently_verified_facts': 0,
              'alert_eligible_count': 0, 'distinct_release_total_verified': False}
    return report, candidates


def main():
    from scripts.consolidate_diagnostic_campaign import consolidate, write_private
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    _, _, observations = consolidate(args.input_dir)
    report, candidates = recover(observations)
    write_private(args.out_dir, report, report['coverage'], candidates)
    print(json.dumps({k: v for k, v in report.items() if k != 'coverage'}, sort_keys=True))


if __name__ == '__main__':
    main()
