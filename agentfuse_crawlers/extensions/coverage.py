"""Scrapy run-coverage audit: never confuse 'finished' with 'all URLs worked'."""

from scrapy import signals
from scrapy.exceptions import CloseSpider

VALID_NAMES = {
    "official_documentation", "official_pricing", "official_changelogs"
}


class SourceCoverageAudit:
    def __init__(self, crawler):
        self.crawler = crawler
        self.observed = {}
        self.duplicates = set()

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(crawler)
        crawler.signals.connect(instance.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(instance.spider_idle, signal=signals.spider_idle)
        crawler.signals.connect(instance.spider_closed, signal=signals.spider_closed)
        return instance

    def item_scraped(self, item, response, spider):
        if spider.name not in VALID_NAMES:
            return
        source_id = item.get("source_id", "") if hasattr(item, "get") else ""
        if source_id in self.observed:
            self.duplicates.add(source_id)
        if source_id:
            self.observed[source_id] = item.get("status", "unknown")

    def summary(self, spider):
        expected = {row["id"] for row in spider.selected}
        observed = set(self.observed)
        missing = expected - observed
        extra = observed - expected
        captured = sum(v == "captured" for k, v in self.observed.items() if k in expected)
        partial = sum(v == "partial_capture" for k, v in self.observed.items() if k in expected)
        stats = self.crawler.stats
        for key, value in {
            "expected_sources": len(expected),
            "reported_sources": len(expected & observed),
            "captured_sources": captured,
            "partial_sources": partial,
            "uncaptured_sources": len(expected) - captured,
            "missing_sources": len(missing),
            "duplicate_sources": len(self.duplicates),
            "unexpected_sources": len(extra),
        }.items():
            stats.set_value("agentfuse/coverage/" + key, value)
        if missing:
            spider.logger.warning("Missing %d source items: %s", len(missing),
                                  ", ".join(sorted(missing)[:15]))
        if extra or self.duplicates:
            spider.logger.error("Source ID anomaly: %d unexpected, %d duplicate",
                                len(extra), len(self.duplicates))
        return missing, extra, captured, partial

    def spider_idle(self, spider):
        if spider.name not in VALID_NAMES:
            return
        missing, extra, captured, partial = self.summary(spider)
        if missing or extra or self.duplicates:
            raise CloseSpider("agentfuse_incomplete_source_coverage")
        if captured == 0 and partial == 0:
            raise CloseSpider("agentfuse_no_usable_sources")

    def spider_closed(self, spider, reason):
        if spider.name in VALID_NAMES:
            self.summary(spider)
            self.crawler.stats.set_value("agentfuse/coverage/close_reason", reason)
