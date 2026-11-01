"""Versioned, explicit crawl-scope provenance; no external data is trusted here.

A source's historical 'proven' membership is NOT the requested job cohort.
Both facts must travel with every item, including errors, for reproducible audits.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files

from agentfuse_crawlers.sources import load_sources


JOB_KEY_PATTERN = re.compile(r"^\d+/\d+/\d+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$", re.I)
PACKAGE_FINGERPRINT_KIND = "package_py_json_sha256_v1"


def fingerprint_entries(entries):
    """Hash exact logical package path + raw byte count + bytes, not mtimes.

    Stable for source trees, zipped Scrapy Cloud eggs and installed wheels.
    This identifies package content; it is NOT a signed Git commit claim.
    """
    digest = hashlib.sha256()
    found = set()
    for path, payload in sorted(entries, key=lambda item: item[0]):
        if (not isinstance(path, str) or path in found
                or not path or path.startswith("/")
                or ".." in path.split("/")
                or not isinstance(payload, bytes)):
            raise ValueError("Invalid or duplicated package fingerprint entry")
        found.add(path)
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
    if not {"run_context.py", "data/sources.json"} <= found:
        raise ValueError("Missing required files in crawler package fingerprint")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def package_fingerprint():
    """Verify the bytes installed/running, including parser and source policies.

    Traversable works with both directories and zip-imported legacy .egg files.
    Only shipped Python/JSON files are included; pycache and metadata are not.
    """
    root = files("agentfuse_crawlers")

    def walk(folder, prefix=""):
        for entry in sorted(folder.iterdir(), key=lambda node: node.name):
            name = prefix + entry.name
            if entry.is_dir():
                yield from walk(entry, name + "/")
            elif entry.is_file() and name.endswith((".py", ".json")):
                yield name, entry.read_bytes()

    return fingerprint_entries(walk(root))




def _digest(value):
    canonical = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def manifest_sha256(sources=None):
    """Ordering and source URL edits both change this fingerprint."""
    rows = load_sources() if sources is None else sources
    return _digest(rows)


def selection_ids_sha256(selected):
    """Ordering-sensitive exact IDs; source URL changes tracked by manifest SHA."""
    return _digest([row["id"] for row in selected])


def build_run_context(spider_name, requested_cohort, selected, *,
                      explicit_cohort=False, started_at=None, job_id=None,
                      revision=None, manifest=None):
    """Capture immutable job facts at spider construction, never from page HTML."""
    if not selected:
        raise ValueError("Cannot build provenance for an empty selection")
    if job_id is None:
        job_id = os.environ.get("SHUB_JOBKEY", "")
    if revision is None:
        revision = os.environ.get("AGENTFUSE_DEPLOY_REVISION", "")
    # Environment variables are not evidence unless they match expected shapes.
    job_id = str(job_id) if JOB_KEY_PATTERN.fullmatch(str(job_id)) else ""
    revision_claim = str(revision).lower() if REVISION_PATTERN.fullmatch(str(revision)) else ""
    installed_digest = package_fingerprint()
    if started_at is None:
        started_at = datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        raise ValueError("run start requires a timezone-aware timestamp")
    return {
        "spider_name": spider_name,
        "requested_cohort": requested_cohort,
        "run_scope_explicit": bool(explicit_cohort),
        "selection_source_count": len(selected),
        "selection_ids_sha256": selection_ids_sha256(selected),
        "manifest_sha256": manifest_sha256(manifest),
        "run_started_at_utc": started_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "zyte_job_id": job_id,
        "deployment_revision": installed_digest,
        "deployment_revision_kind": PACKAGE_FINGERPRINT_KIND,
        "deployment_source_revision_claim": revision_claim,
    }
