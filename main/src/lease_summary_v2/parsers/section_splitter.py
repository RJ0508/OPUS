"""Section detection and splitting for HK commercial offer-to-lease / lease documents."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pdf_text import DocumentText


@dataclass
class Section:
    name: str          # e.g. "principal_terms", "item_1", "schedule_i", ...
    label: str         # display label
    text: str          # raw text of this section
    start_page: int    # 1-based
    end_page: int      # 1-based, inclusive


@dataclass
class SplitDocument:
    principal_terms: str = ""       # pages 1-5 of offer typically
    principal_terms_pages: tuple[int, int] = (1, 1)
    schedule_i: str = ""
    schedule_ii: str = ""
    schedule_iii: str = ""
    annexure: str = ""
    items: dict[str, str] = field(default_factory=dict)  # "1" -> text of item 1
    full_text: str = ""


# ── Patterns for principal-term items (numbered 1-30 at start of line) ─────────
_ITEM_START = re.compile(
    r"(?m)^(\d{1,2})\.\s*\n",
    re.MULTILINE,
)

# ── Patterns for schedule / annexure headings ───────────────────────────────────
_SCHEDULE_HEADINGS = [
    (re.compile(r"SCHEDULE\s+I\b", re.IGNORECASE), "schedule_i"),
    (re.compile(r"SCHEDULE\s+II\b", re.IGNORECASE), "schedule_ii"),
    (re.compile(r"SCHEDULE\s+III\b", re.IGNORECASE), "schedule_iii"),
    (re.compile(r"ANNEXURE\b", re.IGNORECASE), "annexure"),
]

# ── Marker text that signals start of schedule sections in page headers ─────────
_PAGE_HEADER_SCHEDULE = re.compile(
    r"Schedule\s+(I{1,3}|IV)\s+Page\s+\d+",
    re.IGNORECASE,
)
_PAGE_HEADER_ANNEXURE = re.compile(r"Annexure\s+Page\s+\d+", re.IGNORECASE)

# ── Body-level schedule headings (formal tenancy agreements, e.g. Central Plaza) ─
# "THE FIRST SCHEDULE ABOVE REFERRED TO" appears as a heading in the document body
_BODY_SCHEDULE_HEADINGS = [
    (re.compile(r"FIRST\s+SCHEDULE\s+ABOVE\s+REFERRED", re.IGNORECASE), "schedule_i"),
    (re.compile(r"SECOND\s+SCHEDULE\s+ABOVE\s+REFERRED", re.IGNORECASE), "schedule_ii"),
    (re.compile(r"THIRD\s+SCHEDULE\s+ABOVE\s+REFERRED", re.IGNORECASE), "schedule_iii"),
]
_BODY_FIRST_SCHEDULE = re.compile(
    r"FIRST\s+SCHEDULE\s+ABOVE\s+REFERRED", re.IGNORECASE
)

# ── Arabic-numeral SCHEDULE N pages (Trade Desk / formal full lease style) ───────
# Actual SCHEDULE 1 pages start with "SCHEDULE 1" or "SCHEDULE1" (OCR merge) at
# the very top of the page text.  TOC pages reference "Schedule 1" inline (mid-text).
_ARABIC_SCHED_PAGE = re.compile(r"^SCHEDULE\s*([1-9])\b", re.IGNORECASE)
_ARABIC_SCHED_MAP = {"1": "schedule_i", "2": "schedule_ii", "3": "schedule_iii"}

# ── "The Schedule" heading (Deacons / Hang Seng style) ───────────────────────────
# Appears as "The Schedule\nPart I - The Building\n..." in the document body.
_THE_SCHEDULE_HEADING = re.compile(
    r"\bThe\s+Schedule\s*\n\s*Part\s+[IVX1]", re.IGNORECASE
)


def split(doc: DocumentText) -> SplitDocument:
    """Split a DocumentText into named sections."""
    sd = SplitDocument(full_text=doc.full_text)

    # Determine page boundaries for each section by scanning page headers
    principal_end = _find_principal_terms_end(doc)
    sd.principal_terms = doc.pages_range(1, principal_end)
    sd.principal_terms_pages = (1, principal_end)

    schedule_i_pages: list[int] = []
    schedule_ii_pages: list[int] = []
    schedule_iii_pages: list[int] = []
    annexure_pages: list[int] = []

    for p in doc.pages:
        t = p.text
        if _PAGE_HEADER_ANNEXURE.search(t):
            annexure_pages.append(p.page_num)
        elif _PAGE_HEADER_SCHEDULE.search(t):
            m = _PAGE_HEADER_SCHEDULE.search(t)
            roman = m.group(1).upper()
            if roman in ("I",):
                schedule_i_pages.append(p.page_num)
            elif roman in ("II",):
                schedule_ii_pages.append(p.page_num)
            elif roman in ("III",):
                schedule_iii_pages.append(p.page_num)

    if schedule_i_pages:
        sd.schedule_i = doc.pages_range(min(schedule_i_pages), max(schedule_i_pages))
    if schedule_ii_pages:
        sd.schedule_ii = doc.pages_range(min(schedule_ii_pages), max(schedule_ii_pages))
    if schedule_iii_pages:
        sd.schedule_iii = doc.pages_range(min(schedule_iii_pages), max(schedule_iii_pages))
    if annexure_pages:
        sd.annexure = doc.pages_range(min(annexure_pages), max(annexure_pages))

    # ── Body-level schedule headings (formal tenancy agreements) ─────────────────
    # Detect "THE FIRST/SECOND/THIRD SCHEDULE ABOVE REFERRED TO" in document body
    # and assign page ranges to the schedule slots if not already set by page headers.
    current_attr: str | None = None
    current_start: int | None = None

    for p in doc.pages:
        matched_attr: str | None = None
        for pattern, attr in _BODY_SCHEDULE_HEADINGS:
            if pattern.search(p.text):
                matched_attr = attr
                break
        if matched_attr:
            # Close the previous body schedule
            if current_attr and current_start is not None:
                if not getattr(sd, current_attr):
                    setattr(sd, current_attr, doc.pages_range(current_start, p.page_num - 1))
            current_attr = matched_attr
            current_start = p.page_num

    # Close the last body schedule
    if current_attr and current_start is not None:
        if not getattr(sd, current_attr):
            last_page = doc.pages[-1].page_num if doc.pages else current_start
            setattr(sd, current_attr, doc.pages_range(current_start, last_page))

    # ── Arabic-numeral SCHEDULE N / "The Schedule" body headings ─────────────────
    # Runs last; only fills slots still empty after the two passes above.
    _find_numeral_schedule_sections(doc, sd)

    # Extract individual principal-term items from the principal_terms text
    sd.items = _split_items(sd.principal_terms)

    return sd


def _find_numeral_schedule_sections(doc: DocumentText, sd: SplitDocument) -> None:
    """
    Detect Arabic-numeral SCHEDULE N pages (SCHEDULE 1, SCHEDULE 2, …) and
    "The Schedule\\nPart I" body headings (Deacons / Hang Seng style).

    Only fills SplitDocument slots that are still empty after the earlier passes,
    so it never overwrites results already determined by page-header or
    FIRST/SECOND/THIRD SCHEDULE body patterns.
    """
    current_attr: str | None = None
    current_start: int | None = None

    for p in doc.pages:
        matched_attr: str | None = None

        # Arabic-numeral: page TEXT must START with "SCHEDULE N" (distinguishes
        # actual schedule pages from mid-document references / TOC entries).
        m = _ARABIC_SCHED_PAGE.match(p.text.strip()[:20])
        if m:
            matched_attr = _ARABIC_SCHED_MAP.get(m.group(1))

        # "The Schedule\nPart I/II/III/…" heading anywhere on the page
        elif _THE_SCHEDULE_HEADING.search(p.text):
            matched_attr = "schedule_i"

        if matched_attr:
            if current_attr and current_start is not None:
                if not getattr(sd, current_attr):
                    setattr(sd, current_attr, doc.pages_range(current_start, p.page_num - 1))
            current_attr = matched_attr
            current_start = p.page_num

    # Close the last open section
    if current_attr and current_start is not None:
        if not getattr(sd, current_attr):
            last_page = doc.pages[-1].page_num if doc.pages else current_start
            setattr(sd, current_attr, doc.pages_range(current_start, last_page))


def _find_principal_terms_end(doc: DocumentText) -> int:
    """Find last page that belongs to the principal terms (before Schedule I starts)."""
    last_principal = 1
    for p in doc.pages:
        if (_PAGE_HEADER_SCHEDULE.search(p.text) or
                _PAGE_HEADER_ANNEXURE.search(p.text) or
                _BODY_FIRST_SCHEDULE.search(p.text)):
            break
        last_principal = p.page_num
    return last_principal


def _split_items(text: str) -> dict[str, str]:
    """
    Split principal-terms text into numbered items.

    Each item starts with a number like "1." or "12." at the start of a line
    (possibly after optional "(i)" sub-items from the previous item).
    Returns dict "1" -> full text of item 1, etc.
    """
    items: dict[str, str] = {}

    # Use a simpler approach: find numbered items by looking for patterns like:
    # "1.\n" or "12.\n" or "1. \n" at line start
    pattern = re.compile(r"(?m)^(\d{1,2})\.\s*$", re.MULTILINE)

    positions = [(m.group(1), m.start(), m.end()) for m in pattern.finditer(text)]

    for i, (num, start, end) in enumerate(positions):
        if i + 1 < len(positions):
            item_text = text[start:positions[i + 1][1]]
        else:
            item_text = text[start:]
        items[num] = item_text.strip()

    # Fallback: try inline numbering "1.\n" or "1. text" at line start
    if not items:
        pattern2 = re.compile(r"(?m)^(\d{1,2})\.\s+", re.MULTILINE)
        positions2 = [(m.group(1), m.start(), m.end()) for m in pattern2.finditer(text)]
        for i, (num, start, end) in enumerate(positions2):
            if i + 1 < len(positions2):
                item_text = text[start:positions2[i + 1][1]]
            else:
                item_text = text[start:]
            items[num] = item_text.strip()

    return items
