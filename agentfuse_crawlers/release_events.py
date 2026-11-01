"""Conservative release-event candidates from official changelog HTML.

An event date is recognized ONLY when attached to a visible event marker:
a date heading, standalone dateline, matching month/year group, or <time>.
Dates inside explanatory prose and HTTP headers are never publication dates.
Everything produced here is unverified, including event identity and dates.

The module is intentionally a deterministic extractor, not a new spider.
"""

import hashlib
import re
from datetime import date
from urllib.parse import quote, urljoin, urlsplit

from lxml import etree

from agentfuse_crawlers.recent_window import WindowAccumulator

MAX_EVENTS = 80
MAX_BODY_CHARS = 24000
MAX_EXCERPT = 1200
MAX_TITLE = 180
DATE_ISO = re.compile(r"(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])")
DATE_WORDS = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+"
    r"([0-3]?\d)(?:st|nd|rd|th)?[,]?\s+(20\d{2})", re.I
)
DATE_DAY_FIRST = re.compile(
    r"([0-3]?\d)\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|"
    r"Aug|Sep|Sept|Oct|Nov|Dec)\.?,?\s+(20\d{2})", re.I
)
MONTH_YEAR = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"\.?,?\s+(20\d{2})", re.I
)
MONTH_DAY = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"\.?\s+([0-3]?\d)(?:st|nd|rd|th)?", re.I
)
VERSION = re.compile(
    r"(?<![\w.])v?(\d+\.\d+(?:\.\d+){0,3}(?:-[A-Za-z0-9.-]+)?)\b",
    re.I,
)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
SKIP_TITLE = {
    "changelog", "change log", "release notes", "releases", "what's new",
    "recent updates", "latest releases",
    "product updates", "documentation", "updates", "latest updates",
}
SUBHEADING = {"features", "bug fixes", "fixes", "improvements", "changes", "other"}
# Only recurring, non-specific section labels can use a dated heading as a
# distinct review-only identity when there is no release-owned permalink.
# Source-visible dates are not verified publication dates: identity changes
# after vendor date corrections MUST NEVER generate a new-release alert.
GENERIC_DATED_HEADINGS = frozenset({
    "added", "new", "fixed", "fixes", "bug fixes", "bug fix",
    "bug fixes and reliability improvements", "what s changed",
    "what changed", "what s new", "highlights", "changes",
    "improvements", "features", "new features", "enhancements",
    "maintenance", "maintenance updates", "performance improvements",
    "reliability improvements", "security updates", "general updates",
    "updates", "other", "release notes", "other changes",
})
PUBLISHED_DATELINE = re.compile(
    r"^(?:(?:published|released)\s+on|published|released|"
    r"publication\s+date|release\s+date)\s*[:—-]?\s*(.+)$",
    re.I,
)
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5"}
BODY_TAGS = {"p", "li", "pre", "blockquote"}


def _normalize(value):
    return " ".join(str(value).split()).strip()


def _tag(node):
    return node.tag.lower() if isinstance(node.tag, str) else ""


def _year_month(value):
    match = MONTH_YEAR.fullmatch(_normalize(value))
    if match:
        return int(match.group(2)), MONTHS.get(match.group(1).lower()[:3])
    return None


def _date(value, month_context=None):
    """Return (ISO day or None, source_kind); an unknown year is never filled."""
    text = _normalize(value)
    match = DATE_ISO.fullmatch(text)
    if match:
        values = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        match = DATE_WORDS.fullmatch(text)
        if match:
            values = int(match.group(3)), MONTHS.get(match.group(1).lower()[:3]), int(match.group(2))
        else:
            match = DATE_DAY_FIRST.fullmatch(text)
            if match:
                values = int(match.group(3)), MONTHS.get(match.group(2).lower()[:3]), int(match.group(1))
            else:
                partial = MONTH_DAY.fullmatch(text)
                if not partial:
                    return None, ""
                month = MONTHS.get(partial.group(1).lower()[:3])
                if month_context and month_context[1] == month:
                    values = month_context[0], month, int(partial.group(2))
                    kind = "month_day_with_explicit_group_year"
                else:
                    # This is a dateline, but the year is absent or unmatched.
                    return None, "unresolved_month_day"
                try:
                    return date(*values).isoformat(), kind
                except (ValueError, TypeError):
                    return None, "invalid_date"
    try:
        return date(*values).isoformat(), "explicit_date"
    except (ValueError, TypeError):
        return None, "invalid_date"


