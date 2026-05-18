"""Main extraction pipeline."""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from .config import TEMPLATE_PATH, DEFAULT_OUTPUT_DIR
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
    extraction_mode: str | None = None,
) -> dict[str, Path]:
    """
    Full pipeline: PDF -> LeaseSummary -> Excel + JSON outputs.

    Returns dict with keys 'excel', 'json', 'review'.
    """
    input_pdf = Path(input_pdf)
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    template_path = Path(template_path) if template_path else TEMPLATE_PATH
    extraction_mode = (extraction_mode or os.environ.get("LLM_EXTRACTION_MODE", "hybrid")).strip().lower()
    pure_llm = extraction_mode in {"pure", "llm_only", "llm-only", "pure_llm"}

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_pdf.stem

    # ── Step 1: Extract text ────────────────────────────────────────────────────
    doc_text = extract_text(input_pdf)

    # ── Step 2: Split into sections ─────────────────────────────────────────────
    sections = split(doc_text)

    # ── Step 3: Detect document type ────────────────────────────────────────────
    doc_type = _detect_doc_type(sections.principal_terms)

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

    # ── Step 4b: LLM extraction ────────────────────────────────────────────────
    # Hybrid mode fills gaps/low-confidence regex results. Pure mode skips all
    # regex/rule extractors and lets the configured LLM populate the model.
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



_NOT_LEASE_SIGNALS = [
    "invoice", "invoice no", "invoice date", "fee payable",
    "quotation", "receipt", "payment receipt",
    "floor plan", "site plan",
    "management accounts", "financial statement",
    "business registration",
    "company search", "writ of summons",
]

_LEASE_SIGNALS = [
    "landlord", "tenant", "lessor", "lessee",
    "lease", "tenancy", "let and hire",
    "demised premises", "rent", "security deposit",
]


def _detect_doc_type(text: str) -> str:
    text_lower = text.lower()

    # Count lease vs non-lease signals
    lease_hits = sum(1 for s in _LEASE_SIGNALS if s in text_lower)
    non_lease_hits = sum(1 for s in _NOT_LEASE_SIGNALS if s in text_lower)

    # Reject if clearly not a lease (more non-lease signals and very few lease signals)
    if non_lease_hits >= 2 and lease_hits <= 1:
        return "not_a_lease"

    if "offer to lease" in text_lower:
        return "offer_to_lease"
    if "tenancy offer letter" in text_lower or "offer letter" in text_lower:
        return "tenancy_offer_letter"
    if "tenancy agreement" in text_lower:
        return "lease"
    if "signed lease" in text_lower or "lease agreement" in text_lower:
        return "signed_lease"
    return "unknown"
