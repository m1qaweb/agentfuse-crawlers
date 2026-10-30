"""Structured, source-linked HTML evidence extraction (never verified facts).

Captures semantic sections and raw pricing table cells without guessing columns,
currencies, billing tiers, or release importance. Designed for static HTML and
respectful Scrapy crawls, not browser rendering or paywall bypassing.
"""

import hashlib
import re
from collections import Counter
from datetime import datetime
import calendar
from urllib.parse import quote, urlsplit

from lxml import etree, html

BLOCKS = frozenset({
    'article', 'blockquote', 'div', 'dl', 'dt', 'dd', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'li', 'ol', 'p', 'pre', 'section', 'table',
    'tbody', 'thead', 'tfoot', 'tr', 'ul',
})
NOISE_XPATH = (
    './/script|.//style|.//noscript|.//template|.//nav|.//aside|'
    './/header|.//footer|.//form|.//svg|.//button|'
    ".//*[@role='navigation']|.//*[@aria-hidden='true']|"
    ".//*[contains(concat(' ',normalize-space(@class),' '),' sidebar ')]|"
    ".//*[contains(concat(' ',normalize-space(@class),' '),' table-of-contents ')]"
)
DATE_ISO = re.compile(r'\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b')
DATE_MONTH = re.compile(
    r'\b(January|February|March|April|May|June|July|August|September|October|November|December|'
    r'Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Sept\.?|Oct\.?|Nov\.?|Dec\.?)'
    r'\s+(\d{1,2})(?:st|nd|rd|th)?[,]?[ ]+(20\d{2})\b', re.I
)

# Do not infer publication year from the crawl timestamp or a server cache header.
# The official page must explicitly supply both the month/year group and day.
GROUP_MONTH_YEAR = re.compile(r'([A-Za-z]{3,9})\s*,?\s*(20\d{2})', re.I)
GROUP_MONTH_DAY = re.compile(r'([A-Za-z]{3,9})\.?\s+(0?[1-9]|[12]\d|3[01])', re.I)

def _month_number(token):
    part = token.lower().rstrip('.')[:3]
    return next((i for i in range(1, 13)
                 if calendar.month_name[i].lower().startswith(part)), None)


def _date_from_month_group(heading, body):
    """Use only a month/year heading followed by a matching standalone day."""
    match = GROUP_MONTH_YEAR.fullmatch(heading.strip())
    if not match:
        return ''
    month = _month_number(match.group(1))
    if not month:
        return ''
    year = int(match.group(2))
    for line in body.splitlines()[1:10]:
        item = GROUP_MONTH_DAY.fullmatch(line.strip())
        if not item or _month_number(item.group(1)) != month:
            continue
        try:
            return datetime(year, month, int(item.group(2))).date().isoformat()
        except ValueError:
            continue
    return ''


def _leading_release_date(text):
    """Require a standalone full date near top, not a date embedded in prose."""
    for line in text.splitlines()[:12]:
        candidate = line.strip()
        if DATE_ISO.fullmatch(candidate) or DATE_MONTH.fullmatch(candidate):
            day = _date_from_heading(candidate)
            if day:
                return day
    return ''


MAX_SECTION_TEXT = 6000
MAX_SECTIONS = 180
MAX_TABLES = 40
MAX_ROWS = 150
MAX_COLS = 25


def _tag(element):
    return element.tag.lower() if isinstance(element.tag, str) else ''


def _clean(node):
    for unwanted in list(node.xpath(NOISE_XPATH)):
        if unwanted.getparent() is not None:
            unwanted.drop_tree()
    return node


def _normalized_lines(value):
    return '\n'.join(
        line for line in (
            re.sub(r'[ \t\r\f\v]+', ' ', row).strip()
            for row in value.split('\n')
        ) if line
    )


def _collect_text(node):
    parts = []
    for event, element in etree.iterwalk(node, events=('start', 'end')):
        tag = _tag(element)
        if event == 'start':
            if tag in BLOCKS or tag == 'br':
                parts.append('\n')
            if tag in {'td', 'th'}:
                parts.append(' | ')
            if element.text:
                parts.append(element.text)
        else:
            if tag in BLOCKS:
                parts.append('\n')
            if element.tail:
                parts.append(element.tail)
    return _normalized_lines(''.join(parts))


