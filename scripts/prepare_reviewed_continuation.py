"""Build unsigned exact continuation plans using the installed P21B reviews.

Offline planning only. No manifest edits, access grants, deployment or dispatch.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

HISTORY_SHA = 'b4f9310004b90f02c0c98bac1fd39227df11c3d6fd262abcc9d8ba2a8b7fe14b'
HISTORICAL_MANIFEST_SHA = '231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933'
SCOPE_KIND = 'exact_continuation_review_scope_NOT_AUTHORIZATION'
CATEGORIES = ('pricing', 'documentation', 'changelog')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_json(path, limit):
    path = Path(path)
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Expected an exact private non-symlink JSON file')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Continuation input exceeds size limit')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)


def build(scope, history, sources, groups, access, plans, registry_sha, decision):
    """Internal offline builder. CLI supplies validated installed policy inputs."""
    if digest(history) != HISTORY_SHA:
        raise ValueError('Historical inventory fingerprint mismatch')
    old_manifest = [{k: row[k] for k in ('id', 'provider', 'category', 'url')} for row in history]
    manifest_sha = digest(sources)
    if (digest(old_manifest) != HISTORICAL_MANIFEST_SHA
            or Counter(r['acquisition_state'] for r in history) != Counter(
                {'http_200': 200, 'redirect_deferred': 51, 'no_primary_response': 209})
            or [{k: r[k] for k in ('id', 'provider', 'category')} for r in sources] !=
               [{k: r[k] for k in ('id', 'provider', 'category')} for r in old_manifest]):
        raise ValueError('Continuation requires the original ordered source identities')
    known = {s['id']: s for s in sources}
    old = {r['id']: r for r in history}
    if (len(known) != 460 or set(groups) != set(known)
            or len({s['url'] for s in sources}) != len(known)):
        raise ValueError('Malformed current manifest or containment index')
    if (not isinstance(scope, dict) or set(scope) != {'kind', 'current_manifest_sha256', 'targets'}
            or scope['kind'] != SCOPE_KIND or scope['current_manifest_sha256'] != manifest_sha
            or not isinstance(scope['targets'], list) or not 1 <= len(scope['targets']) <= 260):
        raise ValueError('Explicit continuation scope must pin the current manifest')
    # A URL migration may change containment components. A historically held
    # source may never escape review by moving hosts; inherited held neighbors
    # in the current component also need explicit disposition.
    held_by_current_group = defaultdict(dict)
    for row in history:
        if row['hold_reasons']:
            held_by_current_group[groups[row['id']]][row['containment_group']] = row['hold_reasons']
    requested, seen_urls = {}, set()
    url_owner = {s['url']: s['id'] for s in sources}
    for target in scope['targets']:
        if not isinstance(target, dict) or set(target) != {'source_id', 'source_url', 'hold_resolution_note'}:
            raise ValueError('Malformed explicit target')
        sid, url, note = target['source_id'], target['source_url'], target['hold_resolution_note']
        if (not isinstance(sid, str) or sid not in known or sid in requested
                or old[sid]['acquisition_state'] == 'http_200'):
            raise ValueError('Unknown, duplicate or previously acquired source')
        if (not isinstance(url, str) or not 1 <= len(url) <= 2048
                or any(c.isspace() or ord(c) < 32 for c in url)
                or not isinstance(note, str) or len(note) > 1500):
            raise ValueError('Invalid continuation URL or hold review note')
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or url in seen_urls or url_owner.get(url, sid) != sid):
            raise ValueError('Unsafe or colliding continuation URL')
        requested[sid] = target
        seen_urls.add(url)
    rows, selected = [], defaultdict(list)
    access_sha = digest(access)
    for src in sources:
        sid = src['id']
        if sid not in requested:
            continue
        target = requested[sid]
        previous = old[sid]
        holds = held_by_current_group[groups[sid]]
        record = access['reviews'].get(sid, {})
        blockers = []
        if src['url'] != target['source_url']:
            blockers.append('manifest_migration_required')
        else:
            allowed, reason = decision(src)
            if not allowed:
                blockers.append(reason)
        if (not record or record.get('source_url') != target['source_url']
                or record.get('decision') != 'allowed_reviewed'):
            blockers.append('exact_target_access_review_missing')
        if holds:
            note = target['hold_resolution_note'].strip()
            if (len(note) < 80 or note not in record.get('evidence_note', '')
                    or any(group not in note or any(reason not in note for reason in reasons)
                           for group, reasons in holds.items())):
                blockers.append('historical_group_hold_disposition_missing_from_review')
        selected[src['category']].append(sid)
        rows.append({'source_id': sid, 'category': src['category'], 'historical_url': previous['url'],
                     'installed_url': src['url'], 'requested_url': target['source_url'],
                     'historical_state': previous['acquisition_state'], 'inherited_holds': holds,
                     'blockers': blockers, 'current_review_ready_for_unsigned_draft': not blockers,
                     'approved_for_advisor': False})
    conflicts = sorted(pid for pid, plan in plans['plans'].items()
                       if plan['category'] in selected and plan['cohort'] == 'all'
                       and plan['collection_mode'] == 'validation')
    complete = not conflicts and all(not r['blockers'] for r in rows)
    draft = None
    if complete:
        draft = {'schema_version': '1.0',
                 'kind': 'git_reviewed_expiring_bulk_validation_run_plans_not_schedules',
                 'default_policy': 'no_bulk_runs_authorized', 'plans': {}}
        for category in CATEGORIES:
            if category not in selected:
                continue
            full = [s for s in sources if s['category'] == category]
            ids = [s['id'] for s in full]
            permitted = selected[category]
            if not 2 <= len(full) <= 200:
                raise ValueError('Category exceeds existing P21B scope limits')
            plan_id = 'continuation_' + category + '_' + digest({'targets': permitted, 'manifest': manifest_sha, 'access': access_sha})[:12]
            draft['plans'][plan_id] = {
                'category': category, 'collection_mode': 'validation', 'cohort': 'all',
                'source_ids': ids, 'authorized_source_ids': permitted,
                'manifest_sha256': manifest_sha, 'source_registry_sha256': registry_sha,
                'access_registry_sha256': access_sha, 'selection_ids_sha256': digest(ids),
                'source_urls_sha256': digest([{'source_id': s['id'], 'source_url': s['url'], 'category': s['category']} for s in full]),
                'approved_by': '', 'reviewed_at_utc': '', 'expires_at_utc': '',
                'max_primary_requests': len(permitted), 'max_redirects_per_source': 0,
                'purpose': 'bounded_human_supervised_diagnostic', 'publisher_policy_review_attested': False,
            }
    report = {'kind': 'reviewed_continuation_preparation_NOT_AUTHORIZATION',
              'current_manifest_sha256': manifest_sha, 'historical_inventory_sha256': HISTORY_SHA,
              'access_registry_sha256': access_sha, 'scope_sha256': digest(scope),
              'requested_count': len(rows), 'requested_by_category': {c: len(v) for c, v in selected.items()},
              'historical_http_200': 200, 'conditional_cumulative_http_200_ceiling': 200 + len(rows),
              'current_review_ready_count': sum(not r['blockers'] for r in rows),
              'blocker_counts': dict(Counter(b for r in rows for b in r['blockers'])),
              'existing_full_category_plan_conflicts': conflicts,
              'unsigned_plan_count': len(draft['plans']) if draft else 0, 'targets': rows,
              'ready_to_dispatch': False, 'new_primary_requests_authorized_by_tool': 0,
              'publisher_rights_independently_verified_by_tool': False, 'approved_for_advisor': False}
    return report, draft


def prepare(scope, history, *, now=None):
    from agentfuse_crawlers import validation_access as policy
    from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
    from agentfuse_crawlers.sources import load_sources
    from agentfuse_crawlers.validation_containment import group_index

    sources = load_sources()
    access, plans = policy.load_access_registry(), policy.load_run_plan_registry()
    clock = policy._now(now)
    policy.validate_access_registry(access, now=clock)
    policy.validate_plan_registry(plans, now=clock)
    groups, _ = group_index(sources)
    return build(scope, history, sources, groups, access, plans, registry_revision_sha256(),
                 lambda src: policy.validation_access_decision(src, scope='bulk_validation', registry=access, now=clock))


def main():
    from scripts.plan_documentation_children import _private_new_directory, _write_private
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical-inventory', type=Path, required=True)
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    history = read_json(args.historical_inventory, 8_000_000)
    scope = read_json(args.scope, 1_000_000)
    report, draft = prepare(scope, history)
    out = _private_new_directory(args.out_dir)
    for filename, obj in [('continuation_report_NO_GO.json', report), ('bulk_run_authorizations_DRAFT_NOT_AUTHORIZED.json', draft)]:
        if obj is not None:
            _write_private(out / filename, (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())
    print(json.dumps({k: v for k, v in report.items() if k != 'targets'}, sort_keys=True))


if __name__ == '__main__':
    main()
