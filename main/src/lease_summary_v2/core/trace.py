"""Trace data for AI Enhanced extraction."""
from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


class ToolCallTrace(BaseModel):
    tool_call_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_count: int = 0
    latency_ms: int = 0


class ExtractionTrace(BaseModel):
    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    mode: str = "standard"
    file_name: str = ""
    file_size_bytes: int = 0
    parser_backend: str = ""
    ocr_used: bool = False
    ocr_avg_chars: float = 0.0
    pages_count: int = 0
    chunks_count: int = 0
    rule_candidates_count: int = 0
    semantic_candidates_count: int = 0
    agent_tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    final_decisions_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    latency_ms: int = 0


class TraceTimer:
    def __init__(self, trace: ExtractionTrace) -> None:
        self.trace = trace
        self.started = time.perf_counter()

    def finish(self) -> None:
        self.trace.latency_ms = int((time.perf_counter() - self.started) * 1000)