def _date_from_heading(heading):
    iso = DATE_ISO.search(heading)
    if iso:
        try:
            return datetime.strptime(iso.group(0).replace('/', '-'), '%Y-%m-%d').date().isoformat()
        except ValueError:
            return ''
    match = DATE_MONTH.search(heading)
    if match:
        month = match.group(1).replace('.', '').lower()
        month_map = {v.lower(): k for k, v in enumerate(
            ['January', 'February', 'March', 'April', 'May', 'June',
             'July', 'August', 'September', 'October', 'November', 'December'], 1)}
        m = next((idx for name, idx in month_map.items() if name.startswith(month[:3])), None)
        if m:
            try:
                return datetime(int(match.group(3)), m, int(match.group(2))).date().isoformat()
            except ValueError:
                pass
    return ''


def _sections(main, source_url):
    result, title_counts = [], Counter()
    current = None
    buffer = []
    total = 0
    current_day = ''

    def flush():
        if current is None:
            return
        body = _normalized_lines(''.join(buffer)).strip()
        if not current['date_candidate']:
            current['date_candidate'] = _date_from_month_group(current['heading'], body)
        # No speculative release classification: even dated sections are unverified.
        result.append({
            'section_id': current['section_id'],
            'heading': current['heading'],
            'level': current['level'],
            'date_candidate': current['date_candidate'],
            'section_url': current['section_url'],
            'excerpt': body[:MAX_SECTION_TEXT],
            'excerpt_truncated': len(body) > MAX_SECTION_TEXT,
            'sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
        })

    for event, element in etree.iterwalk(main, events=('start', 'end')):
        tag = _tag(element)
        if event == 'start' and tag in {'h2', 'h3', 'h4'}:
            flush()
            total += 1
            heading = re.sub(r'\s+', ' ', element.text_content()).strip()[:250]
            key = re.sub(r'[^a-z0-9]+', '-', heading.lower()).strip('-')[:90] or 'untitled'
            title_counts[key] += 1
            suffix = f'-{title_counts[key]}' if title_counts[key] > 1 else ''
            raw_anchor = element.get('id', '')
            anchor = raw_anchor if re.fullmatch(r'[A-Za-z0-9_:.-]{1,120}', raw_anchor) else ''
            section_id = f'{key}{suffix}'
            # Prefer explicit stable anchors: repeated headings otherwise shift IDs
            # whenever a provider inserts another identically named section.
            if anchor:
                section_id = 'anchor-' + anchor.lower()
            section_url = source_url.split('#', 1)[0] + ('#' + quote(anchor) if anchor else '')
            heading_day = _date_from_heading(heading)
            if tag == 'h2':
                current_day = heading_day
            current = {
                'section_id': section_id,
                'heading': heading,
                'level': int(tag[1]),
                'date_candidate': heading_day or current_day,
                'section_url': section_url,
            }
            buffer = []
        if current is None:
            continue
        if event == 'start' and tag == 'time' and not current['date_candidate']:
            raw_date = (element.get('datetime') or '').strip()[:10]
            if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', raw_date):
                current['date_candidate'] = _date_from_heading(raw_date)
        if event == 'start':
            if tag in BLOCKS or tag == 'br':
                buffer.append('\n')
            if element.text:
                buffer.append(element.text)
        else:
            if tag in BLOCKS:
                buffer.append('\n')
            if element.tail:
                buffer.append(element.tail)
    flush()
    # Capture recent/top sections first without claiming older release completeness.
    return result[:MAX_SECTIONS], len(result) > MAX_SECTIONS


def _tables(main):
    tables = []
    truncated = False
    for index, table in enumerate(main.xpath('.//table')):
        if index >= MAX_TABLES:
            truncated = True
            break
        rows = []
        row_nodes = table.xpath('.//tr')
        if len(row_nodes) > MAX_ROWS:
            truncated = True
        for row in row_nodes[:MAX_ROWS]:
            cells = []
            for cell in row.xpath('./th|./td')[:MAX_COLS]:
                # Preserve colspan/rowspan explicitly; don't fabricate alignment.
                content = re.sub(r'\s+', ' ', cell.text_content()).strip()[:1000]
                cells.append({
                    'text': content,
                    'header': _tag(cell) == 'th',
                    'rowspan': cell.get('rowspan', '1'),
                    'colspan': cell.get('colspan', '1'),
                })
            if len(row.xpath('./th|./td')) > MAX_COLS:
                truncated = True
            rows.append(cells)
        caption = table.xpath('./caption[1]')
        tables.append({
            'table_id': f'table-{index + 1}',
            'caption': re.sub(r'\s+', ' ', caption[0].text_content()).strip() if caption else '',
            'rows': rows,
            'rows_truncated': len(row_nodes) > MAX_ROWS,
        })
    return tables, truncated


