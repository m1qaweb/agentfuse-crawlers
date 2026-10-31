"""Combined-branch regression: release and pricing extractors must coexist."""

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.extensions.coverage import _comparable
from scripts.compare_exports import _healthy


def test_both_extractors_are_registered_without_cross_contamination():
    pricing = extract_evidence(
        '<html><body><main><h2>Region: Global</h2>'
        '<h3>Tier: Standard</h3><table><caption>USD per 1M tokens</caption>'
        '<thead><tr><th>Model</th><th>Input price</th>'
        '<th>Output price</th></tr></thead><tbody>'
        '<tr><th>Model Alpha</th><td>$1.50</td>'
        '<td>$4.50</td></tr></tbody>'
        '</table></main></body></html>',
        'https://developers.openai.com/api/docs/pricing',
        category='pricing', source_id='openai_api_pricing',
    )
    changelog = extract_evidence(
        '<html><body><main><h2>October, 2026</h2><p>Oct 30</p>'
        '<h3>Improved tools</h3><p>Better integration support.</p>'
        '</main></body></html>',
        'https://official.example/changelog',
        category='changelog', source_id='openai_api_changelog',
    )
    assert pricing['pricing_evidence_schema'] == '1.0'
    assert pricing['pricing_comparable_candidate_count'] == 2
    assert 'release_events_schema' not in pricing
    assert changelog['release_events_schema'] == '1.1'
    assert 'pricing_evidence_schema' not in changelog
    assert changelog['release_event_count'] >= 1


def test_typed_quality_guards_do_not_override_each_other():
    p = {'category': 'pricing', 'status': 'captured', 'content_sha256': 'p',
         'pricing_evidence_schema': '1.0', 'pricing_inventory_complete': True,
         'pricing_comparable_candidate_count': 1,
         'pricing_evidence_lost_to_item_budget': False}
    c = {'category': 'changelog', 'status': 'captured', 'content_sha256': 'c',
         'release_events_schema': '1.1', 'release_window_complete': True,
         'release_event_evidence_lost': False,
         'release_event_identity_collision': False,
         'release_recent_body_loss_count': 0}
    assert _healthy(p) and _comparable(p)
    assert _healthy(c) and _comparable(c)
    assert not _healthy(dict(p, pricing_inventory_complete=False))
    assert not _healthy(dict(c, release_window_complete=False))
