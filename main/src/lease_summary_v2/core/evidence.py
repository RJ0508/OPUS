"""Evidence primitives shared by scanners, tools, and the enhancer."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    page: int
    quote: str
    method: str = "unknown"
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    tool_call_id: str | None = None


class EvidenceIndex(BaseModel):
    by_field: dict[str, list[EvidenceSpan]] = Field(default_factory=dict)

    def add(
        self,
        field_path: str,
        evidence: EvidenceSpan | list[EvidenceSpan],
        source: str | None = None,
    ) -> None:
        spans = evidence if isinstance(evidence, list) else [evidence]
        if not spans:
            return
        normalized: list[EvidenceSpan] = []
        for span in spans:
            if not span.quote:
                continue
            if source and span.method in {"", "unknown"}:
                span = span.model_copy(update={"method": source})
            normalized.append(span)
        if normalized:
            self.by_field.setdefault(field_path, []).extend(normalized)

    def first(self, field_path: str) -> EvidenceSpan | None:
        values = self.by_field.get(field_path) or []
        return values[0] if values else None


EvidenceSource = Literal["regex", "rule", "computed", "semantic_llm", "agent"]
