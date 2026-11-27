"""Narrow heading-date evidence for three observed official changelog layouts.

Only exact manifest source/URL pairs and observed heading levels qualify.
A recognizable but impossible date is a boundary, not a valid publication day.
No publication, product ownership, stable-channel or corpus claim is verified.
"""
from datetime import date
import re
from typing import NamedTuple


class HeadingMarker(NamedTuple):
    kind: str
    day: str | None
    version: str | None
    date_text: str


_LAYOUTS = {
    ('deepseek_changelog', 'https://api-docs.deepseek.com/updates/', 2): (
        'date_group', re.compile(r'Date: (?P<day>20[0-9]{2}-[0-9]{2}-[0-9]{2})\u200b?')),
    ('gemini_cli_changelog', 'https://geminicli.com/docs/changelogs/', 2): (
        'dated_heading', re.compile(r'Announcements: v(?P<version>[0-9]+\.[0-9]+\.[0-9]+) - (?P<day>20[0-9]{2}-[0-9]{2}-[0-9]{2})')),
    ('warp_changelog', 'https://docs.warp.dev/changelog/2026/', 3): (
        'dated_heading', re.compile(r'(?P<day>2026\.[0-9]{2}\.[0-9]{2}) \(v(?P<version>0\.[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.[0-9]{2})\)')),
}


def heading_marker(source_id, source_url, level, text):
    """Recognize exact visible markers, preserving the full explicit version."""
    layout = _LAYOUTS.get((source_id, source_url, level))
    if layout is None or not isinstance(text, str) or len(text) > 250:
        return None
    kind, pattern = layout
    match = pattern.fullmatch(text)
    if not match:
        return None
    stamp = match['day']
    try:
        day = date.fromisoformat(stamp.replace('.', '-')).isoformat()
    except ValueError:
        day = None
    return HeadingMarker(kind, day, match.groupdict().get('version'), stamp)


GROQ_ACTION_SCOPE = ('groqcloud_changelog', 'https://console.groq.com/docs/changelog')
_GROQ_ACTION = re.compile(r'(Added|Changed|Deprecated|Removed)(?: +|(?=[A-Z0-9]))[A-Za-z0-9][^\r\n]*')
_GROQ_ANCHOR = re.compile(r'[a-z0-9][a-z0-9_-]{0,119}')


def groq_action_heading(source_id, source_url, level, title, anchor, permalink):
    """Distinguish explicit Groq action labels sharing a subject anchor.

    This is a provisional action/anchor identity, not a publisher event ID,
    date, or release version. Duplicate action+anchor remains ambiguous.
    """
    if ((source_id, source_url) != GROQ_ACTION_SCOPE or level != 3
            or not isinstance(title, str) or not 0 < len(title) < 250
            or not isinstance(anchor, str) or not _GROQ_ANCHOR.fullmatch(anchor)
            or permalink != source_url + '#' + anchor):
        return None
    marker = _GROQ_ACTION.fullmatch(title)
    return marker.group(1).lower() if marker else None
