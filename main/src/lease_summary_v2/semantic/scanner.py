"""Full-document semantic scan that produces evidence-backed candidates."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Callable

from lease_summary.llm_config import (
    _safe_chat_create,
    build_openai_client,
    extract_message_text,
    structured_response_format,
)

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
    warning_callback: Callable[[str], None] | None = None,
) -> list[FieldCandidate]:
    """Scan every document chunk and return candidates with verbatim evidence."""
    fields = fields or FIELD_SPECS
    if scan_chunk_fn is None:
        if client is None or not model:
            client, settings = build_openai_client(
                "https://api.moonshot.cn/v1",
                "kimi-k2.6",
                default_provider="moonshot",
            )
            model = settings.model if settings else None
        if client is None or not model:
            if warning_callback is not None:
                warning_callback("LLM client unavailable; semantic scan skipped.")
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
            else semantic_scan_chunk(
                chunk,
                fields,
                client=client,
                model=model,
                warning_callback=warning_callback,
            )
        )
        accepted_for_chunk = 0
        for finding in findings:
            candidate = _finding_to_candidate(finding, chunk)
            if candidate is not None:
                candidates.append(candidate)
                accepted_for_chunk += 1
        if findings and accepted_for_chunk == 0 and warning_callback is not None:
            warning_callback(
                f"Semantic scan returned {len(findings)} findings for {chunk.chunk_id}, "
                "but none had evidence that could be located in the source chunk."
            )
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
    warning_callback: Callable[[str], None] | None = None,
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
    errors: list[str] = []
    for attempt_name, attempt_kwargs in _semantic_request_attempts(kwargs):
        try:
            response = _safe_chat_create(client, **attempt_kwargs)
            result, error = _parse_semantic_response(
                extract_message_text(response.choices[0].message),
                chunk_id=chunk.chunk_id,
            )
            if result is not None:
                return result.findings
            errors.append(f"{attempt_name}={error}")
        except Exception as exc:
            errors.append(f"{attempt_name}={type(exc).__name__}: {str(exc)[:220]}")

    if warning_callback is not None:
        warning_callback(
            f"Semantic scan failed for {chunk.chunk_id}: "
            f"{'; '.join(errors)}"
        )
    return []


def _semantic_request_attempts(kwargs: dict) -> list[tuple[str, dict]]:
    structured_kwargs = dict(kwargs)

    json_object_kwargs = dict(kwargs)
    json_object_kwargs["response_format"] = {"type": "json_object"}

    plain_kwargs = dict(kwargs)
    plain_kwargs.pop("response_format", None)
    plain_kwargs["messages"] = [
        *plain_kwargs.get("messages", []),
        {
            "role": "user",
            "content": (
                "Return only valid JSON. Use either {\"findings\":[...]} or a nested "
                "object keyed by the target field paths. Do not include Markdown."
            ),
        },
    ]
    return [
        ("json_schema", structured_kwargs),
        ("json_object", json_object_kwargs),
        ("plain_json", plain_kwargs),
    ]


def _parse_semantic_response(raw: str, *, chunk_id: str) -> tuple[SemanticScanResult | None, str]:
    data = _parse_json((raw or "").strip())
    if not data:
        return None, f"non-JSON content for {chunk_id}"
    data = _normalise_semantic_payload(data)
    if "findings" not in data:
        return None, f"no findings array for {chunk_id}"
    try:
        return SemanticScanResult.model_validate(data), ""
    except Exception as exc:
        return None, f"schema validation failed for {chunk_id}: {type(exc).__name__}: {str(exc)[:220]}"


def _finding_to_candidate(finding: SemanticFinding, chunk: DocumentChunk) -> FieldCandidate | None:
    if finding.field_path not in FIELD_SPEC_BY_PATH:
        return None
    value = finding.normalized_value if finding.normalized_value is not None else finding.value
    if _is_missing(value):
        return None
    quote = (finding.evidence_quote or "").strip()
    location = _locate_evidence_quote(quote, chunk.text)
    if location is None:
        return None
    evidence_quote, start, end = location
    page = finding.page_hint or chunk.page_start
    return FieldCandidate(
        field_path=finding.field_path,
        value=value,
        confidence=finding.confidence,
        source="semantic_llm",
        evidence=[EvidenceSpan(
            page=page,
            quote=evidence_quote,
            method="semantic_llm",
            chunk_id=chunk.chunk_id,
            char_start=start,
            char_end=end,
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
        if isinstance(data, list):
            return {"findings": data}
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            array_match = re.search(r"\[.*\]", text, re.DOTALL)
            if not array_match:
                return None
            try:
                data = json.loads(array_match.group(0))
                return {"findings": data} if isinstance(data, list) else None
            except json.JSONDecodeError:
                return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _normalise_semantic_payload(data: dict) -> dict:
    findings = data.get("findings")
    if not isinstance(findings, list):
        for key in ("results", "fields", "items", "extractions"):
            value = data.get(key)
            if isinstance(value, list):
                findings = value
                break
    if not isinstance(findings, list) or not findings:
        nested_findings = _flatten_nested_semantic_payload(data)
        if nested_findings:
            findings = nested_findings
    if not isinstance(findings, list):
        return data

    normalised: list[dict] = []
    for item in findings:
        normalised_item = _normalise_finding_item(item)
        if normalised_item is None:
            continue
        normalised.append(normalised_item)
    return {"findings": normalised}


def _normalise_finding_item(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    field_path = _first_str(item, "field_path", "fieldPath", "path", "field", "key")
    quote = _first_str(item, "evidence_quote", "evidenceQuote", "quote", "source_quote", "sourceQuote", "evidence")
    if not field_path or not quote:
        return None
    return {
        "field_path": field_path,
        "value": item.get("value", item.get("selected_value")),
        "normalized_value": item.get("normalized_value", item.get("normalizedValue", item.get("normalised_value"))),
        "evidence_quote": quote,
        "confidence": _confidence(item.get("confidence")),
        "page_hint": item.get("page_hint", item.get("pageHint", item.get("page"))),
        "notes": _first_str(item, "notes", "reason", "reasoning", "comment") or "",
    }


def _flatten_nested_semantic_payload(data: dict) -> list[dict]:
    findings: list[dict] = []
    for key, value in data.items():
        if key in {"findings", "results", "fields", "items", "extractions"}:
            continue
        if not isinstance(value, dict):
            continue
        if key in FIELD_SPEC_BY_PATH:
            _append_nested_finding(findings, key, value)
            continue
        for child_key, child_value in value.items():
            field_path = child_key if child_key in FIELD_SPEC_BY_PATH else f"{key}.{child_key}"
            _append_nested_finding(findings, field_path, child_value)
    return findings


def _append_nested_finding(findings: list[dict], field_path: str, item: object) -> None:
    if field_path not in FIELD_SPEC_BY_PATH:
        return
    if isinstance(item, dict):
        value = item.get(
            "value",
            item.get("selected_value", item.get("normalized_value", item.get("normalizedValue"))),
        )
        quote = _first_str(
            item,
            "evidence_quote",
            "evidenceQuote",
            "quote",
            "source_quote",
            "sourceQuote",
            "evidence",
        )
        if not quote:
            quote = _quote_from_value(item.get("value")) or _quote_from_value(
                item.get("normalized_value", item.get("normalizedValue"))
            )
        normalized_value = item.get("normalized_value", item.get("normalizedValue", item.get("normalised_value")))
        page_hint = item.get("page_hint", item.get("pageHint", item.get("page")))
        notes = _first_str(item, "notes", "reason", "reasoning", "comment") or ""
        confidence = _confidence(item.get("confidence"))
    else:
        value = item
        quote = _quote_from_value(item)
        normalized_value = None
        page_hint = None
        notes = ""
        confidence = 0.7
    if _is_missing(value) or not quote:
        return
    findings.append({
        "field_path": field_path,
        "value": value,
        "normalized_value": normalized_value,
        "evidence_quote": quote,
        "confidence": confidence,
        "page_hint": page_hint,
        "notes": notes,
    })


def _quote_from_value(value) -> str:
    if _is_missing(value) or isinstance(value, bool) or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _first_str(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _confidence(value) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.7
    return max(0.0, min(1.0, confidence))


def _locate_evidence_quote(quote: str, text: str) -> tuple[str, int, int] | None:
    quote = (quote or "").strip()
    if not quote:
        return None

    start = text.find(quote)
    if start >= 0:
        return quote, start, start + len(quote)

    lowered_start = text.lower().find(quote.lower())
    if lowered_start >= 0:
        return text[lowered_start:lowered_start + len(quote)], lowered_start, lowered_start + len(quote)

    normalised_text, index_map = _collapse_whitespace_with_map(text)
    normalised_quote = " ".join(quote.split())
    if normalised_quote:
        pos = normalised_text.find(normalised_quote)
        if pos < 0:
            pos = normalised_text.lower().find(normalised_quote.lower())
        if pos >= 0 and index_map:
            start = index_map[pos]
            end = index_map[min(pos + len(normalised_quote) - 1, len(index_map) - 1)] + 1
            return text[start:end], start, end

    return _fuzzy_quote_window(quote, text)


def _collapse_whitespace_with_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    index_map: list[int] = []
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if chars and not in_space:
                chars.append(" ")
                index_map.append(index)
            in_space = True
            continue
        chars.append(char)
        index_map.append(index)
        in_space = False

    while chars and chars[-1] == " ":
        chars.pop()
        index_map.pop()
    return "".join(chars), index_map


def _fuzzy_quote_window(quote: str, text: str) -> tuple[str, int, int] | None:
    quote_tokens = _tokens(quote)
    if len(quote_tokens) < 3:
        return None
    quote_token_set = set(quote_tokens)
    best: tuple[float, str, int, int] | None = None
    for match in re.finditer(r"[^.\n;。；]{20,500}(?:[.\n;。；]|$)", text):
        window = match.group(0).strip()
        if not window:
            continue
        window_tokens = set(_tokens(window))
        if not window_tokens:
            continue
        overlap = len(quote_token_set & window_tokens) / len(quote_token_set)
        ratio = SequenceMatcher(None, _normalise_for_similarity(quote), _normalise_for_similarity(window)).ratio()
        score = max(overlap, ratio)
        if best is None or score > best[0]:
            start = text.find(window, match.start(), match.end())
            best = (score, window, start if start >= 0 else match.start(), (start if start >= 0 else match.start()) + len(window))
    if best is None or best[0] < 0.74:
        return None
    return best[1], best[2], best[3]


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9$%]+", value.lower())


def _normalise_for_similarity(value: str) -> str:
    return " ".join(_tokens(value))
