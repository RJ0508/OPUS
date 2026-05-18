"""Base class and helpers for field extractors."""
from __future__ import annotations

import re
from typing import Optional

from ..models import Evidence, ExtractionMethod, ExtractionResult
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument


def normalize_pdf_labels(text: str) -> str:
    """
    Collapse line-continuation newlines in PDF text so that multi-line labels
    become single lines, making regex matching easier.

    A newline is a "continuation" (collapsible) if the next line does NOT start with:
    - a blank line  -> keep double newlines
    - a digit+period  -> numbered item, keep
    - a page header pattern

    We collapse by replacing `\n` (when it's a continuation) with a space.
    Sub-item markers (ii), (iii) are kept as-is since we use them as stop markers.
    """
    # Replace single newlines that aren't followed by a blank, a number, or sub-item
    # Strategy: replace \n with space UNLESS preceded/followed by \n or digit.
    result = re.sub(
        r'\n(?!\n|(?:\d{1,2}\.)(?:\s))',
        ' ',
        text,
    )
    # Restore sub-item markers that got joined (e.g. " (ii) " becomes recognizable)
    return result


def make_result(
    value,
    confidence: float,
    page: int,
    quote: str,
    method: ExtractionMethod = ExtractionMethod.regex,
    flag: Optional[str] = None,
) -> ExtractionResult:
    """Helper to build an ExtractionResult."""
    return ExtractionResult(
        value=value,
        confidence=confidence,
        evidence=[Evidence(page=page, quote=quote[:200], method=method)],
        review_flag=flag,
    )


def not_found(flag: Optional[str] = None) -> ExtractionResult:
    return ExtractionResult(value=None, confidence=0.0, review_flag=flag)


def find_labeled_value(
    text: str,
    *labels: str,
    strip_chars: str = " \t:",
    address_mode: bool = False,
) -> tuple[str, str] | None:
    """
    Search text for 'Label : Value' patterns.
    Returns (matched_label, value_text) or None.

    Handles:
    - Labels split across multiple lines (PDF line-wrapping within words)
    - Optional parenthetical text between label and colon (e.g. "(both days inclusive)")
    - Colons on their own line
    - Sub-items (ii), (iii) as stop markers

    address_mode=True: search original text (preserving newlines) and join value
    lines with ", " instead of " ", giving proper address formatting.
    """
    if address_mode:
        # Search original text so address line breaks are preserved in the value
        search_text = text
        line_join = ", "
    else:
        # Collapse single newlines that are likely line-continuation wraps
        search_text = re.sub(
            r'\n(?!\n|\s*\d{1,2}\.\s|\s*\(\w{1,5}\))',
            ' ',
            text,
        )
        line_join = " "

    for label in labels:
        # Escape the label and allow any whitespace (incl. newlines) between words
        words = re.split(r'\s+', label.strip())
        escaped = [re.escape(w) for w in words if w]
        flex_label = r'\s*'.join(escaped)

        # After label, allow optional parenthetical / extra text before the colon
        # (up to ~100 chars, not crossing a double-newline or numbered item)
        before_colon = r'(?:[^:\n]{0,120}?)?'

        # Stop at: blank line, numbered item, sub-item, major section boundary, or end.
        # This prevents over-capture into subsequent PART/SCHEDULE blocks which is common
        # in OCR text (especially for party/address fields).
        stop = (
            r'(?='
            r'\n\s*\n'
            r'|\n\s*\d{1,2}\.\s'
            r'|\n\s*\(\w{1,5}\)'
            r'|\n\s*PART\s*(?:[IVXLC]+|\d+)\b'
            r'|\n\s*SCHEDULE\s*(?:[IVXLC]+|\d+)\b'
            r'|\n\s*ANNEXURE\b'
            r'|\Z)'
        )

        pattern = re.compile(
            flex_label + before_colon + r'\s*:\s*(.*?)' + stop,
            re.DOTALL,
        )
        m = pattern.search(search_text)
        if m:
            raw_value = m.group(1).strip()
            # Collapse horizontal whitespace, then join remaining newlines
            raw_value = re.sub(r'[ \t]+', ' ', raw_value)
            raw_value = re.sub(r'\s*\n\s*', line_join, raw_value).strip()
            # Remove trailing separator if value ends with one
            if address_mode:
                raw_value = raw_value.rstrip(", ")
            if raw_value:
                return label, raw_value
    return None


def find_schedule_section(text: str, *headings: str) -> str | None:
    """
    Extract text of a named section from a formal tenancy schedule where labels
    are separated by newlines (no colon), e.g.:
        THE LANDLORD
        CENTRAL PLAZA MANAGEMENT COMPANY LIMITED...

    Returns the content between the first matching heading and the next
    section boundary (PART I/II/III, double newline, or end of text).
    """
    for heading in headings:
        words = re.split(r'\s+', heading.strip())
        flex = r'\s*'.join(re.escape(w) for w in words if w)
        pattern = re.compile(
            flex + r'\.?\s*\n(.*?)(?=\n\s*PART\s+|\n\s*\n\s*\n|\Z)',
            re.DOTALL | re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            value = m.group(1).strip()
            if value:
                return value
    return None


def find_page_for_pattern(doc: DocumentText, pattern: re.Pattern) -> int:
    """Return the 1-based page number where pattern first matches, or 0."""
    for p in doc.pages:
        if pattern.search(p.text):
            return p.page_num
    return 0


def extract_schedule1_part(text: str, *labels: str) -> str | None:
    """
    Extract the body text of a named PART block from a SCHEDULE 1 / The Schedule.

    Handles two common formats:

    Format A – label on its own line after PART N (Trade Desk / formal lease style):
        PART IV
        Term
        A term of Four (4) years…

    Format B – label after a dash on the same line as PART N (Deacons style):
        Part IV - Rent
        From 1st March 2023…

    OCR may merge "PART I" → "PARTI" (zero space) or corrupt Roman numerals.
    The function tries each supplied label in order and returns the first match.
    """
    for label in labels:
        esc = re.escape(label)
        # Format A: label on next line
        m = re.search(
            r"PART\s*(?:[IVXLC]+|\d+)\s*\n\s*" + esc +
            r"[^\n]*\n(.*?)(?=\n\s*PART\s*(?:[IVXLC]+|\d+)\b|\Z)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        # Format B: label after dash/en-dash on the PART line
        m = re.search(
            r"Part\s*(?:[IVXLC]+|\d+)\s*[-\u2013]\s*" + esc +
            r"[^\n]*\n(.*?)(?=\n\s*Part\s*(?:[IVXLC]+|\d+)\s*[-\u2013]|\Z)",
            text, re.DOTALL | re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
    return None


def na_to_none(text: str) -> Optional[str]:
    """Return None if text is a N/A variant, else the text."""
    if re.match(r"^\s*n/?a\s*$", text, re.IGNORECASE):
        return None
    return text
