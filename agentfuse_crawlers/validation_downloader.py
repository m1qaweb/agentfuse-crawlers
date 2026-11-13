"""P24D: recheck publisher SOURCE access at the Scrapy download boundary.

A reviewed access record and short-lived bulk plan can expire while a
scheduled source Request waits in the downloader. Spider.start() checks are
necessary, but not sufficient for delayed downloads. This middleware runs
BEFORE RobotsTxtMiddleware, so an expired source URL does not even trigger
an initial robots lookup from the publisher.

Only the three official validation spiders may issue a publisher page GET.
Scrapy's internal robots.txt Requests are *not* source page requests and
remain governed by Scrapy's ROBOTSTXT_OBEY middleware.

This module never grants permission, schedules Zyte, or trusts HTTP 200.
"""
from datetime import datetime, timezone
from urllib.parse import urlsplit

from scrapy.exceptions import IgnoreRequest

from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.validation_access import validation_access_decision

SCOPE_SINGLE = "single_validation"
SCOPE_BULK = "bulk_validation"
HOLD_META = "agentfuse_download_access_hold"


def _utc_expiry(raw):
    if not isinstance(raw, str) or len(raw) > 35:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


class ValidationDownloadGate:
    """Prevent late, duplicate, unreviewed or out-of-plan SOURCE page GETs."""

    def __init__(self, *, clock=None):
        self._by_id = {s["id"]: s for s in load_sources()}
        self._already_attempted = set()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    @staticmethod
    def _hold(request, reason):
        # The existing spider errback exports a normal unverified held Item
        # with an explicit diagnostic instead of silently losing the source.
        request.meta[HOLD_META] = reason
        raise IgnoreRequest(reason)

    def process_request(self, request, spider):
        if getattr(spider, "collection_mode", None) != "validation":
            return None

        # Scrapy itself makes robots lookups (with dont_obey_robotstxt=True)
        # when ROBOTSTXT_OBEY is on. They have no source cb_kwargs and are
        # deliberately handled by Scrapy, not mistaken for publisher pages.
        # The three official spiders never set that meta flag on source GETs.
        source = request.cb_kwargs.get("source")
        if request.meta.get("dont_obey_robotstxt") is True:
            if source is not None or request.method != "GET":
                self._hold(request, "publisher_request_cannot_skip_robots")
            # Deny a source-shaped request that could bypass this middleware.
            if request.cb_kwargs:
                self._hold(request, "unscoped_robots_exception")
            return None

        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            self._hold(request, "validation_request_missing_exact_source")
        sid = source["id"]
        if (self._by_id.get(sid) != source
                or source.get("category") != getattr(spider, "category", None)
                or source not in getattr(spider, "selected", ())):
            self._hold(request, "validation_source_not_in_pinned_selection")

        if (request.method != "GET"
                or request.url != source["url"]
                or request.meta.get("dont_redirect") is not True
                or request.meta.get("dont_retry") is not True):
            self._hold(request, "validation_source_url_or_method_not_exact")

        single = getattr(spider, "single_validation_required", False) is True
        bulk = getattr(spider, "bulk_validation_required", False) is True
        if single == bulk:
            self._hold(request, "validation_scope_not_explicitly_authorized")
        scope = SCOPE_SINGLE if single else SCOPE_BULK

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            self._hold(request, "invalid_downloader_access_clock")
        now = now.astimezone(timezone.utc)

        # Re-run production P23B source/URL/lifecycle/expiry validation at
        # download time, not just when the spider yielded the Request.
        permitted, reason = validation_access_decision(
            source, scope=scope, now=now,
        )
        if not permitted:
            self._hold(request, "download_time_" + reason)

        if bulk:
            expires = _utc_expiry(
                getattr(spider, "bulk_plan_expires_at_utc", None)
            )
            if (not getattr(spider, "bulk_plan_id", "")
                    or sid not in getattr(spider, "bulk_authorized_ids", ())
                    or expires is None or now >= expires):
                self._hold(request, "download_time_bulk_plan_missing_or_expired")

        # The same approved source can be attempted only once in this job.
        # Scrapy request retries are separately disabled by P24B; duplicate
        # yields/redirects must not silently increase the primary GET count.
        if sid in self._already_attempted:
            self._hold(request, "duplicate_validation_source_get")
        self._already_attempted.add(sid)
        return None
