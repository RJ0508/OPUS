"""Confidence level constants and helpers."""
from __future__ import annotations

# Confidence level thresholds
EXPLICIT_LABELED = 1.00    # Found with exact label
INFERRED = 0.85            # Inferred from context
COMPUTED = 0.70            # Derived from two explicit fields
HEURISTIC = 0.50           # Pattern-matched clause summary
LOW = 0.30                 # Uncertain / incomplete


def confidence_label(score: float) -> str:
    if score >= EXPLICIT_LABELED:
        return "HIGH"
    if score >= INFERRED:
        return "MEDIUM-HIGH"
    if score >= COMPUTED:
        return "MEDIUM"
    if score >= HEURISTIC:
        return "LOW-MEDIUM"
    return "LOW"
