"""Guardrails for bounded document tools."""
from __future__ import annotations


MAX_REGEX_PATTERN_CHARS = 240
MAX_REGEX_MATCHES = 50
MAX_CONTEXT_CHARS = 500
MAX_PAGE_CHARS = 12000


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


def validate_regex_pattern(pattern: str) -> str:
    value = (pattern or "").strip()
    if not value:
        raise ValueError("regex pattern is required")
    if len(value) > MAX_REGEX_PATTERN_CHARS:
        raise ValueError("regex pattern is too long")
    return value

