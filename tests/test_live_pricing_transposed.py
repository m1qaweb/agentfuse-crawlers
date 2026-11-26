"""Synthetic HTML regression for the live span-expanded pricing extractor."""
from lxml import html
import pytest

from agentfuse_crawlers.pricing_evidence import extract_pricing_evidence
from agentfuse_crawlers.pricing_transposed import SOURCE, URL


def page():
    return """<main><h2>Model Details</h2><table>
        <tr><td colspan="3">MODEL</td><td>deepseek-example-a (1)</td><td>deepseek-example-b</td></tr>
        <tr><td colspan="5">Synthetic model description</td></tr>
        <tr><td rowspan="6">PRICING (2)</td><td rowspan="2">1M INPUT TOKENS (CACHE HIT)</td>
        <td>OFF-PEAK</td><td>$0.123</td><td>$0.456</td></tr>
        <tr><td>PEAK</td><td>$0.234</td><td>$0.567</td></tr>
        <tr><td rowspan="2">1M INPUT TOKENS (CACHE MISS)</td><td>OFF-PEAK</td><td>$0.345</td><td>$0.678</td></tr>
        <tr><td>PEAK</td><td>$0.456</td><td>$0.789</td></tr>
        <tr><td rowspan="2">1M OUTPUT TOKENS</td><td>OFF-PEAK</td><td>$0.567</td><td>$0.890</td></tr>
        <tr><td>PEAK</td><td>$0.678</td><td>$0.901</td></tr>
        </table><p>Billing schedule requires independent review.</p></main>"""


def test_live_transposed_matrix_preserves_context_and_blocks_comparison():
    data = extract_pricing_evidence(html.fromstring(page()), URL, SOURCE)
    rates = [r for r in data['pricing_observations'] if r.get('billing_time_band_candidate')]
    assert len(rates) == 12 and len({r['observation_id'] for r in rates}) == 12
    assert data['pricing_parser_revision'] == 'evidence_quote_v7_deepseek_transposed_context'
    expected = {(model, dimension, band)
                for model in ('deepseek-example-a', 'deepseek-example-b')
                for dimension in ('cached_input', 'input', 'output')
                for band in ('peak', 'off-peak')}
    assert {(r['model_or_service'], r['price_dimension'], r['billing_time_band_candidate']) for r in rates} == expected
    assert all(r['billing_unit'] == 'per_1m_tokens' and r['currency'] is None for r in rates)
    assert all(r['review_status'] == 'unverified' and not r['approved_for_advisor'] for r in rates)
    assert all(not r['comparable_candidate'] and not r['review_quote_candidate']
               and r['normalized_amount_decimal'] is None for r in rates)
    assert all('peak_off_peak_schedule_requires_review' in r['normalization_blockers'] for r in rates)
    first = next(r for r in rates if r['row_index'] == 2 and r['column_index'] == 3)
    assert first['column_label'] == 'deepseek-example-a (1)'
    assert first['row_label'] == 'PRICING (2) | 1M INPUT TOKENS (CACHE HIT) | OFF-PEAK'
    assert first['observed_single_amount_decimal'] == '0.123'


@pytest.mark.parametrize('source,url,markup', [
    ('other_pricing', URL, page()),
    (SOURCE, URL+'different', page()),
    (SOURCE, URL, page().replace('OFF-PEAK', 'INTRODUCTORY')),
])
def test_unrecognized_scope_or_layout_does_not_rebind_generic_rates(source, url, markup):
    data = extract_pricing_evidence(html.fromstring(markup), url, source)
    assert all('billing_time_band_candidate' not in r for r in data['pricing_observations'])
