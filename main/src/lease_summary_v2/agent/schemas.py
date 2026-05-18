"""Schemas for bounded agent decisions."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..core.evidence import EvidenceSpan


class EnhancedFieldDecision(BaseModel):
    field_path: str
    selected_value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    reason_summary: str = ""
    needs_review: bool = False
    conflict: bool = False


class EnhancedExtractionResult(BaseModel):
    decisions: list[EnhancedFieldDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace_id: str

