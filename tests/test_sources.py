from urllib.parse import urlsplit

from agentfuse_crawlers.sources import load_sources


def test_manifest_has_nine_unique_official_sources():
    sources = load_sources()
    assert len(sources) == 9
    assert len({source["id"] for source in sources}) == len(sources)
    assert {s["category"] for s in sources} == {"documentation", "pricing", "changelog"}
    assert {s["provider"] for s in sources} == {"OpenAI", "Anthropic", "Google Gemini"}
    assert {urlsplit(s["url"]).hostname for s in sources} == {
        "developers.openai.com", "platform.claude.com", "ai.google.dev"
    }
