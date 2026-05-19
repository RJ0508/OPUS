"""Optional LLM tool-calling loop for AI Enhanced final decisions."""
from __future__ import annotations

import json
import re
from typing import Any

from lease_summary.llm_config import (
    _safe_chat_create,
    extract_message_text,
    strict_function_tool,
    structured_response_format,
)

from ..core.candidates import FieldCandidate
from ..core.document_index import DocumentIndex
from ..core.field_specs import FIELD_SPEC_BY_PATH, FIELD_SPECS
from ..models import LeaseSummary
from ..semantic.scanner import _locate_evidence_quote
from .prompts import AGENT_INSTRUCTIONS
from .schemas import ENHANCED_EXTRACTION_JSON_SCHEMA, EnhancedExtractionResult, EnhancedFieldDecision
from .tools import AgentToolbox


MAX_AGENT_TOOL_ROUNDS = 4


def run_llm_tool_agent(
    *,
    doc_index: DocumentIndex,
    current_summary: LeaseSummary,
    rule_candidates: list[FieldCandidate],
    semantic_candidates: list[FieldCandidate],
    toolbox: AgentToolbox,
    client,
    model: str,
) -> EnhancedExtractionResult | None:
    if client is None or not model:
        return None

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": AGENT_INSTRUCTIONS},
        {"role": "user", "content": _agent_input(current_summary, rule_candidates, semantic_candidates)},
    ]

    try:
        for _ in range(MAX_AGENT_TOOL_ROUNDS):
            response = _safe_chat_create(
                client,
                model=model,
                messages=messages,
                tools=_tool_definitions(),
                tool_choice="auto",
                temperature=0,
                max_tokens=2600,
            )
            message = response.choices[0].message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            if not tool_calls:
                parsed = _parse_result(
                    extract_message_text(message),
                    doc_index,
                    candidate_pool=[*rule_candidates, *semantic_candidates],
                )
                if parsed and parsed.decisions:
                    return parsed
                break
            messages.append(_assistant_tool_call_message(message, tool_calls))
            for tool_call in tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(
                        _execute_tool(toolbox, tool_call.function.name, tool_call.function.arguments),
                        ensure_ascii=False,
                        default=_json_default,
                    ),
                })

        return _request_final_result(
            client=client,
            model=model,
            messages=messages,
            doc_index=doc_index,
            candidate_pool=[*rule_candidates, *semantic_candidates],
        )
    except Exception:
        return None


def _request_final_result(
    *,
    client,
    model: str,
    messages: list[dict[str, Any]],
    doc_index: DocumentIndex,
    candidate_pool: list[FieldCandidate],
) -> EnhancedExtractionResult | None:
    final_messages = [
        *messages,
        {
            "role": "user",
            "content": (
                "Return final EnhancedExtractionResult JSON now. Do not call tools. "
                "Prefer a top-level decisions array. Do not include Markdown."
            ),
        },
    ]
    attempts = [
        (
            "json_schema",
            {
                "response_format": structured_response_format(
                    "enhanced_extraction_result",
                    ENHANCED_EXTRACTION_JSON_SCHEMA,
                )
            },
        ),
        ("json_object", {"response_format": {"type": "json_object"}}),
        ("plain_json", {}),
    ]
    last_result: EnhancedExtractionResult | None = None
    for _attempt_name, extra_kwargs in attempts:
        response = _safe_chat_create(
            client,
            model=model,
            messages=final_messages,
            temperature=0,
            max_tokens=2600,
            **extra_kwargs,
        )
        parsed = _parse_result(
            extract_message_text(response.choices[0].message),
            doc_index,
            candidate_pool=candidate_pool,
        )
        if parsed and parsed.decisions:
            return parsed
        if parsed is not None:
            last_result = parsed
    return last_result


def _agent_input(
    current_summary: LeaseSummary,
    rule_candidates: list[FieldCandidate],
    semantic_candidates: list[FieldCandidate],
) -> str:
    payload = {
        "document_meta": current_summary.document_meta.model_dump(),
        "review_flags": [flag.model_dump() for flag in current_summary.review_flags],
        "target_fields": [field.model_dump() for field in FIELD_SPECS],
        "rule_candidates": [_candidate_payload(candidate) for candidate in rule_candidates],
        "semantic_candidates": [_candidate_payload(candidate) for candidate in semantic_candidates],
    }
    return json.dumps(payload, ensure_ascii=False, default=_json_default)


def _candidate_payload(candidate: FieldCandidate) -> dict[str, Any]:
    data = candidate.model_dump()
    for evidence in data.get("evidence", []):
        quote = evidence.get("quote") or ""
        if len(quote) > 420:
            evidence["quote"] = quote[:420]
    return data


