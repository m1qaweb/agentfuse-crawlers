import scrapy
import pytest
from scrapy.http import HtmlResponse
from twisted.python.failure import Failure
from scrapy.exceptions import IgnoreRequest

from agentfuse_crawlers.spiders.official import PricingSpider

SOURCE = {'id': 'openai_api_pricing', 'provider': 'OpenAI',
          'category': 'pricing', 'url': 'https://developers.openai.com/api/docs/pricing'}


def response(body, status=200, url=None):
    return HtmlResponse(url=url or SOURCE['url'], status=status,
                        body=body.encode('utf-8'), encoding='utf-8',
                        headers={'Content-Type': 'text/html'})


def test_200_page_needs_real_content():
    spider = PricingSpider(source_ids='openai_api_pricing')
    short = list(spider.parse_page(response('<main><p>Short shell</p></main>'), SOURCE))[0]
    assert short['status'] == 'needs_review'
    real = list(spider.parse_page(response('<main><h1>Pricing</h1><p>' +
        ('Model pricing $1.50 input and $4.50 output per million tokens. ' * 20) + '</p></main>'), SOURCE))[0]
    assert real['status'] == 'captured'
    assert real['review_status'] == 'unverified'
    assert real['schema_version'] == '2.1'
    assert real['source_cohort'] == 'proven'
    assert real['content_sha256'] and real['word_count'] > 45


def test_access_denied_and_crossdomain_are_not_captured():
    spider = PricingSpider(source_ids='openai_api_pricing')
    blocked = list(spider.parse_page(response('<main>Verify you are human</main>'), SOURCE))[0]
    assert blocked['status'] == 'blocked'
    forbidden = list(spider.parse_page(response('Forbidden', status=403), SOURCE))[0]
    assert forbidden['status'] == 'http_error'
    external = list(spider.parse_page(response('anything', url='https://example.com/evil'), SOURCE))[0]
    assert external['status'] == 'rejected_redirect'


def test_robots_denial_is_recorded_as_failure():
    spider = PricingSpider(source_ids='openai_api_pricing')
    failure = Failure(IgnoreRequest('not allowed by robots'))
    failure.request = scrapy.Request(SOURCE['url'], cb_kwargs={'source': SOURCE})
    output = list(spider.record_failure(failure))[0]
    assert output['status'] == 'robots_or_policy_denied'
