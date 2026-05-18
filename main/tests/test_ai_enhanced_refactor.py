"""Tests for the AI Enhanced evidence/candidate/agent refactor."""
from __future__ import annotations

import sys
import os
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app.main as main_module  # noqa: E402
import app.state as state_module  # noqa: E402
from lease_summary_v2.agent.guardrails import MAX_REGEX_MATCHES  # noqa: E402
from lease_summary_v2.agent.enhancer import run_enhancement_agent  # noqa: E402
from lease_summary_v2.agent.tools import AgentToolbox  # noqa: E402
from lease_summary_v2.agent.tool_calling import run_llm_tool_agent  # noqa: E402
from lease_summary_v2.core.candidates import FieldCandidate  # noqa: E402
from lease_summary_v2.core import guardrails as pipeline_guardrails  # noqa: E402
from lease_summary_v2.core.document_index import DocumentChunk, DocumentIndex  # noqa: E402
from lease_summary_v2.core.evidence import EvidenceSpan  # noqa: E402
from lease_summary_v2.core.trace import ExtractionTrace  # noqa: E402
from lease_summary_v2.models import Evidence, ExtractionMethod, ExtractionResult, LeaseSummary  # noqa: E402
from lease_summary_v2.parsers.pdf_text import DocumentText, PageText  # noqa: E402
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


def test_llm_tool_agent_can_call_tools_and_return_guarded_decision():
    doc_index = _doc_index(["The monthly rent shall be HK$10,000."])
    toolbox = AgentToolbox(doc_index)
    summary = LeaseSummary()
    client = _FakeToolClient()

    result = run_llm_tool_agent(
        doc_index=doc_index,
        current_summary=summary,
        rule_candidates=[],
        semantic_candidates=[],
        toolbox=toolbox,
        client=client,
        model="fake-model",
    )

    assert result is not None
    assert result.decisions[0].field_path == "financials.monthly_rent_hkd"
    assert result.decisions[0].selected_value == 10000
    assert toolbox.trace_calls[0].tool == "read_page"


def test_regex_tool_clamps_match_count():
    doc_index = _doc_index(["rent " * (MAX_REGEX_MATCHES + 12)])
    toolbox = AgentToolbox(doc_index)

    matches = toolbox.regex_search("rent", max_matches=MAX_REGEX_MATCHES + 100)

    assert len(matches) == MAX_REGEX_MATCHES
    assert toolbox.trace_calls[-1].tool == "regex_search"


def test_agent_financial_and_candidate_tools():
    doc_index = _doc_index(["The monthly rent shall be HK$10,000."])
    toolbox = AgentToolbox(doc_index)

    calculated = toolbox.calculate_financials(area_sqft=1000, monthly_rent_hkd=10000, security_deposit_hkd=30000)
    validation = toolbox.validate_candidate(
        field_path="financials.monthly_rent_hkd",
        evidence_quote="The monthly rent shall be HK$10,000.",
        page=1,
        chunk_id=None,
    )

    assert calculated["rent_per_sqft_hkd"] == 10.0
    assert calculated["security_deposit_multiple"] == 3.0
    assert validation.valid is True


def test_break_clause_canonical_fields_are_synced():
    summary = LeaseSummary()
    summary.term.tenant_termination_right_text = ExtractionResult(value="Tenant may break on notice", confidence=0.8)

    _sync_break_clause(summary)

    assert summary.clauses.break_clause_text.value == "Tenant may break on notice"


def test_pipeline_guardrails_record_low_ocr_warning():
    trace = ExtractionTrace(mode="ai_enhanced", file_name="scan.pdf")
    doc = DocumentText(
        pages=[PageText(page_num=1, text="short")],
        parsed_with_ocr=True,
        ocr_avg_chars=10,
    )

    pipeline_guardrails.validate_document_text(doc, trace)

    assert trace.pages_count == 1
    assert trace.warnings


def test_pipeline_guardrails_reject_too_many_pages(monkeypatch):
    trace = ExtractionTrace(mode="ai_enhanced", file_name="long.pdf")
    doc = DocumentText(pages=[
        PageText(page_num=1, text="lease"),
        PageText(page_num=2, text="lease"),
    ])
    monkeypatch.setattr(pipeline_guardrails, "MAX_PAGES", 1)

    with pytest.raises(ValueError, match="Limit"):
        pipeline_guardrails.validate_document_text(doc, trace)


def test_trace_endpoint_serialises_current_trace():
    original = main_module.state.extraction_trace
    trace = ExtractionTrace(mode="ai_enhanced", file_name="lease.pdf")
    try:
        main_module.state.extraction_trace = trace
        payload = main_module.get_trace()
    finally:
        main_module.state.extraction_trace = original

    assert payload["run_id"] == trace.run_id
    assert payload["mode"] == "ai_enhanced"


def test_progress_events_are_run_scoped():
    run_id = main_module._reset_progress("ai_enhanced", "test_progress_run")
    main_module._publish_progress("rule", "Running Rule/Regex extraction", percent=40, run_id=run_id)
    events, done = main_module._progress_events_since(run_id, 0)

    assert done is False
    assert [event["step"] for event in events] == ["extract", "rule"]
    assert events[-1]["percent"] == 40
    assert main_module._progress_events_since("other_run", 0) == ([], False)


