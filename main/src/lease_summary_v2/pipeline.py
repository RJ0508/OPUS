"""Main extraction pipeline."""
from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from lease_summary.doc_type import detect_doc_type
from lease_summary.llm_config import build_openai_client

from .config import TEMPLATE_PATH, DEFAULT_OUTPUT_DIR
from .extractors.ai_primary import ai_primary_extract
from .agent.enhancer import run_enhancement_agent
from .agent.schemas import EnhancedFieldDecision
from .core.candidates import FieldCandidate, assemble_summary_from_candidates
from .core.document_index import build_document_index
from .core.evidence import EvidenceIndex
from .core.field_specs import FIELD_SPECS
from .core.rule_scanner import run_rule_scanners
from .core.trace import ExtractionTrace, TraceTimer
from .core.guardrails import validate_document_text, validate_input_file
from .models import DocumentMeta, Evidence, ExtractionMethod, ExtractionResult, LeaseSummary, SummaryMeta
from .normalizers.dates import parse_date
from .parsers.pdf_text import extract_text
from .parsers.section_splitter import split
from .semantic.scanner import semantic_scan_document
from .validators.business_rules import validate_business_rules
from .validators.field_validator import validate_mandatory
from .writers.excel_writer import write_excel
from .writers.json_writer import write_json, write_review_json


