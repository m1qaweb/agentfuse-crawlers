from agentfuse_crawlers.extract import _date_from_heading, extract_evidence


HTML = '''<html lang="en"><head><title>Model Pricing</title>
<link rel="canonical" href="https://docs.example.com/pricing">
<meta name="description" content=" Pricing and rates. "></head>
<body><nav>Skip navigation</nav><main>
<h1>Pricing and important updates</h1>
<h2 id="2026-10-30">October 30, 2026</h2>
<p>New model API announced and available to test.</p>
<h3>Model alpha pricing</h3>
<table><caption>Standard tier</caption>
<tr><th rowspan="2">Model</th><th colspan="2">Per million tokens</th></tr>
<tr><th>Input</th><th>Output</th></tr>
<tr><td>Alpha</td><td>$1.20</td><td>$4.50</td></tr>
</table>
<h2 id="2026-10-29">2026-10-29</h2><p>Older release information.</p>
</main><footer>Do not include footer text.</footer></body></html>'''


def test_structured_tables_preserve_cells_and_spans():
    ev = extract_evidence(HTML, 'https://docs.example.com/pricing')
    assert ev['title'] == 'Pricing and important updates'
    assert ev['canonical_url'] == 'https://docs.example.com/pricing'
    assert ev['language'] == 'en'
    assert ev['tables'][0]['caption'] == 'Standard tier'
    assert ev['tables'][0]['rows'][0][0]['rowspan'] == '2'
    assert ev['tables'][0]['rows'][0][1]['colspan'] == '2'
    assert [c['text'] for c in ev['tables'][0]['rows'][2]] == ['Alpha', '$1.20', '$4.50']
    assert 'Skip navigation' not in ev['text']
    assert 'Do not include footer' not in ev['text']


def test_dates_and_section_evidence():
    ev = extract_evidence(HTML, 'https://docs.example.com/pricing')
    sections = ev['sections']
    assert sections[0]['date_candidate'] == '2026-10-30'
    assert sections[0]['section_url'] == 'https://docs.example.com/pricing#2026-10-30'
    assert sections[-1]['date_candidate'] == '2026-10-29'
    assert 'Older release' in sections[-1]['excerpt']
    assert sections[0]['sha256'] and ev['content_sha256']
    assert not ev['sections_truncated']
    assert not ev['tables_truncated']


def test_invalid_dates_do_not_invent_publication():
    assert _date_from_heading('March 32, 2026') == ''
    assert _date_from_heading('Latest API updates') == ''
    assert _date_from_heading('2026-11-01 release') == '2026-11-01'


def test_cross_domain_canonical_is_not_trusted():
    doc = '<html><head><link rel="canonical" href="https://attacker.invalid/"/></head><body><main><p>Text</p></main></body></html>'
    assert extract_evidence(doc, 'https://docs.example.com/') ['canonical_url'] == ''


def test_changelog_dates_propagate_to_subheadings_without_inventing_timestamps():
    doc = """<html><body><main>
    <h2 id="release-day">October 30, 2026</h2>
    <h3 id="version-a">New API release</h3><p>Current release details and migration requirements.</p>
    <h3 id="version-b">New model</h3><p>Latest supported model information.</p>
    <h2>Miscellaneous guides</h2><h3>Help page</h3><p>Not a release.</p>
    </main></body></html>"""
    data = extract_evidence(doc, "https://example.com/changelog")
    matching = {s["heading"]: s["date_candidate"] for s in data["sections"]}
    assert matching["New API release"] == "2026-10-30"
    assert matching["New model"] == "2026-10-30"
    assert matching["Help page"] == ""
    assert data["visible_latest_date_candidate"] == "2026-10-30"
    assert any(s["section_id"] == "anchor-version-a" for s in data["sections"])


def test_html_time_datetime_can_supply_explicit_date_candidate():
    doc = """<html><body><main>
    <h3>Release</h3><time datetime="2026-10-29">Oct 29</time>
    <p>A valid dated release.</p></main></body></html>"""
    data = extract_evidence(doc, "https://example.com/changelog")
    assert data["sections"][0]["date_candidate"] == "2026-10-29"
    assert data["visible_latest_date_candidate"] == "2026-10-29"
