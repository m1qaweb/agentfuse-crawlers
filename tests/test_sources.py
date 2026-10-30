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



def test_expanded_manifest_preserves_nine_proven_sources():
    from collections import Counter
    sources = load_sources()
    assert len(sources) == 460
    assert Counter(s["category"] for s in sources) == {
        "documentation": 194, "pricing": 177, "changelog": 89,
    }
    assert sources[0]["id"] == "openai_api_docs"
    assert sources[81]["id"] == "google_cloud_ai_changelog"
    assert sources[82]["id"] == "ai21_labs_docs"
    assert sources[-1]["id"] == "prime_intellect_changelog"
    assert len({x["provider"] for x in sources}) == 194
    assert len(load_proven_source_ids()) == 9


@pytest.mark.parametrize("category", ["documentation", "pricing", "changelog"])
def test_candidate_batches_cover_every_source_once(category):
    full = [s["id"] for s in select_sources(category, cohort="candidate")]
    collected = []
    for offset in range(0, len(full), 15):
        collected.extend(x["id"] for x in select_sources(
            category, cohort="candidate", offset=offset, limit=15,
        ))
    assert collected == full
    assert len(set(collected)) == len(full)
    assert not set(collected).intersection(load_proven_source_ids())


@pytest.mark.parametrize("offset", [-1, "bad", "1.5", True, None, 100001])
def test_invalid_batch_offsets_are_rejected(offset):
    with pytest.raises(ValueError, match="offset"):
        select_sources("changelog", cohort="candidate", offset=offset, limit=10)


def test_out_of_range_batch_fails_closed():
    with pytest.raises(ValueError, match="no sources"):
        select_sources("pricing", cohort="candidate", offset=10000, limit=10)
