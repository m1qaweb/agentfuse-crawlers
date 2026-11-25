"""P24D: recheck publisher SOURCE access at the Scrapy download boundary.

A reviewed access record and short-lived bulk plan can expire while a
scheduled source Request waits in the downloader. Spider.start() checks are
necessary, but not sufficient for delayed downloads. This middleware runs
AFTER RobotsTxtMiddleware so a delayed robots lookup cannot leave a stale
source review unchecked immediately before the source page request.
Robots lookups themselves are separate policy requests, not publisher HTML.

Only the three official validation spiders may issue a publisher page GET.
Scrapy's internal robots.txt Requests are *not* source page requests and
remain governed by Scrapy's ROBOTSTXT_OBEY middleware.

This module never grants permission, schedules Zyte, or trusts HTTP 200.
"""
from datetime import datetime, timezone
from urllib.parse import urlsplit

from scrapy.exceptions import IgnoreRequest
from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware

from agentfuse_crawlers.robots_policy import reviewed_robots_body
from agentfuse_crawlers.public_diagnostic import public_diagnostic_access_decision
from agentfuse_crawlers.validation_containment import (
    GLOBAL_HOLD, INTEGRITY_STOP, PROXY_STOP, TRANSPORT_STOP,
    http_barrier, state_for,
)

from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.validation_access import validation_access_decision

SCOPE_SINGLE = "single_validation"
SCOPE_BULK = "bulk_validation"
HOLD_META = "agentfuse_download_access_hold"
ROBOTS_FAILURE_META = "agentfuse_robots_lookup_failure"


