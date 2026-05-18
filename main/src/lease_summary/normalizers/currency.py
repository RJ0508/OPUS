"""Currency normalization for HK lease documents."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


_CURRENCY_PATTERN = re.compile(
    r"Hong\s+Kong\s+\$\s*([\d,]+(?:\.\d{1,2})?)|"
    r"HK\$\s*([\d,]+(?:\.\d{1,2})?)|"
    r"\$([\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def parse_hkd(text: str) -> Decimal | None:
    """
    Parse 'HK$15,015.00', 'Hong Kong $29,946.00', or '$15,015' to Decimal.
    Returns None if no valid amount found.
    """
    if not text:
        return None
    text = text.strip()
    m = _CURRENCY_PATTERN.search(text)
    if m:
        raw = m.group(1) or m.group(2) or m.group(3)
        try:
            return Decimal(raw.replace(",", ""))
        except InvalidOperation:
            pass
    # Try raw number
    cleaned = re.sub(r"[^\d.]", "", text)
    if cleaned:
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            pass
    return None


def find_amounts(text: str) -> list[tuple[Decimal, str]]:
    """Find all HK$ amounts in text. Returns list of (amount, raw_match)."""
    results: list[tuple[Decimal, str]] = []
    for m in _CURRENCY_PATTERN.finditer(text):
        raw = m.group(1) or m.group(2) or m.group(3)
        try:
            amount = Decimal(raw.replace(",", ""))
            results.append((amount, m.group(0)))
        except InvalidOperation:
            pass
    return results


def format_hkd(amount: Decimal | float | int) -> str:
    """Format a number as HK$ string for Excel display."""
    return f"HK${Decimal(str(amount)):,.2f}"