def _tool_definitions() -> list[dict[str, object]]:
    return [
        strict_function_tool(
            "read_chunk",
            "Read one document chunk by chunk_id.",
            {
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
                "additionalProperties": False,
            },
        ),
        strict_function_tool(
            "read_page",
            "Read text for one page in the current document.",
            {
                "type": "object",
                "properties": {"page_num": {"type": "integer", "minimum": 1}},
                "required": ["page_num"],
                "additionalProperties": False,
            },
        ),
        strict_function_tool(
            "find_section",
            "Read a named section such as principal_terms, schedule_i, schedule_ii, schedule_iii, or annexure.",
            {
                "type": "object",
                "properties": {"section_name": {"type": "string"}},
                "required": ["section_name"],
                "additionalProperties": False,
            },
        ),
        strict_function_tool(
            "regex_search",
            "Search the current document with a bounded regex pattern and return evidence snippets.",
            {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "scope": {"type": "string", "enum": ["full_text", "pages"]},
                    "page_start": {"type": ["integer", "null"]},
                    "page_end": {"type": ["integer", "null"]},
                    "chunk_ids": {"type": ["array", "null"], "items": {"type": "string"}},
                    "max_matches": {"type": "integer", "minimum": 1, "maximum": 50},
                    "context_chars": {"type": "integer", "minimum": 20, "maximum": 500},
                },
                "required": ["pattern", "scope", "page_start", "page_end", "chunk_ids", "max_matches", "context_chars"],
                "additionalProperties": False,
            },
        ),
        strict_function_tool(
            "semantic_rescan_chunk",
            "Run the semantic scanner again on one chunk for specific target fields.",
            {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "target_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["chunk_id", "target_fields"],
                "additionalProperties": False,
            },
        ),
        strict_function_tool(
            "calculate_financials",
            "Calculate missing financial values such as rent per square foot or deposit multiple.",
            {
                "type": "object",
                "properties": {
                    "area_sqft": {"type": ["number", "string", "null"]},
                    "monthly_rent_hkd": {"type": ["number", "string", "null"]},
                    "rent_per_sqft_hkd": {"type": ["number", "string", "null"]},
                    "security_deposit_hkd": {"type": ["number", "string", "null"]},
                    "management_fee_hkd": {"type": ["number", "string", "null"]},
                },
                "required": [
                    "area_sqft",
                    "monthly_rent_hkd",
                    "rent_per_sqft_hkd",
                    "security_deposit_hkd",
                    "management_fee_hkd",
                ],
                "additionalProperties": False,
            },
        ),
        strict_function_tool(
            "validate_candidate",
            "Validate that a proposed field path and evidence quote are allowed and present in this document.",
            {
                "type": "object",
                "properties": {
                    "field_path": {"type": "string"},
                    "evidence_quote": {"type": "string"},
                    "page": {"type": ["integer", "null"]},
                    "chunk_id": {"type": ["string", "null"]},
                },
                "required": ["field_path", "evidence_quote", "page", "chunk_id"],
                "additionalProperties": False,
            },
        ),
    ]


def _execute_tool(toolbox: AgentToolbox, name: str, arguments: str) -> Any:
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    if name == "read_chunk":
        return {"text": toolbox.read_chunk(str(args.get("chunk_id", "")))}
    if name == "read_page":
        return {"text": toolbox.read_page(int(args.get("page_num") or 1))}
    if name == "find_section":
        return {"text": toolbox.find_section(str(args.get("section_name", "")))}
    if name == "regex_search":
        return [match.model_dump() for match in toolbox.regex_search(**args)]
    if name == "semantic_rescan_chunk":
        return [candidate.model_dump() for candidate in toolbox.semantic_rescan_chunk(**args)]
    if name == "calculate_financials":
        return toolbox.calculate_financials(**args)
    if name == "validate_candidate":
        return toolbox.validate_candidate(**args).model_dump()
    return {"error": f"Unknown tool: {name}"}


def _assistant_tool_call_message(message, tool_calls) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": getattr(message, "content", None) or "",
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in tool_calls
        ],
    }


def _parse_result(
    text: str,
    doc_index: DocumentIndex,
    candidate_pool: list[FieldCandidate] | None = None,
) -> EnhancedExtractionResult | None:
    data = _parse_json(text)
    if not data:
        return None
    data = _normalise_result_payload(data)
    if candidate_pool:
        data = _attach_candidate_evidence(data, candidate_pool)
    try:
        result = EnhancedExtractionResult.model_validate(data)
    except Exception:
        return None
    guarded = [_guard_decision(decision, doc_index) for decision in result.decisions]
    decisions = [decision for decision in guarded if decision is not None]
    return result.model_copy(update={"decisions": decisions})


