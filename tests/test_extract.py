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



def test_month_and_year_group_propagates_nearby_standalone_release_date():
    from agentfuse_crawlers.extract import extract_evidence
    page = """<html><main><h1>API changelog</h1>
    <h3>October, 2026</h3><div>Oct 30</div>
    <p>Released a new API model for approved users.</p><div>Oct 28</div>
    <p>Added improved caching.</p><h3>September, 2026</h3>
    <div>Sep 29</div><p>Improved tools.</p>
    </main></html>"""
    ev = extract_evidence(page, "https://official.example/changelog")
    assert ev["visible_latest_date_candidate"] == "2026-10-30"
    assert ev["visible_latest_date_provenance"] == "dated_section_or_group"
    assert ev["sections"][0]["date_candidate"] == "2026-10-30"
    assert ev["sections"][1]["date_candidate"] == "2026-09-29"


def test_release_date_on_page_before_first_heading_is_recognized():
    from agentfuse_crawlers.extract import extract_evidence
    page = """<html><main><p>Oct 28, 2026</p>
    <h2>Windows System-Wide Installer</h2>
    <p>This release adds Windows system-wide installers.</p></main></html>"""
    ev = extract_evidence(page, "https://official.example/changelog")
    assert ev["visible_latest_date_candidate"] == "2026-10-28"
    assert ev["visible_latest_date_provenance"] == "leading_explicit_date_line"


def test_future_deprecation_date_inside_release_prose_not_falsely_promoted():
    from agentfuse_crawlers.extract import extract_evidence
    page = """<html><main><h3>October, 2026</h3>
    <p>We will deprecate the older model on November 21, 2026.</p>
    <p>Another release note appears here.</p></main></html>"""
    ev = extract_evidence(page, "https://official.example/changelog")
    assert not ev["visible_latest_date_candidate"]


def test_invalid_month_day_does_not_invent_a_date():
    from agentfuse_crawlers.extract import extract_evidence
    page = """<html><main><h3>February 2026</h3>
    <div>Feb 30</div><p>Updated settings.</p></main></html>"""
    ev = extract_evidence(page, "https://official.example/changelog")
    assert not ev["visible_latest_date_candidate"]