def extract_evidence(raw_html, source_url):
    """Return structured *unverified* evidence and stable text for comparisons."""
    root = html.fromstring(raw_html)
    title = ' '.join(root.xpath('//title[1]/text()') or []).strip()
    main_nodes = root.xpath('//main | //*[@role="main"]')
    if not main_nodes:
        main_nodes = root.xpath('//article')
    if not main_nodes:
        main_nodes = root.xpath('//body')
    main = max(main_nodes, key=lambda n: len(n.text_content())) if main_nodes else root
    main = _clean(main)
    heading1 = main.xpath('.//h1[1]')
    if heading1:
        title = re.sub(r'\s+', ' ', heading1[0].text_content()).strip() or title
    text = _collect_text(main)
    paragraphs = main.xpath('.//p')
    prose_paragraphs = sum(
        len(re.sub(r'\s+', ' ', p.text_content()).strip()) >= 65
        for p in paragraphs
    )
    links = main.xpath('.//a[@href]')
    link_chars = sum(len(re.sub(r'\s+', ' ', a.text_content()).strip()) for a in links)
    main_link_text_ratio = min(1.0, link_chars / max(len(text), 1))
    sections, sections_truncated = _sections(main, source_url)
    dated_sections = [s['date_candidate'] for s in sections if s['date_candidate']]
    leading_date = _leading_release_date(text) if not dated_sections else ''
    tables, tables_truncated = _tables(main)
    canonical = root.xpath('//link[translate(@rel,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="canonical"]/@href')
    canonical_url = canonical[0].strip() if canonical else ''
    # Don't trust cross-domain canonical links for attribution or fetching.
    if canonical_url and (urlsplit(canonical_url).scheme != 'https'
                          or urlsplit(canonical_url).hostname != urlsplit(source_url).hostname):
        canonical_url = ''
    description = root.xpath('//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="description"]/@content')
    description = re.sub(r'\s+', ' ', description[0]).strip()[:500] if description else ''
    return {
        'title': title[:300],
        'text': text,
        'word_count': len(text.split()),
        'content_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'canonical_url': canonical_url,
        'description': description,
        'language': root.get('lang', ''),
        'prose_paragraphs': prose_paragraphs,
        'main_link_count': len(links),
        'main_link_text_ratio': round(main_link_text_ratio, 4),
        'visible_latest_date_candidate': max(dated_sections + [leading_date], default=''),
        'visible_latest_date_provenance': (
            'dated_section_or_group' if dated_sections else
            'leading_explicit_date_line' if leading_date else ''
        ),
        'sections': sections,
        'sections_truncated': sections_truncated,
        'tables': tables,
        'tables_truncated': tables_truncated,
    }


def extract_text(raw_html):
    """Compatibility wrapper used by legacy callers and original tests."""
    evidence = extract_evidence(raw_html, 'https://example.invalid/source')
    return evidence['title'], evidence['text']
