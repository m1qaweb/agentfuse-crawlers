"""Bounded review-only interpretation of the observed DeepSeek token matrix."""
import re

SOURCE = 'deepseek_pricing'
URL = 'https://api-docs.deepseek.com/quick_start/pricing/'
MODEL = re.compile(r'(deepseek-[a-z0-9][a-z0-9.-]{0,79})(?:\s*\([0-9]{1,2}\))?')
PRICE = re.compile(r'\$\s*[0-9]{1,8}(?:\.[0-9]{1,8})?')
RATE_ROWS = (
    ('1M INPUT TOKENS (CACHE HIT)', 'OFF-PEAK', 'cached_input'),
    ('1M INPUT TOKENS (CACHE HIT)', 'PEAK', 'cached_input'),
    ('1M INPUT TOKENS (CACHE MISS)', 'OFF-PEAK', 'input'),
    ('1M INPUT TOKENS (CACHE MISS)', 'PEAK', 'input'),
    ('1M OUTPUT TOKENS', 'OFF-PEAK', 'output'),
    ('1M OUTPUT TOKENS', 'PEAK', 'output'),
)


def _text(cell):
    return ' '.join(cell['text'].replace('\u200b', '').split())


def deepseek_rate_contexts(matrix, *, source_id, source_url, heading_context, clipped):
    """Bind literal rate rows to model columns, or reject the entire layout.

    The grid must be span-expanded by the existing HTML table reader. No
    guessed schedules, currency, model versions or inferred missing cells.
    """
    if (source_id != SOURCE or source_url != URL or clipped or not matrix
            or heading_context.replace('\u200b', '').strip() != 'Model Details'):
        return {}
    header = matrix[0]
    if len(header) != 5 or [_text(c) for c in header[:3]] != ['MODEL'] * 3:
        return {}
    if any((c['origin_row'], c['origin_col']) != (0, 0) for c in header[:3]):
        return {}
    models = []
    for col in (3, 4):
        c = header[col]
        raw = _text(c)
        match = MODEL.fullmatch(raw)
        if not match or (c['origin_row'], c['origin_col']) != (0, col):
            return {}
        models.append((match[1], raw))
    if models[0][0] == models[1][0]:
        return {}
    rate_rows = [(i, row) for i, row in enumerate(matrix[1:], 1)
                 if row and re.fullmatch(r'PRICING(?:\s*\([0-9]{1,2}\))?', _text(row[0]))]
    if len(rate_rows) != len(RATE_ROWS):
        return {}
    start = rate_rows[0][0]
    output = {}
    for offset, ((i, row), (label, band, dimension)) in enumerate(zip(rate_rows, RATE_ROWS)):
        if (i != start + offset or len(row) != 5
                or [_text(c) for c in row[1:3]] != [label, band]
                or _text(row[0]) != _text(rate_rows[0][1][0])
                or (row[0]['origin_row'], row[0]['origin_col']) != (start, 0)
                or (row[1]['origin_row'], row[1]['origin_col']) != (i - offset % 2, 1)
                or (row[2]['origin_row'], row[2]['origin_col']) != (i, 2)):
            return {}
        for col, (model, raw_model) in zip((3, 4), models):
            cell = row[col]
            if ((cell['origin_row'], cell['origin_col']) != (i, col)
                    or not PRICE.fullmatch(_text(cell))):
                return {}
            output[(i, col)] = {
                'model': model, 'model_header': raw_model,
                'rate_label': ' | '.join(_text(c) for c in row[:3]),
                'price_dimension': dimension, 'billing_unit': 'per_1m_tokens',
                'billing_time_band_candidate': band.lower(),
            }
    return output
