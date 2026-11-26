"""Prioritize historical acquisition gaps without granting access or changing URLs."""
import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

MANIFEST = '231534c826b16ec19ca3358a1603cbfa8f7f478bd6f99717ad9784b167787933'
ORDINARY = 'agentfuse_validation_ordinary_redirect_deferred'
COUNTS = {'pricing': 177, 'documentation': 194, 'changelog': 89}
TIERS = ('review_original_url', 'review_ordinary_redirect', 'review_other_redirect_hold',
         'review_unfetched_group_hold', 'retain_existing_http_200')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def redirect_shape(source, target, targets, manifest_urls):
    try:
        a, b = urlsplit(source), urlsplit(target)
        if (b.scheme != 'https' or not b.hostname or b.netloc != b.hostname
                or b.query or b.fragment or target == source):
            return 'invalid_or_ambiguous_target'
        if a.netloc != b.netloc:
            return 'cross_origin'
        if targets[target] > 1 or target in manifest_urls:
            return 'shared_target_or_manifest_collision'
        if source.rstrip('/') == target.rstrip('/'):
            return 'trailing_slash_only'
        return 'same_origin_path_change'
    except (TypeError, ValueError, AttributeError):
        return 'invalid_or_ambiguous_target'


def build_review(report, inventory):
    """Only the historical consolidation may supply evidence to the CLI."""
    manifest = [{k: row[k] for k in ('id', 'provider', 'category', 'url')} for row in inventory]
    if (report.get('kind') != 'historical_diagnostic_evidence_NOT_PERMISSION_OR_ACCURACY'
            or report.get('manifest_sha256') != MANIFEST or digest(manifest) != MANIFEST
            or Counter(s['category'] for s in manifest) != COUNTS
            or report.get('approved_for_advisor') is not False
            or report.get('publisher_rights_independently_verified') is not False):
        raise ValueError('Not the exact unapproved historical 460-source consolidation')
    held = report['held_groups']
    groups, rows = defaultdict(list), []
    targets = Counter(r['redirect_review_target'] for r in inventory if r['acquisition_state'] == 'redirect_deferred')
    manifest_urls = {s['url'] for s in manifest}
    for row in inventory:
        group = row['containment_group']
        reasons = row['hold_reasons']
        state = row['acquisition_state']
        primary = row['primary_evidence']
        if (row.get('approved_for_advisor') is not False or reasons != sorted(held.get(group, []))
                or row['latest_accounting'] != row['accounting_history'][-1]
                or (primary is not None and primary not in row['accounting_history'])):
            raise ValueError('Inconsistent historical source or group evidence')
        status = primary['http_status'] if primary is not None else None
        expected = ('http_200' if status == 200 else 'redirect_deferred' if status in (301, 302, 303, 307, 308)
                    else 'no_primary_response' if primary is None else 'other_response')
        if state != expected or state == 'other_response':
            raise ValueError('Unexpected historical acquisition state')
        target, shape = None, None
        quarantined = row['latest_accounting']['lifecycle_state'] == 'quarantined'
        if state == 'http_200':
            tier = TIERS[4]
        elif state == 'redirect_deferred':
            target = row['redirect_review_target']
            shape = redirect_shape(row['url'], target, targets, manifest_urls)
            if not reasons:
                raise ValueError('Deferred redirect without containment hold')
            tier = TIERS[1] if reasons == [ORDINARY] and not quarantined and shape in (
                'trailing_slash_only', 'same_origin_path_change') else TIERS[2]
        else:
            tier = TIERS[0] if not reasons and not quarantined else TIERS[3]
        r = {**{k: row[k] for k in ('id', 'provider', 'category', 'url', 'original_scope_member',
                                     'containment_group', 'hold_reasons', 'primary_evidence', 'latest_accounting')},
             'acquisition_state': state, 'review_tier': tier, 'redirect_target_NOT_VERIFIED': target,
             'redirect_shape_NOT_PERMISSION': shape, 'lifecycle_quarantined': quarantined,
             'group_hold_release_required': bool(reasons), 'manifest_change_review_required': target is not None,
             'source_review_required': tier != TIERS[4], 'eligible_for_next_run': False,
             'approved_for_advisor': False}
        rows.append(r)
        groups[group].append(r)
    if not set(held) <= set(groups) or Counter(r['acquisition_state'] for r in rows) != Counter({
            'http_200': 200, 'redirect_deferred': 51, 'no_primary_response': 209}):
        raise ValueError('Historical totals or group ledger changed')
    rows.sort(key=lambda r: (TIERS.index(r['review_tier']), r['category'], r['id']))
    summary = Counter(r['review_tier'] for r in rows)
    held_groups = [{'containment_group': g, 'hold_reasons': held[g], 'hold_release_review_required': True,
                    'member_ids': [r['id'] for r in groups[g]],
                    'missing_http_200_ids': [r['id'] for r in groups[g] if r['acquisition_state'] != 'http_200'],
                    'retained_http_200_ids': [r['id'] for r in groups[g] if r['acquisition_state'] == 'http_200'],
                    'redirect_evidence_ids': [r['id'] for r in groups[g] if r['redirect_target_NOT_VERIFIED'] is not None],
                    'automatic_release': False} for g in sorted(held)]
    first = [r for r in rows if r['review_tier'] in TIERS[:2]]
    result = {'kind': 'historical_remaining_acquisition_review_NOT_RUN_SCOPE', 'manifest_sha256': MANIFEST,
              'historical_inventory_count': len(rows), 'historical_http_200': 200,
              'missing_http_200': 260, 'review_tiers': dict(summary),
              'by_category': {c: dict(Counter(r['review_tier'] for r in rows if r['category'] == c)) for c in COUNTS},
              'redirect_shapes': dict(Counter(r['redirect_shape_NOT_PERMISSION'] for r in rows if r['acquisition_state'] == 'redirect_deferred')),
              'initial_review_pool': len(first), 'initial_review_groups': len({r['containment_group'] for r in first}),
              'initial_review_by_category': dict(Counter(r['category'] for r in first)),
              'initial_pool_theoretical_cumulative_http_200_ceiling': 200 + len(first),
              'held_group_count': len(held_groups), 'reviewed_run_scope_generated': False,
              'publisher_rights_verified': False, 'automatic_hold_releases': 0, 'authorized_next_primary_requests': 0,
              'approved_for_advisor': False}
    return result, rows, held_groups


