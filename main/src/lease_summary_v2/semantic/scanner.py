"""Full-document semantic scan that produces evidence-backed candidates."""
from __future__ import annotations

import json
import re
from typing import Callable

from lease_summary.llm_config import _safe_chat_create, build_openai_client, structured_response_format

from ..core.candidates import FieldCandidate
from ..core.document_index import DocumentChunk, DocumentIndex
from ..core.evidence import EvidenceSpan
from ..core.field_specs import FIELD_SPEC_BY_PATH, FIELD_SPECS, FieldSpec
from .prompts import SEMANTIC_SYSTEM_PROMPT, SEMANTIC_USER_TEMPLATE
from .schema import SEMANTIC_SCAN_JSON_SCHEMA, SemanticFinding, SemanticScanResult

ScanChunkFn = Callable[[DocumentChunk, list[FieldSpec]], list[SemanticFinding]]


def semantic_scan_document(
    doc_index: DocumentIndex,
    fields: list[FieldSpec] | None = None,
    *,
    client=None,
    model: str | None = None,
    scan_chunk_fn: ScanChunkFn | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> list[FieldCandidate]:
    """Scan every document chunk and return candidates with verbatim evidence."""
    fields = fields or FIELD_SPECS
    if scan_chunk_fn is None:
        if client is None or not model:
            client, settings = build_openai_client(
                "https://api.moonshot.cn/v1",
                "kimi-k2.5",
                default_provider="moonshot",
            )
            model = settings.model if settings else None
        if client is None or not model:
            return []

    candidates: list[FieldCandidate] = []
    total_chunks = max(len(doc_index.chunks), 1)
    for index, chunk in enumerate(doc_index.chunks, start=1):
        if progress_callback is not None:
            progress_callback(
                "scan",
                "Scanning full document with AI",
                percent=44 + int((index - 1) / total_chunks * 30),
                detail=f"Chunk {index}/{total_chunks} · pages {chunk.page_start}-{chunk.page_end}",
                chunk_id=chunk.chunk_id,
            )
        findings = (
            scan_chunk_fn(chunk, fields)
            if scan_chunk_fn is not None
            else semantic_scan_chunk(chunk, fields, client=client, model=model)
        )
        for finding in findings:
            candidate = _finding_to_candidate(finding, chunk)
            if candidate is not None:
                candidates.append(candidate)
    if progress_callback is not None:
        progress_callback(
            "scan",
            "Completed full-document AI scan",
            percent=74,
            detail=f"{len(candidates)} evidence-backed AI candidates",
        )
    return candidates


def semantic_scan_chunk(
    chunk: DocumentChunk,
    fields: list[FieldSpec],
    *,
    client,
    model: str,
) -> list[SemanticFinding]:
    field_lines = "\n".join(f"- {field.field_path}: {field.label} ({field.value_type})" for field in fields)
    prompt = SEMANTIC_USER_TEMPLATE.format(
        fields=field_lines,
        chunk_id=chunk.chunk_id,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        section=chunk.section or "",
        text=chunk.text,
    )
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": SEMANTIC_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 2500,
        "response_format": structured_response_format(
            "semantic_scan_result",
            SEMANTIC_SCAN_JSON_SCHEMA,
        ),
    }
    try:
        response = _safe_chat_create(client, **kwargs)
    except Exception:
        fallback_kwargs = dict(kwargs)
        fallback_kwargs["response_format"] = {"type": "json_object"}
        try:
            response = _safe_chat_create(client, **fallback_kwargs)
        except Exception:
            return []

    raw = (response.choices[0].message.content or "").strip()
    data = _parse_json(raw)
    if not data:
        return []
    try:
        result = SemanticScanResult.model_validate(data)
    except Exception:
        return []
    return result.findings


def _finding_to_candidate(finding: SemanticFinding, chunk: DocumentChunk) -> FieldCandidate | None:
    if finding.field_path not in FIELD_SPEC_BY_PATH:
        return None
    value = finding.normalized_value if finding.normalized_value is not None else finding.value
    if _is_missing(value):
        return None
    quote = (finding.evidence_quote or "").strip()
    if not quote or quote not in chunk.text:
        return None
    start = chunk.text.find(quote)
    page = finding.page_hint or chunk.page_start
    return FieldCandidate(
        field_path=finding.field_path,
        value=value,
        confidence=finding.confidence,
        source="semantic_llm",
        evidence=[EvidenceSpan(
            page=page,
            quote=quote,
            method="semantic_llm",
            chunk_id=chunk.chunk_id,
            char_start=start if start >= 0 else None,
            char_end=start + len(quote) if start >= 0 else None,
        )],
        extractor="semantic_scan_document",
        notes=finding.notes,
    )


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "null", "none", "n/a", "na", "nil"}
    return False


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
