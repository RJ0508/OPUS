"""Document-bound tools available to the AI Enhanced agent."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

from ..core.candidates import FieldCandidate
from ..core.document_index import DocumentIndex
from ..core.evidence import EvidenceSpan
from ..core.field_specs import FIELD_SPEC_BY_PATH, FieldSpec
from ..core.trace import ToolCallTrace
from ..semantic.scanner import semantic_scan_chunk
from .guardrails import (
    MAX_CONTEXT_CHARS,
    MAX_PAGE_CHARS,
    MAX_REGEX_MATCHES,
    clamp,
    validate_regex_pattern,
)


class RegexMatch(BaseModel):
    page: int
    chunk_id: str | None = None
    match: str
    quote: str
    start: int
    end: int


class CandidateValidation(BaseModel):
    valid: bool
    reason: str = ""
    page: int | None = None
    chunk_id: str | None = None


@dataclass
class AgentToolbox:
    doc_index: DocumentIndex
    client: Any = None
    model: str | None = None
    trace_calls: list[ToolCallTrace] = field(default_factory=list)

    def read_chunk(self, chunk_id: str) -> str:
        started = time.perf_counter()
        call_id = _call_id("read_chunk")
        text = self.doc_index.read_chunk(chunk_id)
        self.trace_calls.append(ToolCallTrace(
            tool_call_id=call_id,
            tool="read_chunk",
            args={"chunk_id": chunk_id},
            result_count=1 if text else 0,
            latency_ms=_elapsed_ms(started),
        ))
        return text

    def read_page(self, page_num: int) -> str:
        started = time.perf_counter()
        call_id = _call_id("read_page")
        text = self.doc_index.read_page(page_num)[:MAX_PAGE_CHARS]
        self.trace_calls.append(ToolCallTrace(
            tool_call_id=call_id,
            tool="read_page",
            args={"page_num": page_num},
            result_count=1 if text else 0,
            latency_ms=_elapsed_ms(started),
        ))
        return text

    def find_section(self, section_name: str) -> str:
        started = time.perf_counter()
        call_id = _call_id("find_section")
        name = (section_name or "").strip()
        text = getattr(self.doc_index.sections, name, "") if name else ""
        self.trace_calls.append(ToolCallTrace(
            tool_call_id=call_id,
            tool="find_section",
            args={"section_name": name},
            result_count=1 if text else 0,
            latency_ms=_elapsed_ms(started),
        ))
        return text

    def semantic_rescan_chunk(
        self,
        chunk_id: str,
        target_fields: list[str] | None = None,
    ) -> list[FieldCandidate]:
        started = time.perf_counter()
        call_id = _call_id("semantic_rescan_chunk")
        chunk = self.doc_index.chunk_by_id.get(chunk_id)
        if not chunk or self.client is None or not self.model:
            self.trace_calls.append(ToolCallTrace(
                tool_call_id=call_id,
                tool="semantic_rescan_chunk",
                args={"chunk_id": chunk_id, "target_fields": target_fields or []},
                result_count=0,
                latency_ms=_elapsed_ms(started),
            ))
            return []
        selected_fields: list[FieldSpec] = []
        for field_path in target_fields or []:
            spec = FIELD_SPEC_BY_PATH.get(field_path)
            if spec:
                selected_fields.append(spec)
        if not selected_fields:
            selected_fields = list(FIELD_SPEC_BY_PATH.values())

        findings = semantic_scan_chunk(chunk, selected_fields, client=self.client, model=self.model)
        candidates: list[FieldCandidate] = []
        for finding in findings:
            quote = (finding.evidence_quote or "").strip()
            if finding.field_path not in FIELD_SPEC_BY_PATH or not quote or quote not in chunk.text:
                continue
            start = chunk.text.find(quote)
            value = finding.normalized_value if finding.normalized_value is not None else finding.value
            candidates.append(FieldCandidate(
                field_path=finding.field_path,
                value=value,
                confidence=finding.confidence,
                source="semantic_llm",
                evidence=[EvidenceSpan(
                    page=finding.page_hint or chunk.page_start,
                    quote=quote,
                    method="semantic_llm",
                    chunk_id=chunk.chunk_id,
                    char_start=start if start >= 0 else None,
                    char_end=start + len(quote) if start >= 0 else None,
                    tool_call_id=call_id,
                )],
                extractor="semantic_rescan_chunk",
                notes=finding.notes,
            ))

        self.trace_calls.append(ToolCallTrace(
            tool_call_id=call_id,
            tool="semantic_rescan_chunk",
            args={"chunk_id": chunk_id, "target_fields": target_fields or []},
            result_count=len(candidates),
            latency_ms=_elapsed_ms(started),
        ))
        return candidates

    def calculate_financials(
        self,
        *,
        area_sqft: int | float | str | None = None,
        monthly_rent_hkd: int | float | str | None = None,
        rent_per_sqft_hkd: int | float | str | None = None,
        security_deposit_hkd: int | float | str | None = None,
        management_fee_hkd: int | float | str | None = None,
    ) -> dict[str, float | None]:
        started = time.perf_counter()
        call_id = _call_id("calculate_financials")
        area = _decimal(area_sqft)
        rent = _decimal(monthly_rent_hkd)
        psf = _decimal(rent_per_sqft_hkd)
        deposit = _decimal(security_deposit_hkd)
        mgmt = _decimal(management_fee_hkd)

        if rent is None and area and psf:
            rent = area * psf
        if psf is None and rent and area:
            psf = rent / area
        monthly_charges = rent + mgmt if rent is not None and mgmt is not None else rent
        deposit_multiple = (
            deposit / monthly_charges
            if deposit is not None and monthly_charges not in (None, Decimal("0"))
            else None
        )
        result = {
            "monthly_rent_hkd": _to_float(rent),
            "rent_per_sqft_hkd": _to_float(psf),
            "security_deposit_multiple": _to_float(deposit_multiple),
        }
        self.trace_calls.append(ToolCallTrace(
            tool_call_id=call_id,
            tool="calculate_financials",
            args={
                "area_sqft": area_sqft,
                "monthly_rent_hkd": monthly_rent_hkd,
                "rent_per_sqft_hkd": rent_per_sqft_hkd,
                "security_deposit_hkd": security_deposit_hkd,
                "management_fee_hkd": management_fee_hkd,
            },
            result_count=sum(1 for value in result.values() if value is not None),
            latency_ms=_elapsed_ms(started),
        ))
        return result

    def validate_candidate(
        self,
        *,
        field_path: str,
        evidence_quote: str,
        page: int | None = None,
        chunk_id: str | None = None,
    ) -> CandidateValidation:
        started = time.perf_counter()
        call_id = _call_id("validate_candidate")
        valid = field_path in FIELD_SPEC_BY_PATH
        reason = "" if valid else "Unknown field_path"
        if valid:
            quote = (evidence_quote or "").strip()
            if not quote:
                valid = False
                reason = "Missing evidence quote"
            else:
                haystacks: list[tuple[str | None, int, str]] = []
                if chunk_id and chunk_id in self.doc_index.chunk_by_id:
                    chunk = self.doc_index.chunk_by_id[chunk_id]
                    haystacks.append((chunk.chunk_id, chunk.page_start, chunk.text))
                elif page:
                    haystacks.append((None, page, self.doc_index.read_page(page)))
                else:
                    haystacks.extend((chunk.chunk_id, chunk.page_start, chunk.text) for chunk in self.doc_index.chunks)
                hit = next(((cid, pg) for cid, pg, text in haystacks if quote in text), None)
                if not hit:
                    valid = False
                    reason = "Evidence quote not found in current document"
                else:
                    chunk_id = hit[0] or chunk_id
                    page = hit[1]
        self.trace_calls.append(ToolCallTrace(
            tool_call_id=call_id,
            tool="validate_candidate",
            args={"field_path": field_path, "page": page, "chunk_id": chunk_id},
            result_count=1 if valid else 0,
            latency_ms=_elapsed_ms(started),
        ))
        return CandidateValidation(valid=valid, reason=reason, page=page, chunk_id=chunk_id)

    def regex_search(
        self,
        pattern: str,
        *,
        flags: list[str] | None = None,
        scope: str = "full_text",
        page_start: int | None = None,
        page_end: int | None = None,
        chunk_ids: list[str] | None = None,
        max_matches: int = 20,
        context_chars: int = 160,
    ) -> list[RegexMatch]:
        started = time.perf_counter()
        call_id = _call_id("regex_search")
        pattern = validate_regex_pattern(pattern)
        max_matches = clamp(max_matches, 1, MAX_REGEX_MATCHES)
        context_chars = clamp(context_chars, 20, MAX_CONTEXT_CHARS)
        re_flags = re.IGNORECASE if not flags or "ignorecase" in {f.lower() for f in flags} else 0
        regex = re.compile(pattern, re_flags)

        matches: list[RegexMatch] = []
        for chunk_id, text, page in self._iter_search_units(scope, page_start, page_end, chunk_ids):
            for match in regex.finditer(text):
                start, end = match.span()
                q_start = max(0, start - context_chars)
                q_end = min(len(text), end + context_chars)
                matches.append(RegexMatch(
                    page=page,
                    chunk_id=chunk_id,
                    match=match.group(0),
                    quote=text[q_start:q_end].strip(),
                    start=start,
                    end=end,
                ))
                if len(matches) >= max_matches:
                    self.trace_calls.append(ToolCallTrace(
                        tool_call_id=call_id,
                        tool="regex_search",
                        args={"pattern": pattern, "scope": scope, "max_matches": max_matches},
                        result_count=len(matches),
                        latency_ms=_elapsed_ms(started),
                    ))
                    return matches

        self.trace_calls.append(ToolCallTrace(
            tool_call_id=call_id,
            tool="regex_search",
            args={"pattern": pattern, "scope": scope, "max_matches": max_matches},
            result_count=len(matches),
            latency_ms=_elapsed_ms(started),
        ))
        return matches

    def _iter_search_units(
        self,
        scope: str,
        page_start: int | None,
        page_end: int | None,
        chunk_ids: list[str] | None,
    ):
        if chunk_ids:
            for chunk_id in chunk_ids:
                chunk = self.doc_index.chunk_by_id.get(chunk_id)
                if chunk:
                    yield chunk.chunk_id, chunk.text, chunk.page_start
            return

        if scope == "pages" or page_start or page_end:
            start = page_start or 1
            end = page_end or (self.doc_index.pages[-1].page_num if self.doc_index.pages else start)
            for page in self.doc_index.pages:
                if start <= page.page_num <= end:
                    yield None, page.text, page.page_num
            return

        for chunk in self.doc_index.chunks:
            yield chunk.chunk_id, chunk.text, chunk.page_start


def _call_id(tool: str) -> str:
    return f"{tool}_{uuid.uuid4().hex[:8]}"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _decimal(value: int | float | str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("HK$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _to_float(value: Decimal | None) -> float | None:
    return round(float(value), 4) if value is not None else None
