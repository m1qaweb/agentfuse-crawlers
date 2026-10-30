"""A Scrapy job with no items must not close as an ordinary successful crawl."""

from types import SimpleNamespace

import pytest
from scrapy.exceptions import CloseSpider

from agentfuse_crawlers.extensions.coverage import SourceCoverageAudit


class Stats:
    def __init__(self):
        self.rows = {}

    def set_value(self, name, value):
        self.rows[name] = value


class Logger:
    def warning(self, *args):
        pass

    def error(self, *args):
        pass


def setup(expected=("a", "b")):
    stats = Stats()
    audit = SourceCoverageAudit(SimpleNamespace(stats=stats))
    spider = SimpleNamespace(
        name="official_changelogs",
        selected=[{"id": x} for x in expected],
        logger=Logger(),
    )
    return audit, spider, stats


def test_missing_scrapy_items_raises_explicit_coverage_reason():
    audit, spider, stats = setup()
    audit.item_scraped({"source_id": "a", "status": "captured"}, None, spider)
    with pytest.raises(CloseSpider) as err:
        audit.spider_idle(spider)
    assert err.value.reason == "agentfuse_incomplete_source_coverage"
    assert stats.rows["agentfuse/coverage/missing_sources"] == 1
    assert stats.rows["agentfuse/coverage/captured_sources"] == 1


def test_all_sources_failed_is_not_regular_success():
    audit, spider, stats = setup()
    audit.item_scraped({"source_id": "a", "status": "http_error"}, None, spider)
    audit.item_scraped({"source_id": "b", "status": "needs_review"}, None, spider)
    with pytest.raises(CloseSpider) as err:
        audit.spider_idle(spider)
    assert err.value.reason == "agentfuse_no_usable_sources"
    assert stats.rows["agentfuse/coverage/missing_sources"] == 0


def test_partial_capture_visible_without_claiming_complete():
    audit, spider, stats = setup()
    audit.item_scraped({"source_id": "a", "status": "partial_capture"}, None, spider)
    audit.item_scraped({"source_id": "b", "status": "captured"}, None, spider)
    assert audit.spider_idle(spider) is None
    assert stats.rows["agentfuse/coverage/partial_sources"] == 1


def test_duplicate_results_are_an_anomaly():
    audit, spider, stats = setup(("a",))
    audit.item_scraped({"source_id": "a", "status": "captured"}, None, spider)
    audit.item_scraped({"source_id": "a", "status": "captured"}, None, spider)
    with pytest.raises(CloseSpider) as err:
        audit.spider_idle(spider)
    assert err.value.reason == "agentfuse_incomplete_source_coverage"
    assert stats.rows["agentfuse/coverage/duplicate_sources"] == 1