def _marker_shape(text):
    text = _normalize(text)
    return bool(
        DATE_ISO.fullmatch(text) or DATE_WORDS.fullmatch(text)
        or DATE_DAY_FIRST.fullmatch(text) or MONTH_DAY.fullmatch(text)
    )


def _explicit_publication_dateline(text):
    """Read only an entire explicitly labeled published/released dateline."""
    value = _normalize(text)
    m = PUBLISHED_DATELINE.fullmatch(value)
    if not m:
        return None
    stamp = m.group(1).strip()
    # Never treat 'released on date X...' prose or 'updated' labels as a
    # date. The exact suffix must be an independently recognizable dateline.
    if _marker_shape(stamp):
        return stamp
    return None


def _generic_dated_title(title):
    tokens = re.sub(r"[^a-z0-9]+", " ", _normalize(title).casefold()).strip()
    return tokens in GENERIC_DATED_HEADINGS


def _inline_heading(text, group):
    """Accept a date at the START of a heading, not any date in its body.

    Separator must be outside ISO yyyy-mm-dd; a title about a future
    deprecation deadline is not an official publication date.
    """
    clean = _normalize(text)
    for separator in (" — ", " – ", " | ", " : ", " - ", ": ", "—", "–", "|"):
        if separator not in clean:
            continue
        stamp, title = clean.split(separator, 1)
        if not title.strip():
            continue
        parsed, kind = _date(stamp, group)
        if parsed or kind == "unresolved_month_day":
            return title.strip(), parsed, kind, stamp.strip()
    return text, None, "", ""


def _first_party_reference(href, source_url):
    """An allowlisted source-host reference, not an authorized crawl target."""
    from urllib.parse import urlunsplit

    source = urlsplit(source_url)
    target = urljoin(source_url, href)
    dest = urlsplit(target)
    try:
        safe = (
            dest.scheme == "https" and dest.hostname == source.hostname
            and not dest.username and not dest.password
            and dest.port in (None, 443)
        )
    except ValueError:
        safe = False
    if not safe:
        return None
    if dest.fragment and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", dest.fragment):
        return None
    # Never copy potentially credential-bearing query strings into evidence.
    return urlunsplit((
        dest.scheme, dest.netloc, dest.path, "", dest.fragment[:120],
    ))[:800]


def _related_references(node, source_url):
    """Docs links remain optional supporting evidence, NEVER event identity."""
    links = []
    for link in node.xpath(".//a[@href]")[:5]:
        target = _first_party_reference(link.get("href", ""), source_url)
        if target and target != source_url and target not in links:
            links.append(target)
        if len(links) == 3:
            break
    return links


