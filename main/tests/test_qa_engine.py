"""Tests for Q&A prompt context sizing and page selection."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lease_summary.llm_config import LLMSettings  # noqa: E402
from lease_summary_v2.parsers.pdf_text import DocumentText, PageText  # noqa: E402
from lease_summary_v2.qa import engine  # noqa: E402


def _local_settings() -> LLMSettings:
    return LLMSettings(
        provider="lmstudio",
        api_key="local",
        base_url="http://127.0.0.1:1234/v1",
        model="qwen/qwen3-vl-8b",
    )


def test_local_qa_context_omits_raw_pages_for_smalltalk(monkeypatch):
    monkeypatch.delenv("LLM_QA_CONTEXT_CHARS", raising=False)
    doc = DocumentText(
        pages=[
            PageText(page_num=0, text="=== EXTRACTED LEASE SUMMARY ===\nTenant: Example"),
            PageText(page_num=1, text="Monthly rent is HKD 100,000. " * 500),
        ]
    )

    context = engine._format_document(doc, "hello", _local_settings())

    assert "EXTRACTED LEASE SUMMARY" in context
    assert "[Page 1]" not in context
    assert len(context) < 4_000


def test_local_qa_context_selects_relevant_pages_and_respects_budget(monkeypatch):
    monkeypatch.setenv("LLM_QA_CONTEXT_CHARS", "6000")
    pages = [
        PageText(page_num=0, text="=== EXTRACTED LEASE SUMMARY ===\nMonthly Rent: 100,000"),
    ]
    for page_num in range(1, 12):
        text = f"Page {page_num} general lease text. " * 180
        if page_num == 8:
            text = "Monthly rent is HKD 100,000 and rent free period is nil. " * 180
        pages.append(PageText(page_num=page_num, text=text))

    context = engine._format_document(
        DocumentText(pages=pages),
        "What is the monthly rent?",
        _local_settings(),
    )

    assert "[Page 8]" in context
    assert "[Page 11]" not in context
    assert len(context) <= 6_050


def test_local_qa_context_uses_lmstudio_loaded_context_length(monkeypatch):
    monkeypatch.delenv("LLM_QA_CONTEXT_CHARS", raising=False)
    monkeypatch.delenv("LLM_LOCAL_QA_CONTEXT_CHARS", raising=False)
    body = {
        "models": [
            {
                "key": "qwen/qwen3-vl-8b",
                "loaded_instances": [
                    {
                        "id": "qwen/qwen3-vl-8b",
                        "config": {"context_length": 262144},
                    }
                ],
                "max_context_length": 262144,
            }
        ]
    }

    monkeypatch.setattr(
        engine,
        "_fetch_lmstudio_context_tokens",
        lambda settings: engine._extract_context_tokens(body, settings.model),
    )
    pages = [
        PageText(page_num=0, text="=== EXTRACTED LEASE SUMMARY ===\nTenant: Example"),
    ]
    for page_num in range(1, 36):
        pages.append(PageText(page_num=page_num, text=f"Rent clause page {page_num}. " * 100))

    context = engine._format_document(
        DocumentText(pages=pages),
        "Summarise the key terms",
        _local_settings(),
    )

    assert "[Page 35]" in context
    assert len(context) > 50_000
    assert len(context) <= 120_050
