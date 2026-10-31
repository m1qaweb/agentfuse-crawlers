"""Versioned, explicit crawl-scope provenance; no external data is trusted here.

A source's historical 'proven' membership is NOT the requested job cohort.
Both facts must travel with every item, including errors, for reproducible audits.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone

from agentfuse_crawlers.sources import load_sources


JOB_KEY_PATTERN = re.compile(r"^\d+/\d+/\d+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$", re.I)


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
    revision = str(revision).lower() if REVISION_PATTERN.fullmatch(str(revision)) else ""
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
        "deployment_revision": revision,
    }
