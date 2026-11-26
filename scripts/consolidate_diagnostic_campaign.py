"""Offline, immutable Nov 25-26 diagnostic campaign consolidation, not approval."""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

DATA = Path(__file__).resolve().parents[1] / 'agentfuse_crawlers' / 'data'
MANIFEST = '231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933'
REGISTRY = '776384e860fe3207c734719a19b782adb20b30468f856549bfe35378709e6cc2'
BASE = 'd80b72f6643d3516a39a4e176939c84e9bff215639c40694b5d2d7b30985b15a'
RESUME = '93cd86cff545d451e776239edcd81f835d334afb85adae35a824025d0a00f948'
# File digests in Items, Requests, Logs order; actual historical observations.
JOBS = (
    ('changelogs_41', 'changelog', '883514/1/41', BASE, 'e15a7a8fa5ef9c86759fca19a80e2efdc2f401c462ef0b8737cdbf8feee1202f',
     ('ad91545507abfca16060c1d9db66437558ccb54337809a1f8d2775720bdec0fb', '25fe8e6aeb89e2efe585edd99a0bd6530bc78163951432991a177ea35374cfaa', '68f46421a56b3ac16d02b5e065603211f870a624d14e2eb39dcc747fa21dd94f')),
    ('documentation_40', 'documentation', '883514/2/40', BASE, '1c5ddf64cf982e7118355849c45d7f146ec2a0abe9e4e85f58fea23cff85573f',
     ('7bbf8f60d567d434e150ab2bc4f1e4caa3e3ea418f5be984fffe9683105bd560', '7859fd5b543c92640383acd540b24d25285fba769121801090ee59422ddbc01a', '07144b14b73d471809466b3e29a9890cb5968a309dab4a845d9c9e4589026b63')),
    ('pricing_18', 'pricing', '883514/3/18', BASE, '27909a00fb9aecbde0265bf7d52ca2361f4f811528d081bfe4fad25c6ed974cc',
     ('6a5a2cdd006d2539aa77ccc4db903f4b79d007d4b348a393fb3bcef4271ebc97', '1be7a082b6b095c1e112b3c838ac249d960bc7b6400853ef77f6c239e565add3', 'c8ff253cec174df7f8223cf5f93a9d08dac4f55c2d2dc44f50f1e001752b2348')),
    ('documentation_43', 'documentation', '883514/2/43', RESUME, '29eb148008880f4e7fe55eb24a10024c117a16c6b0df29c85890fd8f50773289',
     ('6d2103517c8a65c3c52c00b1babfad0acf305d9d55e51010d3dc6b542114d572', '4c9814d6d6ba2a158b623c4b44f09271c47afafd2c81b6461802ef5d5545be92', 'fc74b886c961e85db55a8e59bf0c727c8fa6e3b2586cbe5e3c1aa2a974f2c496')),
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, 'Duplicate JSON key')
        obj[key] = value
    return obj


def read_export(path, expected):
    require(path.is_file() and not path.is_symlink() and
            not any(p.is_symlink() for p in path.parents), 'Missing or symlinked export')
    with path.open('rb') as f:
        raw = f.read(32_000_001)
    require(len(raw) <= 32_000_000 and hashlib.sha256(raw).hexdigest() == expected,
            'Export byte digest mismatch: ' + path.name)
    value = json.loads(raw, object_pairs_hook=unique_pairs)
    require(isinstance(value, list) and all(isinstance(x, dict) for x in value),
            'Expected Dashboard JSON array')
    return value


def log_stats(logs, job, revision, items, requests, robots):
    messages = [x['message'] for x in logs]
    dumps = [x for x in messages if 'Dumping Scrapy stats:' in x]
    require(len(dumps) == 1, 'Missing or ambiguous final statistics')
    def stat(key):
        matches = re.findall(r"'" + re.escape(key) + r"': (?:'([^']*)'|(\d+)),?", dumps[0])
        require(len(matches) == 1, 'Missing or ambiguous statistic: ' + key)
        return matches[0][0] or matches[0][1]
    for k, expected in {'agentfuse/run/zyte_job_id': job, 'agentfuse/run/deployment_revision': revision,
                        'item_scraped_count': str(items), 'downloader/request_count': str(requests),
                        'downloader/response_count': str(requests), 'robotstxt/request_count': str(robots)}.items():
        require(stat(k) == expected, 'Logs disagree: ' + k)
    reason = stat('finish_reason')
    require(sum(x == '[scrapy.core.engine] Spider closed (' + reason + ')' for x in messages) == 1,
            'Missing matching final close')
    return reason


