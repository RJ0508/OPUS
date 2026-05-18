"""Bounded evidence-first enhancer for AI Enhanced extraction."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..core.candidates import FieldCandidate
from ..core.document_index import DocumentIndex
from ..core.field_specs import FIELD_SPEC_BY_PATH
from ..core.trace import ExtractionTrace
from .schemas import EnhancedExtractionResult, EnhancedFieldDecision
from .tools import AgentToolbox

_VERIFY_PATTERNS = {
    "term.tenant_termination_right_text": r"break|termination|terminate|early termination",
    "clauses.break_clause_text": r"break|termination|terminate|early termination",
    "clauses.subletting_text": r"subletting|underletting|assignment|sharing|transfer",
    "clauses.signage_text": r"signage|sign|name plate|directory",
    "clauses.parking_text": r"parking|car park|car parking",
    "financials.security_deposit_hkd": r"security deposit|deposit",
    "financials.monthly_rent_hkd": r"monthly rent|rent payable|basic rent",
}


def run_enhancement_agent(
    *,
    doc_index: DocumentIndex,
    rule_candidates: list[FieldCandidate],
    semantic_candidates: list[FieldCandidate],
    trace: ExtractionTrace,
) -> EnhancedExtractionResult:
    toolbox = AgentToolbox(doc_index)
    warnings: list[str] = []
    decisions: list[EnhancedFieldDecision] = []

    grouped: dict[str, list[FieldCandidate]] = defaultdict(list)
    for candidate in [*rule_candidates, *semantic_candidates]:
        if candidate.field_path in FIELD_SPEC_BY_PATH:
            grouped[candidate.field_path].append(candidate)

    for field_path, candidates in grouped.items():
        candidates = [candidate for candidate in candidates if candidate.evidence]
        if not candidates:
            warnings.append(f"{field_path}: no evidence-backed candidates")
            continue

        conflict = _has_conflict(candidates)
        if conflict:
            _verify_conflict(toolbox, field_path, candidates)

        selected = _select_candidate(candidates)
        if selected is None:
            continue

        sources = sorted({candidate.source for candidate in candidates})
        needs_review = conflict and not _semantic_agrees_with_rule(candidates)
        decisions.append(EnhancedFieldDecision(
            field_path=field_path,
            selected_value=selected.value,
            confidence=_decision_confidence(selected, conflict, needs_review),
            evidence=selected.evidence,
            sources=sources,
            reason_summary=_reason(selected, candidates, conflict, needs_review),
            needs_review=needs_review,
            conflict=conflict,
        ))

    trace.agent_tool_calls.extend(toolbox.trace_calls)
    trace.final_decisions_count = len(decisions)
    trace.warnings.extend(warnings)
    return EnhancedExtractionResult(
        decisions=decisions,
        warnings=warnings,
        trace_id=trace.run_id,
    )


def _select_candidate(candidates: list[FieldCandidate]) -> FieldCandidate | None:
    return max(candidates, key=_candidate_score, default=None)


def _candidate_score(candidate: FieldCandidate) -> float:
    boost = {"semantic_llm": 0.12, "rule": 0.08, "regex": 0.07, "agent": 0.15}.get(candidate.source, 0)
    return candidate.confidence + boost


def _has_conflict(candidates: list[FieldCandidate]) -> bool:
    values = {_normalize_value(candidate.value) for candidate in candidates if candidate.value is not None}
    return len(values) > 1


def _semantic_agrees_with_rule(candidates: list[FieldCandidate]) -> bool:
    rule_values = {_normalize_value(candidate.value) for candidate in candidates if candidate.source in {"rule", "regex"}}
    semantic_values = {_normalize_value(candidate.value) for candidate in candidates if candidate.source == "semantic_llm"}
    return bool(rule_values & semantic_values)


def _verify_conflict(toolbox: AgentToolbox, field_path: str, candidates: list[FieldCandidate]) -> None:
    pattern = _VERIFY_PATTERNS.get(field_path)
    if not pattern:
        return
    pages = [ev.page for candidate in candidates for ev in candidate.evidence if ev.page]
    if pages:
        toolbox.regex_search(pattern, scope="pages", page_start=min(pages), page_end=max(pages), max_matches=5)
    else:
        toolbox.regex_search(pattern, max_matches=5)


def _decision_confidence(candidate: FieldCandidate, conflict: bool, needs_review: bool) -> float:
    confidence = candidate.confidence
    if conflict:
        confidence -= 0.08
    if needs_review:
        confidence -= 0.12
    return max(0.0, min(1.0, confidence))


def _reason(
    selected: FieldCandidate,
    candidates: list[FieldCandidate],
    conflict: bool,
    needs_review: bool,
) -> str:
    sources = ", ".join(sorted({candidate.source for candidate in candidates}))
    reason = f"Selected {selected.source} candidate from sources: {sources}."
    if conflict:
        reason += " Conflicting candidate values were detected."
    if needs_review:
        reason += " Marked for review because conflict was not independently resolved."
    return reason


def _normalize_value(value: Any) -> str:
    return str(value).strip().lower().replace(",", "")