class ValidationRobotsMiddleware(RobotsTxtMiddleware):
    """Preserve Scrapy 2.18 parsing; fail closed on unresolved live robots.

    The pinned Scrapy version normally caches None on lookup/parse failure
    and treats that as no restriction. A validation page must never use
    that fallback. Monitoring retains its separate existing policy.
    """

    def _validation(self):
        return getattr(self.crawler.spider, "collection_mode", None) == "validation"

    async def _parse_robots(self, response, netloc, request):
        if self._validation():
            try:
                body = reviewed_robots_body(
                    expected_url="https://" + netloc + "/robots.txt",
                    response_url=response.url, status=response.status,
                    content_type=response.headers.get(b"Content-Type", b""),
                    body=response.body,
                )
            except ValueError as exc:
                # Base robot_parser catches this and resolves its per-host
                # Deferred to None. process_request_2 below then denies ALL
                # waiting source GETs for that unresolved host.
                self._stats.inc_value("robotstxt/response_count")
                self._stats.inc_value(f"robotstxt/response_status_count/{response.status}")
                self._stats.inc_value("agentfuse/robots/response_unresolved")
                state = state_for(self.crawler.spider)
                if state is not None:
                    if response.status == 407:
                        state.stop(PROXY_STOP)
                    else:
                        state.barrier(state.by_origin.get(netloc),
                                      "agentfuse_validation_robots_or_policy_denied")
                raise IgnoreRequest(str(exc)) from exc
            if body != response.body:
                response = response.replace(body=body)
        return await super()._parse_robots(response, netloc, request)

    def process_request_2(self, rp, request):
        state = state_for(self.crawler.spider)
        group = None
        if state is not None:
            group = state.by_origin.get(urlsplit(request.url).hostname)
            reason = state.hold(group)
            if reason:
                # The denied robots response remains in Requests; later
                # source Items must describe a hold, not an HTML fetch.
                request.meta[HOLD_META] = reason
                raise IgnoreRequest(reason)
        if self._validation() and rp is None:
            request.meta[ROBOTS_FAILURE_META] = "robots_lookup_or_parse_unresolved"
            self._stats.inc_value("agentfuse/robots/source_held_unresolved")
            if state is not None:
                state.barrier(group, "agentfuse_validation_robots_or_policy_denied")
            raise IgnoreRequest("Validation robots lookup or parse unresolved")
        try:
            return super().process_request_2(rp, request)
        except IgnoreRequest:
            if state is not None:
                state.barrier(group, "agentfuse_validation_robots_or_policy_denied")
            raise



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
        self._robots_attempted = set()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._timeout_seconds = 0

    @classmethod
    def from_crawler(cls, crawler):
        gate = cls()
        gate._timeout_seconds = crawler.settings.getfloat("CLOSESPIDER_TIMEOUT")
        return gate

    @staticmethod
    def _hold(request, reason):
        # The existing spider errback exports a normal unverified held Item
        # with an explicit diagnostic instead of silently losing the source.
        request.meta[HOLD_META] = reason
        raise IgnoreRequest(reason)

    def _current_access_hold_reason(self, source, spider, now):
        single = getattr(spider, "single_validation_required", False) is True
        bulk = getattr(spider, "bulk_validation_required", False) is True
        if single == bulk:
            return "validation_scope_not_explicitly_authorized"
        scope = SCOPE_SINGLE if single else SCOPE_BULK

        if (not isinstance(now, datetime) or now.tzinfo is None
                or now.utcoffset() is None):
            return "invalid_downloader_access_clock"
        now = now.astimezone(timezone.utc)

        # Re-run production P23B source/URL/lifecycle/expiry validation at
        # download time, not just when the spider yielded the Request.
        public_scope = getattr(spider, "_public_diagnostic_scope", None)
        if public_scope is not None:
            if not bulk:
                return "public_diagnostic_scope_not_bulk"
            permitted, reason = public_diagnostic_access_decision(
                source, public_scope, now=now,
            )
        else:
            permitted, reason = validation_access_decision(
                source, scope=scope, now=now,
            )
        if not permitted:
            return "download_time_" + reason

        if bulk:
            expires = _utc_expiry(
                getattr(spider, "bulk_plan_expires_at_utc", None)
            )
            if (not getattr(spider, "bulk_plan_id", "")
                    or source["id"] not in getattr(spider, "bulk_authorized_ids", ())
                    or expires is None or now >= expires):
                return "download_time_bulk_plan_missing_or_expired"

        return None

    def _fatal_hold(self, request, spider, reason):
        state = state_for(spider)
        if state is not None:
            state.stop(INTEGRITY_STOP)
        self._hold(request, reason)

    def _containment_admit(self, request, spider, token, group):
        state = state_for(spider)
        if state is not None:
            reason = state.hold(group)
            if reason:
                self._hold(request, reason)
            state.admit(token, group)
            request.meta["agentfuse_containment_admission"] = token

    def process_request(self, request, spider):
        if getattr(spider, "collection_mode", None) != "validation":
            return None
        if getattr(spider, "_agentfuse_validation_stop_reason", None):
            self._hold(request, GLOBAL_HOLD)
        state = state_for(spider)
        if state is not None:
            state.limit_runtime(self._timeout_seconds)

        # Scrapy itself makes robots lookups (with dont_obey_robotstxt=True)
        # when ROBOTSTXT_OBEY is on. They have no source cb_kwargs and are
        # deliberately handled by Scrapy, not mistaken for publisher pages.
        # The three official spiders never set that meta flag on source GETs.
        source = request.cb_kwargs.get("source")
        if request.meta.get("dont_obey_robotstxt") is True:
            if source is not None or request.cb_kwargs or request.method != "GET":
                self._fatal_hold(request, spider, "publisher_request_cannot_skip_robots")
            # The ONLY bypass is Scrapy's internal exact-host /robots.txt
            # lookup, never an arbitrary publisher page using this meta flag.
            parts = urlsplit(request.url)
            if (parts.scheme != "https" or not parts.hostname
                    or parts.path != "/robots.txt" or parts.query or parts.fragment
                    or parts.username or parts.password
                    or request.url != "https://" + parts.netloc + "/robots.txt"):
                self._fatal_hold(request, spider, "unreviewed_robots_lookup_target")
            # Full-category selection includes held sources. Require at least
            # one currently authorized exact source on this exact origin,
            # not merely a hostname present in the selected inventory.
            candidates = [s for s in getattr(spider, "selected", ())
                          if isinstance(s, dict) and isinstance(s.get("id"), str)
                          and self._by_id.get(s["id"]) == s
                          and s["category"] == getattr(spider, "category", None)
                          and urlsplit(s["url"]).scheme == parts.scheme
                          and urlsplit(s["url"]).netloc == parts.netloc]
            if not candidates:
                self._fatal_hold(request, spider, "unreviewed_robots_lookup_target")
            group = state.by_origin.get(parts.hostname) if state is not None else None
            if state is not None:
                reason = state.hold(group)
                if reason:
                    self._hold(request, reason)
            now = self._clock()
            try:
                allowed = any(self._current_access_hold_reason(s, spider, now) is None
                              for s in candidates)
            except ValueError:
                if state is None:
                    raise
                self._fatal_hold(request, spider, "validation_authorization_integrity_failure")
            if not allowed:
                self._fatal_hold(request, spider, "robots_origin_no_current_authorized_source")
            if request.url in self._robots_attempted:
                self._fatal_hold(request, spider, "duplicate_validation_robots_get")
            self._containment_admit(request, spider, request.url, group)
            self._robots_attempted.add(request.url)
            # Never follow a robots redirect or retry an access barrier in
            # supervised validation. The exact reviewed URL must be resolved
            # directly; a new robots target requires separate review.
            request.meta["dont_redirect"] = True
            request.meta["dont_retry"] = True
            return None

        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            self._fatal_hold(request, spider, "validation_request_missing_exact_source")
        sid = source["id"]
        if (self._by_id.get(sid) != source
                or source.get("category") != getattr(spider, "category", None)
                or source not in getattr(spider, "selected", ())):
            self._fatal_hold(request, spider, "validation_source_not_in_pinned_selection")

        if (request.method != "GET"
                or request.url != source["url"]
                or request.meta.get("dont_redirect") is not True
                or request.meta.get("dont_retry") is not True):
            self._fatal_hold(request, spider, "validation_source_url_or_method_not_exact")

        group = state.by_source.get(sid) if state is not None else None
        if state is not None:
            reason = state.hold(group)
            if reason:
                self._hold(request, reason)
        try:
            reason = self._current_access_hold_reason(source, spider, self._clock())
        except ValueError:
            if state is None:
                raise
            self._fatal_hold(request, spider, "validation_authorization_integrity_failure")
        if reason is not None:
            self._fatal_hold(request, spider, reason)

        # The same approved source can be attempted only once in this job.
        # Scrapy request retries are separately disabled by P24B; duplicate
        # yields/redirects must not silently increase the primary GET count.
        if sid in self._already_attempted:
            self._fatal_hold(request, spider, "duplicate_validation_source_get")
        if state is not None and len(self._already_attempted) >= spider.bulk_max_primary_requests:
            self._fatal_hold(request, spider, "validation_primary_budget_exhausted")
        self._containment_admit(request, spider, sid, group)
        self._already_attempted.add(sid)
        return None

    def process_response(self, request, response, spider):
        state = state_for(spider)
        if state is None:
            return response
        token = request.meta.get("agentfuse_containment_admission")
        group = state.finish(token)
        if group is None or response.url != request.url:
            # Keep the original response available for diagnostic Items, but
            # no later admission is allowed after a provenance anomaly.
            state.stop(INTEGRITY_STOP)
            return response
        if request.meta.get("dont_obey_robotstxt") is True:
            if response.status == 407:
                state.stop(PROXY_STOP)
            # All other robots responses go through the strict body/parser
            # gate (including genuine 404/410, which are not HTML permits).
            return response
        reason, systemic = http_barrier(response.status)
        if systemic:
            state.stop(reason)
        elif reason:
            state.barrier(group, reason)
        return response

    def process_exception(self, request, exception, spider):
        state = state_for(spider)
        if state is None:
            return None
        token = request.meta.get("agentfuse_containment_admission")
        group = state.finish(token)
        if group is not None:
            if (request.meta.get("dont_obey_robotstxt") is True
                    and type(exception).__name__ in {
                        "DNSLookupError", "TimeoutError", "TCPTimedOutError",
                        "ConnectionRefusedError", "ConnectError",
                    }):
                state.barrier(group, "agentfuse_validation_robots_or_policy_denied")
            else:
                # Unknown transport/proxy failure is not evidence that only
                # this publisher is affected. Fail closed, no retry.
                state.stop(TRANSPORT_STOP)
        elif not isinstance(exception, IgnoreRequest):
            state.stop(INTEGRITY_STOP)
        return None


