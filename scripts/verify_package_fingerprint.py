"""Compare the running/source package fingerprint against built Zyte .egg bytes.

Read-only offline check: deterministic code+manifest fingerprint, not a signature
or claim of verified Git commit. Designed for the legacy bdist_egg build in CI.
"""

import argparse
import json
import zipfile
from pathlib import Path

from agentfuse_crawlers.run_context import fingerprint_entries, package_fingerprint

PREFIX = "agentfuse_crawlers/"


def fingerprint_egg(path):
    if not zipfile.is_zipfile(path):
        raise ValueError("Expected a ZIP-format Zyte egg: " + str(path))
    with zipfile.ZipFile(path, "r") as archive:
        entries = [
            (name[len(PREFIX):], archive.read(name))
            for name in archive.namelist()
            if name.startswith(PREFIX) and name.endswith((".py", ".json"))
            and not name.endswith("/")
        ]
    return fingerprint_entries(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eggs", nargs="*", type=Path)
    args = parser.parse_args()
    eggs = args.eggs or sorted(Path("dist").glob("*.egg"))
    if not eggs:
        parser.error("No Zyte egg was supplied or found in dist/")
    expected = package_fingerprint()
    for path in eggs:
        observed = fingerprint_egg(path)
        if observed != expected:
            raise SystemExit(
                "Package digest differs from Zyte egg; refusing provenance success: "
                + str(path)
            )
    print(json.dumps({
        "fingerprint_kind": "package_py_json_sha256_v1",
        "package_sha256": expected,
        "verified_eggs": [str(path) for path in eggs],
        "equal_package_bytes": True,
        "verified_git_commit": False,
        "deployment_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
