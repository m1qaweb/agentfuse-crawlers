"""Synthetic representatives; no captured publisher bodies in the test suite."""
import pytest

from agentfuse_crawlers.release_heading_layouts import heading_marker

DEEPSEEK = ('deepseek_changelog', 'https://api-docs.deepseek.com/updates/', 2)
GEMINI = ('gemini_cli_changelog', 'https://geminicli.com/docs/changelogs/', 2)
WARP = ('warp_changelog', 'https://docs.warp.dev/changelog/2026/', 3)


@pytest.mark.parametrize('scope,heading,kind,day,version', [
    (DEEPSEEK, 'Date: 2026-11-12\u200b', 'date_group', '2026-11-12', None),
    (DEEPSEEK, 'Date: 2025-01-01', 'date_group', '2025-01-01', None),
    (GEMINI, 'Announcements: v0.99.1 - 2026-11-12', 'dated_heading', '2026-11-12', '0.99.1'),
    (WARP, '2026.11.12 (v0.2026.11.11.07.42)', 'dated_heading', '2026-11-12', '0.2026.11.11.07.42'),
])
def test_known_heading(scope, heading, kind, day, version):
    marker = heading_marker(*scope, heading)
    assert (marker.kind, marker.day, marker.version) == (kind, day, version)


@pytest.mark.parametrize('scope,heading', [
    (DEEPSEEK, 'Date: 2026-02-30'),
    (GEMINI, 'Announcements: v0.99.1 - 2026-13-01'),
    (WARP, '2026.11.31 (v0.2026.11.11.07.42)'),
])
def test_impossible_date_is_a_boundary_not_a_date(scope, heading):
    marker = heading_marker(*scope, heading)
    assert marker is not None and marker.day is None


@pytest.mark.parametrize('scope,heading', [
    (('other_changelog', *GEMINI[1:]), 'Announcements: v0.99.1 - 2026-11-12'),
    ((GEMINI[0], 'https://geminicli.com/other', 2), 'Announcements: v0.99.1 - 2026-11-12'),
    ((DEEPSEEK[0], DEEPSEEK[1], 3), 'Date: 2026-11-12'),
    (GEMINI, 'Deprecation of v0.99.1 - 2026-11-12'),
    (GEMINI, 'Announcements: v0.99.1 - 2026-11-12 (planned)'),
    (DEEPSEEK, 'Date: 2026-11-12 - migration deadline'),
    (WARP, '2026.11.12 (planned v0.2026.11.11.07.42)'),
    (WARP, '2027.01.01 (v0.2026.12.31.07.42)'),
    (WARP, '2026.11.12'),
])
def test_unrecognized_layout_never_claims_date(scope, heading):
    assert heading_marker(*scope, heading) is None
