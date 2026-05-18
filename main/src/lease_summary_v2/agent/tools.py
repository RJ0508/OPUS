"""Document-bound tools available to the AI Enhanced agent."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..core.document_index import DocumentIndex
from ..core.trace import ToolCallTrace
from .guardrails import MAX_CONTEXT_CHARS, MAX_PAGE_CHARS, MAX_REGEX_MATCHES, clamp, validate_regex_pattern


class RegexMatch(BaseModel):
    page: int
    chunk_id: str | None = None
    match: str
    quote: str
    start: int
    end: int


@dataclass
class AgentToolbox:
    doc_index: DocumentIndex
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

