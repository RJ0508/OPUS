"""Global application state — single user, single lease session."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lease_summary.llm_config import (
    get_provider_default_base_url,
    get_provider_default_model,
    is_local_base_url,
)

CONFIG_PATH = Path.home() / ".opus_lease_summary" / "config.json"


def normalise_api_keys(values: object) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}

    result: dict[str, str] = {}
    for provider, api_key in values.items():
        if not isinstance(provider, str):
            continue
        provider_id = provider.strip().lower()
        if not provider_id:
            continue
        if api_key is None:
            continue
        value = api_key.strip() if isinstance(api_key, str) else str(api_key).strip()
        if value:
            result[provider_id] = value
    return result


@dataclass
class AppState:
    # Current lease session
    pdf_path: Path | None = None
    excel_path: Path | None = None
    summary: object = None
    qa_engine: object = None
    field_overrides: dict = field(default_factory=dict)  # user edits: "section.key" → value
    original_filename: str = ""  # Original upload filename (e.g., for converted Word docs)
    ocr_word_data: dict | None = None  # {page_num: [(x0,y0,x1,y1,word), ...]} for OCR PDFs

    # Settings (persisted)
    api_keys: dict[str, str] = field(default_factory=dict)
    mode: str = "regex"  # "regex" | "llm"
    llm_provider: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    def load_config(self) -> None:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                self.mode = data.get("mode", "regex")
                self.llm_provider = data.get("llm_provider", "")
                self.llm_base_url = data.get("llm_base_url", "")
                self.llm_model = data.get("llm_model", "")
                self.api_keys = normalise_api_keys(data.get("api_keys", {}))
                legacy_api_key = str(data.get("api_key", "") or "").strip()
                base_url = (
                    self.llm_base_url
                    or get_provider_default_base_url(self.llm_provider)
                    or ""
                ).strip().lower()
                provider_needs_key = (
                    self.llm_provider not in {"ollama", "lmstudio"}
                    and not is_local_base_url(base_url)
                )
                if legacy_api_key and provider_needs_key and self.llm_provider not in self.api_keys:
                    self.api_keys[self.llm_provider] = legacy_api_key
            except Exception:
                pass

    def save_config(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({
            "api_key": self.active_api_key(),
            "api_keys": self.api_keys,
            "mode": self.mode,
            "llm_provider": self.llm_provider,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
        }, indent=2))

    def active_api_key(self, provider: str | None = None) -> str:
        provider_id = (provider or self.llm_provider or "").strip().lower()
        return self.api_keys.get(provider_id, "").strip()

    def llm_enabled(self) -> bool:
        provider = (self.llm_provider or "").strip().lower()
        base_url = (self.llm_base_url or get_provider_default_base_url(provider)).strip().lower()
        model = (self.llm_model or get_provider_default_model(provider)).strip()
        api_key = self.active_api_key(provider)
        if provider in {"custom", "lmstudio"} and (not base_url or not model):
            return False
        if provider == "ollama":
            return bool(model)
        if is_local_base_url(base_url):
            return bool(model)
        return bool(model and api_key)

    def clear_session(self) -> None:
        """Reset lease-specific state between uploads."""
        self.pdf_path = None
        self.excel_path = None
        self.summary = None
        self.qa_engine = None
        self.field_overrides = {}
        self.original_filename = ""
        self.ocr_word_data = None


state = AppState()
state.load_config()
