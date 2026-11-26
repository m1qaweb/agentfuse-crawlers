import copy
from collections import Counter

import pytest
from scripts import prepare_remaining_acquisition_review as m


def fixture(monkeypatch):
    # 460 synthetic source records with the same historical accounting totals.
    categories = ['pricing'] * 177 + ['documentation'] * 194 + ['changelog'] * 89
    rows = []
    for i, category in enumerate(categories):
        status = 200 if i < 200 else 308 if i < 251 else None
        held = i >= 200 and i < 431
        group = 'group_' + str(i)
        reasons = [m.ORDINARY] if 200 <= i < 231 else ['historical_hold'] if held else []
        ref = {'http_status': status, 'lifecycle_state': 'needs_validation'}
        url = f'https://example{i}.com/docs'
        rows.append(dict(id=f'source_{i}', provider=f'Provider {i}', category=category, url=url,
                         acquisition_state='http_200' if status == 200 else 'redirect_deferred' if status else 'no_primary_response',
                         original_scope_member=bool(status), containment_group=group, hold_reasons=reasons,
                         redirect_review_target=url+'/' if status == 308 else None,
                         primary_evidence=ref if status else None, latest_accounting=ref, accounting_history=[ref],
                         approved_for_advisor=False))
    manifest = [{k:r[k] for k in ('id','provider','category','url')} for r in rows]
    monkeypatch.setattr(m, 'MANIFEST', m.digest(manifest))
    report = dict(kind='historical_diagnostic_evidence_NOT_PERMISSION_OR_ACCURACY', manifest_sha256=m.MANIFEST,
                  held_groups={r['containment_group']:r['hold_reasons'] for r in rows if r['hold_reasons']},
                  approved_for_advisor=False, publisher_rights_independently_verified=False)
    return report, rows


def test_exact_accounting_and_review_only(monkeypatch):
    report, rows = fixture(monkeypatch)
    result, ledger, groups = m.build_review(report, rows)
    assert result['review_tiers'] == dict(zip(m.TIERS, [29,31,20,180,200]))
    assert result['initial_pool_theoretical_cumulative_http_200_ceiling'] == 260
    assert result['authorized_next_primary_requests'] == 0
    assert all(not r['eligible_for_next_run'] and not r['approved_for_advisor'] for r in ledger)
    assert all(not g['automatic_release'] for g in groups)


@pytest.mark.parametrize('change', ['approval','rights','hold','history','status','manifest','missing_hold'])
def test_reject_inconsistent_historical_evidence(monkeypatch, change):
    report, rows = fixture(monkeypatch)
    if change == 'approval': rows[200]['approved_for_advisor'] = True
    if change == 'rights': report['publisher_rights_independently_verified'] = True
    if change == 'hold': rows[200]['hold_reasons'] = []
    if change == 'history': rows[0]['accounting_history'] = [{'http_status': 404}]
    if change == 'status': rows[0]['acquisition_state'] = 'no_primary_response'
    if change == 'manifest': rows[0]['url'] += '/changed'
    if change == 'missing_hold':
        rows[200]['hold_reasons'] = []
        del report['held_groups'][rows[200]['containment_group']]
    with pytest.raises(ValueError): m.build_review(report, rows)


@pytest.mark.parametrize('target,expected', [
    ('https://example.com/docs/', 'trailing_slash_only'),
    ('https://example.com/home', 'same_origin_path_change'),
    ('https://other.com/docs', 'cross_origin'),
    ('https://example.com/docs?token=x', 'invalid_or_ambiguous_target'),
    ('https://user@example.com/home', 'invalid_or_ambiguous_target'),
    ('https://example.com/docs', 'invalid_or_ambiguous_target'),
])
def test_redirect_shape(target, expected):
    assert m.redirect_shape('https://example.com/docs', target, Counter([target]), set()) == expected


def test_shared_target_never_first_review(monkeypatch):
    report, rows = fixture(monkeypatch)
    # Make one ordinary redirect collide with a distinct configured source.
    rows[200]['redirect_review_target'] = rows[200]['url'] + '/'
    assert m.redirect_shape(rows[200]['url'], rows[200]['redirect_review_target'],
                            Counter([rows[200]['redirect_review_target']]*2), set()) == 'shared_target_or_manifest_collision'
    assert m.redirect_shape(rows[200]['url'], rows[200]['redirect_review_target'],
                            Counter([rows[200]['redirect_review_target']]), {rows[200]['redirect_review_target']}) == 'shared_target_or_manifest_collision'


def test_quarantine_not_eligible_even_without_group_hold(monkeypatch):
    report, rows = fixture(monkeypatch)
    rows[-1]['latest_accounting']['lifecycle_state'] = 'quarantined'
    result, ledger, _ = m.build_review(report, rows)
    assert result['initial_review_pool'] == 59
    assert next(r for r in ledger if r['id'] == rows[-1]['id'])['review_tier'] == m.TIERS[3]


def test_private_csv_no_review_prefill(monkeypatch, tmp_path):
    import csv
    report, rows = fixture(monkeypatch)
    out = tmp_path/'packet'
    m.write_review(out, *m.build_review(report, rows))
    with (out/'gap_review_only.csv').open() as f: review = list(csv.DictReader(f))
    assert len(review) == 260 and all(r['eligible_for_next_run'] == 'False' for r in review)
    assert all(not r['reviewer'] and not r['ownership_evidence_url'] and not r['review_note'] for r in review)
    with pytest.raises(ValueError): m.write_review(out, {}, [], [])
