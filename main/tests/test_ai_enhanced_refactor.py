"""Tests for the AI Enhanced evidence/candidate/agent refactor."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app.main as main_module  # noqa: E402
import app.state as state_module  # noqa: E402
from lease_summary_v2.agent.guardrails import MAX_REGEX_MATCHES  # noqa: E402
from lease_summary_v2.agent.enhancer import run_enhancement_agent  # noqa: E402
from lease_summary_v2.agent.tools import AgentToolbox  # noqa: E402
from lease_summary_v2.core.candidates import FieldCandidate  # noqa: E402
from lease_summary_v2.core.document_index import DocumentChunk, DocumentIndex  # noqa: E402
from lease_summary_v2.core.evidence import EvidenceSpan  # noqa: E402
from lease_summary_v2.core.trace import ExtractionTrace  # noqa: E402
from lease_summary_v2.models import ExtractionResult, LeaseSummary  # noqa: E402
from lease_summary_v2.parsers.pdf_text import PageText  # noqa: E402
from lease_summary_v2.parsers.section_splitter import SplitDocument  # noqa: E402
from lease_summary_v2.pipeline import _sync_break_clause  # noqa: E402
from lease_summary_v2.semantic.scanner import semantic_scan_document  # noqa: E402
from lease_summary_v2.semantic.schema import SemanticFinding  # noqa: E402


def _doc_index(texts: list[str]) -> DocumentIndex:
    pages = [PageText(page_num=i + 1, text=text) for i, text in enumerate(texts)]
    chunks = [
        DocumentChunk(
            chunk_id=f"page_{i + 1}_chunk_1",
            text=text,
            page_start=i + 1,
            page_end=i + 1,
            section="principal_terms",
        )
        for i, text in enumerate(texts)
    ]
    return DocumentIndex(
        pages=pages,
        chunks=chunks,
        sections=SplitDocument(principal_terms="\n".join(texts), full_text="\n".join(texts)),
        full_text="\n".join(texts),
    )


def test_normalize_mode_preserves_legacy_values():
    assert state_module.normalize_mode("regex") == "standard"
    assert state_module.normalize_mode("llm") == "ai_enhanced"
    assert state_module.normalize_mode("hybrid") == "ai_enhanced"
    assert state_module.normalize_mode("pure_llm") == "pure_llm"


def test_batch_ai_mode_uses_v2_pipeline(monkeypatch, tmp_path):
    pdf_path = tmp_path / "lease.pdf"
    pdf_path.write_text("lease", encoding="utf-8")
    output_path = tmp_path / "ai.xlsx"
    calls = {"v1": 0, "v2": 0}

    import lease_summary.pipeline as v1_pipeline
    import lease_summary_v2.pipeline as v2_pipeline

    def fake_v1(*_args, **_kwargs):
        calls["v1"] += 1
        return {"excel": output_path}

    def fake_v2(*_args, **_kwargs):
        calls["v2"] += 1
        output_path.touch()
        return {"excel": output_path}

    monkeypatch.setattr(main_module.state, "llm_enabled", lambda: True)
    monkeypatch.setattr(v1_pipeline, "run", fake_v1)
    monkeypatch.setattr(v2_pipeline, "run", fake_v2)

    assert main_module._run_batch_single(pdf_path, "ai_enhanced") == output_path
    assert calls == {"v1": 0, "v2": 1}


def test_semantic_scan_visits_every_chunk_and_requires_quote():
    doc_index = _doc_index([
        "Monthly rent shall be HK$10,000.",
        "Security deposit shall be HK$30,000.",
    ])
    visited: list[str] = []

    def fake_scan(chunk, _fields):
        visited.append(chunk.chunk_id)
        if "Monthly rent" in chunk.text:
            return [
                SemanticFinding(
                    field_path="financials.monthly_rent_hkd",
                    value=10000,
                    evidence_quote="Monthly rent shall be HK$10,000.",
                    confidence=0.9,
                    page_hint=chunk.page_start,
                )
            ]
        return [
            SemanticFinding(
                field_path="financials.security_deposit_hkd",
                value=30000,
                evidence_quote="not an exact quote",
                confidence=0.9,
                page_hint=chunk.page_start,
            )
        ]

    candidates = semantic_scan_document(doc_index, scan_chunk_fn=fake_scan)

    assert visited == ["page_1_chunk_1", "page_2_chunk_1"]
    assert [candidate.field_path for candidate in candidates] == ["financials.monthly_rent_hkd"]


def test_agent_marks_unresolved_rule_semantic_conflict_for_review():
    doc_index = _doc_index(["The monthly rent shall be HK$10,000. The monthly rent may be reviewed."])
    rule = FieldCandidate(
        field_path="financials.monthly_rent_hkd",
        value=10000,
        confidence=0.86,
        source="rule",
        evidence=[EvidenceSpan(page=1, quote="The monthly rent shall be HK$10,000.", method="rule")],
        extractor="test",
    )
    semantic = FieldCandidate(
        field_path="financials.monthly_rent_hkd",
        value=12000,
        confidence=0.9,
        source="semantic_llm",
        evidence=[EvidenceSpan(page=1, quote="The monthly rent may be reviewed.", method="semantic_llm")],
        extractor="test",
    )
    trace = ExtractionTrace(mode="ai_enhanced", file_name="lease.pdf")

    result = run_enhancement_agent(
        doc_index=doc_index,
        rule_candidates=[rule],
        semantic_candidates=[semantic],
        trace=trace,
    )

    decision = result.decisions[0]
    assert decision.field_path == "financials.monthly_rent_hkd"
    assert decision.conflict is True
    assert decision.needs_review is True
    assert trace.agent_tool_calls


def test_regex_tool_clamps_match_count():
    doc_index = _doc_index(["rent " * (MAX_REGEX_MATCHES + 12)])
    toolbox = AgentToolbox(doc_index)

    matches = toolbox.regex_search("rent", max_matches=MAX_REGEX_MATCHES + 100)

    assert len(matches) == MAX_REGEX_MATCHES
    assert toolbox.trace_calls[-1].tool == "regex_search"


def test_break_clause_canonical_fields_are_synced():
    summary = LeaseSummary()
    summary.term.tenant_termination_right_text = ExtractionResult(value="Tenant may break on notice", confidence=0.8)

    _sync_break_clause(summary)

    assert summary.clauses.break_clause_text.value == "Tenant may break on notice"