def reconcile_job(items, requests, logs, manifest, eligible, job, revision, scope, category):
    selected = [s for s in manifest if s['category'] == category]
    by_url = {s['url']: s['id'] for s in selected}
    by_id = {s['id']: s for s in selected}
    selection = digest([s['id'] for s in selected])
    spider = 'official_changelogs' if category == 'changelog' else 'official_' + category
    meta = {'zyte_job_id': job, 'deployment_revision': revision, 'deployment_revision_kind': 'package_py_json_sha256_v1',
            'manifest_sha256': MANIFEST, 'source_registry_sha256': REGISTRY, 'selection_ids_sha256': selection,
            'selection_source_count': len(selected), 'public_diagnostic_scope_sha256': scope, 'spider_name': spider,
            'validation_scope': 'public_diagnostic_resume' if revision == RESUME else 'public_diagnostic',
            'collection_mode': 'validation', 'requested_cohort': 'all', 'run_scope_explicit': True}
    indexed, primary, robots = {}, {}, 0
    for i, row in enumerate(items):
        sid = row.get('source_id')
        require(sid in by_id and sid not in indexed, 'Unexpected or duplicate Item')
        source = by_id[sid]
        require(all(row.get(k) == v for k, v in meta.items()) and row.get('approved_for_advisor') is False
                and row.get('source_url') == source['url'] and row.get('provider') == source['provider']
                and row.get('category') == category and row.get('public_diagnostic_source_in_scope') is (sid in eligible)
                and row.get('review_status') == 'unverified'
                and row.get('public_diagnostic_publisher_rights_independently_verified') is False, 'Item identity/scope/approval mismatch')
        indexed[sid] = (i, row)
    require(len({row['run_started_at_utc'] for _, row in indexed.values()}) == 1, 'Mixed run timestamps')
    origins = {urlsplit(s['url']).netloc for s in selected if s['id'] in eligible}
    for i, request in enumerate(requests):
        require(request.get('method') == 'GET' and type(request.get('status')) is int
                and 100 <= request['status'] <= 599, 'Unexpected request method/status')
        url = request['url']
        if url not in by_url:
            u = urlsplit(url)
            require(u.scheme == 'https' and u.netloc in origins and u.path == '/robots.txt'
                    and not u.query and not u.fragment, 'Unexpected network URL')
            robots += 1
            continue
        sid = by_url[url]
        require(sid in eligible and sid in indexed and sid not in primary, 'Unexpected/duplicate primary response')
        require(indexed[sid][1].get('http_status') == request['status'], 'Request/Item status mismatch')
        primary[sid] = i
    require({sid for sid, (_, row) in indexed.items() if row.get('http_status') is not None} == set(primary),
            'Unmatched primary Item')
    reason = log_stats(logs, job, revision, len(items), len(requests), robots)
    return indexed, primary, {'job_id': job, 'category': category, 'package_sha256': revision,
                              'items': len(items), 'requests': len(requests), 'robots': robots,
                              'primary': len(primary), 'http_200': sum(requests[i]['status'] == 200 for i in primary.values()),
                              'close_reason': reason}