def _permalink(node, source_url):
    """Only a release-owned anchor or nested announcement URL is identity.

    A heading may link to a common /guides/... or /models/... page, but that
    is NOT the publication's permalink. Treating related documentation
    links as release identity collapsed distinct OpenAI/Anthropic/Gemini
    announcements in the October 31 owner's official Zyte run.
    """
    source = urlsplit(source_url)
    source_path = source.path.rstrip("/")
    anchor = node.get("id", "")
    if anchor and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", anchor):
        return source_url.split("#", 1)[0] + "#" + quote(anchor)
    for link in node.xpath(".//a[@href]")[:5]:
        target = _first_party_reference(link.get("href", ""), source_url)
        if not target:
            continue
        dest = urlsplit(target)
        # Explicitly nested under THIS changelog, for example
        # /changelog/release-123 or /releases/tag/v1.2.3. A sibling guide,
        # pricing page, model documentation, or shared releases INDEX does
        # not get to dictate event identity.
        if dest.path.startswith(source_path + "/") and dest.path != source.path:
            return target
        if (dest.path.rstrip("/") == source_path
                and dest.fragment not in {"", "top", "changelog", "releases"}):
            return target
    for ancestor in list(node.iterancestors())[:4]:
        if _tag(ancestor) not in {"article", "section", "li", "div"}:
            continue
        # Only a single-heading release card can own a permalink. A parent
        # list, multi-event section or shared documentation index cannot.
        headings = ancestor.xpath(".//h2|.//h3|.//h4|.//h5")
        if len(headings) != 1 or headings[0] is not node:
            continue
        anchor = ancestor.get("id", "")
        if anchor and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", anchor):
            return source_url.split("#", 1)[0] + "#" + quote(anchor)
        # Release-owned links may appear beside a heading, not within it.
        # Retain the strict nesting under this exact changelog URL; never
        # borrow shared guides, release-list indexes or cross-host pages.
        for link in ancestor.xpath(".//a[@href]")[:8]:
            target = _first_party_reference(link.get("href", ""), source_url)
            if target and urlsplit(target).path.startswith(source_path + "/"):
                return target
    return source_url

def _signals(main):
    """Ordered semantic tokens; only standalone date text is a date marker."""
    for node in main.iter():
        tag = _tag(node)
        if tag == "div" and any(
            _tag(child) in {"div", "p", "li", "section", "article",
                            "h1", "h2", "h3", "h4", "h5", "pre"}
            for child in node
        ):
            # A wrapper can contain an entire long changelog. Never flatten
            # its descendants repeatedly merely to inspect its date text.
            continue
        if tag in HEADING_TAGS:
            title = _normalize(node.text_content())[:250]
            if title:
                yield "heading", title, node, int(tag[1])
        elif tag in {"time", "relative-time"}:
            date_role = " ".join(
                node.get(x, "") for x in
                ("itemprop", "class", "aria-label", "data-testid")
            ).lower()
            if any(x in date_role for x in (
                "datemodified", "date-modified", "last-modified",
                "last-updated", "updated-at", "last updated",
                "last edited", "edited-at", "modified-at",
            )):
                continue  # Edited time is not a release publication date.
            value = (node.get("datetime") or node.get("dateTime") or "").strip()
            if value and DATE_ISO.fullmatch(value[:10]) and _date(value[:10])[0]:
                yield "timestamp", value[:10], node, 0
                continue
            # Many official article cards display <time>Oct 28, 2026</time>
            # without machine-readable datetime. The ENTIRE visible value
            # must still be an explicit day; do not use parent prose or year
            # inference. If datetime attribute exists but conflicts, refuse.
            visible = _normalize(node.text_content())
            direct = visible if _marker_shape(visible) else _explicit_publication_dateline(visible)
            if direct and _date(direct)[0] and not value:
                yield "date", direct, node, 0
        elif tag in {"p", "div", "span", "small", "strong", "b"}:
            # Only parse a date when the entire node text is the dateline.
            # Skip wrapper nodes that simply repeat a child dateline.
            value = _normalize(node.text_content())
            dateline = (
                value if _marker_shape(value)
                else _explicit_publication_dateline(value)
            )
            if len(value) > 65 or dateline is None:
                if tag == "p":
                    if value:
                        yield "body", value, node, 0
                elif tag == "div" and len(value) >= 12 and len(value) <= 400 and not (
                    node.xpath(".//p|.//li|.//h1|.//h2|.//h3|.//h4|.//h5|.//time")
                ):
                    yield "body", value, node, 0
                continue
            if any(_tag(a) in HEADING_TAGS for a in node.iterancestors()):
                continue
            if any(_marker_shape(_normalize(x.text_content())) for x in node.iterdescendants()
                   if _tag(x) in {"p", "div", "span", "small", "strong", "b", "time"}):
                continue
            yield "date", dateline, node, 0
        elif tag in {"li", "pre", "blockquote"}:
            # A list item wrapping paragraphs or headings is not independent text.
            if node.xpath(".//p|.//h1|.//h2|.//h3|.//h4|.//h5"):
                continue
            value = _normalize(node.text_content())
            if value:
                yield "body", value, node, 0