def run(
    input_pdf: str | Path,
    output_dir: str | Path | None = None,
    template_path: str | Path | None = None,
    extraction_mode: str | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Path]:
    """
    Full pipeline: PDF -> LeaseSummary -> Excel + JSON outputs.

    Returns dict with keys 'excel', 'json', 'review'.
    """
    input_pdf = Path(input_pdf)
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    template_path = Path(template_path) if template_path else TEMPLATE_PATH
    extraction_mode = _normalize_extraction_mode(
        extraction_mode or os.environ.get("LLM_EXTRACTION_MODE", "ai_enhanced")
    )
    pure_llm = extraction_mode == "pure_llm"
    legacy_ai = extraction_mode == "legacy_ai"

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_pdf.stem

    trace = ExtractionTrace(
        mode=extraction_mode,
        requested_mode=extraction_mode,
        effective_mode=extraction_mode,
        file_name=input_pdf.name,
    )
    timer = TraceTimer(trace)
    validate_input_file(input_pdf, trace)

    # ── Step 1: Extract text ────────────────────────────────────────────────────
    _emit(progress_callback, "extract", "Extracting text", 8)
    doc_text = extract_text(input_pdf)
    trace.parser_backend = doc_text.extraction_backend
    trace.ocr_used = doc_text.parsed_with_ocr
    validate_document_text(doc_text, trace)

    # ── Step 2: Split into sections ─────────────────────────────────────────────
    _emit(progress_callback, "extract", "Building document index", 18)
    sections = split(doc_text)
    doc_index = build_document_index(doc_text, sections)
    trace.chunks_count = len(doc_index.chunks)

    # ── Step 3: Detect document type ────────────────────────────────────────────
    _emit(progress_callback, "rule", "Detecting document type", 26)
    doc_type = _detect_doc_type(sections.principal_terms)

    if doc_type == "not_a_lease":
        raise ValueError(
            f"This file does not appear to be a lease document: {input_pdf.name}\n"
            "Only lease agreements, tenancy agreements, and offer-to-lease documents are supported."
        )

    # ── Step 4: Rule candidates ────────────────────────────────────────────────
    if pure_llm:
        summary = _empty_summary(input_pdf.name, doc_type, doc_text)
        rule_candidates: list[FieldCandidate] = []
    else:
        _emit(progress_callback, "rule", "Running Rule/Regex extraction", 36)
        summary, rule_candidates = run_rule_scanners(
            doc_text,
            sections,
            source_filename=input_pdf.name,
            document_type=doc_type,
        )
    trace.rule_candidates_count = len(rule_candidates)

    # ── Step 4b: AI Enhanced semantic scan + bounded agent ─────────────────────
    semantic_candidates: list[FieldCandidate] = []
    enhanced = None
    trace_warning_seen: set[str] = set()

    def warn_once(message: str) -> None:
        message = (message or "").strip()
        if not message or message in trace_warning_seen:
            return
        trace_warning_seen.add(message)
        trace.warnings.append(message)

    if extraction_mode == "standard":
        _sync_break_clause(summary)
    elif legacy_ai:
        _emit(progress_callback, "scan", "Running legacy AI extraction", 62)
        ai_primary_extract(summary, doc_text, sections, pure_llm=pure_llm)
        _sync_break_clause(summary)
    else:
        _emit(progress_callback, "scan", "Scanning full document with AI", 44)
        llm_client, llm_settings = build_openai_client(
            "https://api.moonshot.cn/v1",
            "kimi-k2.6",
            default_provider="moonshot",
        )
        llm_model = llm_settings.model if llm_settings else None
        if llm_settings is not None:
            trace.provider = llm_settings.provider
            trace.model = llm_settings.model
        else:
            trace.warnings.append("LLM client unavailable; Rule/Regex candidates remain in use.")
        semantic_candidates = semantic_scan_document(
            doc_index,
            FIELD_SPECS,
            client=llm_client,
            model=llm_model,
            progress_callback=progress_callback,
            warning_callback=warn_once,
        )
        trace.semantic_candidates_count = len(semantic_candidates)
        if semantic_candidates:
            _emit(progress_callback, "verify", "Agent verifying evidence", 80)
            enhanced = run_enhancement_agent(
                doc_index=doc_index,
                current_summary=summary,
                rule_candidates=rule_candidates,
                semantic_candidates=semantic_candidates,
                trace=trace,
                client=llm_client,
                model=llm_model,
            )
            summary = _apply_agent_decisions(summary, enhanced.decisions, trace.run_id)
        elif pure_llm:
            summary = assemble_summary_from_candidates(summary, semantic_candidates, trace_id=trace.run_id)
        else:
            trace.effective_mode = "ai_enhanced_rule_fallback"
            trace.fallback_reason = (
                "AI scan returned no evidence-backed candidates; Rule/Regex extraction is shown."
            )
            trace.warnings.append(trace.fallback_reason)
        _sync_break_clause(summary)

    # ── Step 5: Validate ────────────────────────────────────────────────────────
    _emit(progress_callback, "finalize", "Validating extracted fields", 90)
    validate_mandatory(summary)
    validate_business_rules(summary)
    timer.finish()

    # ── Step 6: Write outputs ───────────────────────────────────────────────────
    _emit(progress_callback, "finalize", "Writing summary files", 96)
    excel_path = output_dir / f"{stem}.summary.xlsx"
    json_path = output_dir / f"{stem}.extraction.json"
    review_path = output_dir / f"{stem}.review.json"
    trace_path = output_dir / f"{stem}.trace.json"

    write_excel(summary, template_path, excel_path)
    write_json(summary, json_path)
    write_review_json(summary, review_path)
    _write_trace(trace, trace_path)

    evidence_index = _build_evidence_index(rule_candidates, semantic_candidates)

    return {
        "excel": excel_path,
        "json": json_path,
        "review": review_path,
        "trace": trace,
        "trace_path": trace_path,
        "summary": summary,
        "doc_text": doc_text,
        "doc_index": doc_index,
        "evidence_index": evidence_index,
        "enhanced": enhanced,
    }


def _normalize_extraction_mode(mode: str) -> str:
    raw = (mode or "").strip().lower().replace("-", "_")
    if raw in {"standard", "regex"}:
        return "standard"
    if raw in {"pure", "pure_llm", "llm_only"}:
        return "pure_llm"
    if raw in {"legacy", "legacy_ai", "ai_primary"}:
        return "legacy_ai"
    if raw in {"llm", "ai", "hybrid", "ai_enhanced", "enhanced"}:
        return "ai_enhanced"
    return "ai_enhanced"


def _emit(
    progress_callback: Callable[..., None] | None,
    step: str,
    label: str,
    percent: int,
    **extra,
) -> None:
    if progress_callback is not None:
        progress_callback(step, label, percent=percent, **extra)


