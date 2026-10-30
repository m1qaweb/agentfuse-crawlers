"""Three read-only, fixed-scope Scrapy spiders for official provider pages."""

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit

import scrapy

from agentfuse_crawlers.extract import extract_text
from agentfuse_crawlers.sources import load_sources

SOURCES = load_sources()
ALLOWED_HOSTS = sorted({urlsplit(entry["url"]).hostname for entry in SOURCES})
MAX_TEXT_CHARS = 250_000
MIN_WORDS = 45
BLOCK_MARKERS = (
    "verify you are human", "checking your browser before accessing",
    "enable javascript and cookies", "access denied", "captcha challenge",
)


class OfficialBaseSpider(scrapy.Spider):
    category = None
    allowed_domains = ALLOWED_HOSTS

    async def start(self):
        """Scrapy 2.18+ calls start(), not the removed start_requests()."""
        for source in SOURCES:
            if source["category"] != self.category:
                continue
            yield scrapy.Request(
                source["url"],
                callback=self.parse_page,
                errback=self.record_failure,
                cb_kwargs={"source": source},
                meta={"handle_httpstatus_all": True},
                dont_filter=True,
            )

    @staticmethod
    def _base_record(source):
        return {
            "schema_version": "1.0",
            "source_id": source["id"],
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "review_status": "unverified",
        }

    def parse_page(self, response, source):
        record = self._base_record(source)
        record["final_url"] = response.url
        record["http_status"] = response.status
        record["content_type"] = response.headers.get(b"Content-Type", b"").decode(
            "utf-8", errors="replace"
        )
        record["error"] = ""

        # Do not attribute a redirected page on another host to a provider.
        final_host = urlsplit(response.url).hostname or ""
        if final_host != urlsplit(source["url"]).hostname:
            record.update(status="rejected_redirect", error="Redirected to another host")
            yield record
            return

        if response.status >= 400:
            record.update(status="http_error", error=f"HTTP {response.status}")
            yield record
            return

        if b"html" not in response.headers.get(b"Content-Type", b"text/html").lower():
            record.update(status="unsupported_content_type", error="Expected HTML")
            yield record
            return

        try:
            title, text = extract_text(response.text)
        except Exception as exc:
            self.logger.warning("Could not extract %s: %s", source["id"], exc)
            record.update(status="extraction_error", error=type(exc).__name__)
            yield record
            return

        words = len(text.split())
        lowered = text[:3000].lower()
        if any(marker in lowered for marker in BLOCK_MARKERS):
            record.update(status="blocked", error="Likely block or interstitial")
            yield record
            return
        if words < MIN_WORDS:
            record.update(status="needs_review", error=f"Only {words} words extracted")
            yield record
            return

        record.update(
            status="captured",
            title=title,
            text=text[:MAX_TEXT_CHARS],
            word_count=words,
            text_truncated=len(text) > MAX_TEXT_CHARS,
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        yield record

    def record_failure(self, failure):
        source = failure.request.cb_kwargs["source"]
        record = self._base_record(source)
        record.update(
            status="fetch_error",
            final_url="",
            http_status=None,
            error=failure.type.__name__,
        )
        self.logger.warning("Failed to fetch %s: %s", source["id"], failure.value)
        yield record


class DocumentationSpider(OfficialBaseSpider):
    name = "official_documentation"
    category = "documentation"


class PricingSpider(OfficialBaseSpider):
    name = "official_pricing"
    category = "pricing"


class ChangelogSpider(OfficialBaseSpider):
    name = "official_changelogs"
    category = "changelog"
