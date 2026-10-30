"""Fixed, reviewed crawl scope. Never accept arbitrary URLs from job arguments."""

import json
from importlib.resources import files
from urllib.parse import urlsplit

VALID_CATEGORIES = frozenset({"documentation", "pricing", "changelog"})


def load_sources():
    source_text = files("agentfuse_crawlers").joinpath("data/sources.json").read_text(
        encoding="utf-8"
    )
    sources = json.loads(source_text)
    ids = set()
    for entry in sources:
        if set(entry) != {"id", "provider", "category", "url"}:
            raise ValueError(f"Invalid source entry: {entry}")
        if entry["id"] in ids:
            raise ValueError(f"Duplicate source ID: {entry['id']}")
        ids.add(entry["id"])
        if entry["category"] not in VALID_CATEGORIES:
            raise ValueError(f"Unsupported category: {entry['category']}")
        parsed = urlsplit(entry["url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ValueError(f"Unsafe or invalid URL: {entry['url']}")
        if not all(isinstance(entry[key], str) and entry[key].strip() for key in entry):
            raise ValueError(f"Empty source value: {entry}")
    return sources
