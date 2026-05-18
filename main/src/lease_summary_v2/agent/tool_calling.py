"""Optional LLM tool-calling loop for AI Enhanced final decisions."""
from __future__ import annotations

import json
from typing import Any

from lease_summary.llm_config import _safe_chat_create, strict_function_tool, structured_response_format

from ..core.candidates import FieldCandidate
from ..core.document_index import DocumentIndex
from ..core.field_specs import FIELD_SPEC_BY_PATH, FIELD_SPECS
from ..models import LeaseSummary
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
                parsed = _parse_result(getattr(message, "content", "") or "", doc_index)
                if parsed:
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

        final_response = _safe_chat_create(
            client,
            model=model,
            messages=[
                *messages,
                {"role": "user", "content": "Return final EnhancedExtractionResult JSON now. Do not call tools."},
            ],
            temperature=0,
            max_tokens=2600,
            response_format=structured_response_format(
                "enhanced_extraction_result",
                ENHANCED_EXTRACTION_JSON_SCHEMA,
            ),
        )
        return _parse_result(final_response.choices[0].message.content or "", doc_index)
    except Exception:
        return None


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


def _parse_result(text: str, doc_index: DocumentIndex) -> EnhancedExtractionResult | None:
    data = _parse_json(text)
    if not data:
        return None
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
    for evidence in decision.evidence:
        if not evidence.quote:
            return None
        if evidence.chunk_id and evidence.chunk_id in doc_index.chunk_by_id:
            if evidence.quote not in doc_index.chunk_by_id[evidence.chunk_id].text:
                return None
        elif evidence.page:
            if evidence.quote not in doc_index.read_page(evidence.page):
                return None
    return decision


def _parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)
