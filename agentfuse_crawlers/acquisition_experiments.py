"""P16B: unapproved, pinned acquisition-method experiments.

All entries are *proposals* for manual, publisher-policy-reviewed capture.
The live Scrapy spiders do NOT select browser rendering, a new API or
additional URLs from this file. The sole Markdown alternate already exists
in the original changelog spider and remains restricted to its allowlist.

An acquisition registry hypothesis is never product ownership, a verified
fact, a crawl authorization, or automatic method-selection permission.
"""
import hashlib
import ipaddress
import json
import re
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit

from agentfuse_crawlers.markdown_releases import allowed_markdown_url
from agentfuse_crawlers.source_lifecycle import source_lifecycle
from agentfuse_crawlers.sources import load_sources

SCHEMA = "1.0"
REVISION = "p16b_acquisition_experiments_offline_v1"
REGISTRY_FILE = "data/acquisition_experiments_v1.json"
MAX_EXPERIMENTS = 16
METHODS = frozenset({"rendered_html", "official_markdown"})
CATEGORIES = frozenset({"documentation", "pricing", "changelog"})
ROOT_FIELDS = frozenset({
    "schema_version", "revision", "description",
    "source_ids_in_manifest_unchanged", "no_new_source_registry_urls",
    "automatic_scheduling_enabled", "approved_for_live_acquisition",
    "approved_for_advisor", "experiments",
})
EXPERIMENT_FIELDS = frozenset({
    "experiment_id", "source_id", "category", "official_source_url",
    "candidate_acquisition_method", "candidate_url",
    "candidate_issue_hypothesis_unverified",
    "operator_publisher_access_review_status",
    "operator_browser_render_budget_review_status",
    "approved_for_live_acquisition", "enabled_in_scrapy",
    "source_product_owner_verified", "approved_for_advisor",
})
EXPERIMENT_ID = re.compile(r"^p16b_[a-z][a-z0-9_]{2,90}$")
ISSUE = re.compile(r"^[a-z][a-z0-9_]{8,110}$")


def _safe_official_https(url, expected_host):
    """No query tokens, credentials, fragments, IPs or arbitrary ports."""
    if not isinstance(url, str) or not 12 <= len(url) <= 950:
        return False
    try:
        target = urlsplit(url)
        if (target.scheme != "https"
                or target.hostname != expected_host
                or target.username is not None or target.password is not None
                or target.port not in (None, 443)
                or target.query or target.fragment
                or target.netloc.lower() != expected_host
                or "\\" in target.path or "%" in target.path
                or "//" in target.path):
            return False
        try:
            ipaddress.ip_address(target.hostname)
            return False
        except ValueError:
            pass
        if not target.path.startswith("/"):
            return False
        return True
    except (ValueError, TypeError):
        return False


def _load_registry():
    return json.loads(files("agentfuse_crawlers").joinpath(
        REGISTRY_FILE
    ).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def acquisition_registry_sha256():
    raw = files("agentfuse_crawlers").joinpath(REGISTRY_FILE).read_bytes()
    return hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=1)
def load_acquisition_experiments():
    data = _load_registry()
    if (not isinstance(data, dict) or set(data) != ROOT_FIELDS
            or data["schema_version"] != SCHEMA
            or data["revision"] != REVISION
            or not isinstance(data["description"], str)
            or not data["description"].strip()
            or data["source_ids_in_manifest_unchanged"] != 460
            or data["no_new_source_registry_urls"] is not True
            or any(data[key] is not False for key in (
                "automatic_scheduling_enabled",
                "approved_for_live_acquisition", "approved_for_advisor"
            ))):
        raise ValueError("Acquisition registry has invalid schema or unsafe flags")
    raw = data["experiments"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_EXPERIMENTS:
        raise ValueError("Acquisition registry experiment count out of bounds")
    manifest = {x["id"]: x for x in load_sources()}
    if len(manifest) != 460:
        raise ValueError("Source manifest baseline changed")
    result = {}
    experiment_ids = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != EXPERIMENT_FIELDS:
            raise ValueError("Unknown or missing experiment fields")
        sid, exp_id = entry["source_id"], entry["experiment_id"]
        src = manifest.get(sid) if isinstance(sid, str) else None
        if (src is None or not isinstance(exp_id, str)
                or not EXPERIMENT_ID.fullmatch(exp_id)
                or exp_id in experiment_ids or sid in result
                or entry["category"] not in CATEGORIES
                or entry["category"] != src["category"]
                or entry["official_source_url"] != src["url"]
                or entry["candidate_acquisition_method"] not in METHODS
                or not isinstance(entry["candidate_issue_hypothesis_unverified"], str)
                or not ISSUE.fullmatch(entry["candidate_issue_hypothesis_unverified"])):
            raise ValueError("Acquisition experiment source/category/ID not pinned")
        if source_lifecycle(src)["state"] in {"quarantined", "retired"}:
            raise ValueError("Blocked publisher source must not get an experiment")
        candidate_url = entry["candidate_url"]
        host = urlsplit(src["url"]).hostname
        if not _safe_official_https(candidate_url, host):
            raise ValueError("Acquisition experiment candidate is not a pinned safe URL")
        method = entry["candidate_acquisition_method"]
        if method == "rendered_html" and candidate_url != src["url"]:
            raise ValueError("Rendered HTML must use original exact manifest URL")
        if method == "official_markdown" and (
            entry["category"] != "changelog"
            or allowed_markdown_url(src) != candidate_url
        ):
            raise ValueError("Unreviewed/unallowlisted publisher Markdown alternate")
        if (entry["operator_publisher_access_review_status"] != "pending"
                or entry["operator_browser_render_budget_review_status"] != "pending"
                or any(entry[key] is not False for key in (
                    "approved_for_live_acquisition", "enabled_in_scrapy",
                    "source_product_owner_verified", "approved_for_advisor"
                ))):
            raise ValueError("Acquisition experiment cannot auto-approve, run or publish")
        result[sid] = dict(entry)
        experiment_ids.add(exp_id)
    return result


def acquire_method_plan():
    """Produce a read-only operator checklist, not runnable Scrapy Args."""
    registry = load_acquisition_experiments()
    jobs = []
    for sid, experiment in sorted(registry.items()):
        method = experiment["candidate_acquisition_method"]
        jobs.append({
            "experiment_id": experiment["experiment_id"],
            "source_id": sid,
            "category": experiment["category"],
            "static_request_url": experiment["official_source_url"],
            "alternate_method": method,
            "alternate_request_url": experiment["candidate_url"],
            "snapshot_media_type": (
                "text/markdown" if method == "official_markdown" else "text/html"
            ),
            "requires_operator_access_and_budget_review": True,
            "robots_terms_and_authentication_bypass_prohibited": True,
            "manual_snapshot_only_no_network_operation": True,
            "approved_for_advisor": False,
        })
    return {
        "schema_version": SCHEMA,
        "kind": "p16b_review_only_offline_acquisition_comparison_plan",
        "registry_sha256": acquisition_registry_sha256(),
        "experiments": jobs,
        "planned_sources": len(jobs),
        "manually_authorized_acquisition_jobs": 0,
        "automatic_rendered_html_requests": 0,
        "automatic_markdown_discovery_requests": 0,
        "automatic_feed_requests": 0,
        "network_requests_performed": 0,
        "approved_for_advisor": False,
        "deployment_authorized": False,
    }
