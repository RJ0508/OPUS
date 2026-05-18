"""Candidate extraction and assembly helpers."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from ..models import Evidence, ExtractionMethod, ExtractionResult, LeaseSummary
from .evidence import EvidenceSpan


class FieldCandidate(BaseModel):
    field_path: str
    value: Any
    confidence: float
    source: str
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    extractor: str = ""
    notes: str = ""


def summary_to_candidates(
    summary: LeaseSummary,
    *,
    source: str = "rule",
    extractor: str = "rule_scanner",
) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    for field_path, result in iter_summary_results(summary):
        if not result.is_found():
            continue
        candidates.append(FieldCandidate(
            field_path=field_path,
            value=result.value,
            confidence=result.confidence,
            source=result.source or source,
            evidence=[_to_span(ev) for ev in result.evidence if ev.quote],
            extractor=extractor,
            notes=result.reason_summary,
        ))
    return candidates


def assemble_summary_from_candidates(
    base_summary: LeaseSummary,
    candidates: list[FieldCandidate],
    *,
    trace_id: str | None = None,
) -> LeaseSummary:
    summary = deepcopy(base_summary)
    by_field: dict[str, FieldCandidate] = {}
    for candidate in candidates:
        if not candidate.evidence:
            continue
        current = by_field.get(candidate.field_path)
        if current is None or _candidate_score(candidate) > _candidate_score(current):
            by_field[candidate.field_path] = candidate

    for field_path, candidate in by_field.items():
        result = ExtractionResult(
            value=candidate.value,
            confidence=max(0.0, min(1.0, candidate.confidence)),
            evidence=[_to_model_evidence(span, candidate.source) for span in candidate.evidence[:3]],
            source=candidate.source,
            sources=[candidate.source],
            reason_summary=candidate.notes,
            trace_id=trace_id,
            needs_review=False,
        )
        _set_result(summary, field_path, result)
    return summary


def iter_summary_results(summary: LeaseSummary):
    for group_name in ("parties", "premises", "term", "financials", "clauses"):
        group = getattr(summary, group_name)
        for field_name, field_value in group.__dict__.items():
            if isinstance(field_value, ExtractionResult):
                yield f"{group_name}.{field_name}", field_value


def get_result(summary: LeaseSummary, field_path: str) -> ExtractionResult | None:
    group_name, field_name = field_path.split(".", 1)
    group = getattr(summary, group_name, None)
    return getattr(group, field_name, None) if group is not None else None


def _set_result(summary: LeaseSummary, field_path: str, result: ExtractionResult) -> None:
    group_name, field_name = field_path.split(".", 1)
    group = getattr(summary, group_name, None)
    if group is not None and hasattr(group, field_name):
        setattr(group, field_name, result)


def _candidate_score(candidate: FieldCandidate) -> float:
    source_boost = {
        "agent": 0.15,
        "semantic_llm": 0.08,
        "rule": 0.04,
        "regex": 0.03,
        "computed": 0.02,
    }.get(candidate.source, 0)
    evidence_boost = 0.04 if candidate.evidence else 0
    return candidate.confidence + source_boost + evidence_boost


def _to_span(evidence: Evidence) -> EvidenceSpan:
    return EvidenceSpan(
        page=evidence.page,
        quote=evidence.quote,
        method=str(evidence.method.value if hasattr(evidence.method, "value") else evidence.method),
        chunk_id=evidence.chunk_id,
        char_start=evidence.char_start,
        char_end=evidence.char_end,
        tool_call_id=evidence.tool_call_id,
    )


def _to_model_evidence(span: EvidenceSpan, source: str) -> Evidence:
    method_value = source if source in ExtractionMethod._value2member_map_ else span.method
    if method_value not in ExtractionMethod._value2member_map_:
        method_value = "heuristic"
    return Evidence(
        page=span.page,
        quote=span.quote,
        method=ExtractionMethod(method_value),
        chunk_id=span.chunk_id,
        char_start=span.char_start,
        char_end=span.char_end,
        tool_call_id=span.tool_call_id,
    )

