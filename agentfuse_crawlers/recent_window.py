"""Bounded changelog evidence windows and Scrapy Cloud Item-size safeguards.

"Window complete" only describes recognized entries *on this fetched page*.
It never proves the vendor's entire changelog is current or exhaustive.
"""

from collections import deque
import json
import re

MAX_RECENT_EVENTS = 80
MAX_SOURCE_TEXT = 24_000
MAX_SECTIONS_RETAINED = 16
MAX_SECTION_EXCERPT = 650
MAX_EVENT_EXCERPT = 1000
ITEM_TARGET_BYTES = 650_000
ITEM_ABSOLUTE_GUARD = 900_000
MIN_RECENT_EVENTS = 2


def version_parts(raw):
    """Only comparable numeric releases, not dates or semver prereleases."""
    if not raw or not re.fullmatch(r"\d+(?:\.\d+){1,3}", str(raw)):
        return None
    return tuple(int(x) for x in raw.split("."))


def observed_direction(values):
    """Order of a *complete recognized sequence*: descending, ascending, mixed."""
    if not values or any(x is None for x in values):
        return "unknown"
    if len(values) == 1:
        return "single"
    desc = all(a >= b for a, b in zip(values, values[1:]))
    asc = all(a <= b for a, b in zip(values, values[1:]))
    if desc and not asc:
        return "newest_first"
    if asc and not desc:
        return "oldest_first"
    if desc and asc:
        return "equal_values"
    return "mixed"


class WindowAccumulator:
    """Keep only newest/oldest bounds while inspecting ALL recognized entries.

    Memory is bounded by 2x MAX_RECENT_EVENTS, independent of backlog size.
    Dated entries outrank version-only ordering; a missing year remains unknown.
    """

    def __init__(self, limit=MAX_RECENT_EVENTS):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 80:
            raise ValueError("recent event limit must be between 1 and 80")
        self.limit = limit
        self.first = []
        self.last = deque(maxlen=limit)
        self.count = 0
        self.seen_ids = set()
        self.collisions = False
        self.date_asc = True
        self.date_desc = True
        self.version_asc = True
        self.version_desc = True
        self.all_dated = True
        self.all_versioned = True
        self.previous_date = None
        self.previous_version = None
        self.body_loss_count = 0

    def add(self, event):
        self.count += 1
        if len(self.first) < self.limit:
            self.first.append(event)
        self.last.append(event)
        key = event.get("event_id")
        if not key or key in self.seen_ids:
            self.collisions = True
        self.seen_ids.add(key)
        if event.get("body_text_truncated"):
            self.body_loss_count += 1
        day = event.get("published_at")
        v = version_parts(event.get("version"))
        if not day:
            self.all_dated = False
        if v is None:
            self.all_versioned = False
        if day and self.previous_date is not None:
            if day > self.previous_date:
                self.date_desc = False
            if day < self.previous_date:
                self.date_asc = False
        if day:
            self.previous_date = day
        if v is not None and self.previous_version is not None:
            if v > self.previous_version:
                self.version_desc = False
            if v < self.previous_version:
                self.version_asc = False
        if v is not None:
            self.previous_version = v

    def finish(self):
        if not self.count:
            return {
                "events": [], "total": 0, "omitted": 0,
                "order": "unknown", "basis": "none", "window_complete": False,
                "collision": self.collisions, "body_loss_count": 0,
            }
        def which(asc, desc):
            if self.count == 1:
                return "single"
            if asc and not desc:
                return "oldest_first"
            if desc and not asc:
                return "newest_first"
            if asc and desc:
                return "equal_values"
            return "mixed"
        if self.all_dated:
            direction = which(self.date_asc, self.date_desc)
            basis = "explicit_publication_dates"
        elif self.all_versioned:
            direction = which(self.version_asc, self.version_desc)
            basis = "numeric_versions_no_date_inference"
        else:
            direction = "unknown"
            basis = "mixed_or_undated_entries"
        if direction == "oldest_first":
            selected = list(reversed(self.last))
        else:
            selected = list(self.first)
        recent_loss = sum(bool(e.get("body_text_truncated")) for e in selected)
        # This proves that bounded events from the fetched page were recognized
        # in a consistent date/version order. It is NOT global vendor coverage.
        window_complete = bool(
            self.count >= MIN_RECENT_EVENTS
            and direction in {"newest_first", "oldest_first"}
            and not self.collisions
            and recent_loss == 0
        )
        return {
            "events": selected,
            "total": self.count,
            "omitted": max(0, self.count - len(selected)),
            "order": direction,
            "basis": basis,
            "window_complete": window_complete,
            "collision": self.collisions,
            "body_loss_count": self.body_loss_count,
            "recent_body_loss_count": recent_loss,
        }


