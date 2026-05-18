"""Tests for provider-specific app settings state."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.state as state_module  # noqa: E402


def test_load_config_migrates_legacy_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "api_key": "moonshot-secret",
        "mode": "llm",
        "llm_provider": "moonshot",
        "llm_base_url": "",
        "llm_model": "kimi-k2.5",
    }))
    monkeypatch.setattr(state_module, "CONFIG_PATH", config_path)

    app_state = state_module.AppState()
    app_state.load_config()

    assert app_state.api_keys == {"moonshot": "moonshot-secret"}
    assert app_state.active_api_key() == "moonshot-secret"


def test_llm_enabled_uses_selected_provider_key():
    app_state = state_module.AppState(
        api_keys={"moonshot": "moon-key", "openai": "open-key"},
        mode="llm",
        llm_provider="openai",
        llm_model="gpt-5.4-mini",
    )

    assert app_state.llm_enabled() is True

    app_state.api_keys.pop("openai")

    assert app_state.llm_enabled() is False


def test_lmstudio_enabled_without_api_key_when_model_selected():
    app_state = state_module.AppState(
        api_keys={},
        mode="llm",
        llm_provider="lmstudio",
        llm_base_url="",
        llm_model="qwen3-vl-8b",
    )

    assert app_state.llm_enabled() is True


def test_load_config_does_not_migrate_legacy_key_to_local_provider(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "api_key": "moonshot-secret",
        "mode": "llm",
        "llm_provider": "lmstudio",
        "llm_base_url": "",
        "llm_model": "qwen3-vl-8b",
    }))
    monkeypatch.setattr(state_module, "CONFIG_PATH", config_path)

    app_state = state_module.AppState()
    app_state.load_config()

    assert app_state.api_keys == {}
    assert app_state.active_api_key() == ""
