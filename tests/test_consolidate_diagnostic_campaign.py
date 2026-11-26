import hashlib
import json

import pytest

from scripts import consolidate_diagnostic_campaign as c


def fixture():
    manifest = [{'id': 'sample_docs', 'provider': 'Synthetic', 'category': 'documentation',
                 'url': 'https://example.com/docs'}]
    job, scope = '1/2/3', 'a' * 64
    row = {'source_id': 'sample_docs', 'provider': 'Synthetic', 'category': 'documentation',
           'source_url': manifest[0]['url'], 'zyte_job_id': job, 'deployment_revision': c.BASE,
           'deployment_revision_kind': 'package_py_json_sha256_v1', 'manifest_sha256': c.MANIFEST,
           'source_registry_sha256': c.REGISTRY, 'selection_ids_sha256': c.digest(['sample_docs']),
           'selection_source_count': 1, 'public_diagnostic_scope_sha256': scope, 'spider_name': 'official_documentation',
           'validation_scope': 'public_diagnostic', 'collection_mode': 'validation', 'requested_cohort': 'all',
           'run_scope_explicit': True, 'approved_for_advisor': False, 'review_status': 'unverified',
           'public_diagnostic_publisher_rights_independently_verified': False,
           'public_diagnostic_source_in_scope': True, 'run_started_at_utc': '2026-11-25T00:00:00Z', 'http_status': 200}
    requests = [{'url': 'https://example.com/robots.txt', 'method': 'GET', 'status': 404},
                {'url': manifest[0]['url'], 'method': 'GET', 'status': 200}]
    stats = {'agentfuse/run/zyte_job_id': job, 'agentfuse/run/deployment_revision': c.BASE,
             'item_scraped_count': 1, 'downloader/request_count': 2, 'downloader/response_count': 2,
             'robotstxt/request_count': 1, 'finish_reason': 'finished'}
    logs = [{'message': 'Dumping Scrapy stats:\n' + repr(stats)}, {'message': '[scrapy.core.engine] Spider closed (finished)'}]
    return [[row], requests, logs, manifest, {'sample_docs'}, job, c.BASE, scope, 'documentation']


def test_reconcile_counts_robots_separately():
    indexed, primary, report = c.reconcile_job(*fixture())
    assert set(indexed) == {'sample_docs'}
    assert primary == {'sample_docs': 1}
    assert report['http_200'] == report['primary'] == report['robots'] == 1


@pytest.mark.parametrize('mutation', ['approval', 'rights', 'scope', 'package', 'duplicate_item',
                                     'duplicate_request', 'unexpected_url', 'status', 'missing_request', 'logs'])
def test_rejects_inconsistent_evidence(mutation):
    args = fixture()
    row = args[0][0]
    if mutation == 'approval':
        row['approved_for_advisor'] = True
    elif mutation == 'rights':
        row['public_diagnostic_publisher_rights_independently_verified'] = True
    elif mutation == 'scope':
        row['public_diagnostic_source_in_scope'] = False
    elif mutation == 'package':
        row['deployment_revision'] = 'b' * 64
    elif mutation == 'duplicate_item':
        args[0].append(row.copy())
    elif mutation == 'duplicate_request':
        args[1].append(args[1][1].copy())
    elif mutation == 'unexpected_url':
        args[1][1]['url'] = 'https://example.com/unreviewed'
    elif mutation == 'status':
        args[1][1]['status'] = 307
    elif mutation == 'missing_request':
        args[1].pop()
    elif mutation == 'logs':
        args[2].pop()
    with pytest.raises(ValueError):
        c.reconcile_job(*args)


def test_raw_digest_and_duplicate_keys(tmp_path):
    path = tmp_path / 'items.json'
    raw = b'[{"a": 1}]'
    path.write_bytes(raw)
    assert c.read_export(path, hashlib.sha256(raw).hexdigest()) == [{'a': 1}]
    with pytest.raises(ValueError, match='digest mismatch'):
        c.read_export(path, '0' * 64)
    raw = b'[{"a": 1, "a": 2}]'
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='Duplicate JSON key'):
        c.read_export(path, hashlib.sha256(raw).hexdigest())


def test_private_output_is_create_only(tmp_path):
    out = tmp_path / 'out'
    c.write_private(out, {'approved_for_advisor': False}, [], [])
    assert json.loads((out / 'report.json').read_text()) == {'approved_for_advisor': False}
    assert (out.stat().st_mode & 0o777) == 0o700
    assert ((out / 'report.json').stat().st_mode & 0o777) == 0o600
    with pytest.raises(ValueError):
        c.write_private(out, {}, [], [])


def test_full_synthetic_continuation_preserves_previous_capture(monkeypatch):
    # Real packaged source identity, entirely synthetic rows and logs.
    manifest = json.loads((c.DATA / 'sources.json').read_text())
    base = json.loads((c.DATA / 'public_diagnostic_scope.json').read_text())
    resume = json.loads((c.DATA / 'public_diagnostic_resume.json').read_text())
    sid = next(s['id'] for s in manifest if s['category'] == 'documentation'
               and s['id'] in base['source_ids'] and s['id'] not in resume['source_ids'])
    fake = {}
    for suffix, category, job, rev, scope, hashes in c.JOBS:
        eligible = set(resume['source_ids'] if rev == c.RESUME else base['source_ids'])
        rows, primary = {}, {}
        for index, source in enumerate(s for s in manifest if s['category'] == category):
            source_id = source['id']
            row = {'validation_containment_group': source_id, 'public_diagnostic_source_in_scope': source_id in eligible,
                   'status': 'source_bulk_validation_not_approved', 'http_status': None, 'fetched_at_utc': job}
            if source_id == sid and rev == c.BASE:
                row.update(status='captured', http_status=200, provider=source['provider'],
                           quality_axes={'content_capture_status': 'text_observed_unverified'})
                primary[source_id] = 0
            rows[source_id] = (index, row)
        fake[job] = rows, primary, {'job_id': job, 'requests': len(primary), 'robots': 0}
    monkeypatch.setattr(c, 'read_export', lambda *args: [])
    monkeypatch.setattr(c, 'reconcile_job', lambda items, requests, logs, manifest, eligible, job, *args: fake[job])
    report, inventory, observations = c.consolidate(c.DATA)
    record = next(x for x in inventory if x['id'] == sid)
    assert record['acquisition_state'] == 'http_200'
    assert record['primary_evidence']['job_id'] == '883514/2/40'
    assert record['latest_accounting']['job_id'] == '883514/2/43'
    assert record['latest_accounting']['http_status'] is None
    assert len(observations) == report['totals']['http_200'] == 1
    assert report['totals']['inventory'] == 460
