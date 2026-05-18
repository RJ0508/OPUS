"""LLM-powered Q&A engine with page attribution for lease documents."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.request import Request, urlopen

from lease_summary.llm_config import LLMSettings, build_openai_client, is_local_provider, _safe_chat_create
from ..parsers.pdf_text import DocumentText

_DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
_DEFAULT_MODEL = "kimi-k2.6"
_REMOTE_MAX_DOC_CHARS = 120_000
_LOCAL_MAX_DOC_CHARS = 120_000
_LOCAL_FALLBACK_DOC_CHARS = 32_000
_LOCAL_MIN_DETECTED_DOC_CHARS = 12_000
_SUMMARY_MAX_CHARS = 3_500
_LOCAL_MIN_PAGES = 6
_LOCAL_MAX_PAGES = 48
_REMOTE_PRIORITY_PAGES = 24

_SYSTEM_PROMPT = """\
You are a helpful Hong Kong commercial lease analyst assistant with expertise in \
tenancy agreements, offer letters, and commercial property leasing in Hong Kong.

You have been provided with a lease document and a structured summary extracted from it. \
Answer any question the user asks — including greetings, general queries about lease terms, \
calculations, and follow-up questions. Be conversational and helpful.

For questions about specific lease data, prefer the EXTRACTED LEASE SUMMARY section \
(which contains validated structured data) over the raw document text. \
Each field in the summary is annotated with [p.N] showing the exact source page. \
When you use information from the summary, cite that [p.N] page number in page_references. \
Only cite raw document pages when the answer is NOT found in the summary.

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{
  "answer": "your helpful answer",
  "page_references": [list of integer page numbers where information was found, or [] if not applicable],
  "quote": "brief verbatim excerpt from the document supporting the answer (≤150 chars), or empty string"
}

Only set answer to "Not found in document" if specific information was explicitly asked for \
and genuinely cannot be found anywhere in the document or summary.
"""


@dataclass
class QAResult:
    question: str
    answer: str
    page_references: list[int] = field(default_factory=list)
    quote: str = ""
    error: str | None = None

    @property
    def found(self) -> bool:
        return bool(self.page_references) or (
            self.answer and "not found" not in self.answer.lower()
        )


class QAEngine:
    """
    Ask free-form questions about a lease document.
    Requires a configured OpenAI-compatible LLM provider.
    """

    def __init__(self, doc: DocumentText) -> None:
        self.doc = doc
        # Don't cache the client — always rebuild from current env vars so
        # settings changes and credential refreshes take effect without re-upload.

    def available(self) -> bool:
        """Check whether an LLM client can be built from current env vars."""
        client, settings = _get_client()
        return client is not None and settings is not None

    def ask(self, question: str) -> QAResult:
        """Ask a single question. Returns QAResult with answer + page citations."""
        # Rebuild client on every call so API-key / base-URL changes are picked
        # up immediately, without needing to re-upload the lease PDF.
        client, settings = _get_client()
        if client is None or settings is None:
            return QAResult(
                question=question,
                answer="",
                error="LLM provider not configured — Q&A unavailable",
            )
        try:
            context = _format_document(self.doc, question, settings)
            raw = _call_api(client, settings.model, context, question)
            return _parse_response(question, raw)
        except Exception as exc:
            return QAResult(question=question, answer="", error=str(exc))

    def ask_batch(self, questions: list[str]) -> list[QAResult]:
        """Ask multiple questions, one API call each."""
        return [self.ask(q) for q in questions]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _format_document(
    doc: DocumentText,
    question: str = "",
    settings: LLMSettings | None = None,
) -> str:
    """Format a question-focused context that stays inside the model budget."""
    budget = _context_char_budget(settings)
    parts: list[str] = []

    summary, pages = _split_summary_and_pages(doc)
    if summary:
        summary_budget = min(_SUMMARY_MAX_CHARS, max(0, budget // 2))
        budget = _append_context_part(parts, _format_page(summary), budget, summary_budget)

    if budget <= 0 or _looks_like_smalltalk(question):
        return "\n\n".join(parts)

    selected = _select_pages(pages, question, settings, budget)
    for page in selected:
        if budget <= 0:
            break
        budget = _append_context_part(parts, _format_page(page), budget)

    return "\n\n".join(parts)


def _context_char_budget(settings: LLMSettings | None) -> int:
    override = _env_int("LLM_QA_CONTEXT_CHARS", 0)
    if override:
        return override

    if settings is not None and is_local_provider(settings.provider, settings.base_url):
        local_override = _env_int("LLM_LOCAL_QA_CONTEXT_CHARS", 0)
        if local_override:
            return local_override
        detected = _detected_local_context_char_budget(settings)
        if detected:
            return detected
        return _LOCAL_FALLBACK_DOC_CHARS
    return _env_int("LLM_REMOTE_QA_CONTEXT_CHARS", _REMOTE_MAX_DOC_CHARS)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _detected_local_context_char_budget(settings: LLMSettings) -> int | None:
    tokens = _fetch_lmstudio_context_tokens(settings)
    if not tokens:
        return None
    return min(
        _LOCAL_MAX_DOC_CHARS,
        max(_LOCAL_MIN_DETECTED_DOC_CHARS, tokens * 2),
    )


def _fetch_lmstudio_context_tokens(settings: LLMSettings) -> int | None:
    """Read loaded context length from LM Studio's local REST API when present."""
    base_url = _native_local_base_url(settings.base_url)
    if not base_url:
        return None

    request = Request(
        f"{base_url}/api/v1/models",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=_env_int("LLM_LOCAL_CONTEXT_TIMEOUT", 1)) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    return _extract_context_tokens(body, settings.model)