, re.I)
GROUP_MONTH_DAY = re.compile(r'^([A-Za-z]{3,9})\.?\s+(0?[1-9]|[12]\d|3[01])
MAX_SECTIONS = 180
MAX_TABLES = 40
MAX_ROWS = 150
MAX_COLS = 25


def _tag(element):
    return element.tag.lower() if isinstance(element.tag, str) else ''


def _clean(node):
    for unwanted in list(node.xpath(NOISE_XPATH)):
        if unwanted.getparent() is not None:
            unwanted.drop_tree()
    return node


def _normalized_lines(value):
    return '\n'.join(
        line for line in (
            re.sub(r'[ \t\r\f\v]+', ' ', row).strip()
            for row in value.split('\n')
        ) if line
    )


def _collect_text(node):
    parts = []
    for event, element in etree.iterwalk(node, events=('start', 'end')):
        tag = _tag(element)
        if event == 'start':
            if tag in BLOCKS or tag == 'br':
                parts.append('\n')
            if tag in {'td', 'th'}:
                parts.append(' | ')
            if element.text:
                parts.append(element.text)
        else:
            if tag in BLOCKS:
                parts.append('\n')
            if element.tail:
                parts.append(element.tail)
    return _normalized_lines(''.join(parts))


def _date_from_heading(heading):
    iso = DATE_ISO.search(heading)
    if iso:
        try:
            return datetime.strptime(iso.group(0).replace('/', '-'), '%Y-%m-%d').date().isoformat()
        except ValueError:
            return ''
    match = DATE_MONTH.search(heading)
    if match:
        month = match.group(1).replace('.', '').lower()
        month_map = {v.lower(): k for k, v in enumerate(
            ['January', 'February', 'March', 'April', 'May', 'June',
             'July', 'August', 'September', 'October', 'November', 'December'], 1)}
        m = next((idx for name, idx in month_map.items() if name.startswith(month[:3])), None)
        if m:
            try:
                return datetime(int(match.group(3)), m, int(match.group(2))).date().isoformat()
            except ValueError:
                pass
    return ''


def _sections(main, source_url):
    result, title_counts = [], Counter()
    current = None
    buffer = []
    total = 0
    current_day = ''

    def flush():
        if current is None:
            return
        body = _normalized_lines(''.join(buffer)).strip()
        # No speculative release classification: even dated sections are unverified.
        result.append({
            'section_id': current['section_id'],
            'heading': current['heading'],
            'level': current['level'],
            'date_candidate': current['date_candidate'],
            'section_url': current['section_url'],
            'excerpt': body[:MAX_SECTION_TEXT],
            'excerpt_truncated': len(body) > MAX_SECTION_TEXT,
            'sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
        })

    for event, element in etree.iterwalk(main, events=('start', 'end')):
        tag = _tag(element)
        if event == 'start' and tag in {'h2', 'h3', 'h4'}:
            flush()
            total += 1
            heading = re.sub(r'\s+', ' ', element.text_content()).strip()[:250]
            key = re.sub(r'[^a-z0-9]+', '-', heading.lower()).strip('-')[:90] or 'untitled'
            title_counts[key] += 1
            suffix = f'-{title_counts[key]}' if title_counts[key] > 1 else ''
            raw_anchor = element.get('id', '')
            anchor = raw_anchor if re.fullmatch(r'[A-Za-z0-9_:.-]{1,120}', raw_anchor) else ''
            section_id = f'{key}{suffix}'
            # Prefer explicit stable anchors: repeated headings otherwise shift IDs
            # whenever a provider inserts another identically named section.
            if anchor:
                section_id = 'anchor-' + anchor.lower()
            section_url = source_url.split('#', 1)[0] + ('#' + quote(anchor) if anchor else '')
            heading_day = _date_from_heading(heading)
            if tag == 'h2':
                current_day = heading_day
            current = {
                'section_id': section_id,
                'heading': heading,
                'level': int(tag[1]),
                'date_candidate': heading_day or current_day,
                'section_url': section_url,
            }
            buffer = []
        if current is None:
            continue
        if event == 'start' and tag == 'time' and not current['date_candidate']:
            raw_date = (element.get('datetime') or '').strip()[:10]
            if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', raw_date):
                current['date_candidate'] = _date_from_heading(raw_date)
        if event == 'start':
            if tag in BLOCKS or tag == 'br':
                buffer.append('\n')
            if element.text:
                buffer.append(element.text)
        else:
            if tag in BLOCKS:
                buffer.append('\n')
            if element.tail:
                buffer.append(element.tail)
    flush()
    # Capture recent/top sections first without claiming older release completeness.
    return result[:MAX_SECTIONS], len(result) > MAX_SECTIONS


def _tables(main):
    tables = []
    truncated = False
    for index, table in enumerate(main.xpath('.//table')):
        if index >= MAX_TABLES:
            truncated = True
            break
        rows = []
        row_nodes = table.xpath('.//tr')
        if len(row_nodes) > MAX_ROWS:
            truncated = True
        for row in row_nodes[:MAX_ROWS]:
            cells = []
            for cell in row.xpath('./th|./td')[:MAX_COLS]:
                # Preserve colspan/rowspan explicitly; don't fabricate alignment.
                content = re.sub(r'\s+', ' ', cell.text_content()).strip()[:1000]
                cells.append({
                    'text': content,
                    'header': _tag(cell) == 'th',
                    'rowspan': cell.get('rowspan', '1'),
                    'colspan': cell.get('colspan', '1'),
                })
            if len(row.xpath('./th|./td')) > MAX_COLS:
                truncated = True
            rows.append(cells)
        caption = table.xpath('./caption[1]')
        tables.append({
            'table_id': f'table-{index + 1}',
            'caption': re.sub(r'\s+', ' ', caption[0].text_content()).strip() if caption else '',
            'rows': rows,
            'rows_truncated': len(row_nodes) > MAX_ROWS,
        })
    return tables, truncated


def extract_evidence(raw_html, source_url):
    """Return structured *unverified* evidence and stable text for comparisons."""
    root = html.fromstring(raw_html)
    title = ' '.join(root.xpath('//title[1]/text()') or []).strip()
    main_nodes = root.xpath('//main | //*[@role="main"]')
    if not main_nodes:
        main_nodes = root.xpath('//article')
    if not main_nodes:
        main_nodes = root.xpath('//body')
    main = max(main_nodes, key=lambda n: len(n.text_content())) if main_nodes else root
    main = _clean(main)
    heading1 = main.xpath('.//h1[1]')
    if heading1:
        title = re.sub(r'\s+', ' ', heading1[0].text_content()).strip() or title
    text = _collect_text(main)
    paragraphs = main.xpath('.//p')
    prose_paragraphs = sum(
        len(re.sub(r'\s+', ' ', p.text_content()).strip()) >= 65
        for p in paragraphs
    )
    links = main.xpath('.//a[@href]')
    link_chars = sum(len(re.sub(r'\s+', ' ', a.text_content()).strip()) for a in links)
    main_link_text_ratio = min(1.0, link_chars / max(len(text), 1))
    sections, sections_truncated = _sections(main, source_url)
    tables, tables_truncated = _tables(main)
    canonical = root.xpath('//link[translate(@rel,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="canonical"]/@href')
    canonical_url = canonical[0].strip() if canonical else ''
    # Don't trust cross-domain canonical links for attribution or fetching.
    if canonical_url and (urlsplit(canonical_url).scheme != 'https'
                          or urlsplit(canonical_url).hostname != urlsplit(source_url).hostname):
        canonical_url = ''
    description = root.xpath('//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="description"]/@content')
    description = re.sub(r'\s+', ' ', description[0]).strip()[:500] if description else ''
    return {
        'title': title[:300],
        'text': text,
        'word_count': len(text.split()),
        'content_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'canonical_url': canonical_url,
        'description': description,
        'language': root.get('lang', ''),
        'prose_paragraphs': prose_paragraphs,
        'main_link_count': len(links),
        'main_link_text_ratio': round(main_link_text_ratio, 4),
        'visible_latest_date_candidate': max(
            (s['date_candidate'] for s in sections if s['date_candidate']),
            default='',
        ),
        'sections': sections,
        'sections_truncated': sections_truncated,
        'tables': tables,
        'tables_truncated': tables_truncated,
    }


def extract_text(raw_html):
    """Compatibility wrapper used by legacy callers and original tests."""
    evidence = extract_evidence(raw_html, 'https://example.invalid/source')
    return evidence['title'], evidence['text']
, re.I)


