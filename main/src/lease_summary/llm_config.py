"""Shared LLM client configuration for OpenAI-compatible providers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.request import Request, urlopen

_DEFAULT_PROVIDER = ""
_DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
_DEFAULT_LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
_DEFAULT_CHAT_REQUEST_TIMEOUT_SECONDS = 45.0
_LOCAL_BASE_PREFIXES = ("http://127.0.0.1", "http://localhost")
_LOCAL_PROVIDERS = {"ollama", "lmstudio"}
_TRUE_VALUES = {"1", "true", "on", "enabled", "always", "yes"}
_FALSE_VALUES = {"0", "false", "off", "disabled", "never", "no"}
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
        "model": "kimi-k2.6",
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


def strict_function_tool(
    name: str,
    description: str,
    parameters: dict[str, object],
) -> dict[str, object]:
    """Build an OpenAI-compatible strict function tool definition."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
            "strict": True,
        },
    }


def structured_response_format(
    name: str,
    schema: dict[str, object],
    *,
    strict: bool = True,
) -> dict[str, object]:
    """Build a strict json_schema response_format payload."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": strict,
        },
    }


def extract_message_text(message_or_content) -> str:
    """Return plain text from common OpenAI-compatible message shapes."""
    if message_or_content is None:
        return ""
    if isinstance(message_or_content, str):
        return message_or_content
    if isinstance(message_or_content, list):
        parts: list[str] = []
        for item in message_or_content:
            text = extract_message_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(message_or_content, dict):
        part_type = str(message_or_content.get("type") or "").lower()
        if part_type in {"reasoning", "thinking"}:
            return ""
        for key in ("text", "content", "output_text"):
            value = message_or_content.get(key)
            text = extract_message_text(value)
            if text:
                return text
        if "json" in message_or_content:
            try:
                return json.dumps(message_or_content["json"], ensure_ascii=False)
            except TypeError:
                return str(message_or_content["json"])
        return ""

    content = getattr(message_or_content, "content", None)
    text = extract_message_text(content)
    if text:
        return text
    for attr in ("text", "output_text"):
        value = getattr(message_or_content, attr, None)
        text = extract_message_text(value)
        if text:
            return text
    return ""


def should_use_llm_tool_agent(*, provider: str | None = None, model: str | None = None) -> bool:
    """Return whether the optional LLM tool finalizer should run in auto mode.

    AI Enhanced does not depend on this finalizer. Unknown or partially
    compatible models still get full-document semantic scan plus deterministic
    evidence verification.
    """
    mode = os.environ.get("LLM_TOOL_AGENT", "auto").strip().lower()
    if mode in _FALSE_VALUES:
        return False
    if mode in _TRUE_VALUES:
        return True

    provider_id = (provider or os.environ.get("LLM_PROVIDER") or "").strip().lower()
    normalized_model = (model or os.environ.get("LLM_MODEL") or "").strip().lower().replace("_", "-")
    if not normalized_model:
        return False

    denied = _csv_contains(os.environ.get("LLM_TOOL_AGENT_DENY_MODELS"), normalized_model, provider_id)
    if denied:
        return False
    allowed = _csv_contains(os.environ.get("LLM_TOOL_AGENT_ALLOW_MODELS"), normalized_model, provider_id)
    if allowed:
        return True

    if provider_id == "openai":
        return True
    if provider_id == "openrouter" and normalized_model.startswith("openai/"):
        return True

    reliable_prefixes = (
        "gpt-",
        "chatgpt-",
        "openai/gpt-",
        "openai/chatgpt-",
        "o1",
        "o3",
        "o4",
    )
    return normalized_model.startswith(reliable_prefixes)


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


def _csv_contains(raw: str | None, model: str, provider: str) -> bool:
    if not raw:
        return False
    values = [item.strip().lower().replace("_", "-") for item in raw.split(",") if item.strip()]
    if not values:
        return False
    haystacks = [model, provider, f"{provider}:{model}" if provider and model else ""]
    return any(value and any(value in haystack for haystack in haystacks if haystack) for value in values)


def _safe_chat_create(client, **kwargs):
    """Call chat.completions.create with automatic parameter adaptation.

    OpenAI-compatible providers differ on small but important request
    parameters. This helper keeps callers provider-agnostic by retrying with
    conservative parameter changes when a model rejects otherwise valid input.
    """
    current_kwargs = _prepare_chat_kwargs(dict(kwargs))
    seen_signatures: set[str] = set()
    last_exc: Exception | None = None

    for _ in range(8):
        signature = _kwargs_signature(current_kwargs)
        seen_signatures.add(signature)
        try:
            return client.chat.completions.create(**current_kwargs)
        except Exception as exc:
            last_exc = exc
            next_kwargs = _adapt_chat_kwargs_for_error(current_kwargs, str(exc))
            if next_kwargs is None:
                raise
            next_signature = _kwargs_signature(next_kwargs)
            if next_signature in seen_signatures:
                raise
            current_kwargs = next_kwargs

    if last_exc is not None:
        raise last_exc
    return client.chat.completions.create(**kwargs)


def _adapt_chat_kwargs_for_error(kwargs: dict, error_text: str) -> dict | None:
    text = (error_text or "").lower()

    if _temperature_must_be_one(text) and kwargs.get("temperature") != 1:
        retry_kwargs = dict(kwargs)
        retry_kwargs["temperature"] = 1
        return retry_kwargs

    if _parameter_rejected(text, "temperature") and "temperature" in kwargs:
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("temperature", None)
        return retry_kwargs

    if _parameter_rejected(text, "max_tokens") and "max_tokens" in kwargs:
        retry_kwargs = dict(kwargs)
        retry_kwargs["max_completion_tokens"] = retry_kwargs.pop("max_tokens")
        return retry_kwargs

    if _parameter_rejected(text, "max_completion_tokens") and "max_completion_tokens" in kwargs:
        retry_kwargs = dict(kwargs)
        retry_kwargs["max_tokens"] = retry_kwargs.pop("max_completion_tokens")
        return retry_kwargs

    if _response_format_rejected(text) and "response_format" in kwargs:
        retry_kwargs = dict(kwargs)
        response_format = retry_kwargs.get("response_format")
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            retry_kwargs["response_format"] = {"type": "json_object"}
        else:
            retry_kwargs.pop("response_format", None)
        return retry_kwargs

    if _tools_rejected(text) and ("tools" in kwargs or "tool_choice" in kwargs):
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("tools", None)
        retry_kwargs.pop("tool_choice", None)
        retry_kwargs.pop("parallel_tool_calls", None)
        return retry_kwargs

    if _extra_body_rejected(text) and "extra_body" in kwargs:
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("extra_body", None)
        return retry_kwargs

    if _parameter_rejected(text, "timeout") and "timeout" in kwargs:
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("timeout", None)
        return retry_kwargs

    return None


def _prepare_chat_kwargs(kwargs: dict) -> dict:
    kwargs = _with_default_chat_timeout(kwargs)
    return _with_model_specific_chat_options(kwargs)


def _with_default_chat_timeout(kwargs: dict) -> dict:
    if "timeout" not in kwargs:
        kwargs["timeout"] = _chat_request_timeout_seconds()
    return kwargs


def _with_model_specific_chat_options(kwargs: dict) -> dict:
    model = str(kwargs.get("model") or "").strip().lower()
    if not model:
        return kwargs

    if _is_kimi_configurable_thinking_model(model):
        thinking_mode = os.environ.get("LLM_THINKING", "disabled").strip().lower()
        if thinking_mode not in {"enabled", "default"}:
            extra_body = dict(kwargs.get("extra_body") or {})
            thinking = dict(extra_body.get("thinking") or {})
            thinking.setdefault("type", "disabled")
            extra_body["thinking"] = thinking
            kwargs["extra_body"] = extra_body
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
        elif thinking_mode == "enabled":
            kwargs["temperature"] = 1.0

    elif _is_kimi_forced_thinking_model(model):
        kwargs["temperature"] = 1.0

    return kwargs


def _chat_request_timeout_seconds() -> float:
    raw = os.environ.get("LLM_REQUEST_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_CHAT_REQUEST_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_CHAT_REQUEST_TIMEOUT_SECONDS
    return max(5.0, min(value, 300.0))


def _kwargs_signature(kwargs: dict) -> str:
    try:
        return json.dumps(kwargs, sort_keys=True, default=str)
    except TypeError:
        return repr(sorted((key, repr(value)) for key, value in kwargs.items()))


def _parameter_rejected(error_text: str, parameter: str) -> bool:
    text = (error_text or "").lower()
    parameter_text = parameter.lower()
    if parameter_text not in text:
        return False
    rejection_markers = (
        "unsupported",
        "not supported",
        "does not support",
        "invalid",
        "unknown",
        "unrecognized",
        "unexpected",
        "not allowed",
        "extra inputs",
    )
    return any(marker in text for marker in rejection_markers)


def _response_format_rejected(error_text: str) -> bool:
    text = (error_text or "").lower()
    if not any(term in text for term in ("response_format", "json_schema", "json_object")):
        return False
    return _parameter_rejected(text, "response_format") or any(
        marker in text
        for marker in (
            "json_schema is not supported",
            "json_object is not supported",
            "must be one of",
            "unsupported response format",
        )
    )


def _tools_rejected(error_text: str) -> bool:
    text = (error_text or "").lower()
    if not any(term in text for term in ("tools", "tool_choice", "function_call", "function calling")):
        return False
    return any(
        marker in text
        for marker in (
            "unsupported",
            "not supported",
            "does not support",
            "unknown",
            "unrecognized",
            "unexpected",
            "invalid",
        )
    )


def _extra_body_rejected(error_text: str) -> bool:
    text = (error_text or "").lower()
    if not any(term in text for term in ("extra_body", "thinking")):
        return False
    return any(
        marker in text
        for marker in (
            "unsupported",
            "not supported",
            "does not support",
            "unknown",
            "unrecognized",
            "unexpected",
            "invalid",
            "extra inputs",
        )
    )


def _temperature_must_be_one(error_text: str) -> bool:
    text = (error_text or "").lower()
    return "temperature" in text and "only 1" in text and ("allowed" in text or "invalid" in text)


def _is_kimi_configurable_thinking_model(model: str) -> bool:
    normalized = model.replace("_", "-")
    if "kimi-k2-thinking" in normalized:
        return False
    return any(marker in normalized for marker in ("kimi-k2.6", "kimi-k2.5", "kimi-k2-6", "kimi-k2-5", "kimi-k2p5"))


def _is_kimi_forced_thinking_model(model: str) -> bool:
    normalized = model.replace("_", "-")
    return "kimi-k2-thinking" in normalized or normalized.endswith("-thinking")
