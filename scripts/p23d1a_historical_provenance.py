"""P23D1A: immutable historical policy+egg proof for old canary Jobs.

Only validates privately preserved bytes of reviewed access registry and
legacy Zyte egg as they existed when an already-completed job ran. This
never authorizes new publisher requests, retroactively grants permission,
authenticates a remotely deployed package, or approves extracted claims.

The original P23C1 current-policy strict mode remains the default. Old
job replay is explicit, fail-closed, and bound to the per-item fingerprints.
"""
import json
import re
import stat
import zipfile
from datetime import datetime
from pathlib import Path

from agentfuse_crawlers.validation_access import (
    _utc, digest, validate_access_registry,
)
from scripts.verify_package_fingerprint import fingerprint_egg

SHA = re.compile(r"^[0-9a-f]{64}$")
POLICY_MAX = 100_000
EGG_MAX = 15 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000
MAX_UNCOMPRESSED = 25 * 1024 * 1024
ACCESS_ENTRY = "agentfuse_crawlers/data/validation_access_reviews.json"


def _strict_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate historical policy JSON field")
        result[name] = value
    return result


def _private(root, basename, *, bound):
    path = Path(root)
    if (not path.is_dir() or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)):
        raise ValueError("Historical evidence must be a non-symlink private folder")
    target = path / basename
    if (not target.is_file() or target.is_symlink()
            or not 0 < target.stat().st_size <= bound):
        raise ValueError("Missing, linked or oversized historical evidence file")
    return target


def _json_data(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid historical publisher review JSON") from exc


def _safe_egg(egg):
    with zipfile.ZipFile(egg, "r") as f:
        files = f.infolist()
        if not 1 <= len(files) <= MAX_ZIP_ENTRIES:
            raise ValueError("Malformed historical package archive")
        seen = set()
        total = 0
        for member in files:
            name = member.filename
            if (not name or len(name) > 512 or name.startswith("/")
                    or "\\" in name or "\x00" in name or
                    any(part in {".", "..", ""} for part in
                        name.rstrip("/").split("/"))
                    or name in seen):
                raise ValueError("Unsafe or duplicated historical egg member")
            seen.add(name)
            total += member.file_size
            if total > MAX_UNCOMPRESSED:
                raise ValueError("Historical Zyte egg would exceed memory budget")
            unix_mode = (member.external_attr >> 16) & 0o170000
            if unix_mode == stat.S_IFLNK:
                raise ValueError("Symlink in historical Zyte egg")
        if ACCESS_ENTRY not in seen:
            raise ValueError("Historical egg does not include the access policy")
        contents = f.read(ACCESS_ENTRY)
        if not 1 <= len(contents) <= POLICY_MAX:
            raise ValueError("Malformed access-registry bytes in historical egg")
    return _json_data(contents)


def verify_historical_context(item, *, policy_root, egg_root):
    """Return registry and proven local package digest for one archived job.

    The policy and egg MUST match both each other and two independent item
    claims. This is local byte evidence, never remote Zyte attestation.
    """
    if not isinstance(item, dict):
        raise ValueError("Missing archived Zyte source Item")
    policy_sha = item.get("bulk_access_registry_sha256")
    package_sha = item.get("deployment_revision")
    if (not isinstance(policy_sha, str) or not SHA.fullmatch(policy_sha)
            or not isinstance(package_sha, str) or not SHA.fullmatch(package_sha)):
        raise ValueError("Archived job missing exact policy/package SHA-256")
    started = _utc(item.get("run_started_at_utc"))
    policy = _private(policy_root, policy_sha + ".json", bound=POLICY_MAX)
    registry = _json_data(policy.read_bytes())
    validate_access_registry(registry, now=started)
    if digest(registry) != policy_sha:
        raise ValueError("Historical access policy file differs from Item fingerprint")
    egg = _private(egg_root, package_sha + ".egg", bound=EGG_MAX)
    installed = _safe_egg(egg)
    if installed != registry:
        raise ValueError("Historical egg policy bytes differ from review snapshot")
    if fingerprint_egg(egg) != package_sha:
        raise ValueError("Historical egg package digest differs from Item fingerprint")
    return registry, package_sha
