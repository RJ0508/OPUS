"""Shared LLM client configuration for OpenAI-compatible providers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.request import Request, urlopen

_DEFAULT_PROVIDER = ""
_DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
_DEFAULT_LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
_LOCAL_BASE_PREFIXES = ("http://127.0.0.1", "http://localhost")
_LOCAL_PROVIDERS = {"ollama", "lmstudio"}
_PROVIDER_DEFAULTS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5.4-mini",
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-pro",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "model": "openai/gpt-oss-20b",
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "model": "accounts/fireworks/routers/kimi-k2p5-turbo",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-5.2",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.5",
    },
    "ollama": {
        "base_url": _DEFAULT_OLLAMA_BASE_URL,
        "model": "",
    },
    "lmstudio": {
        "base_url": _DEFAULT_LMSTUDIO_BASE_URL,
        "model": "",
    },
    "custom": {
        "base_url": "",
        "model": "",
    },
}

_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "google": "Google Gemini",
    "xai": "xAI",
    "groq": "Groq",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "openrouter": "OpenRouter",
    "deepseek": "DeepSeek",
    "moonshot": "Moonshot",
    "ollama": "Ollama",
    "lmstudio": "LM Studio (Local)",
    "custom": "Custom OpenAI-compatible",
}

_PROVIDER_KEY_PLACEHOLDERS = {
    "openai": "sk-...",
    "google": "AIza...",
    "xai": "xai-...",
    "groq": "gsk_...",
    "together": "together-...",
    "fireworks": "fw_...",
    "openrouter": "sk-or-...",
    "deepseek": "sk-...",
    "moonshot": "sk-...",
    "custom": "sk-...",
}


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str
    base_url: str
    model: str


def load_llm_settings(
    default_base_url: str,
    default_model: str,
    *,
    default_provider: str = _DEFAULT_PROVIDER,
) -> LLMSettings | None:
    """Resolve provider settings with LLM_* taking precedence over legacy names."""
    provider = (
        os.environ.get("LLM_PROVIDER")
        or os.environ.get("MOONSHOT_PROVIDER")
        or default_provider
    ).strip().lower()
    provider_defaults = _PROVIDER_DEFAULTS.get(provider)
    resolved_default_base_url = default_base_url
    resolved_default_model = default_model
    if provider_defaults is not None:
        if provider_defaults["base_url"] or provider == "ollama":
            resolved_default_base_url = provider_defaults["base_url"] or default_base_url
        else:
            resolved_default_base_url = provider_defaults["base_url"]
        if provider_defaults["model"] or provider == "ollama":
            resolved_default_model = provider_defaults["model"] or default_model
        else:
            resolved_default_model = provider_defaults["model"]
    base_url = (
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("MOONSHOT_BASE_URL")
        or ""
    ).strip()
    model = (
        os.environ.get("LLM_MODEL")
        or os.environ.get("MOONSHOT_MODEL")
        or resolved_default_model
    ).strip()
    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("MOONSHOT_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()

    if provider == "ollama":
        base_url = base_url or _DEFAULT_OLLAMA_BASE_URL
        api_key = api_key or "ollama"
    elif provider == "lmstudio":
        base_url = base_url or _DEFAULT_LMSTUDIO_BASE_URL
        api_key = api_key or "local"
    elif not base_url:
        base_url = resolved_default_base_url

    if not api_key:
        if _looks_local(base_url):
            api_key = "local"
        else:
            return None

    if not model:
        return None

    return LLMSettings(
        provider=provider or default_provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


def build_openai_client(
    default_base_url: str,
    default_model: str,
    *,
    default_provider: str = _DEFAULT_PROVIDER,
):
    """Return an OpenAI client plus resolved settings when configured."""
    try:
        from openai import OpenAI
    except ImportError:
        return None, None

    settings = load_llm_settings(
        default_base_url,
        default_model,
        default_provider=default_provider,
    )
    if settings is None:
        return None, None

    return OpenAI(api_key=settings.api_key, base_url=settings.base_url), settings


def get_provider_default_base_url(provider: str, fallback: str = "") -> str:
    defaults = _PROVIDER_DEFAULTS.get((provider or "").strip().lower())
    if defaults is None:
        return fallback
    return defaults["base_url"] or fallback


def get_provider_default_model(provider: str, fallback: str = "") -> str:
    defaults = _PROVIDER_DEFAULTS.get((provider or "").strip().lower())
    if defaults is None:
        return fallback
    return defaults["model"] or fallback


def get_provider_catalog() -> dict[str, dict[str, object]]:
    """Return frontend-safe provider defaults from the backend source of truth."""
    catalog: dict[str, dict[str, object]] = {}
    for provider, defaults in _PROVIDER_DEFAULTS.items():
        catalog[provider] = {
            "label": _PROVIDER_LABELS.get(provider, provider),
            "baseUrl": defaults["base_url"],
            "requiresKey": provider not in _LOCAL_PROVIDERS,
            "keyPlaceholder": _PROVIDER_KEY_PLACEHOLDERS.get(provider, ""),
            "defaultModel": defaults["model"],
        }
    for provider in _LOCAL_PROVIDERS:
        if provider in catalog:
            catalog[provider]["requiresKey"] = False
    return catalog


def list_available_models(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    timeout: float = 10.0,
) -> list[str]:
    """List model IDs from an OpenAI-compatible endpoint when possible."""
    provider = (provider or _DEFAULT_PROVIDER).strip().lower()
    base_url = (base_url or "").strip()
    api_key = (api_key or "").strip()

    if provider == "ollama":
        base_url = base_url or _DEFAULT_OLLAMA_BASE_URL
        api_key = api_key or "ollama"
    elif provider == "lmstudio":
        base_url = base_url or _DEFAULT_LMSTUDIO_BASE_URL
        api_key = api_key or "local"
    elif _looks_local(base_url):
        api_key = api_key or "local"

    if not base_url:
        return []

    if api_key:
        try:
            model_ids = _request_models_via_openai(base_url, api_key)
            if model_ids:
                return _dedupe_model_ids(model_ids)
        except Exception:
            pass

    try:
        payload = _request_models_via_http(base_url, api_key, timeout=timeout)
    except Exception:
        return []

    return _extract_model_ids(payload)


def _looks_local(base_url: str) -> bool:
    return base_url.startswith(_LOCAL_BASE_PREFIXES)


def is_local_base_url(base_url: str) -> bool:
    """Return True for localhost OpenAI-compatible endpoints."""
    return _looks_local((base_url or "").strip().lower())


def is_local_provider(provider: str, base_url: str = "") -> bool:
    """Return True when settings target a local model runtime."""
    provider_id = (provider or "").strip().lower()
    return provider_id in _LOCAL_PROVIDERS or is_local_base_url(base_url)


def _request_models_via_openai(base_url: str, api_key: str) -> list[str]:
    from openai import OpenAI

    response = OpenAI(api_key=api_key, base_url=base_url).models.list()
    return _extract_model_ids({"data": getattr(response, "data", [])})


def _request_models_via_http(base_url: str, api_key: str, *, timeout: float) -> object:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(f"{base_url.rstrip('/')}/models", headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_model_ids(payload: object) -> list[str]:
    if isinstance(payload, dict):
        candidates = payload.get("data")
        if not isinstance(candidates, list):
            candidates = payload.get("models")
    elif isinstance(payload, list):
        candidates = payload
    else:
        candidates = None

    if not isinstance(candidates, list):
        return []

    return _dedupe_model_ids(
        _coerce_model_id(item)
        for item in candidates
    )


def _coerce_model_id(item: object) -> str | None:
    if isinstance(item, str):
        value = item
    elif isinstance(item, dict):
        value = item.get("id") or item.get("name")
    else:
        value = getattr(item, "id", None) or getattr(item, "name", None)

    if not isinstance(value, str):
        return None

    value = value.strip()
    return value or None


def _dedupe_model_ids(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_chat_create(client, **kwargs):
    """Call chat.completions.create with automatic parameter adaptation.

    Some models (e.g. OpenAI o1/o3/gpt-4.5) reject ``max_tokens`` and
    require ``max_completion_tokens`` instead.  This helper catches that
    error and retries with the corrected parameter, so callers never
    need to hard-code provider-specific parameter names.
    """
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as exc:
        text = str(exc).lower()
        # max_tokens -> max_completion_tokens
        if "max_tokens" in text and ("unsupported" in text or "not supported" in text):
            retry_kwargs = dict(kwargs)
            if "max_tokens" in retry_kwargs:
                retry_kwargs["max_completion_tokens"] = retry_kwargs.pop("max_tokens")
                try:
                    return client.chat.completions.create(**retry_kwargs)
                except Exception as exc2:
                    text2 = str(exc2).lower()
                    # Some reasoning models also reject temperature
                    if "temperature" in text2 and ("unsupported" in text2 or "not supported" in text2):
                        retry_kwargs.pop("temperature", None)
                        return client.chat.completions.create(**retry_kwargs)
                    raise
        raise
