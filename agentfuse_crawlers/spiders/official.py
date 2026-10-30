"""Read-only official-source spiders, with safe source cohorts and evidence output."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

import scrapy

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.sources import (
    load_proven_source_ids,
    load_sources,
    select_sources,
)

ALLOWED_HOSTS = sorted({urlsplit(s['url']).hostname for s in load_sources()})
PROVEN_IDS = load_proven_source_ids()
MAX_TEXT_CHARS = 250_000
MIN_WORDS = 45
BLOCK_MARKERS = (
    'verify you are human', 'checking your browser before accessing',
    'enable javascript and cookies', 'access denied', 'captcha challenge',
    'just a moment... cloudflare',
)
JS_SHELL_MARKERS = ('enable javascript to view this', 'this app requires javascript',
                    'you need to enable javascript to run this app')


class OfficialBaseSpider(scrapy.Spider):
    category = None
    allowed_domains = ALLOWED_HOSTS

    def __init__(self, cohort='all', source_ids=None, limit=None, **kwargs):
        super().__init__(**kwargs)
        # Fail closed on unknown IDs. Spider args cannot add new target URLs.
        self.selected = select_sources(self.category, cohort, source_ids, limit)
        self.cohort = cohort

    async def start(self):
        """Scrapy >=2.18 start hook; input is a fixed allowlisted manifest."""
        self.logger.info('Starting %s: %d approved URLs (cohort=%s)',
                         self.category, len(self.selected), self.cohort)
        for source in self.selected:
            yield scrapy.Request(
                source['url'],
                callback=self.parse_page,
                errback=self.record_failure,
                cb_kwargs={'source': source},
                meta={'handle_httpstatus_all': True},
                dont_filter=True,
            )

    @staticmethod
    def _base_record(source):
        return {
            'schema_version': '2.0',
            'source_id': source['id'],
            'provider': source['provider'],
            'category': source['category'],
            'source_url': source['url'],
            'fetched_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source_cohort': 'proven' if source['id'] in PROVEN_IDS else 'candidate',
            'review_status': 'unverified',
            'status': 'needs_review',
            'error': '',
        }

    def parse_page(self, response, source):
        record = self._base_record(source)
        record.update(
            final_url=response.url,
            http_status=response.status,
            content_type=response.headers.get(b'Content-Type', b'').decode(
                'utf-8', errors='replace'),
            last_modified=response.headers.get(b'Last-Modified', b'').decode(
                'utf-8', errors='replace'),
            etag=response.headers.get(b'ETag', b'').decode('utf-8', errors='replace'),
        )

        if urlsplit(response.url).hostname != urlsplit(source['url']).hostname:
            record.update(status='rejected_redirect', error='Redirected to a different host')
            yield record
            return
        if not 200 <= response.status < 300:
            record.update(status='http_error', error=f'HTTP {response.status}')
            yield record
            return
        if b'html' not in response.headers.get(b'Content-Type', b'text/html').lower():
            record.update(status='unsupported_content_type', error='Expected HTML')
            yield record
            return

        try:
            evidence = extract_evidence(response.text, source['url'])
        except Exception as exc:
            self.logger.warning('Failed to extract %s: %s', source['id'], exc)
            record.update(status='extraction_error', error=type(exc).__name__)
            yield record
            return

        text = evidence.pop('text')
        record.update(evidence)
        record['text_truncated'] = len(text) > MAX_TEXT_CHARS
        # A 200 response is not proof that the documentation was extracted.
        lowered = (record.get('title', '') + ' ' + text[:4000]).lower()
        if any(marker in lowered for marker in BLOCK_MARKERS):
            record.update(status='blocked', error='Likely access challenge')
        elif any(marker in lowered for marker in JS_SHELL_MARKERS):
            record.update(status='needs_review', error='Likely JavaScript-only shell')
        elif record['word_count'] < MIN_WORDS:
            record.update(status='needs_review', error=f'Only {record["word_count"]} words')
        elif record['text_truncated']:
            record.update(status='partial_capture', error='Text exceeds output limit')
        else:
            record.update(status='captured')

        if record['status'] in {'captured', 'partial_capture'}:
            record['text'] = text[:MAX_TEXT_CHARS]
        else:
            # Diagnostic sample, not a full untrusted access/block page.
            record['text_sample'] = text[:500]
        if getattr(self, 'crawler', None) is not None:
            self.crawler.stats.inc_value(f'agentfuse/status/{record["status"]}')
        yield record

    def record_failure(self, failure):
        source = failure.request.cb_kwargs['source']
        record = self._base_record(source)
        exception_name = failure.type.__name__
        status = 'robots_or_policy_denied' if exception_name == 'IgnoreRequest' else 'fetch_error'
        record.update(
            status=status, final_url='', http_status=None, error=exception_name,
        )
        self.logger.warning('Failed to fetch %s: %s', source['id'], failure.value)
        if getattr(self, 'crawler', None) is not None:
            self.crawler.stats.inc_value(f'agentfuse/status/{record["status"]}')
        yield record


class DocumentationSpider(OfficialBaseSpider):
    name = 'official_documentation'
    category = 'documentation'


class PricingSpider(OfficialBaseSpider):
    name = 'official_pricing'
    category = 'pricing'


class ChangelogSpider(OfficialBaseSpider):
    name = 'official_changelogs'
    category = 'changelog'
