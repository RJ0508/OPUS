"""Text normalization utilities."""
from __future__ import annotations

import re


def normalize(text: str) -> str:
    """General text normalization: whitespace, quotes, line breaks."""
    if not text:
        return text
    # Smart quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Full-width punctuation
    text = text.replace("\uff08", "(").replace("\uff09", ")")
    text = text.replace("\uff1a", ":").replace("\uff0c", ",")
    # Collapse whitespace within a line
    text = re.sub(r"[ \t]+", " ", text)
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def smart_title_case(name: str) -> str:
    """
    Convert an all-caps company name to title case while preserving
    short abbreviations (HK, LLC, LTD, PTE, etc.) and parenthetical tokens.
    Only transforms strings that are entirely uppercase.

    "KLDISCOVERY ONTRACK (HK) LIMITED" -> "Kldiscovery Ontrack (HK) Limited"
    "Tak Shing Investment Company, Limited" -> unchanged (already mixed case)
    """
    if not name or not name.upper() == name:
        return name  # already mixed-case — don't touch
    # Tokenize on whitespace and punctuation boundaries, preserving delimiters
    tokens = re.split(r'(\s+|[(),./])', name)
    result = []
    _KEEP_UPPER = {"HK", "UK", "US", "EU", "LLC", "LTD", "PTE", "BVI", "HKG",
                   "OR", "HK.", "LTD.", "CO.", "CO", "NO", "NO."}
    for tok in tokens:
        stripped = tok.strip("(),./")
        if not stripped:
            result.append(tok)  # whitespace/punctuation delimiter
        elif stripped in _KEEP_UPPER or (len(stripped) <= 3 and stripped.isupper()):
            result.append(tok)  # short abbreviation — keep uppercase
        else:
            result.append(tok.title())
    return "".join(result)


def join_lines(text: str) -> str:
    """Collapse line breaks within a paragraph into spaces."""
    return re.sub(r"\s*\n\s*", " ", text).strip()


def extract_after_colon(text: str, label: str) -> str | None:
    """
    Find 'label:  value' in text and return the value.
    Handles multi-line values (indented continuation lines).
    """
    pattern = re.compile(
        re.escape(label) + r"\s*:\s*(.+?)(?=\n\s*\n|\n[A-Z0-9]|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        return join_lines(m.group(1)).strip()
    return None