def _native_local_base_url(base_url: str) -> str | None:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return None
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _extract_context_tokens(body: object, model: str) -> int | None:
    if not isinstance(body, dict):
        return None
    models = body.get("models")
    if not isinstance(models, list):
        return None

    target = (model or "").strip().lower()
    fallback: int | None = None
    for item in models:
        if not isinstance(item, dict):
            continue
        model_ids = _lmstudio_model_ids(item)
        context = _lmstudio_model_context(item, target)
        if context and target and target in model_ids:
            return context
        if context and fallback is None:
            fallback = context
    return fallback


def _lmstudio_model_ids(item: dict) -> set[str]:
    ids = {
        str(item.get(key, "")).strip().lower()
        for key in ("id", "key", "display_name", "selected_variant")
        if item.get(key)
    }
    variants = item.get("variants")
    if isinstance(variants, list):
        ids.update(str(value).strip().lower() for value in variants if value)
    loaded = item.get("loaded_instances")
    if isinstance(loaded, list):
        for instance in loaded:
            if isinstance(instance, dict) and instance.get("id"):
                ids.add(str(instance["id"]).strip().lower())
    return {value for value in ids if value}


def _lmstudio_model_context(item: dict, target: str) -> int | None:
    loaded = item.get("loaded_instances")
    best: int | None = None
    if isinstance(loaded, list):
        for instance in loaded:
            if not isinstance(instance, dict):
                continue
            instance_id = str(instance.get("id", "")).strip().lower()
            config = instance.get("config")
            if not isinstance(config, dict):
                continue
            context = _coerce_positive_int(config.get("context_length"))
            if not context:
                continue
            if target and instance_id == target:
                return context
            best = max(best or 0, context)

    return best or _coerce_positive_int(item.get("max_context_length"))


def _coerce_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _split_summary_and_pages(doc: DocumentText) -> tuple[object | None, list[object]]:
    summary = None
    pages: list[object] = []
    for page in doc.pages:
        text = getattr(page, "text", "") or ""
        if not text.strip():
            continue
        if getattr(page, "page_num", None) == 0:
            summary = page
        else:
            pages.append(page)
    return summary, pages


def _append_context_part(
    parts: list[str],
    text: str,
    budget: int,
    part_limit: int | None = None,
) -> int:
    limit = min(budget, part_limit) if part_limit else budget
    if limit <= 0:
        return budget
    if len(text) > limit:
        text = text[: max(0, limit - 24)].rstrip() + "\n[Context truncated]"
    if text.strip():
        parts.append(text.strip())
        budget -= len(text)
    return max(0, budget)


def _format_page(page: object) -> str:
    text = (getattr(page, "text", "") or "").strip()
    page_num = getattr(page, "page_num", 0)
    if page_num == 0:
        return text
    return f"[Page {page_num}]\n{text}"


def _looks_like_smalltalk(question: str) -> bool:
    value = " ".join((question or "").strip().lower().split())
    if not value:
        return True
    greetings = {
        "hi",
        "hello",
        "hey",
        "yo",
        "thanks",
        "thank you",
        "你好",
        "您好",
        "早晨",
        "hello there",
    }
    return value in greetings


