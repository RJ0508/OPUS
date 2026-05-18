"""Main extraction pipeline."""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from .config import TEMPLATE_PATH, DEFAULT_OUTPUT_DIR
from .doc_type import detect_doc_type
from .extractors.ai_primary import ai_primary_extract
from .extractors.clauses import extract_clauses
from .extractors.dates import extract_term
from .extractors.financials import extract_financials
from .extractors.parties import extract_parties
from .extractors.premises import extract_premises
from .models import DocumentMeta, LeaseSummary, SummaryMeta
from .parsers.pdf_text import extract_text
from .parsers.section_splitter import split
from .validators.business_rules import validate_business_rules
from .validators.field_validator import validate_mandatory
from .writers.excel_writer import write_excel
from .writers.json_writer import write_json, write_review_json


def run(
    input_pdf: str | Path,
    output_dir: str | Path | None = None,
    template_path: str | Path | None = None,
    use_ai: bool = False,
    extraction_mode: str | None = None,
) -> dict[str, Path]:
    """
    Full pipeline: PDF -> LeaseSummary -> Excel + JSON outputs.

    Returns dict with keys 'excel', 'json', 'review'.
    """
    input_pdf = Path(input_pdf)
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    template_path = Path(template_path) if template_path else TEMPLATE_PATH
    extraction_mode = (extraction_mode or os.environ.get("LLM_EXTRACTION_MODE", "")).strip().lower()
    pure_llm = extraction_mode in {"pure", "llm_only", "llm-only", "pure_llm"}

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_pdf.stem

    # ── Step 1: Extract text ────────────────────────────────────────────────────
    doc_text = extract_text(input_pdf)

    # ── Step 2: Split into sections ─────────────────────────────────────────────
    sections = split(doc_text)

    # ── Step 3: Detect document type ────────────────────────────────────────────
    doc_type = detect_doc_type(sections.principal_terms)

    if doc_type == "not_a_lease":
        raise ValueError(
            f"This file does not appear to be a lease document: {input_pdf.name}\n"
            "Only lease agreements, tenancy agreements, and offer-to-lease documents are supported."
        )

    # ── Step 4: Extract fields ──────────────────────────────────────────────────
    summary = LeaseSummary(
        document_meta=DocumentMeta(
            source_filename=input_pdf.name,
            document_type=doc_type,
            parsed_with_ocr=doc_text.parsed_with_ocr,
            pages=len(doc_text.pages),
        ),
        summary_meta=SummaryMeta(
            summary_date=datetime.date.today(),
        ),
    )

    if not pure_llm:
        summary.parties = extract_parties(doc_text, sections)
        summary.premises = extract_premises(doc_text, sections)
        summary.term = extract_term(doc_text, sections)
        summary.financials = extract_financials(doc_text, sections)
        summary.clauses = extract_clauses(doc_text, sections)

    # ── Step 4b: Optional LLM primary extraction ────────────────────────────────
    # The standard pipeline is intentionally regex-only by default.  The desktop
    # app selects lease_summary_v2 for AI-enhanced mode.
    if use_ai or pure_llm:
        ai_primary_extract(summary, doc_text, sections, pure_llm=pure_llm)

    # ── Step 5: Validate ────────────────────────────────────────────────────────
    validate_mandatory(summary)
    validate_business_rules(summary)

    # ── Step 6: Write outputs ───────────────────────────────────────────────────
    excel_path = output_dir / f"{stem}.summary.xlsx"
    json_path = output_dir / f"{stem}.extraction.json"
    review_path = output_dir / f"{stem}.review.json"

    write_excel(summary, template_path, excel_path)
    write_json(summary, json_path)
    write_review_json(summary, review_path)

    return {
        "excel": excel_path,
        "json": json_path,
        "review": review_path,
        "summary": summary,
        "doc_text": doc_text,
    }

def _detect_doc_type(text: str) -> str:
    """Compatibility wrapper for tests/imports that still reference this helper."""
    return detect_doc_type(text)
