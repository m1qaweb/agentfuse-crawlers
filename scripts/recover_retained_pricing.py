"""Recover bounded, review-only price observations from retained diagnostic Items."""
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

AMOUNT = r'\$((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)'
SHA = re.compile(r'[0-9a-f]{64}')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def rows(table):
    return [[cell['text'] for cell in row] for row in table['rows']]


def recover_item(item):
    """Never upgrade a raw display observation to a verified/comparable fact."""
    sid = item['source_id']
    text = item.get('text', '')
    tables = item.get('tables', [])
    sections = item.get('sections', [])
    result = []

    def add(label, kind, amount, unit, locator, raw, *, currency=None, context=None, state='numeric_candidate'):
        if amount is not None:
            amount = amount.replace(',', '')
        if amount is not None and not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', amount):
            raise ValueError('Invalid displayed decimal')
        blockers = ['independent_fact_review_required', 'publisher_reuse_review_required']
        if amount is not None and currency is None:
            blockers.append('missing_explicit_currency')
        if item.get('freshness_warnings') or item.get('error') == 'server_cached_response_over_one_day':
            blockers.append('freshness_review_required')
        if (context or {}).get('batch_selector_state') == 'unresolved':
            blockers.append('service_tier_unresolved')
        if (context or {}).get('schedule_review_required'):
            blockers.append('conditional_schedule_review_required')
        record = dict(source_id=sid, subject_label=label, charge_kind=kind,
                      displayed_amount_decimal=amount, displayed_symbol='$' if amount is not None else None,
                      currency=currency, billing_unit=unit, context=context or {}, price_state=state,
                      evidence_locator=locator, evidence_text=raw, evidence_sha256=digest(raw),
                      normalization_blockers=blockers, comparable_candidate=False,
                      approved_for_advisor=False, review_status='unverified')
        record['candidate_id'] = digest(record)
        result.append(record)

    if sid == 'xai_pricing' and tables and 'All prices are in USD.' in text and 'Prices per 1M tokens' in text:
        t = tables[0]
        rr = rows(t)
        headers = ['Model', 'Context'] + ['Short context'] * 3 + ['Long context'] * 3
        if t.get('heading_context') == 'Text API' and rr[:2] == [headers, ['Model', 'Context'] + ['Input', 'Cached', 'Output'] * 2]:
            for i, row in enumerate(rr[2:], 2):
                if len(row) != 8:
                    continue
                model = re.fullmatch(r'(grok-[\w.-]+) Long context ≥ ([0-9]+[kKmM]) tokens', row[0])
                if not model or not re.fullmatch(r'[0-9]+[kKmM]', row[1]):
                    continue
                for j in range(2, 8):
                    m = re.fullmatch(AMOUNT, row[j])
                    if m:
                        add(model[1], ['input', 'cached_input', 'output'][(j-2) % 3], m[1], 'per_1m_tokens',
                            {'table_id': t['table_id'], 'row_index': i, 'column_index': j},
                            {'row': row, 'headers': rr[:2], 'currency_declaration': 'All prices are in USD.',
                             'unit_declaration': 'Prices per 1M tokens'}, currency='USD',
                            context={'context_band': headers[j], 'long_context_threshold': model[2], 'maximum_context': row[1], 'region': None})
    elif sid == 'deepseek_pricing' and 'Model prices are listed per 1M tokens.' in text:
        header = re.search(r'^\| MODEL \| (deepseek-[\w.-]+)(?:\(\d+\))? \| (deepseek-[\w.-]+)\s*$', text, re.M)
        schedule = re.search(r'^\(2\) Off-peak rates[^\n]+$', text, re.M)
        block = re.search(r'^\| PRICING\(2\) \| (.*?)(?=^\| Concurrency Limit)', text, re.M | re.S)
        if header and schedule and block:
            pattern = (r'(?:^|^\| )1M (INPUT TOKENS\s*\(CACHE (?:HIT|MISS)\)|OUTPUT TOKENS)'
                       r' \| OFF-PEAK \| ' + AMOUNT + r' \| ' + AMOUNT + r'\n\| PEAK \| ' + AMOUNT + r' \| ' + AMOUNT + r'$')
            for m in re.finditer(pattern, block[1], re.M):
                kind = 'cached_input' if 'HIT' in m[1] else 'input' if 'MISS' in m[1] else 'output'
                for model_index, label in enumerate(header.groups()):
                    for tier, offset in [('off_peak', 2), ('peak', 4)]:
                        add(label, kind, m[offset + model_index], 'per_1m_tokens',
                            {'field': 'text', 'start': block.start(1)+m.start(), 'end': block.start(1)+m.end()},
                            {'model_header': header[0], 'rate_block': m[0], 'schedule': schedule[0]},
                            context={'time_tier': tier, 'schedule_review_required': True})
    elif sid == 'together_ai_pricing' and tables:
        t = tables[0]
        # Header and exact matching row must be present in the flattened evidence;
        # the batch toggle's state is not preserved, so no service tier is asserted.
        h = re.search(r'Price per 1M tokens\s+Batch API price\s+\|\s+Model\s+\|\s+Input\s+\|\s+output\s+\|', text)
        if h and t.get('heading_context') == 'Serverless Inference':
            # The first table is anchored immediately after its header; stop
            # at the first mismatch rather than borrowing a row from a later tab.
            visible = ' '.join(text[h.end():].split()).split(' | ')
            for i, row in enumerate(rows(t)):
                if len(row) != 3 or not row[0] or len(row[0]) > 160:
                    continue
                rendered = [' '.join(cell.split()) for cell in row]
                if visible[3*i:3*i+3] != rendered:
                    break
                raw = {'header': h[0], 'row': row}
                ctx = {'service': 'Serverless Inference', 'batch_selector_state': 'unresolved'}
                a = re.fullmatch(AMOUNT + r'(?:\s+' + AMOUNT + r'\s*\(cached\))?', row[1])
                b = re.fullmatch(AMOUNT + r'\s*\(cached\)', row[1])
                output = re.fullmatch(AMOUNT, row[2])
                for kind, value, col in [('input', a[1] if a else None, 1),
                                         ('cached_input', a[2] if a and a[2] else b[1] if b else None, 1),
                                         ('output', output[1] if output else None, 2)]:
                    if value is not None:
                        add(row[0], kind, value, 'per_1m_tokens', {'table_id': t['table_id'], 'row_index': i, 'column_index': col}, raw, context=ctx)
    elif sid == 'replit_pricing':
        for m in re.finditer(r'^(Core|Pro)\n' + AMOUNT + r' ' + AMOUNT + r' / month, billed annually$', text, re.M):
            add(m[1], 'subscription', m[3], 'per_month', {'field': 'text', 'start': m.start(), 'end': m.end()}, m[0], context={'billing_commitment': 'annual'})
    elif sid in {'hyper3d_rodin_pricing', 'apify_pricing', 'weaviate_pricing'}:
        for i, s in enumerate(sections):
            label, excerpt = s['heading'], s['excerpt']
            if not excerpt.startswith(label+'\n') or s.get('excerpt_truncated'):
                continue
            locator = {'section_id': s['section_id'], 'section_index': i}
            if sid == 'hyper3d_rodin_pricing' and label in {'Creator', 'Business'}:
                m = re.search(r'Billed monthly - '+AMOUNT+r' / month\. Billed yearly - '+AMOUNT+r' today\.', excerpt)
                if m:
                    for n, unit, commitment in [(1, 'per_month', 'monthly'), (2, 'per_year', 'annual')]:
                        add(label, 'subscription', m[n], unit, locator, {'heading': label, 'billing': m[0]}, context={'billing_commitment': commitment})
            if sid == 'hyper3d_rodin_pricing' and label == 'Free':
                m = re.search(r'Direct credits cost '+AMOUNT+r' per credit\.', excerpt)
                if m:
                    add(label, 'credit_purchase', m[1], 'per_credit', locator, {'heading': label, 'billing': m[0]})
            if sid == 'apify_pricing' and label in {'Starter', 'Scale', 'Business'}:
                m = re.match(re.escape(label)+r'\n'+AMOUNT+r'\n/ month \+ pay as you go\n', excerpt)
                if m:
                    add(label, 'subscription', m[1], 'per_month', locator, m[0], context={'additional_usage_charges': True})
            if sid == 'apify_pricing' and label in {'Free', 'Starter', 'Scale', 'Business'}:
                m = re.search(r'^'+AMOUNT+r' per compute unit$', excerpt, re.M)
                if m:
                    add(label, 'compute_usage', m[1], 'per_compute_unit', locator, {'heading': label, 'billing': m[0]})
            if sid == 'weaviate_pricing' and label == 'Premium' and '\nContact Sales\n' in excerpt:
                add(label, 'contract_offer', None, None, locator, {'heading': label, 'offer': 'Contact Sales'}, state='contact_sales')
    elif sid == 'perplexity_pricing':
        for t in tables:
            rr = rows(t)
            if not rr:
                continue
            context = t.get('heading_context')
            if context == 'View Agent API Model Pricing > Tool Pricing' and rr[0] == ['Tool', 'Price', 'Description']:
                for i, row in enumerate(rr[1:], 1):
                    if len(row) != 3:
                        continue
                    m = re.fullmatch(AMOUNT+r' per (invocation|successful invocation|20-minute block)', row[1])
                    if m:
                        unit = {'invocation':'per_invocation', 'successful invocation':'per_successful_invocation', '20-minute block':'per_20_minute_block'}[m[2]]
                        add(row[0], 'tool_usage', m[1], unit, {'table_id':t['table_id'], 'row_index':i, 'column_index':1}, {'heading':context, 'row':row}, context={'service':'Agent API'})
            if context == 'Search API Pricing' and rr[0] == ['API', 'Price per 1K requests', 'Description']:
                for i, row in enumerate(rr[1:], 1):
                    if len(row) != 3:
                        continue
                    m = re.fullmatch(AMOUNT, row[1])
                    if m:
                        add(row[0], 'api_usage', m[1], 'per_1k_requests', {'table_id':t['table_id'], 'row_index':i, 'column_index':1}, {'heading':context, 'header':rr[0], 'row':row}, context={'service':'Search API', 'successful_requests_review_required':True})
    return result


