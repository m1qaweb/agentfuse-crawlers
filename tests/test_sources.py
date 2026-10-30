from urllib.parse import urlsplit

from agentfuse_crawlers.sources import load_sources


def test_manifest_is_unique_and_only_official_allowlisted_urls():
    sources = load_sources()
    assert len(sources) == 82
    assert len({s["id"] for s in sources}) == len(sources)
    assert len({s["url"] for s in sources}) == len(sources)
    assert len({s["provider"] for s in sources}) == 29
    assert {s["category"] for s in sources} == {"documentation", "pricing", "changelog"}
    assert all(urlsplit(s["url"]).scheme == "https" for s in sources)
    assert {s["provider"] for s in sources}.issuperset({"OpenAI", "Anthropic", "Google Gemini"})


def test_verified_original_nine_sources_unchanged():
    source_ids = {s["id"] for s in load_sources()}
    assert {
        "openai_api_docs", "openai_api_pricing", "openai_api_changelog",
        "anthropic_api_docs", "anthropic_api_pricing", "anthropic_api_changelog",
        "gemini_api_docs", "gemini_api_pricing", "gemini_api_changelog",
    }.issubset(source_ids)
