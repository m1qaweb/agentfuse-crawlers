"""P18A2: manual ORIGINAL documentation HTML capture after exact human review.

Default CLI only validates registry and prints a read-only plan. Capturing
requires both a separately reviewed, P18A1-bound exact page entry and an
explicit operator --capture --policy-reviewed attestation. The committed
registry is empty. Never run an automatic spider/job from these entries.

Captured HTML is untrusted publisher input; NO capability or advisor
approval is conferred by collection, HTTP 200, review claims or SHA-256.
"""
import argparse
import hashlib
import ipaddress
import json
import re
import shutil
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from agentfuse_crawlers.documentation_scope import (
    TOPIC_PATTERNS, canonical_relationship,
)
from agentfuse_crawlers.provider_profiles import (
    load_provider_profiles, provider_profiles_sha256,
)
from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from scripts.capture_pricing_html import (
    NoRedirect, AGENT, _fetch_exact, _host, _private_exclusive_directory,
    _robots_check, _write_new_private_file,
)
from scripts.plan_documentation_children import (
    KIND as PACKET_KIND, VERSION, _candidate_id, _json_sha,
    _pinned_documentation, _strict_child_url, _task_id, HEX64,
)

KIND = "p18a2_exact_reviewed_documentation_pages_manual_only"
REGISTRY_KEYS = frozenset({
    "schema_version", "kind", "approved_for_advisor",
    "automatic_collection_enabled", "entries",
})
ENTRY_KEYS = frozenset({
    "page_id", "source_id", "source_url", "product_id",
    "child_url", "task_id", "parent_snapshot_sha256",
    "review_packet_sha256", "policy_review", "product_review",
    "capture_method", "approved_for_manual_capture",
    "approved_for_unattended_collection", "approved_for_advisor",
})
POLICY_KEYS = frozenset({
    "decision", "publisher_policy_evidence_url", "reviewed_by",
    "reviewed_at_utc", "expires_at_utc", "review_note",
})
PRODUCT_KEYS = frozenset({
    "decision", "reviewed_by", "reviewed_at_utc",
    "official_canonical_url", "locale", "version", "technical_topic",
})
DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / (
    "registries/approved_doc_pages_v1.json"
)
MAX_REGISTRY_BYTES = 160_000
MAX_PACKET_BYTES = 2_000_000
MAX_ENTRIES = 60
MAX_CAPTURE = 5
MAX_POLICY_NOTE = 500
MAX_REVIEW_AGE_DAYS = 90
MAX_TEXT_BYTES = 8_000_000
ID = re.compile(r"^[a-f0-9]{24}$")
LOCALE = re.compile(r"^[a-zA-Z]{2,5}(?:-[a-zA-Z0-9]{2,12})?$")
VERSION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,39}$")
REVIEWER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_ .@-]{2,89}$")
CHALLENGE_HEADINGS = {
    "just a moment", "access denied", "verify you are human",
    "captcha", "checking your browser", "attention required",
}


def page_id(source_id, url):
    """Stable page identity, not an automatically approved source ID."""
    return hashlib.sha256(
        (source_id + "|docs-page|" + url).encode("utf-8")
    ).hexdigest()[:24]


def _utc(value, label):
    if (not isinstance(value, str) or not 12 <= len(value) <= 45):
        raise ValueError("Invalid " + label + " timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid " + label + " timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone-aware " + label + " is mandatory")
    return parsed.astimezone(timezone.utc)


def _now_utc(now=None):
    current = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("Validation clock must be timezone aware")
    return current.astimezone(timezone.utc)


