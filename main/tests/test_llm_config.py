"""Tests for shared LLM provider configuration."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lease_summary import llm_config  # noqa: E402
from lease_summary.llm_config import load_llm_settings  # noqa: E402


def test_ollama_uses_local_defaults_without_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = load_llm_settings("https://api.example.com/v1", "gemma4:e4b")

    assert settings is not None
    assert settings.provider == "ollama"
    assert settings.api_key == "ollama"
    assert settings.base_url == "http://127.0.0.1:11434/v1"
    assert settings.model == "gemma4:e4b"


def test_lmstudio_uses_local_defaults_without_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LLM_MODEL", "qwen3-vl-8b")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = load_llm_settings("https://api.example.com/v1", "fallback-model")

    assert settings is not None
    assert settings.provider == "lmstudio"
    assert settings.api_key == "local"
    assert settings.base_url == "http://127.0.0.1:1234/v1"
    assert settings.model == "qwen3-vl-8b"


def test_local_custom_base_url_uses_dummy_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9000/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = load_llm_settings("https://api.example.com/v1", "fallback-model")

    assert settings is not None
    assert settings.api_key == "local"
    assert settings.base_url == "http://localhost:9000/v1"
    assert settings.model == "test-model"


def test_remote_provider_requires_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = load_llm_settings("https://api.example.com/v1", "fallback-model")

    assert settings is None


def test_generic_env_overrides_legacy_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("LLM_BASE_URL", "https://override.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "override-model")
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    monkeypatch.setenv("MOONSHOT_BASE_URL", "https://legacy.example.com/v1")
    monkeypatch.setenv("MOONSHOT_MODEL", "legacy-model")
    monkeypatch.setenv("MOONSHOT_API_KEY", "legacy-key")

    settings = load_llm_settings("https://default.example.com/v1", "default-model")

    assert settings is not None
    assert settings.base_url == "https://override.example.com/v1"
    assert settings.model == "override-model"
    assert settings.api_key == "generic-key"


def test_provider_specific_defaults_apply_for_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MOONSHOT_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("MOONSHOT_MODEL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    settings = load_llm_settings("https://legacy.example.com/v1", "legacy-model")

    assert settings is not None
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.model == "gpt-5.4-mini"
    assert settings.api_key == "test-key"


def test_moonshot_default_base_url_matches_public_platform(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "moonshot")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MOONSHOT_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    settings = load_llm_settings("https://legacy.example.com/v1", "legacy-model")

    assert settings is not None
    assert settings.base_url == "https://api.moonshot.cn/v1"
    assert settings.model == "kimi-k2.6"


def test_local_provider_helper_detects_localhost_endpoint():
    assert llm_config.is_local_provider("custom", "http://localhost:9000/v1")
    assert llm_config.is_local_provider("lmstudio", "")
    assert not llm_config.is_local_provider("openai", "https://api.openai.com/v1")


def test_extract_message_text_accepts_common_content_shapes():
    message = SimpleNamespace(content=[
        {"type": "reasoning", "content": "hidden reasoning"},
        {"type": "text", "text": '{"ok":true}'},
    ])

    assert llm_config.extract_message_text(message) == '{"ok":true}'
    assert llm_config.extract_message_text({"content": [{"text": "hello"}]}) == "hello"


def test_tool_agent_auto_mode_is_capability_based(monkeypatch):
    monkeypatch.delenv("LLM_TOOL_AGENT", raising=False)
    monkeypatch.delenv("LLM_TOOL_AGENT_ALLOW_MODELS", raising=False)
    monkeypatch.delenv("LLM_TOOL_AGENT_DENY_MODELS", raising=False)

    assert llm_config.should_use_llm_tool_agent(provider="openai", model="gpt-5.4-mini")
    assert llm_config.should_use_llm_tool_agent(provider="openrouter", model="openai/gpt-5.2")
    assert not llm_config.should_use_llm_tool_agent(provider="moonshot", model="kimi-k2.6")
    assert not llm_config.should_use_llm_tool_agent(provider="custom", model="unknown-model")

    monkeypatch.setenv("LLM_TOOL_AGENT_ALLOW_MODELS", "unknown-model")
    assert llm_config.should_use_llm_tool_agent(provider="custom", model="unknown-model")

    monkeypatch.setenv("LLM_TOOL_AGENT", "disabled")
    assert not llm_config.should_use_llm_tool_agent(provider="openai", model="gpt-5.4-mini")


def test_list_available_models_uses_ollama_defaults(monkeypatch):
    captured: dict[str, object] = {}

    def fake_openai(base_url: str, api_key: str) -> list[str]:
        raise RuntimeError("skip openai")

    def fake_http(base_url: str, api_key: str, *, timeout: float) -> object:
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        captured["timeout"] = timeout
        return {"data": [{"id": "gemma4:e4b"}]}

    monkeypatch.setattr(llm_config, "_request_models_via_openai", fake_openai)
    monkeypatch.setattr(llm_config, "_request_models_via_http", fake_http)

    models = llm_config.list_available_models(
        provider="ollama",
        api_key="",
        base_url="",
    )

    assert models == ["gemma4:e4b"]
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["api_key"] == "ollama"
    assert captured["timeout"] == 10.0


def test_list_available_models_falls_back_to_http_and_dedupes(monkeypatch):
    def fake_openai(base_url: str, api_key: str) -> list[str]:
        raise RuntimeError("boom")

    def fake_http(base_url: str, api_key: str, *, timeout: float) -> object:
        assert base_url == "https://api.example.com/v1"
        assert api_key == "test-key"
        return {"data": [{"id": "model-a"}, {"id": "model-b"}, {"id": "model-a"}]}

    monkeypatch.setattr(llm_config, "_request_models_via_openai", fake_openai)
    monkeypatch.setattr(llm_config, "_request_models_via_http", fake_http)

    models = llm_config.list_available_models(
        provider="custom",
        api_key="test-key",
        base_url="https://api.example.com/v1",
    )

    assert models == ["model-a", "model-b"]


def test_safe_chat_create_retries_temperature_one_models():
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                raise RuntimeError("invalid temperature: only 1 is allowed for this model")
            return SimpleNamespace(ok=True)

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    response = llm_config._safe_chat_create(
        client,
        model="kimi-k2.6",
        messages=[],
        temperature=0,
        max_tokens=10,
    )

    assert response.ok is True
    assert calls[0]["timeout"] == 45.0
    assert "temperature" not in calls[0]
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert len(calls) == 1


def test_safe_chat_create_adapts_common_provider_parameter_rejections():
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("max_tokens is not supported by this model")
            if len(calls) == 2:
                raise RuntimeError("temperature is unsupported")
            if len(calls) == 3:
                raise RuntimeError("json_schema is not supported")
            if len(calls) == 4:
                raise RuntimeError("tools are not supported")
            return SimpleNamespace(ok=True)

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    response = llm_config._safe_chat_create(
        client,
        model="provider-model",
        messages=[],
        temperature=0,
        max_tokens=10,
        response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        tools=[{"type": "function", "function": {"name": "read_page"}}],
        tool_choice="auto",
    )

    assert response.ok is True
    assert "max_tokens" in calls[0]
    assert calls[1]["max_completion_tokens"] == 10
    assert "temperature" not in calls[2]
    assert calls[3]["response_format"] == {"type": "json_object"}
    assert "tools" not in calls[4]
    assert "tool_choice" not in calls[4]


def test_safe_chat_create_uses_configurable_default_timeout(monkeypatch):
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(ok=True)

    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "12")
    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    response = llm_config._safe_chat_create(client, model="provider-model", messages=[])

    assert response.ok is True
    assert calls[0]["timeout"] == 12.0


def test_safe_chat_create_preserves_explicit_timeout():
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(ok=True)

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    response = llm_config._safe_chat_create(
        client,
        model="provider-model",
        messages=[],
        timeout=3,
    )

    assert response.ok is True
    assert calls[0]["timeout"] == 3


def test_safe_chat_create_removes_rejected_extra_body_for_compatible_providers():
    calls: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("extra_body.thinking is not supported")
            return SimpleNamespace(ok=True)

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    response = llm_config._safe_chat_create(
        client,
        model="kimi-k2.6",
        messages=[],
        temperature=0,
    )

    assert response.ok is True
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in calls[1]