def _guard_decision(
    decision: EnhancedFieldDecision,
    doc_index: DocumentIndex,
) -> EnhancedFieldDecision | None:
    if decision.field_path not in FIELD_SPEC_BY_PATH or not decision.evidence:
        return None
    guarded_evidence = []
    for evidence in decision.evidence:
        if not evidence.quote:
            return None
        if evidence.chunk_id and evidence.chunk_id in doc_index.chunk_by_id:
            chunk = doc_index.chunk_by_id[evidence.chunk_id]
            located = _locate_evidence_quote(evidence.quote, chunk.text)
            if located is None:
                return None
            quote, start, end = located
            guarded_evidence.append(evidence.model_copy(update={
                "quote": quote,
                "page": evidence.page or chunk.page_start,
                "char_start": start,
                "char_end": end,
            }))
        elif evidence.page:
            page_text = doc_index.read_page(evidence.page)
            located = _locate_evidence_quote(evidence.quote, page_text)
            if located is None:
                return None
            quote, start, end = located
            guarded_evidence.append(evidence.model_copy(update={
                "quote": quote,
                "char_start": start,
                "char_end": end,
            }))
        else:
            hit = None
            for chunk in doc_index.chunks:
                located = _locate_evidence_quote(evidence.quote, chunk.text)
                if located is not None:
                    hit = (chunk, located)
                    break
            if hit is None:
                return None
            chunk, located = hit
            quote, start, end = located
            guarded_evidence.append(evidence.model_copy(update={
                "quote": quote,
                "page": chunk.page_start,
                "chunk_id": chunk.chunk_id,
                "char_start": start,
                "char_end": end,
            }))
    return decision.model_copy(update={"evidence": guarded_evidence})


def _normalise_result_payload(data: dict) -> dict:
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        for key in ("fields", "results", "items", "extractions"):
            value = data.get(key)
            if isinstance(value, list):
                decisions = value
                break
    if not isinstance(decisions, list) or not decisions:
        nested_decisions = _flatten_nested_result_payload(data, inherited_review=bool(data.get("needs_review", False)))
        if nested_decisions:
            decisions = nested_decisions
    if not isinstance(decisions, list):
        return data

    normalised: list[dict[str, Any]] = []
    inherited_review = bool(data.get("needs_review", False))
    for item in decisions:
        decision = _normalise_decision_item(item, inherited_review)
        if decision is not None:
            normalised.append(decision)

    return {
        "decisions": normalised,
        "warnings": data.get("warnings") if isinstance(data.get("warnings"), list) else [],
        "trace_id": data.get("trace_id") if isinstance(data.get("trace_id"), str) else "",
    }


def _normalise_decision_item(item: object, inherited_review: bool) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    field_path = _first_str(item, "field_path", "fieldPath", "path", "field", "key")
    if not field_path:
        return None
    value = item.get("selected_value", item.get("value", item.get("normalized_value", item.get("normalizedValue"))))
    evidence = item.get("evidence", item.get("evidences", []))
    direct_quote = _first_str(item, "quote", "evidence_quote", "evidenceQuote", "source_quote", "sourceQuote")
    if not evidence and direct_quote:
        evidence = [{
            "page": item.get("page", item.get("page_hint", item.get("pageHint"))),
            "quote": direct_quote,
            "method": item.get("method", item.get("source", "agent")),
            "chunk_id": item.get("chunk_id", item.get("chunkId")),
        }]
    if isinstance(evidence, dict):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = []
    normalised_evidence = [_normalise_evidence_span(span) for span in evidence if isinstance(span, dict)]
    source = _first_str(item, "source")
    sources = item.get("sources")
    if not isinstance(sources, list):
        sources = [source] if source else []
    if not sources:
        sources = sorted({
            span.get("method")
            for span in normalised_evidence
            if isinstance(span.get("method"), str) and span.get("method") != "unknown"
        })
    return {
        "field_path": field_path,
        "selected_value": value,
        "confidence": _confidence(item.get("confidence")),
        "evidence": normalised_evidence,
        "sources": [str(source) for source in sources if source],
        "reason_summary": _first_str(item, "reason_summary", "reason", "notes") or "",
        "needs_review": bool(item.get("needs_review", inherited_review)),
        "conflict": bool(item.get("conflict", False)),
    }