def _evidence_url(value):
    """Policy evidence URL is descriptive only and is NEVER fetched."""
    if (not isinstance(value, str) or len(value) > 450
            or not value.startswith("https://") or not value.isascii()
            or any(c in value for c in ("%", "\\", "?", "#"))
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
        raise ValueError("Unsafe publisher policy evidence URL")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("Malformed policy evidence URL") from exc
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not parsed.path.startswith("/")):
        raise ValueError("Invalid policy evidence origin")
    hostname = parsed.hostname.lower()
    if (hostname == "localhost" or hostname.endswith(
            (".localhost", ".local", ".internal")
        ) or "." not in hostname):
        raise ValueError("Nonpublic policy evidence hostname")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return value
    raise ValueError("Numeric policy evidence hosts are forbidden")


def _valid_packet(packet, docs, profiles):
    if not isinstance(packet, dict):
        raise ValueError("Original P18A1 review packet is required")
    original = dict(packet)
    checksum = original.pop("packet_sha256", None)
    if (not isinstance(checksum, str) or not HEX64.fullmatch(checksum)
            or _json_sha(original) != checksum
            or packet.get("schema_version") != VERSION
            or packet.get("kind") != PACKET_KIND
            or packet.get("expected_manifest_sha256") != manifest_sha256()
            or packet.get("expected_source_lifecycle_sha256") != registry_revision_sha256()
            or packet.get("expected_provider_profile_sha256") != provider_profiles_sha256()
            or packet.get("expected_documentation_source_count") != 194
            or packet.get("approved_for_crawl") is not False
            or packet.get("approved_for_advisor") is not False
            or packet.get("new_fetch_permissions") != 0
            or not isinstance(packet.get("tasks"), list)
            or packet.get("review_task_count") != len(packet["tasks"])):
        raise ValueError("P18A1 packet integrity, identity or privilege mismatch")
    selected = packet.get("selected_source_ids")
    tasks = packet.get("tasks")
    if (not isinstance(selected, list) or len(selected) > 194
            or any(not isinstance(x, str) or x not in docs for x in selected)
            or selected != sorted(set(selected))
            or not isinstance(tasks, list) or len(tasks) > 400):
        raise ValueError("Unbounded or invalid review-packet source inventory")
    mapping, urls = {}, set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Malformed P18A1 review task")
        sid, url = task.get("source_id"), task.get("candidate_url")
        source = docs.get(sid) if isinstance(sid, str) else None
        profile = profiles.get(sid) if source else None
        if not source or not profile or sid not in selected:
            raise ValueError("Review packet contains unprofiled or foreign source")
        _strict_child_url(source, url)
        if (task.get("source_url") != source["url"]
                or task.get("provider") != source["provider"]
                or task.get("product_id_unverified") != profile["product_id"]
                or task.get("task_id") != _task_id(sid, profile["product_id"], url)
                or task.get("review_status") !=
                    "pending_independent_policy_and_product_review"
                or task.get("approved_for_crawl") is not False
                or task.get("approved_for_advisor") is not False
                or task.get("product_ownership_independently_verified") is not False):
            raise ValueError("Review packet task attribution or privilege mismatch")
        key = (sid, url)
        if key in mapping or url in urls:
            raise ValueError("Repeated or cross-owned documentation review URL")
        mapping[key] = task
        urls.add(url)
    return mapping


