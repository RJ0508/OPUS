"""PDF text extraction using PyMuPDF — with automatic OCR fallback.

OCR strategy:
- Native text first (fast, lossless).
- Scanned-document detection: avg < 100 chars/page over the first 5 pages.
- OCR pass uses PyMuPDF + Tesseract at 300 DPI with the best available
  language bundle (prefers `eng+chi_tra+chi_sim` → `eng+chi_tra` → `eng`).
- Quality is recorded on DocumentText so downstream stages can surface it.

This gives us meaningfully better recognition on HK commercial leases
(which routinely mix English schedule text with Traditional Chinese
signatures, stamps, and names) without adding a heavyweight dependency.
If the user wants a top-tier model (e.g. PaddleOCR-VL) we can plug in a
new backend — the interface intentionally centralizes through a single
`_ocr_page` helper.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class PageText:
    page_num: int  # 1-based
    text: str
    has_text: bool = True

    @property
    def lower(self) -> str:
        return self.text.lower()


@dataclass
class DocumentText:
    pages: list[PageText] = field(default_factory=list)
    source_path: "Path | None" = None  # original file path for vision extraction
    parsed_with_ocr: bool = False
    ocr_language: str | None = None  # e.g. "eng+chi_tra"
    ocr_avg_chars: float = 0.0  # avg chars/page after OCR — quality signal
    extraction_backend: str = "pymupdf"  # "pymupdf" | "pymupdf+tesseract"
    word_bboxes: dict | None = None  # {page_num: [(x0,y0,x1,y1,word), ...]} when OCR

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def page(self, num: int) -> str:
        """Return text for 1-based page number, or empty string."""
        for p in self.pages:
            if p.page_num == num:
                return p.text
        return ""

    def pages_range(self, start: int, end: int) -> str:
        """Return concatenated text for 1-based page range [start, end]."""
        return "\n".join(
            p.text for p in self.pages if start <= p.page_num <= end
        )


# Known Tesseract data directory locations
_TESSDATA_CANDIDATES = [
    "/opt/homebrew/share/tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4/tessdata",
    "/usr/local/share/tessdata",
]

# Preferred OCR language combinations, in descending order of quality.
# HK leases are predominantly English but commonly include Traditional
# Chinese (party names, signature blocks, stamps). A multi-language pack
# yields noticeably cleaner text when either script appears.
_LANGUAGE_PREFERENCES = [
    ("eng", "chi_tra", "chi_sim"),
    ("eng", "chi_tra"),
    ("eng",),
]

_OCR_DPI = 300  # up from 200 — better for HK lease scans (small print)


def _find_tessdata() -> str | None:
    for p in _TESSDATA_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _pick_language(tessdata: str) -> str | None:
    """Return the best available language string (e.g. 'eng+chi_tra')."""
    for combo in _LANGUAGE_PREFERENCES:
        if all(os.path.exists(os.path.join(tessdata, f"{lang}.traineddata")) for lang in combo):
            return "+".join(combo)
    return None


def extract_text(
    pdf_path: str | Path,
    force_ocr: bool = False,
    skip_ocr: bool = False,
) -> DocumentText:
    """
    Extract text page by page from a PDF file.
    Automatically falls back to OCR (via Tesseract) when the PDF is scanned
    (i.e. contains images but negligible native text).

    skip_ocr=True: never run Tesseract even if the PDF is scanned.
    Use this when a vision LLM will handle extraction directly from images.
    """
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    pages: list[PageText] = []

    # First pass: native text extraction
    for i, page in enumerate(doc):
        text = page.get_text()
        text = _normalize_whitespace(text)
        pages.append(PageText(page_num=i + 1, text=text, has_text=bool(text.strip())))

    # Decide whether OCR is needed
    sample_pages = [p.text for p in pages[:5]]
    avg_len = sum(len(t) for t in sample_pages) / max(len(sample_pages), 1)
    needs_ocr = (force_ocr or avg_len < 100) and not skip_ocr

    ocr_language: str | None = None
    backend = "pymupdf"
    word_bboxes: dict | None = None
    if needs_ocr:
        tessdata = _find_tessdata()
        if tessdata:
            ocr_language = _pick_language(tessdata)
        if tessdata and ocr_language:
            backend = "pymupdf+tesseract"
            pages, word_bboxes = _ocr_all_pages(doc, tessdata, ocr_language)
        # If tessdata or language packs missing, keep the native pages
        # (empty but present) and flag parsed_with_ocr so callers know the
        # PDF was scanned — the AI fallback can still try to salvage text.

    doc.close()

    ocr_avg_chars = (
        sum(len(p.text) for p in pages) / max(len(pages), 1) if needs_ocr else 0.0
    )
    return DocumentText(
        pages=pages,
        source_path=pdf_path,
        parsed_with_ocr=needs_ocr,
        ocr_language=ocr_language,
        ocr_avg_chars=ocr_avg_chars,
        extraction_backend=backend,
        word_bboxes=word_bboxes,
    )


def _ocr_all_pages(doc, tessdata: str, language: str) -> tuple[list[PageText], dict]:
    out: list[PageText] = []
    word_bboxes: dict[int, list] = {}
    for i, page in enumerate(doc):
        page_num = i + 1
        text, words = _ocr_page(page, tessdata, language)
        out.append(PageText(page_num=page_num, text=text, has_text=bool(text.strip())))
        word_bboxes[page_num] = words
    return out, word_bboxes


def _ocr_page(page, tessdata: str, language: str) -> tuple[str, list]:
    """Single-page OCR with graceful fallback if a language pack fails.

    Returns (normalized_text, word_bboxes) where word_bboxes is a list of
    (x0, y0, x1, y1, word) tuples in PyMuPDF page coordinates (top-left
    origin, y increases downward, units = points).

    PyMuPDF's `get_textpage_ocr` wraps Tesseract under the hood. If the
    preferred multi-language combo fails at runtime (corrupt traineddata,
    ABI mismatch, etc.) we degrade to 'eng' rather than losing the page
    entirely.
    """
    try:
        tp = page.get_textpage_ocr(tessdata=tessdata, language=language, dpi=_OCR_DPI)
        text = page.get_text(textpage=tp)
        words = [(w[0], w[1], w[2], w[3], w[4])
                 for w in page.get_text("words", textpage=tp) if (w[4] or "").strip()]
    except Exception:
        if language != "eng":
            try:
                tp = page.get_textpage_ocr(tessdata=tessdata, language="eng", dpi=_OCR_DPI)
                text = page.get_text(textpage=tp)
                words = [(w[0], w[1], w[2], w[3], w[4])
                         for w in page.get_text("words", textpage=tp) if (w[4] or "").strip()]
            except Exception:
                text = ""
                words = []
        else:
            text = ""
            words = []
    return _normalize_whitespace(text), words


def _normalize_whitespace(text: str) -> str:
    """Clean up whitespace artifacts from PDF extraction."""
    # Replace smart quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Remove trailing spaces on lines
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Collapse excessive blank lines (3+ -> 2)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
