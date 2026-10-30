from urllib.parse import urlsplit

import pytest

from agentfuse_crawlers.sources import load_proven_source_ids, load_sources, select_sources


def test_source_manifest_is_unique_and_fixed():
    sources = load_sources()
    assert len(sources) >= 9
    assert len({s['id'] for s in sources}) == len(sources)
    assert len({s['url'] for s in sources}) == len(sources)
    assert {s['category'] for s in sources} == {'documentation', 'pricing', 'changelog'}
    assert all(urlsplit(s['url']).scheme == 'https' for s in sources)


def test_proven_cohort_preserves_nine_successful_initial_sources():
    proven = load_proven_source_ids()
    assert len(proven) == 9
    assert len(select_sources('pricing', cohort='proven')) == 3
    assert len(select_sources('changelog', cohort='proven')) == 3
    assert len(select_sources('documentation', cohort='proven')) == 3


def test_source_id_selection_cannot_inject_url():
    with pytest.raises(ValueError):
        select_sources('changelog', source_ids='https://example.com/')
    assert select_sources('pricing', source_ids='openai_api_pricing')[0]['id'] == 'openai_api_pricing'


def test_malformed_selection_rejected():
    for cohort in ('illegal', '', None):
        with pytest.raises(ValueError):
            select_sources('pricing', cohort=cohort)
    for limit in ('no', '0', -1, 900):
        with pytest.raises(ValueError):
            select_sources('pricing', limit=limit)
    with pytest.raises(ValueError):
        select_sources('pricing', source_ids='openai_api_changelog')
