"""Conservative HTML-to-text extraction for evidence snapshots, not price parsing."""

import re
from lxml import etree, html

BLOCKS = frozenset({
    "article", "blockquote", "div", "dl", "dt", "dd", "h1", "h2", "h3",
    "h4", "h5", "h6", "li", "ol", "p", "pre", "section", "table",
    "tbody", "thead", "tfoot", "tr", "ul",
})
NOISE_XPATH = (
    ".//script|.//style|.//noscript|.//template|.//nav|.//aside|"
    ".//header|.//footer|.//form|.//svg|.//button|"
    ".//*[@role='navigation']|.//*[@aria-hidden='true']|"
    ".//*[contains(concat(' ',normalize-space(@class),' '),' sidebar ')]|"
    ".//*[contains(concat(' ',normalize-space(@class),' '),' table-of-contents ')]"
)


def _clean(node):
    for unwanted in list(node.xpath(NOISE_XPATH)):
        if unwanted.getparent() is not None:
            unwanted.drop_tree()
    return node


def _collect_text(node):
    parts = []
    for event, element in etree.iterwalk(node, events=("start", "end")):
        tag = element.tag.lower() if isinstance(element.tag, str) else ""
        if event == "start":
            if tag in BLOCKS or tag == "br":
                parts.append("\n")
            if tag in {"td", "th"}:
                parts.append(" | ")
            if element.text:
                parts.append(element.text)
        else:
            if tag in BLOCKS:
                parts.append("\n")
            if element.tail:
                parts.append(element.tail)
    text = "".join(parts)
    return "\n".join(
        re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        for line in text.split("\n") if line.strip()
    )


def extract_text(raw_html):
    """Return (document_title, cleaned_text) from a single HTML response."""
    root = html.fromstring(raw_html)
    title = " ".join(root.xpath("//title[1]/text()") or []).strip()
    h1 = root.xpath("//h1[1]//text()")
    if h1:
        title = " ".join(x.strip() for x in h1 if x.strip()) or title

    # A changelog may contain many release entries; preserve the full main area.
    candidates = root.xpath("//main | //*[@role='main']")
    if not candidates:
        candidates = root.xpath("//article")
    if not candidates:
        candidates = root.xpath("//body")
    chosen = max(candidates, key=lambda node: len(node.text_content())) if candidates else root

    text = _collect_text(_clean(chosen))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return title, text
