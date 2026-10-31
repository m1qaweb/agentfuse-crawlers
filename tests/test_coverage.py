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



def test_successful_accounting_is_not_necessarily_usable_evidence():
    audit, spider, stats = setup(("a",))
    audit.item_scraped({
        "source_id": "a", "status": "captured",
        "content_sha256": "hash",
        "sections": [{"excerpt_truncated": True}],
        "approved_for_advisor": False,
    }, None, spider)
    assert audit.spider_idle(spider) is None
    assert stats.rows["agentfuse/coverage/comparable_sources"] == 0
    assert stats.rows["agentfuse/coverage/captured_with_clipped_excerpts"] == 1
    assert stats.rows["agentfuse/run/quality_outcome"] == "degraded_unverified"


def test_job_provenance_mismatch_is_an_error_even_with_one_captured_item():
    audit, spider, stats = setup(("a",))
    spider.run_context = {
        "spider_name": "official_changelogs",
        "requested_cohort": "proven",
        "run_scope_explicit": False,
        "selection_source_count": 1,
        "selection_ids_sha256": "expected-hash",
        "manifest_sha256": "expected-manifest",
        "run_started_at_utc": "2026-10-31T09:00:00+00:00",
        "zyte_job_id": "",
        "deployment_revision": "",
    }
    item = dict(spider.run_context)
    item.update(source_id="a", status="captured", content_sha256="hash",
                selection_ids_sha256="different-hash", approved_for_advisor=False)
    audit.item_scraped(item, None, spider)
    with pytest.raises(CloseSpider) as caught:
        audit.spider_idle(spider)
    assert caught.value.reason == "agentfuse_incomplete_source_coverage"
    assert stats.rows["agentfuse/coverage/provenance_errors"] == 1


def test_explicit_approval_in_crawler_is_anomaly():
    audit, spider, stats = setup(("a",))
    audit.item_scraped({
        "source_id": "a", "status": "captured",
        "approved_for_advisor": True, "content_sha256": "hash",
    }, None, spider)
    with pytest.raises(CloseSpider) as caught:
        audit.spider_idle(spider)
    assert caught.value.reason == "agentfuse_incomplete_source_coverage"
    assert stats.rows["agentfuse/coverage/advisor_approval_anomalies"] == 1



def test_missing_unverified_flag_in_modern_spider_is_detected():
    audit, spider, stats = setup(("a",))
    spider.run_context = {
        "spider_name": "official_changelogs", "requested_cohort": "proven",
        "run_scope_explicit": True, "selection_source_count": 1,
        "selection_ids_sha256": "hash", "manifest_sha256": "manifest",
        "run_started_at_utc": "2026-10-31T10:00:00+00:00",
        "zyte_job_id": "", "deployment_revision": "",
    }
    # Fields agree, but an explicit refusal to approve MUST be present.
    item = dict(spider.run_context, source_id="a", status="captured",
                content_sha256="a-hash")
    audit.item_scraped(item, None, spider)
    with pytest.raises(CloseSpider) as caught:
        audit.spider_idle(spider)
    assert caught.value.reason == "agentfuse_incomplete_source_coverage"
    assert stats.rows["agentfuse/coverage/advisor_approval_anomalies"] == 1
