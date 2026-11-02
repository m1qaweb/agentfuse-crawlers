"""P18A1: offline, fail-closed review of observed documentation child URLs.

This is NOT a crawler, collection permission registry or verified docs corpus.
The original 460-source manifest, spider package and source policy stay fixed.
A candidate URL, tentative product mapping or reviewer packet authorizes ZERO
new HTTP requests and ZERO AgentFuse facts.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.documentation_scope import (
    _same_official_host, _trusted_page_family,
)
from agentfuse_crawlers.provider_profiles import (
    load_provider_profiles, provider_profiles_sha256,
)
from agentfuse_crawlers.run_context import manifest_sha256
from agentfuse_crawlers.source_lifecycle import (
    collection_decision, registry_revision_sha256,
)
from agentfuse_crawlers.sources import load_sources
from scripts.triage_documentation import triage_documentation_items

VERSION = "1.0"
KIND = "p18a1_offline_documentation_child_review_not_permission"
MAX_PER_SOURCE = 24
MAX_TOTAL = 400
MAX_EXPLICIT_IDS = 25
MAX_ITEMS_FILE_BYTES = 200_000_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_PATH = re.compile(r"^/[A-Za-z0-9/_~.-]+$")
COLUMNS = (
    "task_id", "source_id", "provider", "product_id_unverified",
    "source_url", "candidate_url", "anchor_text", "found_in",
    "parent_snapshot_sha256_unverified", "review_status",
    "approved_for_crawl", "approved_for_advisor",
)
REQUIRED_CHECKS = (
    "publisher_ownership_and_exact_product",
    "publisher_terms_robots_and_retention",
    "canonical_url_no_migration",
    "page_locale_version_and_relevance",
    "separate_operator_collection_authorization",
)


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha(value):
    return _sha(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ))


def _pinned_documentation():
    sources = load_sources()
    if len(sources) != 460:
        raise ValueError("Docs review needs the pinned 460-source manifest")
    docs = {s["id"]: s for s in sources if s["category"] == "documentation"}
    if len(docs) != 194:
        raise ValueError("Docs review needs the pinned 194-documentation inventory")
    return docs


def _strict_child_url(source, candidate):
    """Require exact parent host/path family. Never canonicalize into permission."""
    if (not isinstance(candidate, str) or not 1 <= len(candidate) <= 650
            or not candidate.isascii() or not candidate.startswith("https://")
            or any(x in candidate for x in ("\\", "%", "?", "#"))
            or any(ord(ch) <= 32 or ord(ch) == 127 for ch in candidate)):
        raise ValueError("Unsafe documentation child URL syntax")
    try:
        parsed, parent = urlsplit(candidate), urlsplit(source["url"])
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.netloc != parent.netloc
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment
                or not _same_official_host(candidate, source["url"])
                or not SAFE_PATH.fullmatch(parsed.path)
                or "//" in parsed.path
                or any(segment in (".", "..") for segment in parsed.path.split("/"))):
            raise ValueError("Unsafe or cross-owner documentation child URL")
        family = _trusted_page_family(source["url"])
        if (not family or not parsed.path.startswith(family)
                or parsed.path.rstrip("/") == parent.path.rstrip("/")):
            raise ValueError("Child URL is outside the reviewed parent path family")
    except (TypeError, ValueError) as exc:
        raise ValueError("Child URL failed parent host/path validation") from exc
    return candidate


def _source_item_hash(item):
    digest = item.get("content_sha256")
    return digest if isinstance(digest, str) and HEX64.fullmatch(digest) else None


def _candidate_id(source_id, url):
    return _sha(source_id + "|docs-child|" + url)[:24]


def _task_id(source_id, product_id, url):
    return _sha(source_id + "|" + product_id + "|" + url)[:24]


def build_review_packet(items, *, source_ids=None, per_source=8, max_total=160):
    """Validate old Zyte Items and build bounded, independently reviewable URLs.

    No site is contacted, no approval is inferred and the packet is never
    consumed by any spider. Source IDs and product labels are pinned candidate
    identities only; an HTTP 200 is not sufficient to approve a page.
    """
    if (type(per_source) is not int or not 1 <= per_source <= MAX_PER_SOURCE
            or type(max_total) is not int or not 1 <= max_total <= MAX_TOTAL):
        raise ValueError("Invalid bounded per-source or overall review limits")
    docs = _pinned_documentation()
    triage = triage_documentation_items(items)
    profiles = load_provider_profiles()
    by_id = {
        item["source_id"]: item for item in items
        if isinstance(item, dict) and item.get("category") == "documentation"
    }
    if source_ids is None:
        chosen = sorted(by_id)
        explicit = False
    else:
        if (not isinstance(source_ids, (list, tuple)) or
                not 1 <= len(source_ids) <= MAX_EXPLICIT_IDS or
                any(not isinstance(sid, str) for sid in source_ids) or
                len(set(source_ids)) != len(source_ids)):
            raise ValueError("Select 1-25 distinct exact documentation source IDs")
        chosen = sorted(source_ids)
        explicit = True
        for sid in chosen:
            if sid not in docs or sid not in by_id:
                raise ValueError("Selected docs source absent from Items/manifest: " + sid)

    candidates_by_source = defaultdict(list)
    source_audit = []
    seen_url_to_owner = defaultdict(set)
    raw = 0
    held = Counter()
    for sid in chosen:
        source = docs[sid]
        item = by_id[sid]
        allowed, lifecycle_reason = collection_decision(source, mode="validation")
        profile = profiles.get(sid)
        if explicit and not allowed:
            raise ValueError("Explicitly selected publisher-policy blocked source: " + sid)
        conflict = item.get("source_product_title_conflict") is True
        reviewable = bool(
            allowed and profile and profile["category"] == "documentation"
            and not conflict
        )
        hold_reason = (
            "publisher_source_policy_blocked" if not allowed else
            "no_pinned_product_profile" if not profile else
            "product_title_conflict" if conflict else
            "pending_independent_human_url_and_product_review"
        )
        links = item.get("documentation_nav_candidates") or []
        raw += len(links)
        seen_local = set()
        for link in links:
            url = _strict_child_url(source, link["candidate_url"])
            if link.get("candidate_id") != _candidate_id(sid, url):
                raise ValueError("Child candidate ID disagrees with source and URL")
            if url in seen_local:
                raise ValueError("Duplicate candidate URL within one source: " + sid)
            seen_local.add(url)
            if not reviewable:
                held[hold_reason] += 1
                continue
            task = {
                "task_id": _task_id(sid, profile["product_id"], url),
                "source_id": sid,
                "provider": source["provider"],
                "product_id_unverified": profile["product_id"],
                "source_url": source["url"],
                "candidate_url": url,
                "anchor_text": str(link.get("anchor_text") or "")[:125],
                "found_in": str(link.get("found_in") or "")[:45],
                "parent_snapshot_sha256_unverified": _source_item_hash(item),
                "parent_profile_review_status": profile["review_status"],
                "product_ownership_independently_verified": False,
                "required_human_checks": list(REQUIRED_CHECKS),
                "review_status": "pending_independent_policy_and_product_review",
                "approved_for_crawl": False,
                "approved_for_advisor": False,
            }
            candidates_by_source[sid].append(task)
            seen_url_to_owner[url].add(sid)
        source_audit.append({
            "source_id": sid,
            "source_url": source["url"],
            "candidate_count_in_item": len(links),
            "pinned_product_id_candidate": (
                profile["product_id"] if profile else None
            ),
            "product_ownership_independently_verified": False,
            "source_validation_mode": lifecycle_reason,
            "eligible_for_review": reviewable,
            "review_hold_reason": hold_reason,
            "approved_child_requests": 0,
        })
    # One child URL claimed by two different source/product owners is NOT
    # safe to silently assign to the first parent or approve for collection.
    collisions = {url for url, owners in seen_url_to_owner.items()
                  if len(owners) > 1}
    for sid, candidates in candidates_by_source.items():
        candidates.sort(key=lambda task: task["candidate_url"])
        safe = [task for task in candidates
                if task["candidate_url"] not in collisions]
        held["cross_source_child_owner_collision"] += len(candidates) - len(safe)
        candidates_by_source[sid] = safe

    tasks = []
    # Deterministic round-robin, rather than letting one large docs portal
    # consume the entire reviewer budget.
    for index in range(per_source):
        for sid in chosen:
            source_tasks = candidates_by_source[sid]
            if index < len(source_tasks) and len(tasks) < max_total:
                tasks.append(source_tasks[index])
    possible = sum(min(len(v), per_source) for v in candidates_by_source.values())
    held["bounded_selection_omitted"] += sum(
        len(v) - min(len(v), per_source) for v in candidates_by_source.values()
    ) + max(0, possible - len(tasks))
    packet = {
        "schema_version": VERSION,
        "kind": KIND,
        "expected_manifest_sha256": manifest_sha256(),
        "expected_source_lifecycle_sha256": registry_revision_sha256(),
        "expected_provider_profile_sha256": provider_profiles_sha256(),
        "expected_documentation_source_count": len(docs),
        "input_documentation_source_count": triage["summary"]["documentation_items"],
        "input_manifest_complete": triage["summary"]["complete_docs_manifest_accounted"],
        "selected_source_ids": chosen,
        "raw_nav_candidate_count": raw,
        "review_task_count": len(tasks),
        "held_candidate_reasons": dict(sorted(held.items())),
        "cross_source_owner_collision_urls": len(collisions),
        "sampling": "bounded_deterministic_source_round_robin",
        "sources": source_audit,
        "tasks": tasks,
        "new_network_requests": 0,
        "new_fetch_permissions": 0,
        "human_publisher_policy_approvals": 0,
        "verified_product_owners": 0,
        "advisor_approved_facts": 0,
        "approved_for_crawl": False,
        "approved_for_advisor": False,
    }
    packet["packet_sha256"] = _json_sha(packet)
    return packet


def _safe_csv(value):
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def _private_new_directory(out_dir):
    root = Path(out_dir)
    if root.exists() or root.is_symlink() or any(
        parent.is_symlink() for parent in root.parents
    ):
        raise ValueError("Use a NEW non-symlink private output directory")
    checkout = Path(__file__).resolve().parents[1]
    absolute = root.resolve(strict=False)
    if (absolute.is_relative_to(checkout)
            and not absolute.is_relative_to(checkout / "output")):
        raise ValueError("Under this repo, reviewer data must stay in output/")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(root, 0o700)
    return root


def _write_private(path, raw):
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    os.chmod(path, 0o600)


def write_review_packet(packet, out_dir):
    """Private, no-overwrite output; audit template is NOT an approval API."""
    root = _private_new_directory(out_dir)
    try:
        _write_private(root / "child_review_packet.json", (
            json.dumps(packet, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8"))
        template = {
            "schema_version": VERSION,
            "kind": "p18a1_human_review_notes_not_authorization",
            "packet_sha256": packet["packet_sha256"],
            "manual_review_records": [],
            "approved_for_crawl": False,
            "approved_for_advisor": False,
        }
        _write_private(root / "human_review_notes_template.json", (
            json.dumps(template, indent=2) + "\n"
        ).encode("utf-8"))
        import io
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
        writer.writeheader()
        for task in packet["tasks"]:
            writer.writerow({field: _safe_csv(task.get(field))
                             for field in COLUMNS})
        _write_private(root / "child_review_tasks.csv",
                       buffer.getvalue().encode("utf-8-sig"))
        return root
    except Exception:
        shutil.rmtree(root)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, required=True, nargs="+",
                        help="One or more existing Zyte documentation Items JSON arrays")
    parser.add_argument("--source-ids",
                        help="Optional exact manifest IDs, comma-separated (max 25)")
    parser.add_argument("--per-source", type=int, default=8)
    parser.add_argument("--max-total", type=int, default=160)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/private/p18a1-doc-child-review"))
    args = parser.parse_args()
    items = []
    for path in args.items:
        if path.stat().st_size > MAX_ITEMS_FILE_BYTES:
            raise ValueError("Oversized documentation Items export")
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, list):
            raise ValueError("Zyte Items must be a JSON array")
        items.extend(loaded)
    packet = build_review_packet(
        items, source_ids=(
            [s.strip() for s in args.source_ids.split(",")]
            if args.source_ids else None
        ), per_source=args.per_source, max_total=args.max_total,
    )
    saved = write_review_packet(packet, args.out_dir)
    print(json.dumps({
        "private_review_packet": str(saved / "child_review_packet.json"),
        "review_tasks": packet["review_task_count"],
        "held_candidate_reasons": packet["held_candidate_reasons"],
        "new_network_requests": 0,
        "new_fetch_permissions": 0,
        "advisor_approved_facts": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
