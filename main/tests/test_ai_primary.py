"""Tests for AI primary provider compatibility."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lease_summary.models import LeaseSummary as LeaseSummaryV1  # noqa: E402
from lease_summary.models import ExtractionResult as ExtractionResultV1  # noqa: E402
from lease_summary.extractors import ai_primary as v1_ai_primary  # noqa: E402
from lease_summary_v2.models import LeaseSummary as LeaseSummaryV2  # noqa: E402
from lease_summary_v2.models import ExtractionResult as ExtractionResultV2  # noqa: E402
from lease_summary_v2.extractors import ai_primary as v2_ai_primary  # noqa: E402


class _Message:
    content = '{"tenant_name": "Example Tenant"}'


class _Choice:
    message = _Message()


class _Response:
    choices = [_Choice()]


class _Completions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "response_format" in kwargs:
            raise RuntimeError("'response_format.type' must be 'json_schema' or 'text'")
        return _Response()


class _Chat:
    def __init__(self) -> None:
        self.completions = _Completions()


class _Client:
    def __init__(self) -> None:
        self.chat = _Chat()


def test_v1_chat_completion_falls_back_when_json_object_is_unsupported():
    client = _Client()

    response = v1_ai_primary._create_chat_completion(client, {"model": "local", "messages": []})

    assert response is not None
    assert len(client.chat.completions.calls) == 2
    assert "response_format" in client.chat.completions.calls[0]
    assert "response_format" not in client.chat.completions.calls[1]


def test_v2_chat_completion_falls_back_when_json_object_is_unsupported():
    client = _Client()

    response = v2_ai_primary._create_chat_completion(client, {"model": "local", "messages": []})

    assert response is not None
    assert len(client.chat.completions.calls) == 2
    assert "response_format" in client.chat.completions.calls[0]
    assert "response_format" not in client.chat.completions.calls[1]


def test_v1_local_chunked_apply_preserves_medium_confidence_values():
    summary = LeaseSummaryV1()
    summary.parties.landlord_name = ExtractionResultV1(value="Regex Landlord", confidence=0.85)
    doc = SimpleNamespace(pages=[])

    v1_ai_primary._apply(
        summary,
        doc,
        {"landlord_name": "LLM Landlord", "tenant_name": "LLM Tenant"},
        override_low_confidence=False,
        confidence=0.72,
    )

    assert summary.parties.landlord_name.value == "Regex Landlord"
    assert summary.parties.tenant_name.value == "LLM Tenant"
    assert summary.parties.tenant_name.confidence == 0.72


def test_v2_local_chunked_apply_preserves_medium_confidence_values():
    summary = LeaseSummaryV2()
    summary.parties.landlord_name = ExtractionResultV2(value="Regex Landlord", confidence=0.85)
    doc = SimpleNamespace(pages=[])

    v2_ai_primary._apply(
        summary,
        doc,
        {"landlord_name": "LLM Landlord", "tenant_name": "LLM Tenant"},
        override_low_confidence=False,
        confidence=0.72,
    )

    assert summary.parties.landlord_name.value == "Regex Landlord"
    assert summary.parties.tenant_name.value == "LLM Tenant"
    assert summary.parties.tenant_name.confidence == 0.72


def test_v2_local_chunked_apply_skips_high_risk_signing_date():
    summary = LeaseSummaryV2()
    doc = SimpleNamespace(pages=[])

    v2_ai_primary._apply(
        summary,
        doc,
        {"lease_signing_date": "2023-10-12", "security_deposit_multiple": 3},
        override_low_confidence=False,
        confidence=0.72,
    )

    assert summary.term.lease_signing_date.value is None
    assert summary.financials.security_deposit_multiple.value == 3


def test_v2_extracts_message_content_from_lmstudio_native_response():
    body = {
        "output": [
            {"type": "reasoning", "content": "thinking"},
            {"type": "message", "content": '{"tenant_name": "JSG Limited"}'},
        ]
    }

    assert (
        v2_ai_primary._extract_lmstudio_native_content(body)
        == '{"tenant_name": "JSG Limited"}'
    )


def test_v2_build_client_uses_dummy_key_for_local_endpoint(monkeypatch):
    captured: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3-vl-8b")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client, model, base_url = v2_ai_primary._build_client()

    assert client is not None
    assert model == "qwen3-vl-8b"
    assert base_url == "http://127.0.0.1:1234/v1"
    assert captured == {
        "api_key": "local",
        "base_url": "http://127.0.0.1:1234/v1",
    }


def test_v1_extracts_message_content_from_lmstudio_native_response():
    body = {
        "output": [
            {"type": "reasoning", "content": "thinking"},
            {"type": "message", "content": '{"tenant_name": "JSG Limited"}'},
        ]
    }

    assert (
        v1_ai_primary._extract_lmstudio_native_content(body)
        == '{"tenant_name": "JSG Limited"}'
    )


def test_v1_build_client_uses_dummy_key_for_local_endpoint(monkeypatch):
    captured: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3-vl-8b")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client, model, base_url = v1_ai_primary._build_client()

    assert client is not None
    assert model == "qwen3-vl-8b"
    assert base_url == "http://localhost:1234/v1"
    assert captured == {
        "api_key": "local",
        "base_url": "http://localhost:1234/v1",
    }