def _month_number(token):
    part = token.lower().rstrip('.')[:3]
    return next((i for i in range(1, 13)
                 if calendar.month_name[i].lower().startswith(part)), None)


def _date_from_month_group(heading, body):
    """Example: 'October, 2026' heading followed by standalone 'Oct 30'.

    Only accept a matching month and a standalone day near the group's start.
    Future dates appearing inside prose (such as deprecation deadlines) must
    not be mistaken for dated release headings.
    """
    match = GROUP_MONTH_YEAR.fullmatch(heading.strip())
    if not match:
        return ''
    month = _month_number(match.group(1))
    if not month:
        return ''
    year = int(match.group(2))
    for line in body.splitlines()[1:10]:
        item = GROUP_MONTH_DAY.fullmatch(line.strip())
        if not item or _month_number(item.group(1)) != month:
            continue
        try:
            return datetime(year, month, int(item.group(2))).date().isoformat()
        except ValueError:
            continue
    return ''


def _leading_release_date(text):
    """Require an entire standalone, year-explicit date near the page top.

    Used for release feeds where the date precedes the first h2/h3 heading,
    such as 'Oct 28, 2026' above the release title. Do not scan prose, or use
    HTTP Last-Modified as a release date.
    """
    for line in text.splitlines()[:12]:
        candidate = line.strip()
        if DATE_ISO.fullmatch(candidate) or DATE_MONTH.fullmatch(candidate):
            day = _date_from_heading(candidate)
            if day:
                return day
    return ''


