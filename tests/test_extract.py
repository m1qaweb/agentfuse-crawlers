from agentfuse_crawlers.extract import extract_text


def test_extract_preserves_main_body_and_skips_navigation():
    page = """<html><head><title>Vendor Pricing</title></head><body>
      <nav>Do not include NAV TOKEN</nav>
      <main><h1>Model prices</h1><p>Token costs apply.</p>
      <table><tr><th>Model</th><th>Input</th></tr>
      <tr><td>Sample</td><td>$1</td></tr></table>
      <aside>Skip ASIDE TOKEN</aside></main>
      <footer>Skip FOOTER TOKEN</footer>
      </body></html>"""
    title, content = extract_text(page)
    assert title == "Model prices"
    assert "Token costs apply" in content
    assert "Sample" in content
    assert "$1" in content
    assert "NAV TOKEN" not in content
    assert "ASIDE TOKEN" not in content
    assert "FOOTER TOKEN" not in content


def test_extract_body_fallback():
    title, text = extract_text("<html><title>Simple</title><body><p>Body text</p></body></html>")
    assert title == "Simple"
    assert "Body text" in text
