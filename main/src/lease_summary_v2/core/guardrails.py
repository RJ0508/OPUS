"""Pipeline-level guardrails for AI Enhanced extraction."""
from __future__ import annotations

import os
from pathlib import Path

from ..parsers.pdf_text import DocumentText
from .trace import ExtractionTrace


MAX_INPUT_BYTES = int(os.environ.get("OPUS_MAX_INPUT_BYTES", str(75 * 1024 * 1024)))
MAX_PAGES = int(os.environ.get("OPUS_MAX_PAGES", "250"))
MIN_OCR_AVG_CHARS = int(os.environ.get("OPUS_MIN_OCR_AVG_CHARS", "80"))


def validate_input_file(path: Path, trace: ExtractionTrace) -> None:
    if not path.exists():
        raise ValueError(f"Input file does not exist: {path}")
    size = path.stat().st_size
    trace.file_size_bytes = size
    if size > MAX_INPUT_BYTES:
        max_mb = MAX_INPUT_BYTES / (1024 * 1024)
        raise ValueError(f"Input file is too large for AI Enhanced extraction. Limit: {max_mb:.0f} MB.")


def validate_document_text(doc_text: DocumentText, trace: ExtractionTrace) -> None:
    page_count = len(doc_text.pages)
    trace.pages_count = page_count
    trace.ocr_avg_chars = doc_text.ocr_avg_chars
    if page_count <= 0:
        raise ValueError("No readable pages were found in the uploaded document.")
    if page_count > MAX_PAGES:
        raise ValueError(f"Document has {page_count} pages. Limit: {MAX_PAGES} pages.")
    if doc_text.parsed_with_ocr and doc_text.ocr_avg_chars < MIN_OCR_AVG_CHARS:
        trace.warnings.append(
            f"OCR quality is low ({doc_text.ocr_avg_chars:.0f} chars/page). Evidence may need manual review."
        )
