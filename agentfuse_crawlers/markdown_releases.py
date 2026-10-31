"""Known, first-party Markdown release feeds, not arbitrary discovered URLs.

Only claude_code_changelog is allowlisted initially. The official docs site
serves /docs/en/changelog.md as text/markdown. The source manifest retains
the canonical HTML URL. No cross-domain redirects or browser rendering.
"""

import hashlib
import re
from urllib.parse import urlsplit

from agentfuse_crawlers.recent_window import WindowAccumulator

MARKDOWN_ALTERNATES = {
    "claude_code_changelog": "https://code.claude.com/docs/en/changelog.md",
}
MAX_MD_CHARS = 7_000_000
MAX_MD_EVENT_BODY = 24_000
MAX_MD_EXCERPT = 1100
VERSION_HEADING = re.compile(
    r"^##\s+(?:\[)?v?(\d+\.\d+(?:\.\d+){0,3}(?:-[A-Za-z0-9.-]+)?)(?:\])?\s*$",
    re.I,
)
SUBHEADING = re.compile(r"^#{3,6}\s+")
GENERIC_HEADING = re.compile(r"^#{1,2}\s+")
LINK_LINE = re.compile(r"^\s*\[.*?\]\(.*\)\s*$")


def allowed_markdown_url(source):
    target = MARKDOWN_ALTERNATES.get(source.get("id", ""))
    if not target:
        return None
    host = urlsplit(source["url"])
    parsed = urlsplit(target)
    if (parsed.scheme != "https" or parsed.hostname != host.hostname
            or parsed.port not in (None, 443) or parsed.query
            or parsed.username or parsed.password):
        return None
    return target


def parse_markdown_releases(markdown, source_id, source_html_url,
                            markdown_url, *, recent_limit=80):
    """Extract version records from explicit Markdown ## version headings.

    This does not claim release dates from numeric version strings.
    Full source content hash is calculated over the fetched Markdown.
    """
    if not isinstance(markdown, str) or len(markdown) > MAX_MD_CHARS:
        raise ValueError("Markdown exceeds bounded source size")
    acc = WindowAccumulator(limit=recent_limit)
    current = None
    first_line = 0
    text_size = 0
    full_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

    def finish():
        nonlocal current
        if current is None:
            return
        raw = "\n".join(current.pop("_parts"))
        body = " ".join(raw.split())
        current["body_text_truncated"] = current.pop("_overflow")
        current["excerpt"] = body[:MAX_MD_EXCERPT]
        current["excerpt_truncated"] = len(body) > MAX_MD_EXCERPT or current["body_text_truncated"]
        current["body_sha256"] = hashlib.sha256(
            (current["title"] + "\n" + body).encode("utf-8")
        ).hexdigest()
        # Hash is for retained body only; fail the diff comparator if clipped.
        acc.add(current)
        current = None

    for num, line in enumerate(markdown.splitlines(), start=1):
        text_size += len(line) + 1
        v = VERSION_HEADING.fullmatch(line.strip())
        if v:
            finish()
            version = v.group(1)
            title = version
            identity = hashlib.sha256(
                (source_id + "|version|" + version).encode("utf-8")
            ).hexdigest()[:24]
            current = {
                "event_id": source_id + ":" + identity,
                "source_id": source_id,
                "title": title,
                "version": version,
                "published_at": None,
                "published_date_precision": "unknown",
                "published_date_provenance": "none",
                "date_evidence_text": "",
                "permalink": source_html_url,
                "evidence_locator": {
                    "source_url": source_html_url,
                    "markdown_source_url": markdown_url,
                    "markdown_line_start": num,
                    "heading": line.strip()[:120],
                },
                "body_sha256": "",
                "excerpt": "",
                "excerpt_truncated": False,
                "review_status": "unverified",
                "approved_for_advisor": False,
                "_parts": [],
                "_body_chars": 0,
                "_overflow": False,
            }
            continue
        if current is None:
            continue
        # A subsection such as "### Fixed" is part of this release entry.
        # An unrelated top-level section ends the current release.
        if GENERIC_HEADING.match(line) and not SUBHEADING.match(line):
            finish()
            continue
        if not line.strip() or LINK_LINE.fullmatch(line):
            continue
        room = MAX_MD_EVENT_BODY - current["_body_chars"]
        if room <= 0:
            current["_overflow"] = True
            continue
        if len(line) > room:
            current["_overflow"] = True
        piece = line[:room]
        current["_parts"].append(piece)
        current["_body_chars"] += len(piece)
    finish()
    view = acc.finish()
    events = view["events"]
    # The input is explicitly a version-only changelog; never invent
    # published dates from a version number or the crawl time.
    return {
        "title": "Claude Code changelog",
        "content_sha256": full_sha,
        "word_count": len(markdown.split()),
        "text": markdown[:100_000],
        "text_total_characters": text_size,
        "sections": [],
        "sections_truncated": False,
        "tables": [],
        "tables_truncated": False,
        "prose_paragraphs": 0,
        "main_link_text_ratio": 0.0,
        "visible_latest_date_candidate": "",
        "visible_latest_date_provenance": "",
        "canonical_url": "",
        "release_events_schema": "1.1",
        "release_events": events,
        "release_event_count": view["total"],
        "release_recent_event_count": len(events),
        "release_events_truncated": view["omitted"] > 0,
        "release_historical_event_count_omitted": view["omitted"],
        "release_historical_body_loss_count": view["body_loss_count"],
        "release_recent_body_loss_count": view["recent_body_loss_count"],
        "release_order_direction": view["order"],
        "release_order_basis": view["basis"],
        "release_dated_event_count": 0,
        "release_event_identity_collision": view["collision"],
        "latest_release_date_candidate": None,
        "latest_release_date_status": "unknown_no_official_dates",
        "release_window_complete": view["window_complete"],
        "release_window_coverage_status": (
            "ordered_numeric_versions_on_fetched_markdown"
            if view["window_complete"] else "unverified_markdown_version_order"
        ),
        "source_format": "official_markdown",
        "source_markdown_url": markdown_url,
        "latest_publication_verified": False,
        "approved_for_advisor": False,
    }
