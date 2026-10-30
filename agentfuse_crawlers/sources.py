"""Strict offline manifest; spider arguments select source IDs, never arbitrary URLs."""

import json
import re
from importlib.resources import files
from urllib.parse import urlsplit

VALID_CATEGORIES = frozenset({'documentation', 'pricing', 'changelog'})
VALID_COHORTS = frozenset({'all', 'proven', 'candidate'})
ID_PATTERN = re.compile(r'^[a-z][a-z0-9_]{2,80}$')


def load_sources():
    manifest = files('agentfuse_crawlers').joinpath('data/sources.json')
    sources = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(sources, list) or not sources:
        raise ValueError('Expected a nonempty list of sources')
    ids, urls = set(), set()
    for entry in sources:
        if not isinstance(entry, dict) or set(entry) != {'id', 'provider', 'category', 'url'}:
            raise ValueError(f'Invalid source entry: {entry!r}')
        if not all(isinstance(entry[k], str) and entry[k].strip() for k in entry):
            raise ValueError(f'Empty source value: {entry!r}')
        if not ID_PATTERN.fullmatch(entry['id']):
            raise ValueError(f'Invalid source ID: {entry["id"]!r}')
        if entry['id'] in ids or entry['url'] in urls:
            raise ValueError('Duplicate ID or URL in source manifest')
        ids.add(entry['id'])
        urls.add(entry['url'])
        if entry['category'] not in VALID_CATEGORIES:
            raise ValueError(f'Invalid category: {entry["category"]}')
        parsed = urlsplit(entry['url'])
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment
                or parsed.hostname in {'localhost', '127.0.0.1', '::1'}):
            raise ValueError(f'Unsafe source URL: {entry["url"]}')
    return sources


def load_proven_source_ids():
    """Successful crawl baseline, NOT proof of correctness of underlying claims."""
    manifest = files('agentfuse_crawlers').joinpath('data/proven_sources.json')
    ids = json.loads(manifest.read_text(encoding='utf-8'))
    known = {source['id'] for source in load_sources()}
    if not isinstance(ids, list) or len(set(ids)) != len(ids) or not set(ids) <= known:
        raise ValueError('Invalid proven source manifest')
    return frozenset(ids)


def select_sources(category, cohort='all', source_ids=None, limit=None):
    """Deterministic, safely scoped URL selection from the reviewed manifest."""
    if category not in VALID_CATEGORIES:
        raise ValueError('Unknown category')
    if cohort not in VALID_COHORTS:
        raise ValueError('cohort must be all, proven, or candidate')
    sources = load_sources()
    available = {s['id'] for s in sources}
    if source_ids is not None:
        if isinstance(source_ids, str):
            source_ids = [s.strip() for s in source_ids.split(',')]
        source_ids = set(source_ids)
        if not source_ids or not source_ids <= available:
            raise ValueError(f'Unknown or empty source selection: {sorted(source_ids - available)}')
    proven = load_proven_source_ids()
    filtered = [s for s in sources if s['category'] == category
                and (cohort == 'all' or (s['id'] in proven) == (cohort == 'proven'))
                and (source_ids is None or s['id'] in source_ids)]
    if limit is not None:
        if isinstance(limit, bool) or not str(limit).isdigit() or not 1 <= int(limit) <= 500:
            raise ValueError('limit must be an integer from 1 through 500')
        filtered = filtered[:int(limit)]
    if not filtered:
        raise ValueError('Selection contains no sources; check category/cohort/source_ids')
    return filtered