def _make_event(source_id, source_url, title, heading_node, day, kind, date_text):
    version_match = VERSION.search(title)
    version = version_match.group(1) if version_match else None
    permalink = _permalink(heading_node, source_url)
    related = _related_references(heading_node, source_url)
    # Use the FULL recognized heading (up to parser's bounded 250 chars), not
    # the 100-character display excerpt. A publication-date correction should
    # be an edit, not falsely appear as a brand-new release.
    stable_heading = _normalize(title).casefold()
    title = _normalize(title)[:MAX_TITLE]
    generic_dated = bool(
        permalink == source_url and not version and day
        and _generic_dated_title(title)
    )
    identity = (
        "announcement:" + permalink if permalink != source_url
        else "dated_generic:" + stable_heading + "|day:" + day
        if generic_dated
        else "heading:" + stable_heading + "|version:" + (version or "")
    )
    digest = hashlib.sha256((source_id + "|" + identity).encode("utf-8")).hexdigest()[:24]
    return {
        "event_id": source_id + ":" + digest,
        "source_id": source_id,
        "title": title,
        "version": version,
        "published_at": day,
        "published_date_precision": "day" if day else "unknown",
        "published_date_provenance": kind or "none",
        "date_evidence_text": date_text[:80] if date_text else "",
        "permalink": permalink,
        "related_documentation_urls": related,
        "identity_basis": (
            "release_owned_permalink" if permalink != source_url
            else "date_scoped_generic_heading_review_only" if generic_dated
            else "stable_title_and_version_no_date"
        ),
        "release_identity_requires_manual_review": generic_dated,
        "evidence_locator": {
            "heading_id": heading_node.get("id", "")[:120],
            "source_url": source_url,
        },
        "body_sha256": "",
        "excerpt": "",
        "excerpt_truncated": False,
        "review_status": "unverified",
        "approved_for_advisor": False,
        "_body": [],
        "_body_length": 0,
        "_level": 2,
        "_date_scope": False,
        "_body_overflow": False,
    }


def _finalize_generic_date_identity(event, source_id, source_url):
    """An in-card <time> may appear AFTER the heading used to create event.

    Finalize review-only dated identity from the completed event, not solely
    the date known when its heading was first encountered.
    """
    if (event.get("identity_basis") == "stable_title_and_version_no_date"
            and event.get("permalink") == source_url
            and not event.get("version")
            and event.get("published_at")
            and _generic_dated_title(event.get("title", ""))):
        stable_heading = _normalize(event["title"]).casefold()
        identity = (
            "dated_generic:" + stable_heading + "|day:" + event["published_at"]
        )
        event["event_id"] = source_id + ":" + hashlib.sha256(
            (source_id + "|" + identity).encode("utf-8")
        ).hexdigest()[:24]
        event["identity_basis"] = "date_scoped_generic_heading_review_only"
        event["release_identity_requires_manual_review"] = True