def serialized_size(item):
    return len(json.dumps(
        item, ensure_ascii=False, separators=(",", ":"), default=str,
    ).encode("utf-8"))


def compact_changelog_record(record, text, *, keep_text=True):
    """One source Item under a safe byte target; never silently discard evidence.

    Preserve IDs, run provenance, error state, source URL, and complete hashes.
    A cap is recorded as truncation. When budgets cannot be honored, fail closed.
    """
    record["text_total_characters"] = len(text)
    max_text = MAX_SOURCE_TEXT if keep_text else 500
    record["text_retained_characters"] = min(len(text), max_text)
    record["text_truncated"] = len(text) > max_text
    if keep_text:
        record["text"] = text[:max_text]
        record.pop("text_sample", None)
    else:
        record.pop("text", None)
        record["text_sample"] = text[:max_text]

    sections = record.get("sections", [])
    record["sections_total_in_page_excerpt"] = len(sections)
    if len(sections) > MAX_SECTIONS_RETAINED:
        record["sections_truncated"] = True
    record["sections"] = [
        {
            **s,
            "excerpt": s.get("excerpt", "")[:MAX_SECTION_EXCERPT],
            "excerpt_truncated": bool(s.get("excerpt_truncated")
                                      or len(s.get("excerpt", "")) > MAX_SECTION_EXCERPT),
        }
        for s in sections[:MAX_SECTIONS_RETAINED]
    ]
    record["tables"] = []
    record["tables_truncated"] = False
    for event in record.get("release_events", []):
        snippet = event.get("excerpt", "")
        if len(snippet) > MAX_EVENT_EXCERPT:
            event["excerpt_truncated"] = True
            event["excerpt"] = snippet[:MAX_EVENT_EXCERPT]
    record["historical_text_truncated"] = bool(
        record["text_truncated"] or record.get("sections_truncated")
        or record.get("release_events_truncated")
    )
    record["serialized_item_bytes"] = 0

    # Size changes when the byte count field gains digits; iterate to a
    # fixed point and ensure final actual Item serialized size <= target.
    for _ in range(5):
        size = serialized_size(record)
        if size <= ITEM_TARGET_BYTES:
            record["serialized_item_bytes"] = size
            if serialized_size(record) <= ITEM_TARGET_BYTES:
                return record
        # Preserve recent release evidence before generic historic sections.
        if record["sections"]:
            record["sections"] = []
            record["sections_truncated"] = True
            record["historical_text_truncated"] = True
        elif record.get("text"):
            record["text"] = record["text"][:1000]
            record["text_truncated"] = True
            record["historical_text_truncated"] = True
        else:
            for event in record.get("release_events", []):
                event["excerpt"] = event.get("excerpt", "")[:180]
                event["excerpt_truncated"] = True
    record["serialized_item_bytes"] = serialized_size(record)
    if record["serialized_item_bytes"] > ITEM_TARGET_BYTES:
        # Still too large: event evidence is not representable within budget.
        # Keep source identity/provenance and explicit failure instead.
        record["release_event_count_before_budget"] = record.get("release_event_count", 0)
        record["release_events"] = []
        record["release_event_evidence_lost"] = True
        record["release_window_complete"] = False
        record["status"] = "partial_capture"
        record["error"] = "scrapy_item_budget_exceeded"
        record["text"] = record.get("text", "")[:300]
        record["sections"] = []
        record["serialized_item_bytes"] = serialized_size(record)
    if record["serialized_item_bytes"] > ITEM_ABSOLUTE_GUARD:
        raise ValueError("Cannot build safely bounded source Item")
    return record
