"""Document index and chunking for full-document AI scanning."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..parsers.pdf_text import DocumentText, PageText
from ..parsers.section_splitter import SplitDocument


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    page_start: int
    page_end: int
    section: str | None = None
    char_start: int = 0
    char_end: int = 0


@dataclass
class DocumentIndex:
    pages: list[PageText]
    chunks: list[DocumentChunk]
    sections: SplitDocument
    full_text: str
    chunk_by_id: dict[str, DocumentChunk] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.chunk_by_id = {chunk.chunk_id: chunk for chunk in self.chunks}

    def read_chunk(self, chunk_id: str) -> str:
        chunk = self.chunk_by_id.get(chunk_id)
        return chunk.text if chunk else ""

    def read_page(self, page_num: int) -> str:
        for page in self.pages:
            if page.page_num == page_num:
                return page.text
        return ""


def build_document_index(
    doc: DocumentText,
    sections: SplitDocument,
    *,
    chunk_chars: int = 5000,
    overlap_chars: int = 400,
) -> DocumentIndex:
    chunks: list[DocumentChunk] = []
    char_cursor = 0

    for page in doc.pages:
        page_text = page.text or ""
        if not page_text.strip():
            char_cursor += len(page_text) + 1
            continue
        page_chunks = _split_text(page_text, chunk_chars, overlap_chars)
        for idx, text in enumerate(page_chunks, 1):
            chunk_id = f"page_{page.page_num}_chunk_{idx}"
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                text=text,
                page_start=page.page_num,
                page_end=page.page_num,
                section=_section_for_page(page.page_num, sections),
                char_start=char_cursor,
                char_end=char_cursor + len(text),
            ))
        char_cursor += len(page_text) + 1

    if not chunks and sections.full_text:
        for idx, text in enumerate(_split_text(sections.full_text, chunk_chars, overlap_chars), 1):
            chunks.append(DocumentChunk(
                chunk_id=f"full_text_chunk_{idx}",
                text=text,
                page_start=1,
                page_end=max(1, len(doc.pages)),
                section="full_text",
                char_start=(idx - 1) * max(1, chunk_chars - overlap_chars),
                char_end=(idx - 1) * max(1, chunk_chars - overlap_chars) + len(text),
            ))

    _append_section_chunks(chunks, sections, chunk_chars, overlap_chars)
    return DocumentIndex(
        pages=doc.pages,
        chunks=_dedupe_chunks(chunks),
        sections=sections,
        full_text=doc.full_text,
    )


def _append_section_chunks(
    chunks: list[DocumentChunk],
    sections: SplitDocument,
    chunk_chars: int,
    overlap_chars: int,
) -> None:
    section_sources = [
        ("principal_terms", sections.principal_terms, sections.principal_terms_pages),
        ("schedule_i", sections.schedule_i, (1, 1)),
        ("schedule_ii", sections.schedule_ii, (1, 1)),
        ("schedule_iii", sections.schedule_iii, (1, 1)),
        ("annexure", sections.annexure, (1, 1)),
    ]
    for section, text, pages in section_sources:
        if not text:
            continue
        for idx, chunk_text in enumerate(_split_text(text, chunk_chars, overlap_chars), 1):
            chunks.append(DocumentChunk(
                chunk_id=f"{section}_chunk_{idx}",
                text=chunk_text,
                page_start=pages[0],
                page_end=pages[1],
                section=section,
            ))


def _split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind("\n", start + max_chars // 2, end), text.rfind(". ", start + max_chars // 2, end))
            if boundary > start:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap_chars)
    return [chunk for chunk in chunks if chunk]


def _section_for_page(page_num: int, sections: SplitDocument) -> str | None:
    start, end = sections.principal_terms_pages
    if start <= page_num <= end:
        return "principal_terms"
    return None


def _dedupe_chunks(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    seen: set[str] = set()
    result: list[DocumentChunk] = []
    for chunk in chunks:
        key = " ".join(chunk.text[:400].split()).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    return result

