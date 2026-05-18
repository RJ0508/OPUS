"""Date normalization for HK lease documents."""
from __future__ import annotations

import datetime
import re

from dateutil import parser as dateutil_parser


# ── Common HK date patterns ─────────────────────────────────────────────────────
_DATE_PATTERNS = [
    # "11 February 2026" / "11th February 2026"
    re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{4})\b",
        re.IGNORECASE,
    ),
    # "February 11, 2026" / "February 11 2026"
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
        re.IGNORECASE,
    ),
    # "2026-02-11" ISO
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    # "11/02/2026" DD/MM/YYYY
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
]


def parse_date(text: str) -> datetime.date | None:
    """Parse a date string to datetime.date. Returns None on failure."""
    if not text:
        return None
    text = text.strip()
    # Try dateutil first (very flexible)
    try:
        dt = dateutil_parser.parse(text, dayfirst=True)
        return dt.date()
    except Exception:
        pass
    return None


def find_dates(text: str) -> list[tuple[datetime.date, str]]:
    """Find all date-like expressions in text. Returns list of (date, raw_match)."""
    results: list[tuple[datetime.date, str]] = []
    seen: set[str] = set()

    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(0)
            if raw in seen:
                continue
            seen.add(raw)
            d = parse_date(raw)
            if d:
                results.append((d, raw))

    results.sort(key=lambda x: text.index(x[1]))
    return results


def compute_term_months(start: datetime.date, end: datetime.date) -> int:
    """
    Compute lease term in whole calendar months (HK commercial convention).

    "11 February 2026 to 10 February 2028 (both days inclusive)" = 24 months.
    End day is one day before the anniversary of commencement, which is the
    standard HK commercial lease structure.

    Rule: base = calendar-month difference; add 1 only if end day >= start day
    (meaning we've completed the additional partial month).
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # Add 1 only if the end day has reached or passed the start day within the month
    if end.day >= start.day:
        months += 1
    return max(months, 0)