MAX_SECTION_TEXT = 6000
MAX_SECTIONS = 180
MAX_TABLES = 40
MAX_ROWS = 150
MAX_COLS = 25


def _tag(element):
    return element.tag.lower() if isinstance(element.tag, str) else ''


def _clean(node):
    for unwanted in list(node.xpath(NOISE_XPATH)):
        if unwanted.getparent() is not None:
            unwanted.drop_tree()
    return node


def _normalized_lines(value):
    return '\n'.join(
        line for line in (
            re.sub(r'[ \t\r\f\v]+', ' ', row).strip()
            for row in value.split('\n')
        ) if line
    )


def _collect_text(node):
    parts = []
    for event, element in etree.iterwalk(node, events=('start', 'end')):
        tag = _tag(element)
        if event == 'start':
            if tag in BLOCKS or tag == 'br':
                parts.append('\n')
            if tag in {'td', 'th'}:
                parts.append(' | ')
            if element.text:
                parts.append(element.text)
        else:
            if tag in BLOCKS:
                parts.append('\n')
            if element.tail:
                parts.append(element.tail)
    return _normalized_lines(''.join(parts))


def _date_from_heading(heading):
    iso = DATE_ISO.search(heading)
    if iso:
        try:
            return datetime.strptime(iso.group(0).replace('/', '-'), '%Y-%m-%d').date().isoformat()
        except ValueError:
            return ''
    match = DATE_MONTH.search(heading)
    if match:
        month = match.group(1).replace('.', '').lower()
        month_map = {v.lower(): k for k, v in enumerate(
            ['January', 'February', 'March', 'April', 'May', 'June',
             'July', 'August', 'September', 'October', 'November', 'December'], 1)}
        m = next((idx for name, idx in month_map.items() if name.startswith(month[:3])), None)
        if m:
            try:
                return datetime(int(match.group(3)), m, int(match.group(2))).date().isoformat()
            except ValueError:
                pass
    return ''


def _sections(main, source_url):
    result, title_counts = [], Counter()
    current = None
    buffer = []
    total = 0
    current_day = ''

    def flush():
        if current is None:
            return
        body = _normalized_lines(''.join(buffer)).strip()
        # No speculative release classification: even dated sections are unverified.
        result.append({
            'section_id': current['section_id'],
            'heading': current['heading'],
            'level': current['level'],
            'date_candidate': current['date_candidate'],
            'section_url': current['section_url'],
            'excerpt': body[:MAX_SECTION_TEXT],
            'excerpt_truncated': len(body) > MAX_SECTION_TEXT,
            'sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
        })

    for event, element in etree.iterwalk(main, events=('start', 'end')):
        tag = _tag(element)
        if event == 'start' and tag in {'h2', 'h3', 'h4'}:
            flush()
            total += 1
            heading = re.sub(r'\s+', ' ', element.text_content()).strip()[:250]
            key = re.sub(r'[^a-z0-9]+', '-', heading.lower()).strip('-')[:90] or 'untitled'
            title_counts[key] += 1
            suffix = f'-{title_counts[key]}' if title_counts[key] > 1 else ''
            raw_anchor = element.get('id', '')
            anchor = raw_anchor if re.fullmatch(r'[A-Za-z0-9_:.-]{1,120}', raw_anchor) else ''
            section_id = f'{key}{suffix}'
            # Prefer explicit stable anchors: repeated headings otherwise shift IDs
            # whenever a provider inserts another identically named section.
            if anchor:
                section_id = 'anchor-' + anchor.lower()
            section_url = source_url.split('#', 1)[0] + ('#' + quote(anchor) if anchor else '')
            heading_day = _date_from_heading(heading)
            if tag == 'h2':
                current_day = heading_day
            current = {
                'section_id': section_id,
                'heading': heading,
                'level': int(tag[1]),
                'date_candidate': heading_day or current_day,
                'section_url': section_url,
            }
            buffer = []
        if current is None:
            continue
        if event == 'start' and tag == 'time' and not current['date_candidate']:
            raw_date = (element.get('datetime') or '').strip()[:10]
            if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', raw_date):
                current['date_candidate'] = _date_from_heading(raw_date)
        if event == 'start':
            if tag in BLOCKS or tag == 'br':
                buffer.append('\n')
            if element.text:
                buffer.append(element.text)
        else:
            if tag in BLOCKS:
                buffer.append('\n')
            if element.tail:
                buffer.append(element.tail)
    flush()
    # Capture recent/top sections first without claiming older release completeness.
    return result[:MAX_SECTIONS], len(result) > MAX_SECTIONS