def validate_registry(registry, packet=None, *, now=None):
    """Validate *all* reviewed entries. No network, privilege or promotion."""
    current = _now_utc(now)
    if (not isinstance(registry, dict) or set(registry) != REGISTRY_KEYS
            or registry.get("schema_version") != VERSION
            or registry.get("kind") != KIND
            or registry.get("approved_for_advisor") is not False
            or registry.get("automatic_collection_enabled") is not False
            or not isinstance(registry.get("entries"), list)
            or len(registry["entries"]) > MAX_ENTRIES):
        raise ValueError("Malformed or privileged child-pages registry")
    docs = _pinned_documentation()
    profiles = load_provider_profiles()
    if registry["entries"] and packet is None:
        raise ValueError("Nonempty registry requires matching original P18A1 packet")
    tasks = _valid_packet(packet, docs, profiles) if packet is not None else {}
    recognized = []
    seen_ids, seen_urls = set(), set()
    for entry in registry["entries"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ValueError("Malformed child page approval entry")
        sid = entry.get("source_id")
        source = docs.get(sid) if isinstance(sid, str) else None
        profile = profiles.get(sid) if source else None
        if not source or not profile or profile["category"] != "documentation":
            raise ValueError("Child approval requires exact pinned docs/product source")
        allowed, lifecycle_reason = collection_decision(source, mode="validation")
        if not allowed:
            raise ValueError("Publisher source policy forbids manual validation")
        url = _strict_child_url(source, entry.get("child_url"))
        key = (sid, url)
        task = tasks.get(key)
        if task is None:
            raise ValueError("Child URL was not in exact original P18A1 review packet")
        if (entry["source_url"] != source["url"]
                or entry["product_id"] != profile["product_id"]
                or entry["page_id"] != page_id(sid, url)
                or entry["task_id"] != task["task_id"]
                or entry["parent_snapshot_sha256"] !=
                    task.get("parent_snapshot_sha256_unverified")
                or not isinstance(entry["parent_snapshot_sha256"], str)
                or not HEX64.fullmatch(entry["parent_snapshot_sha256"])
                or entry["review_packet_sha256"] != packet["packet_sha256"]
                or entry["capture_method"] != "static_html"
                or entry["approved_for_manual_capture"] is not True
                or entry["approved_for_unattended_collection"] is not False
                or entry["approved_for_advisor"] is not False):
            raise ValueError("Page registry differs from reviewed exact URL/task or claims privileges")
        if entry["page_id"] in seen_ids or url in seen_urls:
            raise ValueError("Repeated page identity or URL in approved registry")
        seen_ids.add(entry["page_id"])
        seen_urls.add(url)
        policy = entry.get("policy_review")
        product = entry.get("product_review")
        if (not isinstance(policy, dict) or set(policy) != POLICY_KEYS
                or not isinstance(product, dict) or set(product) != PRODUCT_KEYS
                or policy.get("decision") != "permitted_single_manual_static_capture"
                or product.get("decision") != "exact_product_page_reviewed"):
            raise ValueError("Missing exact manual publisher-policy/product review")
        for review in (policy, product):
            if (not isinstance(review.get("reviewed_by"), str)
                    or not REVIEWER.fullmatch(review["reviewed_by"])):
                raise ValueError("Missing human reviewer identifier")
            if _utc(review["reviewed_at_utc"], "review") > current:
                raise ValueError("Future-dated human approval is not valid")
        reviewed_at = _utc(policy["reviewed_at_utc"], "policy review")
        expires_at = _utc(policy["expires_at_utc"], "policy expiry")
        if (reviewed_at > current or expires_at <= current
                or expires_at <= reviewed_at
                or expires_at - reviewed_at > timedelta(days=MAX_REVIEW_AGE_DAYS)
                or current - _utc(product["reviewed_at_utc"], "product review")
                    > timedelta(days=MAX_REVIEW_AGE_DAYS)):
            raise ValueError("Publisher policy or product ownership review expired")
        _evidence_url(policy["publisher_policy_evidence_url"])
        if (not isinstance(policy.get("review_note"), str)
                or not 40 <= len(policy["review_note"].strip()) <= 600):
            raise ValueError("Substantive publisher policy review note required")
        canonical = product.get("official_canonical_url")
        if (not isinstance(canonical, str)
                or not canonical.isascii()
                or any(c in canonical for c in ("?", "#", "%", "\\")) 
                or canonical_relationship(url, canonical)["relation"] !=
                    "equivalent_path"):
            raise ValueError("Publisher canonical change requires separate review")
        if (not isinstance(product.get("locale"), str)
                or not LOCALE.fullmatch(product["locale"])
                or not isinstance(product.get("version"), str)
                or not VERSION_RE.fullmatch(product["version"])
                or product.get("technical_topic") not in TOPIC_PATTERNS):
            raise ValueError("Missing page locale/version or recognized technical topic")
        recognized.append({
            "page_id": entry["page_id"],
            "source_id": sid,
            "source_url": source["url"],
            "child_url": url,
            "product_id": profile["product_id"],
            "review_packet_sha256": packet["packet_sha256"],
            "parent_snapshot_sha256": entry["parent_snapshot_sha256"],
            "reviewed_at_utc": reviewed_at.isoformat(),
            "review_expires_at_utc": expires_at.isoformat(),
            "locale": product["locale"],
            "version": product["version"],
            "technical_topic": product["technical_topic"],
            "source_policy_validation_status": lifecycle_reason,
            "approved_for_advisor": False,
        })
    return recognized


def capture_plan(registry, packet=None, page_ids=None, *, now=None):
    """Read-only plan: never turn an approved URL into a scheduled crawl."""
    approved = validate_registry(registry, packet, now=now)
    if page_ids is None:
        selected = []
    else:
        if (not isinstance(page_ids, (list, tuple))
                or not 1 <= len(page_ids) <= MAX_CAPTURE
                or any(not isinstance(x, str) or not ID.fullmatch(x) for x in page_ids)
                or len(set(page_ids)) != len(page_ids)):
            raise ValueError("Select 1-5 distinct exact approved page IDs")
        by_id = {x["page_id"]: x for x in approved}
        selected = []
        for pid in page_ids:
            if pid not in by_id:
                raise ValueError("Unknown or unapproved exact page ID: " + pid)
            selected.append(by_id[pid])
    return {
        "schema_version": VERSION,
        "kind": "p18a2_read_only_manual_doc_capture_plan",
        "registry_sha256": _json_sha(registry),
        "review_packet_sha256": packet["packet_sha256"] if packet else None,
        "expected_manifest_sha256": manifest_sha256(),
        "expected_source_lifecycle_sha256": registry_revision_sha256(),
        "expected_provider_profile_sha256": provider_profiles_sha256(),
        "reviewed_registry_entries": len(approved),
        "pages_selected_for_manual_capture": selected,
        "selected_count": len(selected),
        "max_pages_per_explicit_capture": MAX_CAPTURE,
        "network_requests_performed": 0,
        "new_spider_sources": 0,
        "automatic_collection_enabled": False,
        "advisor_approved_facts": 0,
        "approved_for_advisor": False,
    }


class _HTMLSafety(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonicals = []
        self.refresh = False
        self._active = None
        self.headings = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and "canonical" in (
            (values.get("rel") or "").casefold().split()
        ):
            self.canonicals.append(values.get("href") or "")
        if (tag == "meta" and (values.get("http-equiv") or "").casefold()
                == "refresh"):
            self.refresh = True
        if tag in {"title", "h1"}:
            self._active = tag

    def handle_endtag(self, tag):
        if tag == self._active:
            self._active = None

    def handle_data(self, data):
        if self._active and len(self.headings) < 25:
            self.headings.append(data[:200])


def _inspect_html(html, exact_url):
    """Refuse canonical drift/challenges; never follow embedded links or code."""
    if not isinstance(html, str) or len(html) > MAX_TEXT_BYTES:
        raise ValueError("Unbounded documentation response")
    parser = _HTMLSafety()
    parser.feed(html)
    if parser.refresh:
        raise ValueError("Meta refresh requires manual URL review")
    for title in parser.headings:
        heading = " ".join(title.casefold().split()).strip(" .:-")
        if any(heading == marker or heading.startswith(marker + " ")
               for marker in CHALLENGE_HEADINGS):
            raise ValueError("Access challenge is not a permitted docs snapshot")
    if len(parser.canonicals) > 1:
        raise ValueError("Ambiguous multiple canonical links")
    if not parser.canonicals:
        return "canonical_absent_requires_review"
    href = parser.canonicals[0].strip()
    if not href or href.startswith("//") or any(
        ch in href for ch in ("?", "#", "%", "\\")
    ):
        raise ValueError("Unsafe publisher canonical")
    resolved = urljoin(exact_url, href)
    if canonical_relationship(exact_url, resolved)["relation"] != "equivalent_path":
        raise ValueError("Publisher canonical moved outside approved page")
    return "equivalent_publisher_canonical_observed"


def capture_documentation_pages(registry, packet, page_ids, out_dir, *,
                                policy_review_note, opener=None, sleep_fn=None,
                                clock=None):
    """One manual batch only. No unattended collection or fact normalization."""
    current_clock = clock if clock is not None else (
        lambda: datetime.now(timezone.utc)
    )
    now = _now_utc(current_clock())
    plan = capture_plan(registry, packet, page_ids, now=now)
    if plan["selected_count"] == 0:
        raise ValueError("No explicitly selected and reviewed documentation pages")
    if (not isinstance(policy_review_note, str)
            or not 30 <= len(policy_review_note.strip()) <= MAX_POLICY_NOTE):
        raise ValueError("Capture needs substantive independent operator policy note")
    destination = Path(out_dir)
    if destination.exists() or destination.is_symlink() or any(
        parent.is_symlink() for parent in destination.parents
    ):
        raise ValueError("A new private non-symlink output directory is required")
    checkout = Path(__file__).resolve().parents[1]
    absolute = destination.resolve(strict=False)
    if absolute.is_relative_to(checkout) and not absolute.is_relative_to(
        checkout / "output"
    ):
        raise ValueError("Raw publisher HTML cannot be stored in tracked repo paths")

    op = opener if opener is not None else urllib.request.build_opener(NoRedirect)
    sleeper = sleep_fn if sleep_fn is not None else time.sleep
    robots_by_host, preflight = {}, []
    # Robots for exact child paths are checked BEFORE any HTML request.
    for entry in plan["pages_selected_for_manual_capture"]:
        child = {"id": entry["page_id"], "url": entry["child_url"]}
        host = _host(child)
        if host not in robots_by_host:
            robots_by_host[host] = _robots_check(child, op)
        if not robots_by_host[host]["parser"].can_fetch(AGENT, child["url"]):
            raise ValueError("Publisher robots disallows exact documentation child")
        preflight.append((entry, host))
    target = _private_exclusive_directory(out_dir)
    snapshots, receipts = [], []
    try:
        for entry, host in preflight:
            # A policy approval can expire during a long multi-page batch.
            # Re-check the authoritative review before each exact GET.
            validate_registry(registry, packet, now=_now_utc(current_clock()))
            robot = robots_by_host[host]
            sleeper(robot["delay_seconds"])
            payload, response, html = _fetch_exact(
                entry["child_url"], op, robots=False,
            )
            canonical_status = _inspect_html(html, entry["child_url"])
            sha = hashlib.sha256(payload).hexdigest()
            name = entry["page_id"] + "-" + sha[:20] + ".html"
            _write_new_private_file(target / name, payload)
            timestamp = _now_utc(current_clock()).isoformat()
            snapshots.append({
                "page_id": entry["page_id"],
                "source_id": entry["source_id"],
                "product_id_reviewed_manual_only": entry["product_id"],
                "source_url": entry["source_url"],
                "child_url": entry["child_url"],
                "parent_snapshot_sha256_unverified":
                    entry["parent_snapshot_sha256"],
                "review_packet_sha256": entry["review_packet_sha256"],
                "snapshot": {
                    "file": name, "sha256": sha,
                    "request_url": entry["child_url"],
                    "final_url": entry["child_url"],
                    "http_status": 200,
                    "media_type": "text/html",
                    "capture_method": "static_html",
                    "captured_at_utc": timestamp,
                    "canonical_observation": canonical_status,
                },
                "substantive_technical_claims_verified": False,
                "approved_for_advisor": False,
            })
            receipts.append({
                "page_id": entry["page_id"],
                "source_id": entry["source_id"],
                "child_url": entry["child_url"],
                "snapshot_sha256": sha,
                "robots_url": robot["robots_url"],
                "robots_sha256": robot["robots_sha256"],
                "robots_allowed_for_agent": True,
                "crawl_delay_seconds": robot["delay_seconds"],
                "html_bytes": response["response_bytes"],
                "http_date": response["date"],
                "last_modified": response["last_modified"],
                "canonical_status": canonical_status,
                "publisher_origin_independently_authenticated": False,
                "technical_capabilities_independently_verified": False,
            })
        manifest = {
            "schema_version": VERSION,
            "kind": "p18a2_private_original_html_child_snapshots_unverified",
            "registry_sha256": plan["registry_sha256"],
            "review_packet_sha256": plan["review_packet_sha256"],
            "expected_manifest_sha256": plan["expected_manifest_sha256"],
            "expected_source_lifecycle_sha256":
                plan["expected_source_lifecycle_sha256"],
            "snapshots": snapshots,
            "automatic_collection_enabled": False,
            "advisor_approved_facts": 0,
            "approved_for_advisor": False,
        }
        audit = {
            "schema_version": VERSION,
            "kind": "p18a2_manual_capture_audit_not_fact_approval",
            "source_page_count": len(snapshots),
            "page_ids": list(page_ids),
            "robots_checks": len(robots_by_host),
            "page_requests": len(snapshots),
            "network_requests_performed":
                len(robots_by_host) + len(snapshots),
            "policy_review_note": policy_review_note.strip(),
            "publisher_policy_review_operator_attested": True,
            "publisher_policy_independently_authenticated": False,
            "content_accuracy_independently_verified": False,
            "source_receipts": receipts,
            "new_spider_sources": 0,
            "scheduled_jobs_created": 0,
            "production_database_writes": 0,
            "advisor_approved_facts": 0,
        }
        _write_new_private_file(
            target / "child_html_snapshots.json",
            (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        _write_new_private_file(
            target / "capture_audit.json",
            (json.dumps(audit, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        return manifest, audit
    except Exception:
        # A failed batch cannot look like a complete approved capture.
        shutil.rmtree(target)
        raise


def _load_json(path, max_bytes):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or symlinked P18A review input")
    if path.stat().st_size > max_bytes:
        raise ValueError("Oversized P18A review input")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--review-packet", type=Path,
                        help="Exact original P18A1 private review packet")
    parser.add_argument("--page-ids", type=str,
                        help="Comma-separated exact reviewed page IDs, maximum five")
    parser.add_argument("--capture", action="store_true",
                        help="Make manual publisher requests; default has NO network")
    parser.add_argument("--policy-reviewed", action="store_true",
                        help="Re-attest publisher access/retention terms before capture")
    parser.add_argument("--policy-review-note", default="",
                        help="Private operator note, 30-500 characters")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/private/p18a2-doc-capture"))
    args = parser.parse_args()
    registry = _load_json(args.registry, MAX_REGISTRY_BYTES)
    packet = (_load_json(args.review_packet, MAX_PACKET_BYTES)
              if args.review_packet else None)
    ids = ([s.strip() for s in args.page_ids.split(",")]
           if args.page_ids else None)
    plan = capture_plan(registry, packet, ids)
    if not args.capture:
        if args.policy_reviewed or args.policy_review_note:
            parser.error("Policy review flags apply only with --capture")
        print(json.dumps(plan, indent=2))
        return
    if not args.policy_reviewed or ids is None:
        parser.error("--capture requires --policy-reviewed and --page-ids")
    manifest, audit = capture_documentation_pages(
        registry, packet, ids, args.out_dir,
        policy_review_note=args.policy_review_note,
    )
    print(json.dumps({
        "status": "private_original_documentation_html_unverified",
        "page_count": len(manifest["snapshots"]),
        "network_requests_performed": audit["network_requests_performed"],
        "private_capture_directory": str(args.out_dir),
        "advisor_approved_facts": 0, "scheduled_jobs": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