def _select_pages(
    pages: list[object],
    question: str,
    settings: LLMSettings | None,
    budget: int,
) -> list[object]:
    if not pages:
        return []

    local = settings is not None and is_local_provider(settings.provider, settings.base_url)
    if _is_document_wide_question(question):
        return pages[: _local_page_cap(budget) if local else len(pages)]

    terms = _expanded_query_terms(question)
    if not terms:
        return pages[: min(3, len(pages))]

    ranked = []
    for index, page in enumerate(pages):
        text = (getattr(page, "text", "") or "").lower()
        score = _score_page(text, terms)
        if score > 0:
            ranked.append((score, index, page))

    if not ranked:
        return pages[: min(3, len(pages))]

    ranked.sort(key=lambda item: (-item[0], item[1]))
    cap = _local_page_cap(budget) if local else _REMOTE_PRIORITY_PAGES
    selected = ranked[:cap]

    selected_indexes = {index for _, index, _ in selected}
    if not local:
        for index, page in enumerate(pages):
            if index not in selected_indexes:
                selected.append((0, index, page))

    selected.sort(key=lambda item: item[1])
    return [page for _, _, page in selected]


def _local_page_cap(budget: int) -> int:
    return min(_LOCAL_MAX_PAGES, max(_LOCAL_MIN_PAGES, budget // 2_500))


def _score_page(text: str, terms: set[str]) -> int:
    score = 0
    for term in terms:
        if not term:
            continue
        count = text.count(term)
        if count:
            score += 1 + min(count, 4)
    return score


_STOPWORDS = {
    "about",
    "also",
    "does",
    "from",
    "have",
    "lease",
    "leases",
    "please",
    "that",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}

_QUERY_KEYWORD_GROUPS = (
    (
        ("rent", "rental", "租金", "免租"),
        ("rent", "rental", "monthly rent", "rent free", "rent-free", "免租"),
    ),
    (
        ("deposit", "security", "按金", "押金"),
        ("deposit", "security deposit", "balance", "按金", "押金"),
    ),
    (
        ("expire", "expiry", "commencement", "term", "date", "到期", "生效", "日期"),
        ("commencement", "expiry", "expiration", "term", "date", "year", "month"),
    ),
    (
        ("break", "terminate", "termination", "early", "終止"),
        ("break", "termination", "terminate", "notice", "early termination"),
    ),
    (
        ("renew", "renewal", "option", "續租"),
        ("renew", "renewal", "option", "notice", "trigger date"),
    ),
    (
        ("restore", "restoration", "reinstate", "yield", "handover", "復原", "交還"),
        ("restore", "restoration", "reinstate", "yield up", "handover", "condition"),
    ),
    (
        ("sublet", "assignment", "transfer", "share", "分租", "轉讓"),
        ("sublet", "subletting", "assignment", "transfer", "sharing", "consent"),
    ),
    (
        ("signage", "sign", "display", "招牌"),
        ("signage", "signboard", "display", "advertisement", "approval"),
    ),
    (
        ("parking", "car park", "車位"),
        ("parking", "car parking", "space", "licence", "車位"),
    ),
    (
        ("premises", "address", "building", "area", "物業", "地址", "面積"),
        ("premises", "address", "building", "floor", "suite", "area", "sq ft"),
    ),
)


def _expanded_query_terms(question: str) -> set[str]:
    value = (question or "").lower()
    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9'/-]{2,}", value)
        if token not in _STOPWORDS
    }
    terms.update(re.findall(r"[\u4e00-\u9fff]{2,}", value))

    for triggers, additions in _QUERY_KEYWORD_GROUPS:
        if any(trigger in value for trigger in triggers):
            terms.update(additions)

    return {term.lower() for term in terms if term.strip()}


def _is_document_wide_question(question: str) -> bool:
    value = (question or "").lower()
    return any(
        term in value
        for term in (
            "summarize",
            "summarise",
            "summary",
            "overview",
            "key terms",
            "entire lease",
            "whole document",
            "整份",
            "摘要",
            "總結",
        )
    )


def _get_client():
    return build_openai_client(_DEFAULT_BASE_URL, _DEFAULT_MODEL)


def _call_api(client, model: str, formatted_doc: str, question: str) -> str:
    resp = _safe_chat_create(
        client,
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Lease document:\n\n{formatted_doc}\n\nQuestion: {question}",
            },
        ],
        max_tokens=600,
        temperature=1,
    )
    return resp.choices[0].message.content.strip()


def _parse_response(question: str, raw: str) -> QAResult:
    try:
        data = json.loads(raw)
        return QAResult(
            question=question,
            answer=data.get("answer", ""),
            page_references=data.get("page_references", []),
            quote=data.get("quote", ""),
        )
    except json.JSONDecodeError:
        # Fallback: try to extract page numbers from freeform text
        pages = [int(x) for x in re.findall(r"\bpage\s+(\d+)\b", raw, re.IGNORECASE)]
        return QAResult(question=question, answer=raw, page_references=pages)