def _flatten_nested_result_payload(data: dict, *, inherited_review: bool) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for key, value in data.items():
        if key in {"decisions", "fields", "results", "items", "extractions", "warnings", "trace_id", "needs_review"}:
            continue
        if not isinstance(value, dict):
            continue
        if key in FIELD_SPEC_BY_PATH:
            _append_nested_decision(decisions, key, value, inherited_review)
            continue
        for child_key, child_value in value.items():
            field_path = child_key if child_key in FIELD_SPEC_BY_PATH else f"{key}.{child_key}"
            _append_nested_decision(decisions, field_path, child_value, inherited_review)
    return decisions


def _append_nested_decision(
    decisions: list[dict[str, Any]],
    field_path: str,
    item: object,
    inherited_review: bool,
) -> None:
    if field_path not in FIELD_SPEC_BY_PATH:
        return
    if isinstance(item, dict):
        value = item.get("selected_value", item.get("value", item.get("normalized_value", item.get("normalizedValue"))))
        quote = _first_str(item, "quote", "evidence_quote", "evidenceQuote", "source_quote", "sourceQuote")
        page = item.get("page", item.get("page_hint", item.get("pageHint")))
        method = item.get("method", item.get("source", "agent"))
        chunk_id = item.get("chunk_id", item.get("chunkId"))
        sources = item.get("sources", [item.get("source", "agent")])
        reason = _first_str(item, "reason_summary", "reason", "notes") or ""
        needs_review = bool(item.get("needs_review", inherited_review))
        conflict = bool(item.get("conflict", False))
        confidence = _confidence(item.get("confidence"))
    else:
        value = item
        quote = ""
        page = None
        method = "agent"
        chunk_id = None
        sources = ["agent"]
        reason = ""
        needs_review = inherited_review
        conflict = False
        confidence = 0.7
    if value in (None, ""):
        return
    decisions.append({
        "field_path": field_path,
        "selected_value": value,
        "confidence": confidence,
        "evidence": [{
            "page": page,
            "quote": quote,
            "method": method,
            "chunk_id": chunk_id,
        }] if quote else [],
        "sources": sources,
        "reason_summary": reason,
        "needs_review": needs_review,
        "conflict": conflict,
    })


def _attach_candidate_evidence(data: dict, candidate_pool: list[FieldCandidate]) -> dict:
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        return data
    updated: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        if decision.get("evidence"):
            updated.append(decision)
            continue
        match = _find_matching_candidate(
            candidate_pool,
            str(decision.get("field_path") or ""),
            decision.get("selected_value"),
        )
        if match is None or not match.evidence:
            updated.append(decision)
            continue
        sources = decision.get("sources")
        if not isinstance(sources, list) or not sources:
            sources = [match.source]
        else:
            sources = sorted({str(source) for source in [*sources, match.source] if source})
        updated.append({
            **decision,
            "confidence": max(_confidence(decision.get("confidence")), match.confidence),
            "evidence": [evidence.model_dump() for evidence in match.evidence],
            "sources": sources,
            "reason_summary": decision.get("reason_summary") or (
                f"Agent selected a value already supported by {match.source} evidence."
            ),
        })
    return {**data, "decisions": updated}


def _find_matching_candidate(
    candidates: list[FieldCandidate],
    field_path: str,
    selected_value: Any,
) -> FieldCandidate | None:
    target = _normalise_value(selected_value)
    if not field_path or not target:
        return None
    matches = [
        candidate
        for candidate in candidates
        if candidate.field_path == field_path
        and candidate.evidence
        and _normalise_value(candidate.value) == target
    ]
    return max(matches, key=lambda candidate: candidate.confidence, default=None)


def _normalise_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace(",", "")


def _normalise_evidence_span(span: dict) -> dict[str, Any]:
    return {
        "page": _int_or_default(span.get("page", span.get("page_num")), 0),
        "quote": _first_str(span, "quote", "evidence_quote", "evidenceQuote", "source_quote", "sourceQuote"),
        "method": _first_str(span, "method", "source") or "agent",
        "chunk_id": span.get("chunk_id", span.get("chunkId")),
        "char_start": span.get("char_start", span.get("charStart")),
        "char_end": span.get("char_end", span.get("charEnd")),
        "tool_call_id": span.get("tool_call_id", span.get("toolCallId")),
    }


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


def _int_or_default(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return {"decisions": data}
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            array_start = text.find("[")
            array_end = text.rfind("]")
            if array_start < 0 or array_end <= array_start:
                return None
            try:
                data = json.loads(text[array_start:array_end + 1])
                return {"decisions": data} if isinstance(data, list) else None
            except json.JSONDecodeError:
                return None
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)
