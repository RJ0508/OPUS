"""Tests for app settings save behavior."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.main as main_module  # noqa: E402


def test_save_settings_updates_provider_key_and_defers_qa_refresh(monkeypatch):
    app_state = main_module.state
    original = {
        "api_keys": dict(app_state.api_keys),
        "mode": app_state.mode,
        "llm_provider": app_state.llm_provider,
        "llm_base_url": app_state.llm_base_url,
        "llm_model": app_state.llm_model,
        "qa_engine": app_state.qa_engine,
    }
    calls = {"configure": 0, "refresh": 0, "save": 0}

    monkeypatch.setattr(
        main_module,
        "_configure_llm_environment",
        lambda: calls.__setitem__("configure", calls["configure"] + 1),
    )
    monkeypatch.setattr(
        main_module,
        "_refresh_qa_engine",
        lambda **kwargs: calls.__setitem__("refresh", calls["refresh"] + 1),
    )
    monkeypatch.setattr(
        app_state,
        "save_config",
        lambda: calls.__setitem__("save", calls["save"] + 1),
    )

    try:
        payload = main_module.SettingsPayload(
            api_key="openai-secret",
            api_keys={"moonshot": "moonshot-secret"},
            mode="llm",
            llm_provider="openai",
            llm_base_url="https://api.openai.com/v1",
            llm_model="gpt-5.4-mini",
        )

        response = main_module.save_settings(payload)

        assert response == {"ok": True}
        assert app_state.api_keys == {
            "moonshot": "moonshot-secret",
            "openai": "openai-secret",
        }
        assert app_state.llm_provider == "openai"
        assert app_state.qa_engine is None
        assert calls == {"configure": 1, "refresh": 0, "save": 1}
    finally:
        app_state.api_keys = original["api_keys"]
        app_state.mode = original["mode"]
        app_state.llm_provider = original["llm_provider"]
        app_state.llm_base_url = original["llm_base_url"]
        app_state.llm_model = original["llm_model"]
        app_state.qa_engine = original["qa_engine"]
