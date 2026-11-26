import copy

import pytest
from agentfuse_crawlers.pricing_transposed import deepseek_rate_contexts, SOURCE, URL


def cell(text, row, col):
    return {'text': text, 'origin_row': row, 'origin_col': col}


def fixture():
    header = [cell('MODEL', 0, 0)] * 3 + [cell('deepseek-example-a (1)', 0, 3), cell('deepseek-example-b', 0, 4)]
    grid = [header, [cell('FEATURES', 1, 0)]]
    for i, (label, band) in enumerate([
        ('1M INPUT TOKENS (CACHE HIT)', 'OFF-PEAK'),
        ('1M INPUT TOKENS (CACHE HIT)', 'PEAK'),
        ('1M INPUT TOKENS (CACHE MISS)', 'OFF-PEAK'),
        ('1M INPUT TOKENS (CACHE MISS)', 'PEAK'),
        ('1M OUTPUT TOKENS', 'OFF-PEAK'),
        ('1M OUTPUT TOKENS', 'PEAK'),
    ], 2):
        grid.append([cell('PRICING (2)', 2, 0), cell(label, i-(i-2)%2, 1), cell(band, i, 2),
                     cell('$0.123', i, 3), cell('$0.456', i, 4)])
    return grid


def extract(grid, **kwargs):
    return deepseek_rate_contexts(grid, **({'source_id': SOURCE, 'source_url': URL,
        'heading_context': 'Model Details\u200b', 'clipped': False} | kwargs))


def test_recovers_twelve_exact_model_dimension_band_bindings():
    result = extract(fixture())
    assert len(result) == 12
    assert result[(2, 3)] == {'model': 'deepseek-example-a', 'model_header': 'deepseek-example-a (1)',
        'rate_label': 'PRICING (2) | 1M INPUT TOKENS (CACHE HIT) | OFF-PEAK', 'price_dimension': 'cached_input',
        'billing_unit': 'per_1m_tokens', 'billing_time_band_candidate': 'off-peak'}
    assert result[(5, 4)]['price_dimension'] == 'input'
    assert result[(7, 4)]['price_dimension'] == 'output'
    assert result[(7, 4)]['billing_time_band_candidate'] == 'peak'
    assert result[(7, 4)]['model'] == 'deepseek-example-b'


@pytest.mark.parametrize('change', ['wrong_source', 'wrong_url', 'wrong_heading', 'clipped', 'duplicate_model',
    'wrong_unit', 'swapped_band', 'amount_span', 'price_qualifier', 'missing_row', 'unbound_model',
    'unbound_dimension', 'unbound_pricing_group', 'extra_row', 'unrelated_amount'])
def test_rejects_ambiguous_or_incomplete_layout(change):
    grid, kwargs = copy.deepcopy(fixture()), {}
    if change == 'wrong_source': kwargs['source_id'] = 'other_pricing'
    if change == 'wrong_url': kwargs['source_url'] = URL + 'other'
    if change == 'wrong_heading': kwargs['heading_context'] = 'Other products'
    if change == 'clipped': kwargs['clipped'] = True
    if change == 'duplicate_model': grid[0][4]['text'] = 'deepseek-example-a'
    if change == 'wrong_unit': grid[2][1]['text'] = '1000 TOKENS'
    if change == 'swapped_band': grid[3][2]['text'] = 'OFF-PEAK'
    if change == 'amount_span': grid[3][3]['origin_row'] = 2
    if change == 'price_qualifier': grid[4][3]['text'] = 'from $0.123'
    if change == 'missing_row': del grid[3]
    if change == 'unbound_model': grid[0][4]['origin_col'] = 3
    if change == 'unbound_dimension': grid[3][1]['origin_row'] = 3
    if change == 'unbound_pricing_group': grid[4][0]['origin_row'] = 4
    if change == 'extra_row': grid.append(copy.deepcopy(grid[-1]))
    if change == 'unrelated_amount': grid[2][3]['text'] = '$0.12 / hour'
    assert extract(grid, **kwargs) == {}