def _empty_summary(input_name: str, doc_type: str, doc_text) -> LeaseSummary:
    return LeaseSummary(
        document_meta=DocumentMeta(
            source_filename=input_name,
            document_type=doc_type,
            pages=len(doc_text.pages),
            parsed_with_ocr=doc_text.parsed_with_ocr,
        ),
        summary_meta=SummaryMeta(summary_date=datetime.date.today()),
    )


def _apply_agent_decisions(
    summary: LeaseSummary,
    decisions: list[EnhancedFieldDecision],
    trace_id: str,
) -> LeaseSummary:
    for decision in decisions:
        if decision.field_path not in _FIELD_SETTERS:
            continue
        selected_value = _coerce_agent_value(decision.field_path, decision.selected_value)
        if selected_value in (None, ""):
            continue
        evidence = [
            Evidence(
                page=span.page,
                quote=span.quote,
                method=ExtractionMethod.agent,
                chunk_id=span.chunk_id,
                char_start=span.char_start,
                char_end=span.char_end,
                tool_call_id=span.tool_call_id,
            )
            for span in decision.evidence
            if span.quote
        ]
        if not evidence:
            continue
        flag = "Needs review" if decision.needs_review else None
        if decision.conflict and not flag:
            flag = "Conflicting candidates"
        result = ExtractionResult(
            value=selected_value,
            confidence=decision.confidence,
            evidence=evidence,
            review_flag=flag,
            source="agent",
            sources=decision.sources or ["agent"],
            reason_summary=decision.reason_summary,
            trace_id=trace_id,
            needs_review=decision.needs_review,
        )
        _FIELD_SETTERS[decision.field_path](summary, result)
    return summary


def _coerce_agent_value(field_path: str, value: Any) -> Any:
    if value in (None, ""):
        return None
    if field_path in _DATE_FIELD_PATHS:
        return _coerce_date(value)
    if field_path in _INTEGER_FIELD_PATHS:
        return _coerce_int(value)
    if field_path in _NUMBER_FIELD_PATHS:
        return _coerce_number(value)
    return value


