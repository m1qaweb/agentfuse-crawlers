"""Exactly three read-only official-source spiders, preserving original identities.

One fresh network request per reviewed source at each scheduled run.
An HTTP 200 is *not* a guarantee of source completeness, publication freshness,
truth, or approved advisor evidence. Access/policy failures remain visible.
"""

from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import scrapy

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.markdown_releases import (
    allowed_markdown_url, parse_markdown_releases,
)
from agentfuse_crawlers.recent_window import compact_changelog_record
from agentfuse_crawlers.pricing_evidence import (
    MAX_SELECTED_TABLES, compact_pricing_record,
)
from agentfuse_crawlers.documentation_scope import compact_documentation_record
from agentfuse_crawlers.provider_profiles import identify_source_product
from agentfuse_crawlers.run_context import build_run_context
from agentfuse_crawlers.diagnostics import derive_diagnostics
from agentfuse_crawlers.source_lifecycle import (
    COLLECTION_MODES, collection_decision, registry_revision_sha256,
    source_lifecycle,
)
from agentfuse_crawlers.quality import (
    HARD_TEXT_LIMIT, assess_capture, response_freshness,
)
from agentfuse_crawlers.sources import (
    load_proven_source_ids, load_sources, select_sources,
)
from agentfuse_crawlers.validation_access import (
    authorize_bulk_run, bulk_plan_revision_sha256,
    validation_access_decision, validation_access_revision_sha256,
)

ALLOWED_HOSTS = sorted({urlsplit(s["url"]).hostname for s in load_sources()})
PROVEN_IDS = load_proven_source_ids()
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 3


