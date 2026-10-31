"""Exactly three read-only official-source spiders, preserving original identities.

One fresh network request per reviewed source at each scheduled run.
An HTTP 200 is *not* a guarantee of source completeness, publication freshness,
truth, or approved advisor evidence. Access/policy failures remain visible.
"""

from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import scrapy

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.run_context import build_run_context
from agentfuse_crawlers.quality import (
    HARD_TEXT_LIMIT, assess_capture, response_freshness,
)
from agentfuse_crawlers.sources import (
    load_proven_source_ids, load_sources, select_sources,
)

ALLOWED_HOSTS = sorted({urlsplit(s["url"]).hostname for s in load_sources()})
PROVEN_IDS = load_proven_source_ids()
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 3


def _visible_url(raw_url):
    """Keep provenance URL host/path, not query tokens or fragments."""
    parts = urlsplit(raw_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _allowed_redirect(raw_url, source):
    """Only follow HTTPS redirects on this source's exact trusted host."""
    parts = urlsplit(raw_url)
    origin = urlsplit(source["url"])
    try:
        return (parts.scheme == "https" and parts.hostname == origin.hostname
                and not parts.username and not parts.password
                and parts.port in (None, 443))
    except ValueError:
        return False


class OfficialBaseSpider(scrapy.Spider):
    category = None
    allowed_domains = ALLOWED_HOSTS

    def __init__(self, cohort=None, source_ids=None, limit=None, offset=0,
                 confirm_full_inventory=None, **kwargs):
        super().__init__(**kwargs)
        # A missing cohort now means the tiny historical smoke-test scope.
        # Explicit cohort=all is intentionally disruptive without this guard:
        # a previously unbounded scheduled job must be consciously updated.
        explicit_cohort = cohort is not None
        cohort = "proven" if cohort is None else cohort
        if cohort == "all" and source_ids is None and confirm_full_inventory != "yes":
            raise ValueError(
                "cohort=all requires confirm_full_inventory=yes when "
                "source_ids is omitted; use cohort=proven for smoke tests"
            )
        if confirm_full_inventory not in (None, "yes"):
            raise ValueError("confirm_full_inventory must be 'yes' when provided")
        # Source IDs must exist in the reviewed manifest. Never accept URL args.
        self.selected = select_sources(self.category, cohort, source_ids, limit, offset)
        self.cohort = cohort
        self.offset = int(offset)
        self.run_context = build_run_context(
            self.name, cohort, self.selected, explicit_cohort=explicit_cohort,
        )

    async def start(self):
        """Required for Scrapy 2.18+; called on every scheduled job."""
        self.logger.info(
            "Starting %s: %d configured URLs (requested_cohort=%s, offset=%d, "
            "manifest=%s, selection=%s, job_id=%s, revision=%s)",
            self.category, len(self.selected), self.cohort, self.offset,
            self.run_context["manifest_sha256"][:12],
            self.run_context["selection_ids_sha256"][:12],
            self.run_context["zyte_job_id"] or "unknown",
            self.run_context["deployment_revision"] or "unknown",
        )
        for source in self.selected:
            yield scrapy.Request(
                source["url"],
                callback=self.parse_page,
                errback=self.record_failure,
                cb_kwargs={"source": source},
                meta={
                    "handle_httpstatus_all": True,
                    "dont_redirect": True,
                    "source_redirect_depth": 0,
                    "source_redirect_chain": [],
                },
                dont_filter=True,
            )

    def _base_record(self, source):
        return {
            **self.run_context,
            "schema_version": "2.1",
            "source_id": source["id"],
            "provider": source["provider"],
            "category": source["category"],
            "source_url": source["url"],
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_cohort": "proven" if source["id"] in PROVEN_IDS else "candidate",
            "review_status": "unverified",
            "approved_for_advisor": False,
            "status": "needs_review",
            "error": "",
        }

    def _emit_status(self, record):
        if getattr(self, "crawler", None) is not None:
            self.crawler.stats.inc_value(f'agentfuse/status/{record["status"]}')
        return record

    def parse_page(self, response, source):
        record = self._base_record(source)
        meta = response.request.meta if response.request is not None else {}
        chain = list(meta.get("source_redirect_chain", []))
        record.update(
            final_url=_visible_url(response.url),
            http_status=response.status,
            redirect_chain=chain,
            content_type=response.headers.get(b"Content-Type", b"").decode(
                "utf-8", errors="replace")[:200],
            last_modified=response.headers.get(b"Last-Modified", b"").decode(
                "utf-8", errors="replace")[:150],
            etag=response.headers.get(b"ETag", b"").decode(
                "utf-8", errors="replace")[:200],
        )
        record.update(response_freshness(response.headers))

        # Do not silently follow all providers' domains as a shared allowlist.
        # Scrapy's general-purpose redirect and meta-refresh are disabled.
        if response.status in REDIRECT_CODES:
            raw_location = response.headers.get(b"Location", b"").decode(
                "latin-1", errors="replace")
            if not raw_location or len(raw_location) > 2048:
                record.update(status="redirect_needs_review", error="missing_or_long_redirect_location")
                yield self._emit_status(record)
                return
            target = urljoin(response.url, raw_location)
            if not _allowed_redirect(target, source):
                record.update(status="rejected_redirect", error="cross_host_or_non_https_redirect")
                yield self._emit_status(record)
                return
            depth = int(meta.get("source_redirect_depth", 0))
            if depth >= MAX_REDIRECTS or _visible_url(target) in chain + [_visible_url(response.url)]:
                record.update(status="redirect_needs_review", error="redirect_limit_or_loop")
                yield self._emit_status(record)
                return
            yield scrapy.Request(
                target,
                callback=self.parse_page,
                errback=self.record_failure,
                cb_kwargs={"source": source},
                meta={
                    "handle_httpstatus_all": True,
                    "dont_redirect": True,
                    "source_redirect_depth": depth + 1,
                    "source_redirect_chain": chain + [_visible_url(response.url)],
                },
                dont_filter=True,
            )
            return

        # Some servers return a landing page with 200 after redirect. The
        # same-origin host does not prove this is still the requested doc.
        if not _allowed_redirect(response.url, source):
            record.update(status="rejected_redirect", error="unexpected_final_host")
            yield self._emit_status(record)
            return
        if not 200 <= response.status < 300:
            record.update(status="http_error", error=f"HTTP {response.status}")
            yield self._emit_status(record)
            return
        if b"html" not in response.headers.get(b"Content-Type", b"text/html").lower():
            record.update(status="unsupported_content_type", error="expected_html")
            yield self._emit_status(record)
            return

        try:
            evidence = extract_evidence(response.text, source["url"])
        except Exception as exc:
            self.logger.warning("Failed extracting %s: %s", source["id"], exc)
            record.update(status="extraction_error", error=type(exc).__name__)
            yield self._emit_status(record)
            return

        text = evidence.pop("text")
        record.update(evidence)
        record["text_truncated"] = len(text) > HARD_TEXT_LIMIT

        flags = [str(f).lower() for f in response.flags]
        record["scrapy_response_flags"] = flags
        status, reason = assess_capture(
            source["category"], evidence, text,
            cache_warnings=record["freshness_warnings"],
            cached=any("cache" in f for f in flags),
        )
        if chain and urlsplit(_visible_url(response.url)).path.rstrip("/") != (
            urlsplit(source["url"]).path.rstrip("/")
        ):
            status, reason = "needs_review", "source_path_redirected"
        canonical = record.get("canonical_url") or ""
        if canonical and urlsplit(canonical).path.rstrip("/") != urlsplit(
            source["url"]
        ).path.rstrip("/"):
            status, reason = "needs_review", "canonical_path_differs"
        record.update(status=status, error=reason)

        if status in {"captured", "partial_capture"} or (
            status == "needs_review" and reason in {
                "no_dated_release_section_detected",
                "canonical_path_differs",
                "no_price_or_billing_detail_detected",
                "documentation_link_index_only",
            }
        ):
            record["text"] = text[:HARD_TEXT_LIMIT]
        else:
            # Keep a short diagnostic sample for shells and access challenges.
            # Substantive but undated release evidence is retained above for review.
            record["text_sample"] = text[:500]
        yield self._emit_status(record)

    def record_failure(self, failure):
        source = failure.request.cb_kwargs["source"]
        record = self._base_record(source)
        name = failure.type.__name__
        record.update(
            status="robots_or_policy_denied" if name == "IgnoreRequest" else "fetch_error",
            final_url="",
            http_status=None,
            error=name,
        )
        self.logger.warning("Failed fetching %s: %s", source["id"], failure.value)
        yield self._emit_status(record)


class DocumentationSpider(OfficialBaseSpider):
    name = "official_documentation"
    category = "documentation"


class PricingSpider(OfficialBaseSpider):
    name = "official_pricing"
    category = "pricing"


class ChangelogSpider(OfficialBaseSpider):
    name = "official_changelogs"
    category = "changelog"