def extract_release_events(main, source_url, source_id):
    """Build bounded candidates; no inferred publication dates or automatic approval.

    Return only candidates, not confirmed changes or current supported products.
    This first iteration does not guarantee complete historical release coverage.
    """
    window = WindowAccumulator(limit=MAX_EVENTS)
    current = None
    month_group = None
    date_context = (None, "", "")
    context_heading_level = None
    date_group_active = False
    pending_date = False
    entries_seen = 0

    def finish():
        nonlocal current, entries_seen
        if current is None:
            return
        body = _normalize(" ".join(current.pop("_body")))
        current.pop("_body_length", None)
        heading_level = current.pop("_level")
        current.pop("_date_scope")
        # Ordinary page subheadings are not evidence of a release. Preserve
        # undated candidates only for versions or a real month/day marker
        # whose year could not be established.
        unresolved_dateline = "unresolved_month_day" in current["published_date_provenance"]
        if not (current["published_at"] or current["version"] or unresolved_dateline):
            current = None
            return
        # The entire bounded event text is hashed even when the display
        # excerpt must be clipped. PR03 will add full recent-window archives.
        current["body_sha256"] = hashlib.sha256(
            (current["title"] + "\n" + body).encode("utf-8")
        ).hexdigest()
        current["excerpt"] = body[:MAX_EXCERPT]
        current["excerpt_truncated"] = len(body) > MAX_EXCERPT
        current["body_text_truncated"] = bool(current.pop("_body_overflow", False))
        current["heading_level"] = heading_level
        _finalize_generic_date_identity(current, source_id, source_url)
        entries_seen += 1
        window.add(current)
        current = None

    for typ, text, node, level in _signals(main):
        if typ == "heading":
            # H1 normally identifies the entire page; it is not a release
            # event unless it explicitly contains a version or a dateline.
            if level == 1 and not VERSION.search(text) and not _date(text)[0]:
                continue
            group = _year_month(text)
            if group:
                finish()
                month_group = group
                date_context = (None, "", "")
                context_heading_level = level
                date_group_active = False
                pending_date = False
                continue
            parsed_date, kind = _date(text, month_group)
            if parsed_date or kind in {"unresolved_month_day", "invalid_date"}:
                finish()
                date_context = (parsed_date, "heading_" + kind, text)
                context_heading_level = level
                date_group_active = True
                pending_date = True
                continue
            # Exit a month/year group when a sibling or parent heading changes
            # topic; no October 2026 inheritance into a later docs section.
            if (month_group is not None and context_heading_level is not None
                    and level <= context_heading_level):
                month_group = None
            title, inline_day, inline_kind, stamp = _inline_heading(text, month_group)
            if (current is not None and level > current["_level"]
                    and not date_group_active and not VERSION.search(text)):
                # Deeper generic headings within an identified release are
                # subheadings. A separately versioned nested heading must
                # remain its own (potentially undated) release candidate.
                current["_body"].append(text)
                continue
            finish()
            if title.lower() in SKIP_TITLE:
                date_context = (None, "", "")
                date_group_active = False
                pending_date = False
                continue
            if date_group_active and context_heading_level is not None:
                if level <= context_heading_level:
                    date_context = (None, "", "")
                    date_group_active = False
                    pending_date = False
            if inline_kind:
                chosen = (inline_day, "heading_inline_" + inline_kind, stamp)
            elif pending_date or date_group_active:
                chosen = date_context
            else:
                chosen = (None, "", "")
            current = _make_event(source_id, source_url, title, node, *chosen)
            current["_level"] = level
            current["_date_scope"] = date_group_active
            # An ordinary dateline preceding a heading applies once. A day
            # grouping heading applies to nested release titles on that day.
            pending_date = False
            if not date_group_active:
                date_context = (None, "", "")
        elif typ in {"date", "timestamp"}:
            parsed, kind = _date(text, month_group)
            if typ == "timestamp" and not parsed:
                continue
            if not parsed and kind not in {"unresolved_month_day", "invalid_date"}:
                continue
            if current is not None and not current["_body"] and current["published_at"] is None:
                current["published_at"] = parsed
                current["published_date_precision"] = "day" if parsed else "unknown"
                current["published_date_provenance"] = (
                    "html_time_datetime" if typ == "timestamp" else "adjacent_" + kind
                )
                current["date_evidence_text"] = text[:80]
            else:
                finish()
                date_context = (parsed,
                                "html_time_datetime" if typ == "timestamp" else "dateline_" + kind,
                                text)
                pending_date = True
                # Day markers nested under an explicit month/year heading
                # may group several same-day h3 release entries. An ordinary
                # standalone date outside that context applies to one card.
                date_group_active = month_group is not None
                if not date_group_active:
                    context_heading_level = None
        elif typ == "body":
            if current is not None:
                # Bound live memory per event; preserve clipping honestly.
                room = MAX_BODY_CHARS - current["_body_length"]
                if room < len(text):
                    current["_body_overflow"] = True
                if room > 0:
                    piece = text[:room]
                    current["_body"].append(piece)
                    current["_body_length"] += len(piece)
            elif pending_date and len(text) >= 24:
                # A date heading followed directly by prose may represent one
                # dated entry, but must remain an unverified candidate.
                title = text[:100]
                current = _make_event(source_id, source_url, title, node, *date_context)
                current["_body"].append(text[:MAX_BODY_CHARS])
                current["_level"] = 5
                pending_date = False
                date_context = (None, "", "")
                date_group_active = False
    finish()

    view = window.finish()
    events = view["events"]
    collision = view["collision"]
    dated = [entry["published_at"] for entry in events if entry["published_at"]]
    newest_undated = not window.all_dated
    # Only an explicitly dated, ordered window is eligible for a claimed
    # page-level newest date. For a single identified event we expose its
    # actual date as a candidate, without claiming the page is exhaustive.
    dated_order_ok = (
        window.all_dated and view["order"] in {
            "newest_first", "oldest_first", "equal_values", "single",
        }
    )
    reliable_date = bool(dated_order_ok and dated and not collision
                         and view["recent_body_loss_count"] == 0)
    latest = max(dated) if reliable_date else None
    return {
        "release_events_schema": "1.1",
        # A changed event-ID algorithm requires a NEW baseline compared with
        # older archived Items. Same schema of event fields is not the same
        # semantic identity revision. Never issue hundreds of false news.
        "release_identity_revision": "release_owner_date_scope_v3",
        "release_events": events,
        "release_event_count": entries_seen,
        "release_recent_event_count": len(events),
        # Historical retention is separate from completeness of the newest
        # recognized window. A publisher may have hundreds of old releases.
        "release_events_truncated": view["omitted"] > 0,
        "release_historical_event_count_omitted": view["omitted"],
        "release_historical_body_loss_count": view["body_loss_count"],
        "release_recent_body_loss_count": view["recent_body_loss_count"],
        "release_order_direction": view["order"],
        "release_order_basis": view["basis"],
        "release_dated_event_count": len(dated),
        "release_date_scoped_generic_event_count": sum(
            e.get("identity_basis") == "date_scoped_generic_heading_review_only"
            for e in events
        ),
        # An explicitly dated event can be reviewed individually when the
        # page's release order is mixed. Do NOT turn this list into a claimed
        # newest publisher release or an automatic alert.
        "release_individual_date_candidates": [
            {
                "event_id": e["event_id"],
                "published_at": e["published_at"],
                "date_evidence_text": e["date_evidence_text"],
                "published_date_provenance": e["published_date_provenance"],
                "permalink": e["permalink"],
                "review_status": "unverified",
            }
            for e in events if e.get("published_at")
        ][:12],
        "release_event_identity_collision": collision,
        "latest_release_date_candidate": latest,
        "latest_release_date_status": (
            "ambiguous_undated_or_collision"
            if newest_undated or collision or view["order"] in {"mixed", "unknown"}
            else "event_date_candidate_only" if latest else "unknown"
        ),
        "release_window_complete": view["window_complete"],
        "release_window_coverage_status": (
            "ordered_recognized_events_on_fetched_page"
            if view["window_complete"] else "unverified_order_or_entry_evidence"
        ),
        "latest_publication_verified": False,
        "approved_for_advisor": False,
    }