def test_ai_mode_without_llm_reports_rule_regex_fallback(monkeypatch, tmp_path):
    import lease_summary.pipeline as standard_pipeline
    from lease_summary.models import Evidence as V1Evidence
    from lease_summary.models import ExtractionMethod as V1Method
    from lease_summary.models import ExtractionResult as V1Result
    from lease_summary.models import LeaseSummary as V1Summary

    original = {
        "mode": main_module.state.mode,
        "provider": main_module.state.llm_provider,
        "model": main_module.state.llm_model,
        "api_keys": dict(main_module.state.api_keys),
        "summary": main_module.state.summary,
        "excel_path": main_module.state.excel_path,
        "doc_index": main_module.state.doc_index,
        "evidence_index": main_module.state.evidence_index,
        "extraction_trace": main_module.state.extraction_trace,
        "ocr_word_data": main_module.state.ocr_word_data,
        "engine_info": dict(main_module.state.engine_info),
    }
    env_keys = [
        "LLM_API_KEY",
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "MOONSHOT_API_KEY",
        "MOONSHOT_BASE_URL",
        "MOONSHOT_MODEL",
    ]
    original_env = {key: os.environ.get(key) for key in env_keys}
    pdf_path = tmp_path / "lease.pdf"
    pdf_path.write_text("lease", encoding="utf-8")
    excel_path = tmp_path / "lease.xlsx"

    def fake_run(_path, *, output_dir, progress_callback=None, **_kwargs):
        if progress_callback:
            progress_callback("rule", "Running Rule/Regex extraction", percent=50)
        summary = V1Summary()
        summary.document_meta.source_filename = "lease.pdf"
        summary.document_meta.pages = 1
        summary.parties.tenant_name = V1Result(
            value="Regex Tenant",
            confidence=0.8,
            evidence=[V1Evidence(page=1, quote="Regex Tenant", method=V1Method.regex)],
        )
        excel_path.touch()
        return {"summary": summary, "excel": excel_path, "doc_text": None}

    try:
        main_module.state.mode = "ai_enhanced"
        main_module.state.llm_provider = "moonshot"
        main_module.state.llm_model = "kimi-k2.6"
        main_module.state.api_keys = {}
        monkeypatch.setattr(standard_pipeline, "run", fake_run)
        monkeypatch.setattr(main_module, "_refresh_qa_engine", lambda **_kwargs: None)

        payload = main_module._run_extraction(pdf_path, lambda *_args, **_kwargs: None)
    finally:
        main_module.state.mode = original["mode"]
        main_module.state.llm_provider = original["provider"]
        main_module.state.llm_model = original["model"]
        main_module.state.api_keys = original["api_keys"]
        main_module.state.summary = original["summary"]
        main_module.state.excel_path = original["excel_path"]
        main_module.state.doc_index = original["doc_index"]
        main_module.state.evidence_index = original["evidence_index"]
        main_module.state.extraction_trace = original["extraction_trace"]
        main_module.state.ocr_word_data = original["ocr_word_data"]
        main_module.state.engine_info = original["engine_info"]
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert payload["engine"]["effective_mode"] == "standard_regex_fallback"
    assert "API key" in payload["engine"]["fallback_reason"]
    assert payload["parties"]["tenant_name"]["source"] == "regex"
    assert payload["parties"]["tenant_name"]["sources"] == ["regex"]


def test_ocr_word_api_and_serialised_evidence_support_highlight():
    original_word_data = main_module.state.ocr_word_data
    original_summary = main_module.state.summary
    summary = LeaseSummary()
    summary.document_meta.pages = 1
    summary.document_meta.source_filename = "scan.pdf"
    summary.parties.tenant_name = ExtractionResult(
        value="Tenant Limited",
        confidence=0.9,
        evidence=[Evidence(page=1, quote="Tenant Limited", method=ExtractionMethod.agent)],
        source="agent",
        sources=["agent"],
    )
    try:
        main_module.state.ocr_word_data = {1: [(10, 10, 50, 20, "Tenant"), (52, 10, 90, 20, "Limited")]}
        main_module.state.summary = summary
        assert main_module.get_pdf_words()["pages"]["1"][0][4] == "Tenant"
        payload = main_module._serialise_summary(summary)
    finally:
        main_module.state.ocr_word_data = original_word_data
        main_module.state.summary = original_summary

    assert payload["parties"]["tenant_name"]["page"] == 1
    assert payload["parties"]["tenant_name"]["quote"] == "Tenant Limited"


class _FakeToolClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            tool_call = SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="read_page", arguments='{"page_num": 1}'),
            )
            message = SimpleNamespace(content="", tool_calls=[tool_call])
        else:
            message = SimpleNamespace(
                content=(
                    '{"decisions":[{"field_path":"financials.monthly_rent_hkd",'
                    '"selected_value":10000,"confidence":0.91,'
                    '"evidence":[{"page":1,"quote":"The monthly rent shall be HK$10,000.",'
                    '"method":"agent"}],"sources":["agent"],'
                    '"reason_summary":"Read page 1 and verified the rent quote.",'
                    '"needs_review":false,"conflict":false}],"warnings":[],"trace_id":"run_fake"}'
                ),
                tool_calls=[],
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
