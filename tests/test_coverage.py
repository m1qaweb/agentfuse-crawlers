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


class RecordingEngine:
    def __init__(self):
        self.closed = []

    def close_spider(self, spider, reason="cancelled"):
        self.closed.append((spider, reason))


@pytest.mark.parametrize("status,http_status,error,reason", [
    ("source_access_limited", 429, "HTTP 429",
     "agentfuse_validation_http_429"),
    ("http_error", 429, "HTTP 429",
     "agentfuse_validation_http_429"),
    ("http_error", 401, "HTTP 401",
     "agentfuse_validation_http_access_denied"),
    ("http_error", 403, "HTTP 403",
     "agentfuse_validation_http_access_denied"),
    ("http_error", 407, "HTTP 407",
     "agentfuse_validation_http_access_denied"),
    ("robots_or_policy_denied", None, "IgnoreRequest",
     "agentfuse_validation_robots_or_policy_denied"),
    ("blocked", 200, "access_or_login_challenge",
     "agentfuse_validation_access_or_login_challenge"),
    ("rejected_redirect", 301, "cross_host_or_non_https_redirect",
     "agentfuse_validation_unreviewed_redirect"),
    ("redirect_needs_review", 302, "single_source_redirect_target_requires_review",
     "agentfuse_validation_unreviewed_redirect"),
])
def test_validation_shard_requests_shutdown_after_real_item_pipeline(
        status, http_status, error, reason):
    audit, spider, stats = setup(("a", "b"))
    engine = RecordingEngine()
    audit.crawler.engine = engine
    spider.collection_mode = "validation"
    spider.source_registry_sha256 = "synthetic"
    row = dict(
        source_id="a", collection_mode="validation",
        source_registry_sha256="synthetic", approved_for_advisor=False,
        status=status, http_status=http_status, error=error,
    )
    audit.item_scraped(row, None, spider)
    assert engine.closed == [(spider, reason)]
    assert audit.validation_abort_requested is True
    assert stats.rows["agentfuse/run/validation_abort_reason"] == reason
    assert stats.rows["agentfuse/run/validation_abort_source_id"] == "a"
    assert spider._agentfuse_validation_stop_reason == reason
    # Later in-flight failures must not issue competing close calls.
    audit.item_scraped({**row, "source_id": "b"}, None, spider)
    assert engine.closed == [(spider, reason)]


@pytest.mark.parametrize("mode,status,http_status,error", [
    ("validation", "source_single_validation_not_approved", None,
     "single_source_policy_not_reviewed"),
    ("validation", "source_bulk_validation_not_approved", None,
     "bulk_run_plan_not_present"),
    ("validation", "http_error", 503, "HTTP 503"),
    ("validation", "needs_review", 200, "documentation_link_index_only"),
    ("monitor", "source_access_limited", 429, "HTTP 429"),
    ("monitor", "blocked", 200, "access_or_login_challenge"),
])
def test_nonfatal_holds_and_monitoring_do_not_request_validation_shutdown(
        mode, status, http_status, error):
    audit, spider, stats = setup(("a",))
    engine = RecordingEngine()
    audit.crawler.engine = engine
    spider.collection_mode = mode
    spider.source_registry_sha256 = "synthetic"
    audit.item_scraped(dict(
        source_id="a", collection_mode=mode,
        source_registry_sha256="synthetic",
        status=status, http_status=http_status, error=error,
        approved_for_advisor=False,
    ), None, spider)
    assert engine.closed == []
    assert audit.validation_abort_requested is False
    assert not getattr(spider, "_agentfuse_validation_stop_reason", None)
    assert "agentfuse/run/validation_abort_reason" not in stats.rows


def test_unknown_source_item_does_not_abort_selected_validation_shard():
    audit, spider, stats = setup(("a",))
    engine = RecordingEngine()
    audit.crawler.engine = engine
    spider.collection_mode = "validation"
    spider.source_registry_sha256 = "synthetic"
    audit.item_scraped(dict(
        source_id="evil", collection_mode="validation",
        source_registry_sha256="synthetic", status="source_access_limited",
        error="HTTP 429", http_status=429,
    ), None, spider)
    assert engine.closed == []
    assert audit.validation_abort_requested is False


def test_actual_synthetic_429_spider_item_triggers_extension_stop():
    """No real network; production spider status passes through extension."""
    from scrapy import Request
    from scrapy.http import HtmlResponse
    from agentfuse_crawlers.sources import load_sources
    from agentfuse_crawlers.spiders.official import DocumentationSpider

    spider = DocumentationSpider(cohort="all", source_ids="openai_api_docs")
    source = next(s for s in load_sources() if s["id"] == "openai_api_docs")
    request = Request(source["url"])
    response = HtmlResponse(
        url=source["url"], request=request, status=429, encoding="utf-8",
        headers={"Content-Type": "text/html"},
        body=b"<html><body>Rate limited</body></html>",
    )
    observed = list(spider.parse_page(response, source))
    assert len(observed) == 1
    assert observed[0]["status"] == "source_access_limited"
    engine = RecordingEngine()
    stats = Stats()
    audit = SourceCoverageAudit(SimpleNamespace(stats=stats, engine=engine))
    audit.item_scraped(observed[0], response, spider)
    assert engine.closed == [(spider, "agentfuse_validation_http_429")]


def test_global_stop_latched_before_engine_shutdown_and_for_missing_engine():
    reason = "agentfuse_validation_http_429"
    for has_engine in (True, False):
        audit, spider, stats = setup(("a", "b"))
        spider.collection_mode = "validation"
        spider.source_registry_sha256 = "synthetic"

        class CheckingEngine(RecordingEngine):
            def close_spider(self, spider, reason="cancelled"):
                assert spider._agentfuse_validation_stop_reason == reason
                super().close_spider(spider, reason=reason)

        engine = CheckingEngine() if has_engine else None
        audit.crawler.engine = engine
        row = dict(
            source_id="a", collection_mode="validation",
            source_registry_sha256="synthetic", approved_for_advisor=False,
            status="source_access_limited", http_status=429, error="HTTP 429",
        )
        if has_engine:
            audit.item_scraped(row, None, spider)
            assert engine.closed == [(spider, reason)]
        else:
            with pytest.raises(RuntimeError, match="without Scrapy engine"):
                audit.item_scraped(row, None, spider)
        assert spider._agentfuse_validation_stop_reason == reason
