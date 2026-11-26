import copy

import pytest
from scripts import prepare_reviewed_continuation as m


def fixture(monkeypatch):
    cats = ['pricing'] * 177 + ['documentation'] * 194 + ['changelog'] * 89
    sources = [dict(id=f'source_{i}', provider=f'Provider {i}', category=cat, url=f'https://example{i}.com/page')
               for i, cat in enumerate(cats)]
    history = [dict(s, acquisition_state='http_200' if i < 200 else 'redirect_deferred' if i < 251 else 'no_primary_response',
                    hold_reasons=['ordinary_redirect'] if i == 200 else [], containment_group=s['id'])
               for i, s in enumerate(sources)]
    monkeypatch.setattr(m, 'HISTORY_SHA', m.digest(history))
    monkeypatch.setattr(m, 'HISTORICAL_MANIFEST_SHA', m.digest(sources))
    groups = {s['id']: s['id'] for s in sources}
    scope = {'kind': m.SCOPE_KIND, 'current_manifest_sha256': m.digest(sources),
             'targets': [{'source_id': sources[i]['id'], 'source_url': sources[i]['url'], 'hold_resolution_note': ''} for i in (300, 400)]}
    access = {'reviews': {}}
    plans = {'plans': {}}
    return scope, history, sources, groups, access, plans, 'a'*64


def build(args):
    return m.build(*args, lambda s: (s['id'] in args[4]['reviews'], 'missing_review'))


def approve(args):
    for t in args[0]['targets']:
        args[4]['reviews'][t['source_id']] = {'source_url': t['source_url'], 'decision': 'allowed_reviewed', 'evidence_note': t['hold_resolution_note']}


def test_empty_registry_no_drafts(monkeypatch):
    args = fixture(monkeypatch)
    report, draft = build(args)
    assert draft is None and report['current_review_ready_count'] == 0
    assert report['requested_count'] == 2 and report['new_primary_requests_authorized_by_tool'] == 0
    assert report['conditional_cumulative_http_200_ceiling'] == 202


def test_small_explicit_subset_only_unsigned(monkeypatch):
    args = fixture(monkeypatch)
    approve(args)
    report, draft = build(args)
    assert report['unsigned_plan_count'] == 2 and not report['ready_to_dispatch']
    assert {p['category'] for p in draft['plans'].values()} == {'documentation', 'changelog'}
    assert {s for p in draft['plans'].values() for s in p['authorized_source_ids']} == {'source_300', 'source_400'}
    for p in draft['plans'].values():
        assert p['max_primary_requests'] == 1 and p['max_redirects_per_source'] == 0
        assert p['approved_by'] == '' and p['publisher_policy_review_attested'] is False
        assert p['selection_ids_sha256'] == m.digest(p['source_ids'])
        assert len(p['source_ids']) > 1


def test_uninstalled_migration_never_drafted(monkeypatch):
    args = fixture(monkeypatch)
    args[0]['targets'][0]['source_url'] += '/new'
    approve(args)
    report, draft = build(args)
    assert draft is None and 'manifest_migration_required' in report['targets'][0]['blockers']


def test_real_migration_preserves_historical_hold_and_requires_note(monkeypatch):
    args = fixture(monkeypatch)
    src = args[2][200]
    src['url'] = 'https://new.example.com/page'
    args[0]['current_manifest_sha256'] = m.digest(args[2])
    target = {'source_id': src['id'], 'source_url': src['url'], 'hold_resolution_note': ''}
    args[0]['targets'] = [target]
    approve(args)
    report, draft = build(args)
    assert draft is None and report['targets'][0]['inherited_holds'] == {'source_200': ['ordinary_redirect']}
    target['hold_resolution_note'] = 'Synthetic reviewer evaluated source_200 ordinary_redirect and recorded the exact reason for disposition.'
    approve(args)
    report, draft = build(args)
    assert report['unsigned_plan_count'] == 1 and draft is not None
    args[4]['reviews'][src['id']]['evidence_note'] = 'Unrelated synthetic review.'
    assert build(args)[1] is None


def test_current_group_inherits_other_historical_hold(monkeypatch):
    args = fixture(monkeypatch)
    args[3]['source_300'] = args[3]['source_200']
    approve(args)
    report, draft = build(args)
    assert draft is None and report['targets'][0]['inherited_holds'] == {'source_200': ['ordinary_redirect']}


def test_existing_plan_conflict_not_replaced(monkeypatch):
    args = fixture(monkeypatch)
    approve(args)
    args[5]['plans']['existing_docs'] = {'category': 'documentation', 'cohort': 'all', 'collection_mode': 'validation'}
    report, draft = build(args)
    assert draft is None and report['existing_full_category_plan_conflicts'] == ['existing_docs']