def recover(observations):
    candidates, coverage = [], []
    seen = set()
    for entry in observations:
        item, evidence = entry['item'], entry['evidence']
        if item.get('category') != 'pricing' or item.get('http_status') != 200:
            continue
        sid = item['source_id']
        if (sid in seen or entry.get('source_id') != sid or entry.get('approved_for_advisor') is not False
                or item.get('approved_for_advisor') is not False or item.get('review_status') != 'unverified'
                or evidence.get('http_status') != 200 or evidence.get('job_id') != item.get('zyte_job_id')
                or any(not SHA.fullmatch(str(evidence.get(k, ''))) for k in ['items_sha256','requests_sha256'])):
            raise ValueError('Invalid or duplicate historical pricing evidence')
        seen.add(sid)
        rr = recover_item(item)
        for record in rr:
            record.update(source_url=item['source_url'], observed_at_utc=item['fetched_at_utc'], primary_evidence=evidence)
        candidates.extend(rr)
        coverage.append({'source_id':sid, 'original_error':item.get('error'), 'candidate_count':len(rr),
                         'state':'review_candidates' if rr else 'unresolved', 'approved_for_advisor':False})
    if len({x['candidate_id'] for x in candidates}) != len(candidates):
        raise ValueError('Duplicate recovered candidate identity')
    report = {'kind':'retained_price_recovery_NOT_VERIFIED', 'source_count':len(coverage),
              'sources_with_candidates':sum(bool(x['candidate_count']) for x in coverage), 'candidate_count':len(candidates),
              'candidates_with_explicit_currency':sum(x['currency'] is not None for x in candidates),
              'charge_kinds':dict(Counter(x['charge_kind'] for x in candidates)),
              'coverage':coverage, 'approved_for_advisor':False, 'independently_verified_facts':0}
    return report, candidates


def main():
    from scripts.consolidate_diagnostic_campaign import consolidate, write_private
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    _, _, observations = consolidate(args.input_dir)
    report, candidates = recover(observations)
    # Reuse the existing create-only, private, outside-repository writer.
    write_private(args.out_dir, report, report['coverage'], candidates)
    print(json.dumps({k:v for k,v in report.items() if k != 'coverage'}, sort_keys=True))


if __name__ == '__main__':
    main()
