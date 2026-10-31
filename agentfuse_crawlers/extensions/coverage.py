"""Run-accounting audit separate from source quality and fact approval.

Scrapy 'finished' means the crawl lifecycle ended; it does not mean sources
were relevant, complete, fresh, or suitable for an AI recommendation.
"""

from collections import Counter

from scrapy import signals
from scrapy.exceptions import CloseSpider

VALID_NAMES = {
    "official_documentation", "official_pricing", "official_changelogs"
}
CONTEXT_FIELDS = (
    "spider_name", "requested_cohort", "run_scope_explicit",
    "selection_source_count", "selection_ids_sha256", "manifest_sha256",
    "run_started_at_utc", "zyte_job_id", "deployment_revision",
)


def _comparable(item):
    """Conservative page completeness, not approval of any vendor fact."""
    return bool(
        item.get("status") == "captured"
        and item.get("content_sha256")
        and not any(item.get(field) for field in (
            "text_truncated", "sections_truncated", "tables_truncated",
        ))
        and not any(
            section.get("excerpt_truncated")
            for section in item.get("sections", [])
        )
    )


class SourceCoverageAudit:
    def __init__(self, crawler):
        self.crawler = crawler
        self.observed = {}
        self.duplicates = set()
        self.context_errors = set()
        self.status_counts = Counter()
        self.comparable = set()
        self.clipped_excerpts = set()
        self.advisor_approval_anomalies = set()

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
            self.status_counts[item.get("status", "unknown")] += 1
            if _comparable(item):
                self.comparable.add(source_id)
            if any(s.get("excerpt_truncated") for s in item.get("sections", [])):
                self.clipped_excerpts.add(source_id)
            context = getattr(spider, "run_context", None)
            if (item.get("approved_for_advisor") is True
                    or (context is not None and
                        item.get("approved_for_advisor") is not False)):
                self.advisor_approval_anomalies.add(source_id)
            if context is not None and any(
                item.get(field) != context.get(field) for field in CONTEXT_FIELDS
            ):
                self.context_errors.add(source_id)

    def summary(self, spider):
        expected = {row["id"] for row in spider.selected}
        observed = set(self.observed)
        missing = expected - observed
        extra = observed - expected
        captured = sum(
            status == "captured" for sid, status in self.observed.items()
            if sid in expected
        )
        partial = sum(
            status == "partial_capture" for sid, status in self.observed.items()
            if sid in expected
        )
        comparable = len(self.comparable & expected)
        problems = bool(
            missing or extra or self.duplicates or self.context_errors
            or self.advisor_approval_anomalies
        )
        if problems:
            quality = "coverage_or_provenance_failed"
        elif captured == 0 and partial == 0:
            quality = "no_usable_sources"
        elif captured != len(expected) or comparable != len(expected):
            quality = "degraded_unverified"
        else:
            quality = "all_captured_unverified"

        stats = self.crawler.stats
        metrics = {
            "expected_sources": len(expected),
            "reported_sources": len(expected & observed),
            "captured_sources": captured,
            "partial_sources": partial,
            "uncaptured_sources": len(expected) - captured,
            "comparable_sources": comparable,
            "captured_with_clipped_excerpts": len(self.clipped_excerpts & expected),
            "missing_sources": len(missing),
            "duplicate_sources": len(self.duplicates),
            "unexpected_sources": len(extra),
            "provenance_errors": len(self.context_errors),
            "advisor_approval_anomalies": len(self.advisor_approval_anomalies),
            "captured_rate": round(captured / len(expected), 4) if expected else 0,
            "comparable_rate": round(comparable / len(expected), 4) if expected else 0,
        }
        for key, value in metrics.items():
            stats.set_value("agentfuse/coverage/" + key, value)
        for key, value in self.status_counts.items():
            stats.set_value("agentfuse/coverage/status/" + str(key), value)
        stats.set_value("agentfuse/run/quality_outcome", quality)
        context = getattr(spider, "run_context", None)
        if context:
            for field in CONTEXT_FIELDS:
                stats.set_value("agentfuse/run/" + field, context[field])

        if missing:
            spider.logger.warning(
                "Missing %d source Items: %s", len(missing),
                ", ".join(sorted(missing)[:15]),
            )
        if problems:
            spider.logger.error(
                "Coverage/provenance mismatch (missing=%d unexpected=%d "
                "duplicate=%d context=%d approval=%d)",
                len(missing), len(extra), len(self.duplicates),
                len(self.context_errors), len(self.advisor_approval_anomalies),
            )
        elif quality != "all_captured_unverified":
            spider.logger.warning(
                "Job accounted for %d/%d sources but evidence quality=%s; "
                "captured=%d comparable=%d partial=%d",
                len(expected & observed), len(expected), quality,
                captured, comparable, partial,
            )
        return missing, extra, captured, partial

    def spider_idle(self, spider):
        if spider.name not in VALID_NAMES:
            return
        missing, extra, captured, partial = self.summary(spider)
        if (missing or extra or self.duplicates or self.context_errors
                or self.advisor_approval_anomalies):
            raise CloseSpider("agentfuse_incomplete_source_coverage")
        if captured == 0 and partial == 0:
            raise CloseSpider("agentfuse_no_usable_sources")

    def spider_closed(self, spider, reason):
        if spider.name in VALID_NAMES:
            self.summary(spider)
            self.crawler.stats.set_value(
                "agentfuse/coverage/close_reason", reason,
            )