def consolidate(input_dir):
    manifest = json.loads((DATA / 'sources.json').read_text())
    base = json.loads((DATA / 'public_diagnostic_scope.json').read_text())
    resume = json.loads((DATA / 'public_diagnostic_resume.json').read_text())
    require(digest(manifest) == MANIFEST and digest(base['source_ids']) == '2f0609681cdd32ab8b88fd6c43c5e1e80ee4218e272224df7b3d707f35bcf590'
            and digest(resume['source_ids']) == 'cd73c9590f4cb3e6250d9df470eef2d253ce7447f1bed6cf6d2a942ee1595145'
            and digest(base['prior_held_groups']) == '3128eadae1aeeaf3df0d32213030bd066c5be50a5ab67de8a847492a1e415226', 'Historical package scope mismatch')
    histories, holds, captures, jobs = defaultdict(list), defaultdict(set), {}, []
    for group in base['prior_held_groups']:
        holds[group].add('historical_packaged_hold')
    group_by_id = {}
    for suffix, category, job, rev, scope, hashes in JOBS:
        names = [f'{kind}_official_{suffix}.json' for kind in ('items', 'requests', 'log')]
        items, requests, logs = [read_export(input_dir / n, h) for n, h in zip(names, hashes)]
        eligible = set(resume['source_ids'] if rev == RESUME else base['source_ids'])
        indexed, primary, summary = reconcile_job(items, requests, logs, manifest, eligible, job, rev, scope, category)
        summary['exports_sha256'] = dict(zip(names, hashes))
        jobs.append(summary)
        for sid, (i, row) in indexed.items():
            group = row['validation_containment_group']
            require(group_by_id.setdefault(sid, group) == group, 'Source containment group changed')
            reason = row.get('validation_containment_block_reason')
            if reason:
                holds[group].add(reason)
            ref = {'job_id': job, 'item_index': i, 'items_sha256': hashes[0], 'http_status': row.get('http_status'),
                   'status': row['status'], 'error': row.get('error'), 'recorded_at_utc': row['fetched_at_utc'],
                   'lifecycle_state': row.get('source_lifecycle_state'), 'policy_status': row.get('source_policy_status'),
                   'lifecycle_reason': row.get('source_lifecycle_reason'), 'in_job_scope': row['public_diagnostic_source_in_scope']}
            if sid in primary:
                require(sid not in captures, 'Duplicate primary across historical jobs')
                ref.update(request_index=primary[sid], requests_sha256=hashes[1])
                captures[sid] = {'source_id': sid, 'evidence': ref, 'item': row, 'approved_for_advisor': False}
            histories[sid].append(ref)
    inventory, counts = [], defaultdict(Counter)
    for source in manifest:
        sid = source['id']
        require(sid in group_by_id, 'Missing historical inventory accounting')
        group = group_by_id[sid]
        capture = captures.get(sid)
        row = capture['item'] if capture else {}
        status = row.get('http_status')
        state = 'http_200' if status == 200 else 'redirect_deferred' if status in (301, 302, 303, 307, 308) else 'other_response' if capture else 'no_primary_response'
        text_observed = status == 200 and row.get('quality_axes', {}).get('content_capture_status') == 'text_observed_unverified'
        counts[source['category']].update({'inventory': 1, state: 1, 'text_observed_unverified': int(text_observed),
                                           'captured_status': int(status == 200 and row.get('status') == 'captured')})
        inventory.append({**source, 'acquisition_state': state, 'original_scope_member': sid in base['source_ids'],
                          'containment_group': group, 'hold_reasons': sorted(holds.get(group, ())),
                          'latest_accounting': histories[sid][-1],
                          'redirect_review_target': row.get('redirect_review_target'), 'text_observed_unverified': text_observed,
                          'primary_evidence': capture['evidence'] if capture else None, 'accounting_history': histories[sid],
                          'approved_for_advisor': False})
    totals = sum(counts.values(), Counter())
    report = {'schema_version': '1.0', 'kind': 'historical_diagnostic_evidence_NOT_PERMISSION_OR_ACCURACY', 'manifest_sha256': MANIFEST,
              'jobs': jobs, 'category_counts': {k: dict(v) for k, v in sorted(counts.items())}, 'totals': dict(totals),
              'network_requests': sum(x['requests'] for x in jobs), 'robots_requests': sum(x['robots'] for x in jobs),
              'primary_responses': len(captures),
              'successful_provider_labels': len({c['item']['provider'] for c in captures.values() if c['item']['http_status'] == 200}),
              'unfetched_without_recorded_group_hold': sum(x['acquisition_state'] == 'no_primary_response' and not x['hold_reasons'] for x in inventory),
              'held_group_count': len(holds), 'held_groups': {k: sorted(v) for k, v in sorted(holds.items())},
              'approved_for_advisor': False, 'independently_verified_sources': 0,
              'publisher_rights_independently_verified': False, 'original_response_bodies_available': False}
    return report, inventory, [captures[s['id']] for s in manifest if s['id'] in captures]


def write_private(out, report, inventory, captures):
    require(not out.exists() and not out.is_symlink() and not any(p.is_symlink() for p in out.parents)
            and not out.resolve().is_relative_to(DATA.parent.parent), 'Use a new private directory outside repository')
    out.mkdir(mode=0o700)
    for name, value in [('report.json', report), ('inventory.json', inventory), ('primary_observations.json', captures)]:
        path = out / name
        with path.open('x', encoding='utf-8') as f:
            path.chmod(0o600)
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    result = consolidate(args.input_dir)
    write_private(args.out_dir, *result)
    print(json.dumps(result[0]['totals'], sort_keys=True))


if __name__ == '__main__':
    main()