def _visible_url(raw_url):
    """Keep provenance URL host/path, not query tokens or fragments."""
    parts = urlsplit(raw_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _safe_redirect_review_target(raw_url):
    """A rejected redirect is review evidence, never a new fetch target."""
    try:
        parts = urlsplit(raw_url)
        if (parts.scheme != "https" or not parts.hostname or
                parts.username or parts.password or
                parts.port not in (None, 443)):
            return ""
        return urlunsplit(("https", parts.hostname, parts.path[:600] or "/", "", ""))
    except (TypeError, ValueError):
        return ""


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
                 confirm_full_inventory=None, expected_manifest_sha256=None,
                 expected_selection_ids_sha256=None, collection_mode="validation",
                 expected_source_registry_sha256=None, bulk_run_plan_id=None,
                 expected_bulk_plan_sha256=None,
                 expected_deployment_package_sha256=None, **kwargs):
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
        if collection_mode not in COLLECTION_MODES:
            raise ValueError("Invalid collection_mode")
        self.collection_mode = collection_mode
        self.source_registry_sha256 = registry_revision_sha256()
        if (expected_source_registry_sha256 is not None and
                expected_source_registry_sha256 != self.source_registry_sha256):
            raise ValueError("Source registry changed since validation plan")
        self.cohort = cohort
        self.offset = int(offset)
        self.run_context = build_run_context(
            self.name, cohort, self.selected, explicit_cohort=explicit_cohort,
        )
        # A validation plan pins both the complete source-registry revision and
        # the exact selected IDs. Prevent silently shifted offset/cohort batches.
        for provided, field in (
            (expected_manifest_sha256, "manifest_sha256"),
            (expected_selection_ids_sha256, "selection_ids_sha256"),
        ):
            if provided is not None and provided != self.run_context[field]:
                raise ValueError(
                    f"Run scope mismatch: {field} differs from pinned validation plan"
                )
        # P21B: the historic "proven" cohort is NOT a publisher policy
        # review. A single manual validation must identify exactly ONE source
        # and cannot be formed indirectly through limit/offset. EVERY other
        # validation scope (default three-source smoke, chunks, full category)
        # needs both independently Git-reviewed source access and an
        # exact-bound short-lived run approval. The two registries ship empty.
        ids = (
            [part.strip() for part in source_ids.split(",")]
            if isinstance(source_ids, str) else
            list(source_ids) if isinstance(source_ids, (list, tuple, set))
            else []
        )
        single = (
            len(ids) == 1 and ids[0] == self.selected[0]["id"]
            and len(self.selected) == 1 and limit is None and self.offset == 0
        )
        self.validation_scope = (
            "monitor" if collection_mode == "monitor"
            else "single_exact_source" if single
            else "bulk_reviewed_plan_required"
        )
        self.bulk_validation_required = (
            collection_mode == "validation" and not single
        )
        self.single_validation_required = (
            collection_mode == "validation" and single
        )
        self.bulk_plan_id = ""
        self.bulk_plan_sha256 = ""
        self.bulk_authorized_ids = frozenset()
        self.bulk_max_primary_requests = 0
        self.bulk_max_redirects_per_source = MAX_REDIRECTS
        self.bulk_plan_expires_at_utc = None
        self.validation_access_registry_sha256 = validation_access_revision_sha256()
        self.bulk_run_plan_registry_sha256 = bulk_plan_revision_sha256()
        if self.bulk_validation_required:
            decision = authorize_bulk_run(
                selected=self.selected, category=self.category, cohort=self.cohort,
                collection_mode=self.collection_mode, plan_id=bulk_run_plan_id,
                expected_plan_sha256=expected_bulk_plan_sha256,
                expected_package_sha256=expected_deployment_package_sha256,
                current_package_sha256=self.run_context["deployment_revision"],
            )
            self.bulk_plan_id = decision["plan_id"]
            self.bulk_plan_sha256 = decision["plan_sha256"]
            self.bulk_authorized_ids = decision["authorized_source_ids"]
            self.bulk_max_primary_requests = decision["max_primary_requests"]
            if self.bulk_plan_id:
                self.bulk_max_redirects_per_source = decision[
                    "max_redirects_per_source"
                ]
            self.bulk_plan_expires_at_utc = decision["plan_expires_at_utc"]
            self.bulk_gate_decision = decision["decision"]
        else:
            if (bulk_run_plan_id is not None or
                    expected_bulk_plan_sha256 is not None or
                    expected_deployment_package_sha256 is not None):
                raise ValueError(
                    "Bulk plan flags cannot grant single-source validation "
                    "or unattended monitoring"
                )
            self.bulk_gate_decision = "not_applicable_to_exact_single_or_monitor"

    async def start(self):
        """Required for Scrapy 2.18+; called on every scheduled job."""
        self.logger.info(
            "Starting %s: %d configured URLs (requested_cohort=%s, offset=%d, "
            "manifest=%s, selection=%s, job_id=%s, revision=%s)",
            self.category, len(self.selected), self.cohort, self.offset,
            self.run_context["manifest_sha256"][:12],
            self.run_context["selection_ids_sha256"][:12],
            self.run_context["zyte_job_id"] or "unknown",
            self.run_context["deployment_revision"][:12],
        )
        if self.category == "pricing":
            self.logger.info(
                "Pricing table evidence window: relevant_offset=%d, limit=%d",
                self.pricing_table_offset, self.pricing_table_limit,
            )
        primary_requests_issued = 0
        for source in self.selected:
            allowed, reason = collection_decision(source, self.collection_mode)
            if not allowed:
                record = self._base_record(source)
                status = ("source_quarantined"
                          if reason == "policy_unresolved_or_quarantined"
                          else "source_retired" if reason == "source_retired"
                          else "source_not_validated_for_monitor")
                record.update(
                    status=status, error=reason,
                    http_status=None, final_url="",
                    policy_observation="not_fetched_by_lifecycle_guard",
                )
                # Preserve one summary Item per selected source. Skipping
                # a network request must not silently shrink accounting.
                yield self._emit_status(record)
                continue
            # P23B: even one explicitly selected source must have an
            # existing, current, Git-reviewed exact-URL publisher access
            # decision with single_validation scope. An ID, CLI argument,
            # historical "proven" cohort or lifecycle status is not approval.
            if self.single_validation_required:
                single_allowed, single_reason = validation_access_decision(
                    source, scope="single_validation",
                )
                if not single_allowed:
                    record = self._base_record(source)
                    record.update(
                        status="source_single_validation_not_approved",
                        error=single_reason,
                        http_status=None,
                        final_url="",
                        policy_observation=(
                            "not_fetched_by_single_source_access_gate"
                        ),
                    )
                    yield self._emit_status(record)
                    continue
            if (self.bulk_validation_required
                    and source["id"] not in self.bulk_authorized_ids):
                record = self._base_record(source)
                record.update(
                    status="source_bulk_validation_not_approved",
                    error=("bulk_run_plan_not_present"
                           if not self.bulk_plan_id
                           else "bulk_source_not_in_authorized_scope"),
                    http_status=None, final_url="",
                    policy_observation="not_fetched_by_bulk_source_access_gate",
                )
                yield self._emit_status(record)
                continue
            if self.bulk_validation_required:
                primary_requests_issued += 1
                if primary_requests_issued > self.bulk_max_primary_requests:
                    raise ValueError(
                        "Bulk primary request count exceeds exact reviewed budget"
                    )
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
        profile = source_lifecycle(source)
        allowed_monitor, _ = collection_decision(source, "monitor")
        return {
            **self.run_context,
            "collection_mode": self.collection_mode,
            "source_registry_sha256": self.source_registry_sha256,
            "validation_scope": self.validation_scope,
            "bulk_validation_required": self.bulk_validation_required,
            "single_validation_access_required": self.single_validation_required,
            "bulk_access_registry_sha256": self.validation_access_registry_sha256,
            "bulk_run_plan_registry_sha256": self.bulk_run_plan_registry_sha256,
            "bulk_run_plan_id": self.bulk_plan_id,
            "bulk_run_plan_sha256": self.bulk_plan_sha256,
            "bulk_run_expires_at_utc": self.bulk_plan_expires_at_utc,
            "bulk_max_redirects_per_source": self.bulk_max_redirects_per_source,
            "bulk_source_authorized_by_reviewed_plan": bool(
                self.bulk_validation_required
                and source["id"] in self.bulk_authorized_ids
            ),
            "bulk_gate_decision": self.bulk_gate_decision,
            "source_lifecycle_state": profile["state"],
            "source_policy_status": profile["policy_status"],
            "source_lifecycle_reason": profile["reason_code"],
            "collection_eligible_for_unattended": allowed_monitor,
            "policy_observation": "not_yet_observed",
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
        record.update(derive_diagnostics(record))
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
                record.update(status="rejected_redirect", error="cross_host_or_non_https_redirect",
                              redirect_review_target=_safe_redirect_review_target(target))
                yield self._emit_status(record)
                return
            # P23D1B: BOTH single-source and bulk validation review the
            # exact original manifest URL, not every path on its hostname.
            # A plan's max_redirects_per_source is a resource ceiling, NOT
            # permission to request another URL. Deny changed query,
            # path, scheme, or port even if the host is first party.
            # Legacy monitoring retains separate, pre-existing handling.
            if ((self.single_validation_required or self.bulk_validation_required)
                    and target != source["url"]):
                record.update(
                    status="redirect_needs_review",
                    error=(
                        "single_source_redirect_target_requires_review"
                        if self.single_validation_required else
                        "bulk_source_redirect_target_requires_review"
                    ),
                    policy_observation=(
                        "redirect_not_fetched_without_exact_url_review"
                    ),
                    redirect_review_target=_safe_redirect_review_target(target),
                )
                yield self._emit_status(record)
                return
            if self.single_validation_required:
                still_allowed, single_reason = validation_access_decision(
                    source, scope="single_validation",
                )
                if not still_allowed:
                    record.update(
                        status="redirect_needs_review",
                        error=single_reason,
                        policy_observation=(
                            "redirect_not_fetched_due_to_source_access_gate"
                        ),
                    )
                    yield self._emit_status(record)
                    return
            depth = int(meta.get("source_redirect_depth", 0))
            if depth >= self.bulk_max_redirects_per_source or _visible_url(target) in chain + [_visible_url(response.url)]:
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

        # Defense in depth: even if a callback is handed a different
        # first-party final URL by middleware or a third-party downloader,
        # the exact-URL human review for validation cannot cover its HTML.
        # Do not run extractors or attach substantive content to that Item.
        if ((self.single_validation_required or self.bulk_validation_required)
                and response.url != source["url"]):
            record.update(
                status="redirect_needs_review",
                error="unreviewed_validation_response_url",
                policy_observation="response_url_not_in_exact_review_scope",
                redirect_review_target=_safe_redirect_review_target(response.url),
            )
            yield self._emit_status(record)
            return
        # Some servers return a landing page with 200 after redirect. The
        # same-origin host does not prove this is still the requested doc.
        if not _allowed_redirect(response.url, source):
            record.update(status="rejected_redirect", error="unexpected_final_host")
            yield self._emit_status(record)
            return
        if response.status == 429:
            record.update(status="source_access_limited", error="HTTP 429",
                          policy_observation="content_endpoint_rate_limited")
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
            evidence = extract_evidence(
                response.text, source["url"], category=source["category"],
                source_id=source["id"],
                pricing_table_window=(
                    {"table_offset": self.pricing_table_offset,
                     "table_limit": self.pricing_table_limit}
                    if source["category"] == "pricing" else None
                ),
            )
        except Exception as exc:
            self.logger.warning("Failed extracting %s: %s", source["id"], exc)
            record.update(status="extraction_error", error=type(exc).__name__)
            yield self._emit_status(record)
            return

        # P16A: a source ID is only an unverified expected product mapping.
        # Title/DOM-derived family cues NEVER select a different scraper or
        # grant advisor access. Persist them for independent publisher review.
        identity = identify_source_product(source, evidence)
        text = evidence.pop("text")
        record.update(evidence)
        record.update(identity)
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
        if (canonical and urlsplit(canonical).path.rstrip("/") != urlsplit(
            source["url"]
        ).path.rstrip("/") and not (
            source["category"] == "documentation"
            and record.get("documentation_canonical_relation") == "equivalent_path"
        )):
            status, reason = "needs_review", "canonical_path_differs"
        if identity["source_product_title_conflict"]:
            # A first-party host may serve the wrong product/landing page.
            # Retain the conflict rather than treating HTTP 200 as ownership.
            status, reason = "needs_review", "source_product_title_conflict"
        record.update(status=status, error=reason)
        # Include diagnostics in Item-size compaction, not as hidden overage.
        record.update(derive_diagnostics(record))

        if (source["category"] == "changelog"
                and allowed_markdown_url(source)
                # A Markdown alternate is a DIFFERENT publisher URL and
                # is not covered by an exact source-URL bulk access review.
                # Until separately approved, bulk jobs may NOT fetch it.
                and not self.bulk_validation_required
                # Single-source source_url review does not authorize the
                # separately hosted/path-scoped Markdown alternate URL.
                and not self.single_validation_required
                and status not in {"blocked", "robots_or_policy_denied"}
                and (not evidence.get("release_window_complete")
                     or evidence.get("release_event_count", 0) < 2)
                and (len(text) > HARD_TEXT_LIMIT
                     or not evidence.get("release_event_count"))):
            # Only the single allowlisted publisher-host Markdown URL may be
            # used; this is a format alternate, never a robot/captcha bypass.
            primary_record = compact_changelog_record(record, text, keep_text=True)
            primary_record["markdown_alternate_attempted"] = True
            yield scrapy.Request(
                allowed_markdown_url(source),
                callback=self.parse_official_markdown,
                errback=self.markdown_fetch_failed,
                cb_kwargs={"source": source, "primary": primary_record},
                meta={"handle_httpstatus_all": True, "dont_redirect": True},
                dont_filter=True,
                headers={"Accept": "text/markdown,text/plain;q=0.9"},
            )
            return

        if status in {"captured", "partial_capture"} or (
            status == "needs_review" and reason in {
                "no_dated_release_section_detected",
                "canonical_path_differs",
                "no_price_or_billing_detail_detected",
                "documentation_link_index_only",
                "documentation_scope_not_established",
                "documentation_product_scope_ambiguous",
                "no_release_events_detected",
                "release_events_missing_publication_dates",
                "latest_release_date_ambiguous",
                "release_event_identity_collision",
            }
        ):
            record["text"] = text[:HARD_TEXT_LIMIT]
        else:
            # Keep a short diagnostic sample for shells and access challenges.
            # Substantive but undated release evidence is retained above for review.
            record["text_sample"] = text[:500]
        if source["category"] == "changelog":
            record = compact_changelog_record(
                record, text, keep_text="text" in record,
            )
        if source["category"] == "pricing":
            try:
                record = compact_pricing_record(record, text)
            except ValueError:
                record = self._base_record(source)
                record.update(
                    status="partial_capture", error="pricing_item_budget_exceeded",
                    pricing_evidence_lost_to_item_budget=True,
                    content_sha256=evidence.get("content_sha256", ""),
                    final_url=_visible_url(response.url),
                    http_status=response.status,
                )
        if source["category"] == "documentation":
            try:
                record = compact_documentation_record(record, text)
            except ValueError:
                record = self._base_record(source)
                record.update(
                    status="partial_capture",
                    error="documentation_item_budget_exceeded",
                    documentation_item_budget_truncated=True,
                    content_sha256=evidence.get("content_sha256", ""),
                    final_url=_visible_url(response.url),
                    http_status=response.status,
                )
        yield self._emit_status(record)

    def parse_official_markdown(self, response, source, primary):
        """Use exact vetted same-domain Markdown only; no generic discovery."""
        alternate = allowed_markdown_url(source)
        if (not alternate or response.url != alternate
                or not _allowed_redirect(response.url, source)):
            primary["markdown_alternate_result"] = "rejected_url"
            yield self._emit_status(primary)
            return
        if response.status != 200:
            primary["markdown_alternate_result"] = "http_error"
            primary["markdown_alternate_http_status"] = response.status
            yield self._emit_status(primary)
            return
        kind = response.headers.get(b"Content-Type", b"").decode(
            "latin-1", errors="replace",
        ).lower()
        if not any(x in kind for x in ("text/markdown", "text/plain", "text/x-markdown")):
            primary["markdown_alternate_result"] = "unsupported_content_type"
            yield self._emit_status(primary)
            return
        try:
            evidence = parse_markdown_releases(
                response.text, source["id"], source["url"], alternate,
            )
        except Exception as exc:
            self.logger.warning("Unable to read official Markdown %s: %s",
                                source["id"], type(exc).__name__)
            primary["markdown_alternate_result"] = type(exc).__name__
            yield self._emit_status(primary)
            return

        if evidence.get("release_event_count", 0) == 0:
            primary["markdown_alternate_result"] = "no_structured_versions"
            yield self._emit_status(primary)
            return

        record = dict(primary)
        record.update(evidence)
        record.update(response_freshness(response.headers))
        record.update(
            markdown_alternate_result="structured_version_evidence",
            final_url=_visible_url(response.url),
            content_type=kind[:200],
            markdown_source_url=alternate,
            markdown_html_source_url=source["url"],
            markdown_alternate_http_status=200,
            # The HTML fetch remains an evidence source with different scope.
            html_source_hash=primary.get("content_sha256", ""),
            http_status=200,
            last_modified=response.headers.get(b"Last-Modified", b"").decode(
                "latin-1", errors="replace")[:150],
            etag=response.headers.get(b"ETag", b"").decode(
                "latin-1", errors="replace")[:200],
        )
        content = record.pop("text")
        cached = any("cache" in str(x).lower() for x in response.flags)
        status, reason = assess_capture(
            "changelog", evidence, content,
            cache_warnings=record["freshness_warnings"], cached=cached,
        )
        record.update(status=status, error=reason)
        record = compact_changelog_record(record, content, keep_text=True)
        yield self._emit_status(record)

    def markdown_fetch_failed(self, failure):
        """A denied alternate never erases the original source observation."""
        primary = failure.request.cb_kwargs["primary"]
        primary["markdown_alternate_result"] = failure.type.__name__
        yield self._emit_status(primary)

    def record_failure(self, failure):
        source = failure.request.cb_kwargs["source"]
        record = self._base_record(source)
        name = failure.type.__name__
        record.update(
            status="robots_or_policy_denied" if name == "IgnoreRequest" else "fetch_error",
            policy_observation=("blocked_by_middleware" if name == "IgnoreRequest"
                                else "fetch_failure_unknown_policy"),
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

    def __init__(self, pricing_table_offset=None, pricing_table_limit=None,
                 **kwargs):
        super().__init__(**kwargs)
        raw_offset = "0" if pricing_table_offset is None else str(pricing_table_offset)
        raw_limit = (str(MAX_SELECTED_TABLES) if pricing_table_limit is None
                     else str(pricing_table_limit))
        if (not raw_offset.isascii() or not raw_offset.isdecimal()
                or not raw_limit.isascii() or not raw_limit.isdecimal()):
            raise ValueError("pricing table offset and limit must be decimal integers")
        self.pricing_table_offset = int(raw_offset)
        self.pricing_table_limit = int(raw_limit)
        if (self.pricing_table_offset > 700
                or not 1 <= self.pricing_table_limit <= MAX_SELECTED_TABLES):
            raise ValueError("pricing table window must be offset=0..700, limit=1..64")


class ChangelogSpider(OfficialBaseSpider):
    name = "official_changelogs"
    category = "changelog"