def _coerce_date(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        return parse_date(text)


def _coerce_int(value: Any) -> int | None:
    number = _coerce_number(value)
    if number is None:
        return None
    return int(round(number))


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _sync_break_clause(summary: LeaseSummary) -> None:
    term_break = summary.term.tenant_termination_right_text
    clause_break = summary.clauses.break_clause_text
    if term_break.is_found() and not clause_break.is_found():
        summary.clauses.break_clause_text = term_break
    elif clause_break.is_found() and not term_break.is_found():
        summary.term.tenant_termination_right_text = clause_break


def _build_evidence_index(
    rule_candidates: list[FieldCandidate],
    semantic_candidates: list[FieldCandidate],
) -> EvidenceIndex:
    index = EvidenceIndex()
    for candidate in [*rule_candidates, *semantic_candidates]:
        for evidence in candidate.evidence:
            index.add(candidate.field_path, evidence, candidate.source)
    return index


def _write_trace(trace: ExtractionTrace, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(trace.model_dump(), ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return output_path


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)


_DATE_FIELD_PATHS = {field.field_path for field in FIELD_SPECS if field.value_type == "date"}
_INTEGER_FIELD_PATHS = {field.field_path for field in FIELD_SPECS if field.value_type == "integer"}
_NUMBER_FIELD_PATHS = {field.field_path for field in FIELD_SPECS if field.value_type == "number"}


_FIELD_SETTERS = {
    "parties.landlord_name": lambda s, r: setattr(s.parties, "landlord_name", r),
    "parties.landlord_registered_address": lambda s, r: setattr(s.parties, "landlord_registered_address", r),
    "parties.landlord_agent": lambda s, r: setattr(s.parties, "landlord_agent", r),
    "parties.landlord_solicitor": lambda s, r: setattr(s.parties, "landlord_solicitor", r),
    "parties.tenant_name": lambda s, r: setattr(s.parties, "tenant_name", r),
    "parties.tenant_registered_address": lambda s, r: setattr(s.parties, "tenant_registered_address", r),
    "parties.tenant_correspondence_address": lambda s, r: setattr(s.parties, "tenant_correspondence_address", r),
    "parties.tenant_contact_person": lambda s, r: setattr(s.parties, "tenant_contact_person", r),
    "premises.full_address": lambda s, r: setattr(s.premises, "full_address", r),
    "premises.building_name": lambda s, r: setattr(s.premises, "building_name", r),
    "premises.floor_suite": lambda s, r: setattr(s.premises, "floor_suite", r),
    "premises.rentable_area_sqft": lambda s, r: setattr(s.premises, "rentable_area_sqft", r),
    "premises.area_comment": lambda s, r: setattr(s.premises, "area_comment", r),
    "term.lease_signing_date": lambda s, r: setattr(s.term, "lease_signing_date", r),
    "term.scheduled_commencement_date": lambda s, r: setattr(s.term, "scheduled_commencement_date", r),
    "term.lease_commencement_date": lambda s, r: setattr(s.term, "lease_commencement_date", r),
    "term.lease_expiry_date": lambda s, r: setattr(s.term, "lease_expiry_date", r),
    "term.lease_term_months": lambda s, r: setattr(s.term, "lease_term_months", r),
    "term.fit_out_period_text": lambda s, r: setattr(s.term, "fit_out_period_text", r),
    "term.rent_free_period_text": lambda s, r: setattr(s.term, "rent_free_period_text", r),
    "term.option_to_renew_text": lambda s, r: setattr(s.term, "option_to_renew_text", r),
    "term.trigger_date_text": lambda s, r: setattr(s.term, "trigger_date_text", r),
    "term.right_of_expansion_text": lambda s, r: setattr(s.term, "right_of_expansion_text", r),
    "term.tenant_termination_right_text": lambda s, r: setattr(s.term, "tenant_termination_right_text", r),
    "financials.monthly_rent_hkd": lambda s, r: setattr(s.financials, "monthly_rent_hkd", r),
    "financials.monthly_rent_psf_hkd": lambda s, r: setattr(s.financials, "monthly_rent_psf_hkd", r),
    "financials.management_fee_monthly_hkd": lambda s, r: setattr(s.financials, "management_fee_monthly_hkd", r),
    "financials.management_fee_psf_hkd": lambda s, r: setattr(s.financials, "management_fee_psf_hkd", r),
    "financials.rates_quarterly_hkd": lambda s, r: setattr(s.financials, "rates_quarterly_hkd", r),
    "financials.rates_monthly_hkd": lambda s, r: setattr(s.financials, "rates_monthly_hkd", r),
    "financials.government_rent_monthly_hkd": lambda s, r: setattr(s.financials, "government_rent_monthly_hkd", r),
    "financials.security_deposit_hkd": lambda s, r: setattr(s.financials, "security_deposit_hkd", r),
    "financials.security_deposit_multiple": lambda s, r: setattr(s.financials, "security_deposit_multiple", r),
    "financials.security_deposit_note": lambda s, r: setattr(s.financials, "security_deposit_note", r),
    "financials.advance_rent_text": lambda s, r: setattr(s.financials, "advance_rent_text", r),
    "clauses.user_clause_text": lambda s, r: setattr(s.clauses, "user_clause_text", r),
    "clauses.handover_condition_text": lambda s, r: setattr(s.clauses, "handover_condition_text", r),
    "clauses.break_clause_text": lambda s, r: setattr(s.clauses, "break_clause_text", r),
    "clauses.signage_text": lambda s, r: setattr(s.clauses, "signage_text", r),
    "clauses.subletting_text": lambda s, r: setattr(s.clauses, "subletting_text", r),
    "clauses.parking_text": lambda s, r: setattr(s.clauses, "parking_text", r),
    "clauses.restoration_obligations_text": lambda s, r: setattr(s.clauses, "restoration_obligations_text", r),
}



def _detect_doc_type(text: str) -> str:
    return detect_doc_type(text)