@pytest.mark.parametrize('change', ['history', 'manifest_pin', 'duplicate', 'old_success', 'unknown', 'identity_change', 'unsafe_url', 'url_collision', 'extra_field'])
def test_reject_invalid_scope(monkeypatch, change):
    args = fixture(monkeypatch)
    scope, history, sources, *_ = args
    if change == 'history': history[0]['acquisition_state'] = 'no_primary_response'
    elif change == 'manifest_pin': scope['current_manifest_sha256'] = 'b'*64
    elif change == 'duplicate': scope['targets'].append(copy.deepcopy(scope['targets'][0]))
    elif change == 'old_success': scope['targets'][0].update(source_id=sources[0]['id'], source_url=sources[0]['url'])
    elif change == 'unknown': scope['targets'][0]['source_id'] = 'unknown'
    elif change == 'identity_change': sources[300]['provider'] = 'Different'; scope['current_manifest_sha256'] = m.digest(sources)
    elif change == 'unsafe_url': scope['targets'][0]['source_url'] = 'https://user@example.com/page'
    elif change == 'url_collision': scope['targets'][0]['source_url'] = sources[301]['url']
    elif change == 'extra_field': scope['targets'][0]['approved'] = True
    with pytest.raises(ValueError): build(args)


def test_read_rejects_duplicate_json_keys_and_size(tmp_path):
    p = tmp_path/'test.json'
    p.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError): m.read_json(p, 100)
    p.write_text('{"a":1}')
    with pytest.raises(ValueError): m.read_json(p, 2)


def test_unsigned_then_synthetic_signed_plan_matches_existing_policy(monkeypatch):
    # The full repository CI exercises the actual production policy. The
    # standalone local test checkout may not contain the crawler package.
    policy = pytest.importorskip('agentfuse_crawlers.validation_access')
    from datetime import datetime, timedelta, timezone
    from urllib.parse import urlsplit
    from agentfuse_crawlers.run_context import manifest_sha256
    from agentfuse_crawlers.source_lifecycle import registry_revision_sha256, collection_decision
    from agentfuse_crawlers.sources import load_sources
    from agentfuse_crawlers.validation_containment import group_index

    sources = load_sources()
    history = [dict(s, acquisition_state='http_200' if i < 200 else 'redirect_deferred' if i < 251 else 'no_primary_response',
                    hold_reasons=[], containment_group=s['id']) for i, s in enumerate(sources)]
    monkeypatch.setattr(m, 'HISTORY_SHA', m.digest(history))
    monkeypatch.setattr(m, 'HISTORICAL_MANIFEST_SHA', manifest_sha256(sources))
    src = next(s for s in sources[251:] if collection_decision(s, 'validation')[0])
    sid = src['id']
    scope = {'kind': m.SCOPE_KIND, 'current_manifest_sha256': manifest_sha256(sources),
             'targets': [{'source_id': sid, 'source_url': src['url'], 'hold_resolution_note': ''}]}
    clock = datetime.now(timezone.utc)
    stamp = lambda days: (clock + timedelta(days=days)).isoformat(timespec='seconds')
    origin = 'https://' + urlsplit(src['url']).hostname
    access = {'schema_version': policy.SCHEMA, 'kind': policy.ACCESS_KIND,
              'default_decision': 'not_reviewed', 'reviews': {sid: {
                  'source_url': src['url'], 'category': src['category'], 'decision': 'allowed_reviewed',
                  'scopes': ['bulk_validation'], 'reviewed_by': 'Synthetic Reviewer',
                  'reviewed_at_utc': stamp(-1), 'expires_at_utc': stamp(5),
                  'ownership_evidence_url': src['url'], 'publisher_access_policy_url': origin+'/terms',
                  'robots_url': origin+'/robots.txt', 'publisher_terms_reviewed': True,
                  'robots_reviewed': True, 'private_retention_reviewed': True,
                  'evidence_note': 'Synthetic test fixture only. This record does not assert real publisher permission or approval of any source.'}}}
    plans = {'schema_version': policy.SCHEMA, 'kind': policy.PLAN_KIND,
             'default_policy': 'no_bulk_runs_authorized', 'plans': {}}
    monkeypatch.setattr(policy, 'load_access_registry', lambda: access)
    monkeypatch.setattr(policy, 'load_run_plan_registry', lambda: plans)
    report, draft = m.prepare(scope, history, now=clock)
    assert report['unsigned_plan_count'] == 1 and draft is not None
    with pytest.raises(ValueError):
        policy.validate_plan_registry(draft, now=clock)
    pid, plan = next(iter(draft['plans'].items()))
    plan.update(approved_by='Synthetic Reviewer', reviewed_at_utc=stamp(-1), expires_at_utc=stamp(1),
                publisher_policy_review_attested=True)
    policy.validate_plan_registry(draft, now=clock)
    full = [s for s in sources if s['category'] == src['category']]
    result = policy.authorize_bulk_run(selected=full, category=src['category'], cohort='all',
        collection_mode='validation', plan_id=pid, expected_plan_sha256=policy.digest(plan),
        expected_package_sha256='f'*64, current_package_sha256='f'*64,
        access_registry=access, run_plans=draft, now=clock)
    assert result['authorized_source_ids'] == frozenset({sid})
    assert result['max_primary_requests'] == 1 and result['max_redirects_per_source'] == 0
