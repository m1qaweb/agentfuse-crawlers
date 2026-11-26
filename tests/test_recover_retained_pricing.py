import pytest

from scripts.recover_retained_pricing import recover, recover_item


def table(heading, values):
    return {'table_id':'table-1', 'heading_context':heading,
            'rows':[[{'text':cell} for cell in row] for row in values]}


def section(label, excerpt):
    return {'heading':label, 'section_id':label, 'excerpt':label+'\n'+excerpt, 'excerpt_truncated':False}


def item(sid, text='', tables=(), sections=(), **extra):
    return dict(source_id=sid, text=text, tables=list(tables), sections=list(sections), **extra)


def test_xai_context_and_currency():
    t = table('Text API', [['Model','Context']+['Short context']*3+['Long context']*3,
                           ['Model','Context']+['Input','Cached','Output']*2,
                           ['grok-test Long context ≥ 100k tokens','500k','$1','$2','$3','$4','$5','$6']])
    rr = recover_item(item('xai_pricing','All prices are in USD.\nPrices per 1M tokens',[t]))
    assert len(rr) == 6
    assert rr[1]['charge_kind'] == 'cached_input'
    assert rr[3]['context']['context_band'] == 'Long context'
    assert rr[3]['context']['long_context_threshold'] == '100k'
    assert all(x['currency'] == 'USD' and not x['comparable_candidate'] for x in rr)
    assert not recover_item(item('xai_pricing','Prices per 1M tokens',[t]))


def test_deepseek_transposed_explicit_tiers_not_inferred_currency():
    text = ('Model prices are listed per 1M tokens.\n| MODEL | deepseek-test(1) | deepseek-other\n'
            '| PRICING(2) | 1M INPUT TOKENS\n(CACHE HIT) | OFF-PEAK | $1 | $2\n'
            '| PEAK | $3 | $4\n| Concurrency Limit\n(2) Off-peak rates are conditional.')
    rr = recover_item(item('deepseek_pricing',text))
    assert [(x['subject_label'],x['displayed_amount_decimal'],x['context']['time_tier']) for x in rr] == [
        ('deepseek-test','1','off_peak'),('deepseek-test','3','peak'),
        ('deepseek-other','2','off_peak'),('deepseek-other','4','peak')]
    assert all(x['currency'] is None and 'missing_explicit_currency' in x['normalization_blockers'] for x in rr)
    assert not recover_item(item('deepseek_pricing',text.replace('(2) Off-peak rates','No schedule')))


def test_together_cached_only_and_mixed_component_scope():
    t = table('Serverless Inference',[['Model A','$1 $0.25 (cached)','$2'],['Model B','$0.1 (cached)','$3']])
    text = ('Price per 1M tokens\nBatch API price\n|\nModel\n|\nInput\n|\noutput\n|\n'
            'Model A\n|\n$1 $0.25 (cached)\n|\n$2\n|\nModel B\n|\n$0.1 (cached)\n|\n$3')
    rr = recover_item(item('together_ai_pricing',text,[t]))
    assert [x['charge_kind'] for x in rr] == ['input','cached_input','output','cached_input','output']
    assert all('service_tier_unresolved' in x['normalization_blockers'] for x in rr)
    assert not recover_item(item('together_ai_pricing',text.replace('Model A\n|','Different\n|',1),[t]))


def test_replit_only_explicit_annual_price():
    rr = recover_item(item('replit_pricing','Core\n$30 $25 / month, billed annually\n$30 included credits'))
    assert len(rr) == 1 and rr[0]['displayed_amount_decimal'] == '25'
    assert rr[0]['context']['billing_commitment'] == 'annual'
    assert rr[0]['currency'] is None


def test_hyper3d_annual_total_and_credit_separated():
    rr = recover_item(item('hyper3d_rodin_pricing',sections=[section('Free','Direct credits cost $2 per credit.'),
                     section('Business','Billed monthly - $200 / month. Billed yearly - $2,000 today.')]))
    assert [(x['charge_kind'],x['billing_unit'],x['displayed_amount_decimal']) for x in rr] == [
        ('credit_purchase','per_credit','2'),('subscription','per_month','200'),('subscription','per_year','2000')]


def test_apify_included_credit_is_not_subscription():
    rr = recover_item(item('apify_pricing',sections=[section('Starter','$10\n/ month + pay as you go\n$5\n$0.5 per compute unit')]))
    assert [(x['charge_kind'],x['displayed_amount_decimal']) for x in rr] == [('subscription','10'),('compute_usage','0.5')]
    assert not recover_item(item('apify_pricing',sections=[section('Starter','$5 included credit')]))


def test_perplexity_distinct_units():
    a = table('View Agent API Model Pricing > Tool Pricing',[['Tool','Price','Description'],['fetch','$0.01 per invocation','Example: $10'],['sandbox','$0.02 per 20-minute block','']])
    b = table('Search API Pricing',[['API','Price per 1K requests','Description'],['Search','$5','']])
    rr = recover_item(item('perplexity_pricing',tables=[a,b]))
    assert [x['billing_unit'] for x in rr] == ['per_invocation','per_20_minute_block','per_1k_requests']


def test_weaviate_contact_sales_is_nonnumeric():
    rr = recover_item(item('weaviate_pricing',sections=[section('Premium','Prepaid contract\nContact Sales\nMore information')]))
    assert len(rr) == 1 and rr[0]['displayed_amount_decimal'] is None and rr[0]['price_state'] == 'contact_sales'
    assert rr[0]['charge_kind'] == 'contract_offer'


def test_no_unscoped_fallback_and_truncated_section():
    assert not recover_item(item('unknown_pricing','Pricing $1 / month'))
    s = section('Business','Billed monthly - $200 / month. Billed yearly - $2,000 today.')
    s['excerpt_truncated'] = True
    assert not recover_item(item('hyper3d_rodin_pricing',sections=[s]))


def test_stale_capture_remains_blocked():
    rr = recover_item(item('replit_pricing','Core\n$30 $25 / month, billed annually',freshness_warnings=['stale']))
    assert 'freshness_review_required' in rr[0]['normalization_blockers']
    assert rr[0]['approved_for_advisor'] is False


def entry():
    i = item('replit_pricing','Core\n$30 $25 / month, billed annually',category='pricing',http_status=200,
             review_status='unverified',approved_for_advisor=False,zyte_job_id='1/2/3',source_url='https://example.com/pricing',fetched_at_utc='2026-11-25T00:00:00Z')
    return {'source_id':i['source_id'],'item':i,'approved_for_advisor':False,'evidence':{'http_status':200,'job_id':'1/2/3','items_sha256':'a'*64,'requests_sha256':'b'*64}}


def test_provenance_and_coverage():
    e = entry()
    report, rr = recover([e])
    assert report['candidate_count'] == report['sources_with_candidates'] == 1
    assert report['independently_verified_facts'] == 0
    assert rr[0]['primary_evidence'] == e['evidence']
    assert rr[0]['observed_at_utc'] == e['item']['fetched_at_utc']


@pytest.mark.parametrize('mutation',['approved','wrong_job','digest','duplicate'])
def test_reject_bad_provenance(mutation):
    e = entry()
    if mutation == 'approved':
        e['approved_for_advisor'] = True
    elif mutation == 'wrong_job':
        e['evidence']['job_id'] = '2/3/4'
    elif mutation == 'digest':
        e['evidence']['items_sha256'] = 'not-a-digest'
    with pytest.raises(ValueError):
        recover([e,e] if mutation == 'duplicate' else [e])