CSV_FIELDS = ('id', 'provider', 'category', 'url', 'acquisition_state', 'review_tier', 'containment_group',
              'hold_reasons', 'redirect_target_NOT_VERIFIED', 'redirect_shape_NOT_PERMISSION', 'lifecycle_quarantined',
              'group_hold_release_required', 'manifest_change_review_required', 'eligible_for_next_run',
              'reviewer', 'ownership_evidence_url', 'robots_and_policy_evidence', 'retention_review', 'review_note')


def write_review(out, report, rows, groups):
    if (out.exists() or any(p.is_symlink() for p in (out, *out.parents))
            or out.resolve().is_relative_to(Path(__file__).resolve().parents[1])):
        raise ValueError('Use a new private directory outside checkout')
    out.mkdir(mode=0o700)
    os.chmod(out, 0o700)
    for name, obj in [('report.json', report), ('inventory_review.json', rows), ('held_groups.json', groups)]:
        with (out / name).open('x', encoding='utf-8') as f:
            os.chmod(out / name, 0o600)
            json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
    with (out / 'gap_review_only.csv').open('x', encoding='utf-8', newline='') as f:
        os.chmod(out / 'gap_review_only.csv', 0o600)
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            if row['review_tier'] == TIERS[4]:
                continue
            values = {k: str(row.get(k) if row.get(k) is not None else '') for k in CSV_FIELDS}
            values['hold_reasons'] = '; '.join(row['hold_reasons'])
            writer.writerow({k: "'" + v if v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v
                             for k, v in values.items()})


def main():
    from scripts.consolidate_diagnostic_campaign import consolidate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    report, inventory, _ = consolidate(args.input_dir)
    result = build_review(report, inventory)
    write_review(args.out_dir, *result)
    print(json.dumps(result[0], sort_keys=True))


if __name__ == '__main__':
    main()