class ValidationPreRobotsGuard:
    """Do not let an invalid/held primary request trigger even a robots GET.

    This extra admission check is confined to R2 bulk diagnostics. The
    post-robots gate still independently checks exact identity, current
    permissions, plan budget and duplicate admission.
    """

    def __init__(self):
        self.gate = ValidationDownloadGate()

    @classmethod
    def from_crawler(cls, crawler):
        guard = cls()
        guard.gate = ValidationDownloadGate.from_crawler(crawler)
        return guard

    def process_request(self, request, spider):
        state = state_for(spider)
        if state is None:
            return None
        state.limit_runtime(self.gate._timeout_seconds)
        if state.global_reason or getattr(spider, "_agentfuse_validation_stop_reason", None):
            self.gate._hold(request, GLOBAL_HOLD)
        if request.meta.get("dont_obey_robotstxt") is True:
            # The original exact internal-robots gate at 110 handles it.
            return None
        source = request.cb_kwargs.get("source")
        if (not isinstance(source, dict) or not isinstance(source.get("id"), str)
                or self.gate._by_id.get(source["id"]) != source
                or source.get("category") != spider.category
                or source not in spider.selected
                or request.method != "GET" or request.url != source["url"]
                or request.meta.get("dont_redirect") is not True
                or request.meta.get("dont_retry") is not True):
            self.gate._fatal_hold(request, spider, "validation_pre_robots_source_not_exact")
        reason = state.hold(state.by_source.get(source["id"]))
        if reason:
            self.gate._hold(request, reason)
        try:
            reason = self.gate._current_access_hold_reason(source, spider, self.gate._clock())
        except ValueError:
            self.gate._fatal_hold(request, spider, "validation_authorization_integrity_failure")
        if reason:
            self.gate._fatal_hold(request, spider, reason)
        return None
