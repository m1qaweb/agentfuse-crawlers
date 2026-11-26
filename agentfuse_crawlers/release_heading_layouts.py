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
