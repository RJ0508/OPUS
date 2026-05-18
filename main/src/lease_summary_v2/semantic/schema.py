"""Structured semantic scanner schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SemanticFinding(BaseModel):
    field_path: str
    value: Any = None
    normalized_value: Any = None
    evidence_quote: str
    confidence: float = Field(ge=0.0, le=1.0)
    page_hint: int | None = None
    notes: str = ""


class SemanticScanResult(BaseModel):
    findings: list[SemanticFinding] = Field(default_factory=list)


SEMANTIC_SCAN_JSON_SCHEMA = {
    "name": "semantic_scan_result",
    "schema": SemanticScanResult.model_json_schema(),
    "strict": True,
}