def _tables(main):
    tables = []
    truncated = False
    for index, table in enumerate(main.xpath('.//table')):
        if index >= MAX_TABLES:
            truncated = True
            break
        rows = []
        row_nodes = table.xpath('.//tr')
        if len(row_nodes) > MAX_ROWS:
            truncated = True
        for row in row_nodes[:MAX_ROWS]:
            cells = []
            for cell in row.xpath('./th|./td')[:MAX_COLS]:
                # Preserve colspan/rowspan explicitly; don't fabricate alignment.
                content = re.sub(r'\s+', ' ', cell.text_content()).strip()[:1000]
                cells.append({
                    'text': content,
                    'header': _tag(cell) == 'th',
                    'rowspan': cell.get('rowspan', '1'),
                    'colspan': cell.get('colspan', '1'),
                })
            if len(row.xpath('./th|./td')) > MAX_COLS:
                truncated = True
            rows.append(cells)
        caption = table.xpath('./caption[1]')
        tables.append({
            'table_id': f'table-{index + 1}',
            'caption': re.sub(r'\s+', ' ', caption[0].text_content()).strip() if caption else '',
            'rows': rows,
            'rows_truncated': len(row_nodes) > MAX_ROWS,
        })
    return tables, truncated


def extract_evidence(raw_html, source_url):
    """Return structured *unverified* evidence and stable text for comparisons."""
    root = html.fromstring(raw_html)
    title = ' '.join(root.xpath('//title[1]/text()') or []).strip()
    main_nodes = root.xpath('//main | //*[@role="main"]')
    if not main_nodes:
        main_nodes = root.xpath('//article')
    if not main_nodes:
        main_nodes = root.xpath('//body')
    main = max(main_nodes, key=lambda n: len(n.text_content())) if main_nodes else root
    main = _clean(main)
    heading1 = main.xpath('.//h1[1]')
    if heading1:
        title = re.sub(r'\s+', ' ', heading1[0].text_content()).strip() or title
    text = _collect_text(main)
    paragraphs = main.xpath('.//p')
    prose_paragraphs = sum(
        len(re.sub(r'\s+', ' ', p.text_content()).strip()) >= 65
        for p in paragraphs
    )
    links = main.xpath('.//a[@href]')
    link_chars = sum(len(re.sub(r'\s+', ' ', a.text_content()).strip()) for a in links)
    main_link_text_ratio = min(1.0, link_chars / max(len(text), 1))
    sections, sections_truncated = _sections(main, source_url)
    tables, tables_truncated = _tables(main)
    canonical = root.xpath('//link[translate(@rel,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="canonical"]/@href')
    canonical_url = canonical[0].strip() if canonical else ''
    # Don't trust cross-domain canonical links for attribution or fetching.
    if canonical_url and (urlsplit(canonical_url).scheme != 'https'
                          or urlsplit(canonical_url).hostname != urlsplit(source_url).hostname):
        canonical_url = ''
    description = root.xpath('//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="description"]/@content')
    description = re.sub(r'\s+', ' ', description[0]).strip()[:500] if description else ''
    return {
        'title': title[:300],
        'text': text,
        'word_count': len(text.split()),
        'content_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'canonical_url': canonical_url,
        'description': description,
        'language': root.get('lang', ''),
        'prose_paragraphs': prose_paragraphs,
        'main_link_count': len(links),
        'main_link_text_ratio': round(main_link_text_ratio, 4),
        'visible_latest_date_candidate': max(
            (s['date_candidate'] for s in sections if s['date_candidate']),
            default='',
        ),
        'sections': sections,
        'sections_truncated': sections_truncated,
        'tables': tables,
        'tables_truncated': tables_truncated,
    }


def extract_text(raw_html):
    """Compatibility wrapper used by legacy callers and original tests."""
    evidence = extract_evidence(raw_html, 'https://example.invalid/source')
    return evidence['title'], evidence['text']
