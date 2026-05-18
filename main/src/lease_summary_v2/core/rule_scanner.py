"""Adapter that exposes existing regex/rule extractors as candidates."""
from __future__ import annotations

import datetime

from ..extractors.clauses import extract_clauses
from ..extractors.dates import extract_term
from ..extractors.financials import extract_financials
from ..extractors.parties import extract_parties
from ..extractors.premises import extract_premises
from ..models import DocumentMeta, LeaseSummary, SummaryMeta
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument
from .candidates import FieldCandidate, summary_to_candidates


def run_rule_scanners(
    doc_text: DocumentText,
    sections: SplitDocument,
    *,
    source_filename: str = "",
    document_type: str = "unknown",
) -> tuple[LeaseSummary, list[FieldCandidate]]:
    summary = LeaseSummary(
        document_meta=DocumentMeta(
            source_filename=source_filename,
            document_type=document_type,
            parsed_with_ocr=doc_text.parsed_with_ocr,
            pages=len(doc_text.pages),
        ),
        summary_meta=SummaryMeta(summary_date=datetime.date.today()),
    )
    summary.parties = extract_parties(doc_text, sections)
    summary.premises = extract_premises(doc_text, sections)
    summary.term = extract_term(doc_text, sections)
    summary.financials = extract_financials(doc_text, sections)
    summary.clauses = extract_clauses(doc_text, sections)
    _sync_break_clause(summary)
    candidates = summary_to_candidates(summary, source="rule", extractor="existing_extractors")
    return summary, candidates


def _sync_break_clause(summary: LeaseSummary) -> None:
    clause_break = summary.clauses.break_clause_text
    term_break = summary.term.tenant_termination_right_text
    if clause_break.is_found() and not term_break.is_found():
        summary.term.tenant_termination_right_text = clause_break
    elif term_break.is_found() and not clause_break.is_found():
        summary.clauses.break_clause_text = term_break

