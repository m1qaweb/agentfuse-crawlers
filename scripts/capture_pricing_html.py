"""P17B3: opt-in, source-pinned ORIGINAL HTML capture for pricing replay.

Default: read-only plan. A real request requires explicit --capture,
--policy-reviewed and a private operator policy note. Maximum five named
first-party source IDs, never arbitrary URLs. Robots is checked fail-closed.

No Zyte scheduling, browser impersonation, login, CAPTCHA bypass, cookies,
retries, redirects, provider approval, DB writes or advisor publication.
SHA-256 validates bytes, not independent publisher authenticity or truth.
Never commit captured original HTML or reviewer artifacts to Git.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from agentfuse_crawlers import settings as crawler_settings
from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources
from scripts.replay_pricing_snapshots import source_pins, validate_snapshot_manifest

AGENT = crawler_settings.USER_AGENT
MAX_SOURCES = 5
MAX_PAGE_BYTES = crawler_settings.DOWNLOAD_MAXSIZE
MAX_ROBOTS_BYTES = 256_000
TIMEOUT_SECONDS = 35
MIN_DELAY = crawler_settings.DOWNLOAD_DELAY
MAX_CRAWL_DELAY = 30
MAX_POLICY_NOTE = 500


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Moved sources require manual review, never automatic URL switching."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _request(url, *, robots):
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": AGENT,
            "Accept": "text/plain" if robots else "text/html",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )


def _fetch_exact(url, opener, *, robots):
    """One strict original HTTPS GET, bounded bytes, no redirect or retry."""
    part = urlsplit(url)
    if (part.scheme != "https" or not part.hostname
            or part.username or part.password or part.query or part.fragment
            or part.port not in (None, 443)):
        raise ValueError("Only exact configured HTTPS URLs can be fetched")
    limit = MAX_ROBOTS_BYTES if robots else MAX_PAGE_BYTES
    try:
        with opener.open(_request(url, robots=robots),
                         timeout=TIMEOUT_SECONDS) as response:
            if response.geturl() != url:
                raise ValueError("Redirect changed exact publisher source URL")
            if type(response.status) is not int or response.status != 200:
                raise ValueError("Publisher returned non-200 response")
            headers = response.headers
            content_type = str(headers.get("Content-Type") or "")
            mime = content_type.split(";", 1)[0].strip().lower()
            if mime != ("text/plain" if robots else "text/html"):
                raise ValueError("Publisher content type not approved for raw capture")
            encoding = str(headers.get("Content-Encoding") or "").lower()
            if encoding not in {"", "identity"}:
                raise ValueError("Compressed publisher response not accepted as raw HTML")
            if not robots:
                for part in content_type.split(";")[1:]:
                    if part.strip().lower().startswith("charset="):
                        charset = part.split("=", 1)[1].strip().strip('"').lower()
                        if charset not in {"utf-8", "utf8"}:
                            raise ValueError("Non-UTF-8 source needs separate capture review")
            declared = headers.get("Content-Length")
            if declared is not None:
                try:
                    n = int(declared)
                except (ValueError, TypeError) as exc:
                    raise ValueError("Invalid Content-Length header") from exc
                if not 0 <= n <= limit:
                    raise ValueError("Publisher response exceeds bounded byte size")
            data = response.read(limit + 1)
            if not isinstance(data, bytes) or not 1 <= len(data) <= limit:
                raise ValueError("Publisher response is empty or oversized")
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Publisher bytes are not UTF-8") from exc
            metadata = {
                "date": str(headers.get("Date") or "")[:120],
                "last_modified": str(headers.get("Last-Modified") or "")[:120],
                "http_status": 200, "content_type": mime,
                "response_bytes": len(data),
            }
            return data, metadata, text
    except urllib.error.HTTPError as exc:
        raise ValueError("Publisher HTTP " + str(exc.code) +
                         "; redirects/challenges are never followed") from exc
    except urllib.error.URLError as exc:
        raise ValueError("Publisher HTTP/TLS connection failed; no bypass") from exc


def _host(source):
    parsed = urlsplit(source["url"])
    host = parsed.hostname
    if parsed.scheme != "https" or not host:
        raise ValueError("Invalid first-party pricing source URL")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError("Numeric IP literals are not permitted source hosts")


def _robots_url(source):
    part = urlsplit(source["url"])
    return urlunsplit(("https", part.netloc, "/robots.txt", "", ""))


def _robots_check(source, opener):
    url = _robots_url(source)
    data, metadata, text = _fetch_exact(url, opener, robots=True)
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(url)
    parser.parse(text.splitlines())
    if not parser.can_fetch(AGENT, source["url"]):
        raise ValueError("Publisher robots disallows " + source["id"])
    delay = parser.crawl_delay(AGENT)
    if delay is not None and (
        type(delay) not in {int, float} or
        not 0 <= delay <= MAX_CRAWL_DELAY
    ):
        raise ValueError("Publisher robots crawl-delay is outside safe budget")
    return {
        "parser": parser,
        "robots_sha256": hashlib.sha256(data).hexdigest(),
        "robots_url": url,
        "delay_seconds": max(MIN_DELAY, delay or 0),
        "robots_response_http_status": metadata["http_status"],
    }


def capture_plan(source_ids):
    if (not isinstance(source_ids, list)
            or not 1 <= len(source_ids) <= MAX_SOURCES
            or any(not isinstance(s, str) or not s.strip() for s in source_ids)
            or len(set(source_ids)) != len(source_ids)):
        raise ValueError("Choose one to five distinct configured pricing source IDs")
    pins = source_pins(source_ids)
    known = {s["id"]: s for s in load_sources()}
    sources = []
    for sid in source_ids:
        source = known[sid]
        allowed, reason = collection_decision(source, mode="validation")
        if not allowed:
            raise ValueError("Publisher source is blocked for validation: " + sid)
        sources.append({
            "source_id": sid,
            "official_source_url": source["url"],
            "robots_url": _robots_url(source),
            "source_lifecycle_validation_status": reason,
            "publisher_policy_review_required": True,
        })
    return {
        "schema_version": "1.0",
        "kind": "p17b3_manual_original_html_capture_plan_only",
        "expected_manifest_sha256": pins["expected_manifest_sha256"],
        "expected_source_registry_sha256":
            pins["expected_source_registry_sha256"],
        "sources": sources,
        "max_source_count": MAX_SOURCES,
        "network_requests_performed": 0,
        "captures_created": 0,
        "publisher_policy_review_required": True,
        "approved_for_advisor": False,
    }


def _private_exclusive_directory(out_dir):
    root = Path(out_dir)
    if any(node.is_symlink() for node in (root, *root.parents)):
        raise ValueError("Private output path must not contain symlinks")
    repo_root = Path(__file__).resolve().parents[1]
    dest = root.resolve(strict=False)
    if dest.is_relative_to(repo_root) and not dest.is_relative_to(
        repo_root / "output"
    ):
        raise ValueError(
            "Publisher HTML inside this Git checkout must stay in "
            "the gitignored output/ directory"
        )
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(root, 0o700)
    return root


def _write_new_private_file(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    os.chmod(path, 0o600)


def capture_pricing_html(source_ids, out_dir, *, policy_review_note,
                         opener=None, sleep_fn=None, clock=None):
    """Operator-initiated original HTML capture. No source policy promotion."""
    plan = capture_plan(source_ids)
    if (not isinstance(policy_review_note, str)
            or not 30 <= len(policy_review_note.strip()) <= MAX_POLICY_NOTE):
        raise ValueError("Publisher policy review requires a 30–500 character note")
    op = opener if opener is not None else urllib.request.build_opener(NoRedirect)
    sleeper = sleep_fn if sleep_fn is not None else time.sleep
    current_clock = clock if clock is not None else (
        lambda: datetime.now(timezone.utc)
    )
    known = {s["id"]: s for s in load_sources()}
    # Reject existing/symlink outputs before *any* website requests.
    target_path = Path(out_dir)
    if target_path.exists() or target_path.is_symlink() or any(
        parent.is_symlink() for parent in target_path.parents
    ):
        raise ValueError("Choose a fresh non-symlink private output directory")
    repo_root = Path(__file__).resolve().parents[1]
    destination = target_path.resolve(strict=False)
    if destination.is_relative_to(repo_root) and not destination.is_relative_to(
        repo_root / "output"
    ):
        raise ValueError("Use Git-ignored output/ for HTML inside the repository")
    # Preflight the robots policy for every distinct host BEFORE any HTML.
    robots_by_host = {}
    network_requests = 0
    for sid in source_ids:
        source = known[sid]
        host = _host(source)
        if host not in robots_by_host:
            robots_by_host[host] = _robots_check(source, op)
            network_requests += 1
        if not robots_by_host[host]["parser"].can_fetch(AGENT, source["url"]):
            raise ValueError("Publisher robots disallows " + sid)
    target = _private_exclusive_directory(out_dir)
    entries, receipts = [], []
    try:
        for sid in source_ids:
            source = known[sid]
            robot = robots_by_host[_host(source)]
            # Allow at least the normal Scrapy delay even after robots GET.
            sleeper(robot["delay_seconds"])
            payload, response, _ = _fetch_exact(
                source["url"], op, robots=False,
            )
            network_requests += 1
            digest = hashlib.sha256(payload).hexdigest()
            filename = sid + "-" + digest[:20] + ".html"
            _write_new_private_file(target / filename, payload)
            now = current_clock()
            if not isinstance(now, datetime) or now.tzinfo is None:
                raise ValueError("Capture clock must be timezone-aware")
            timestamp = now.astimezone(timezone.utc).isoformat()
            entries.append({
                "source_id": sid,
                "snapshot": {
                    "file": filename, "sha256": digest,
                    "request_url": source["url"],
                    "final_url": source["url"],
                    "http_status": 200, "media_type": "text/html",
                    "capture_method": "static_html",
                    "captured_at_utc": timestamp,
                    "capture_origin_review_status":
                        "operator_supplied_unverified",
                },
            })
            receipts.append({
                "source_id": sid,
                "source_url": source["url"],
                "snapshot_sha256": digest,
                "robots_url": robot["robots_url"],
                "robots_sha256": robot["robots_sha256"],
                "robots_allowed_for_agent": True,
                "crawl_delay_seconds": robot["delay_seconds"],
                "html_bytes": response["response_bytes"],
                "http_date": response["date"],
                "last_modified": response["last_modified"],
                "publisher_origin_independently_authenticated": False,
                "pricing_facts_independently_verified": False,
            })
        manifest = {
            "schema_version": "1.0",
            "kind": "frozen_original_pricing_html_manifest",
            "expected_manifest_sha256": manifest_sha256(),
            "expected_source_registry_sha256": registry_revision_sha256(),
            "approved_for_advisor": False,
            "snapshots": entries,
        }
        # The downstream P17B2 comparator accepts this manifest AS IS.
        validate_snapshot_manifest(manifest)
        audit = {
            "schema_version": "1.0",
            "kind": "manual_original_html_capture_receipts_not_publisher_truth",
            "capture_source_count": len(entries),
            "source_ids": list(source_ids),
            "policy_review_note": policy_review_note.strip(),
            "publisher_policy_review_operator_attested": True,
            "publisher_policy_independently_verified": False,
            "robots_checks": len(robots_by_host),
            "network_requests_performed": network_requests,
            "source_receipts": receipts,
            "advisor_fact_approvals": 0,
            "approved_for_advisor": False,
            "scheduled_job_created": False,
            "deployment_authorized": False,
        }
        _write_new_private_file(
            target / "frozen_snapshots.json",
            (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        )
        _write_new_private_file(
            target / "capture_audit.json",
            (json.dumps(audit, indent=2) + "\n").encode("utf-8"),
        )
        return manifest, audit
    except Exception:
        # This folder was created exclusively by our invocation; aborting
        # never leaves a partial set that looks like an accepted batch.
        shutil.rmtree(target)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-ids", required=True,
                        help="Comma-separated exact pricing IDs, maximum five")
    parser.add_argument("--capture", action="store_true",
                        help="Opt in to real publisher requests; default: NO network")
    parser.add_argument("--policy-reviewed", action="store_true",
                        help="Operator has checked publisher terms/robots/retention")
    parser.add_argument("--policy-review-note", default="",
                        help="Private 30–500 character source-policy review note")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/private/p17b3-original-html"))
    args = parser.parse_args()
    source_ids = [x.strip() for x in args.source_ids.split(",")]
    plan = capture_plan(source_ids)
    if not args.capture:
        if args.policy_reviewed or args.policy_review_note:
            parser.error("Policy review flags require --capture")
        print(json.dumps(plan, indent=2))
        return
    if not args.policy_reviewed:
        parser.error("--capture requires --policy-reviewed")
    manifest, audit = capture_pricing_html(
        source_ids, args.out_dir,
        policy_review_note=args.policy_review_note,
    )
    print(json.dumps({
        "status": "original_publisher_bytes_unverified_saved_privately",
        "capture_source_count": len(manifest["snapshots"]),
        "network_requests_performed": audit["network_requests_performed"],
        "private_capture_directory": str(args.out_dir),
        "advisor_fact_approvals": 0,
        "scheduled_jobs_created": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
