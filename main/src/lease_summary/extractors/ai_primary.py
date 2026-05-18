"""Primary LLM extraction — one-shot structured extraction using Moonshot.

Sends OCR/extracted text to the configured text model for all
document types. LLM results fill gaps and override low-confidence regex
results. Called AFTER regex extraction in the pipeline.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..models import (
    Evidence,
    ExtractionMethod,
    ExtractionResult,
    LeaseSummary,
)
from ..llm_config import _safe_chat_create
from ..normalizers.dates import parse_date
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument

# ── Config ────────────────────────────────────────────────────────────────────
_DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
_DEFAULT_MODEL = "kimi-k2.6"
_CONFIG_PATH = Path.home() / ".opus_lease_summary" / "config.json"

_MAX_CONTEXT_CHARS = 60_000
_LOCAL_CHUNK_CHARS = 5_500
_LOCAL_MAX_CHUNKS = 8
_CHUNK_OVERLAP_CHARS = 500
_LOW_CONFIDENCE_OVERRIDE_THRESHOLD = 0.75
_LOCAL_BASE_PREFIXES = ("http://127.0.0.1", "http://localhost")
_LOCAL_CHUNK_HIGH_RISK_FIELDS = {"lease_signing_date"}

_SYSTEM_PROMPT = """\
You are an expert Hong Kong commercial lease analyst.
You will receive the full text of a lease document (PDF OCR or DOCX) and must
extract specific fields. The document may be in any format: formal full-lease,
offer-to-lease, tenancy agreement, or tenancy offer letter.

Rules:
- Return ONLY a single valid JSON object. No markdown fences, no prose.
- Use null for any field you cannot determine from the text.
- NEVER invent or guess values not clearly stated in the document.
- Numbers: plain JSON numbers, no commas, no currency symbols.
- Dates: YYYY-MM-DD format only.
- Addresses: single line, comma-separated.
- Text fields: concise, under 300 characters.
"""
_CHUNK_SYSTEM_PROMPT = (
    "You extract Hong Kong lease facts. Return only one valid JSON object. "
    "No markdown, no explanation, no invented values."
)

_EXTRACTION_SCHEMA = """\
{
  "landlord_name": "string — full legal name of the landlord/lessor company in English only (no Chinese characters)",
  "landlord_registered_address": "string — registered office address of landlord",
  "tenant_name": "string — full legal name of the tenant/lessee company in English only (no Chinese characters)",
  "tenant_registered_address": "string — registered office address of tenant",

  "full_address": "string — complete address of leased premises (floor/unit + building + street + district)",
  "building_name": "string — building name only, e.g. 'Central Plaza'",
  "floor_suite": "string — floor and unit only, e.g. '22/F & 23/F' or 'Level L18, L19 and L20'",
  "rentable_area_sqft": "number — rentable/lettable area in square feet",

  "lease_signing_date": "YYYY-MM-DD — date the lease was signed/executed",
  "scheduled_commencement_date": "YYYY-MM-DD — scheduled commencement date if separately stated",
  "lease_commencement_date": "YYYY-MM-DD — first day of the lease term",
  "lease_expiry_date": "YYYY-MM-DD — last day of the lease term",
  "lease_term_months": "integer — total lease duration in months",

  "rent_free_period_text": "string — rent-free period, e.g. '4 months' or 'Nil'",
  "fit_out_period_text": "string — fit-out / fitting-out period description",
  "option_to_renew_text": "string — renewal option terms (brief summary)",
  "trigger_date_text": "string — LAST DATE by which tenant must give notice to exercise renewal option. Compute it: subtract the minimum notice period from lease_expiry_date and format as 'DD Mon YYYY (X months before expiry)', e.g. '31 Oct 2028 (4 months before expiry)'. If no option to renew, use 'n/a'.",
  "right_of_expansion_text": "string — right of expansion or right of first offer, brief factual summary (1-2 sentences). If none, use 'n/a'.",
  "tenant_termination_right_text": "string — tenant's right to terminate (break clause)",

  "monthly_rent_hkd": "number — total monthly rent in HKD",
  "monthly_rent_psf_hkd": "number — monthly rent per square foot in HKD",
  "management_fee_monthly_hkd": "number — monthly management fee / service charge in HKD",
  "management_fee_psf_hkd": "number — monthly management fee / service charge per square foot in HKD",
  "rates_quarterly_hkd": "number — government rates (差餉) per quarter in HKD",
  "rates_monthly_hkd": "number — government rates (差餉) per month in HKD",
  "government_rent_monthly_hkd": "number — government rent (地租) per month in HKD",
  "operating_expense_note": "string — concise note about management fees, rates, service charges, or operating expenses",
  "security_deposit_hkd": "number — total security deposit in HKD",
  "security_deposit_multiple": "integer — deposit as multiple of monthly rent, e.g. 3",
  "security_deposit_note": "string — deposit composition, advance deposit, transferred deposit, balance, or special deposit terms",
  "advance_rent_text": "string — advance rent terms, if stated",

  "permitted_use": "string — permitted use / user clause for the premises",
  "handover_condition": "string — condition of premises on handover, e.g. 'As-is', 'Bare shell'",
  "break_clause_text": "string — break clause or early termination clause",
  "subletting_text": "string — subletting, assignment, transfer, or sharing rights",
  "signage_text": "string — signage/display rights and restrictions",
  "parking_text": "string — car parking spaces or parking licence terms",
  "restoration_obligations_text": "string — reinstatement/restoration/yield-up obligations"
}"""

_COMPACT_EXTRACTION_SCHEMA = """\
{
  "landlord_name": "string",
  "landlord_registered_address": "string",
  "tenant_name": "string",
  "tenant_registered_address": "string",
  "full_address": "string",
  "building_name": "string",
  "floor_suite": "string",
  "rentable_area_sqft": "number",
  "lease_signing_date": "YYYY-MM-DD",
  "scheduled_commencement_date": "YYYY-MM-DD",
  "lease_commencement_date": "YYYY-MM-DD",
  "lease_expiry_date": "YYYY-MM-DD",
  "lease_term_months": "integer",
  "rent_free_period_text": "string",
  "fit_out_period_text": "string",
  "option_to_renew_text": "string",
  "trigger_date_text": "string",
  "right_of_expansion_text": "string",
  "tenant_termination_right_text": "string",
  "monthly_rent_hkd": "number",
  "monthly_rent_psf_hkd": "number",
  "management_fee_monthly_hkd": "number",
  "management_fee_psf_hkd": "number",
  "rates_quarterly_hkd": "number",
  "rates_monthly_hkd": "number",
  "government_rent_monthly_hkd": "number",
  "operating_expense_note": "string",
  "security_deposit_hkd": "number",
  "security_deposit_multiple": "integer",
  "security_deposit_note": "string",
  "advance_rent_text": "string",
  "permitted_use": "string",
  "handover_condition": "string",
  "break_clause_text": "string",
  "subletting_text": "string",
  "signage_text": "string",
  "parking_text": "string",
  "restoration_obligations_text": "string"
}"""


# ── Field mapping: JSON key → (summary path, parser) ─────────────────────────
def _p_str(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    return s[:300] if s else None


def _p_num(x: Any) -> Decimal | None:
    if x is None:
        return None
    try:
        s = re.sub(r"[,$HKhk\s]", "", str(x)).strip()
        return Decimal(s) if s else None
    except InvalidOperation:
        return None


def _p_int(x: Any) -> int | None:
    d = _p_num(x)
    return int(d) if d is not None else None


def _p_date(x: Any) -> datetime.date | None:
    if x is None:
        return None
    s = str(x).strip()
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        return parse_date(s)


_FIELD_MAP: dict[str, tuple[str, Any]] = {
    "landlord_name":                    ("parties.landlord_name",               _p_str),
    "landlord_registered_address":      ("parties.landlord_registered_address", _p_str),
    "tenant_name":                      ("parties.tenant_name",                 _p_str),
    "tenant_registered_address":        ("parties.tenant_registered_address",   _p_str),
    "full_address":                     ("premises.full_address",               _p_str),
    "building_name":                    ("premises.building_name",              _p_str),
    "floor_suite":                      ("premises.floor_suite",                _p_str),
    "rentable_area_sqft":               ("premises.rentable_area_sqft",         _p_num),
    "lease_signing_date":               ("term.lease_signing_date",             _p_date),
    "scheduled_commencement_date":      ("term.scheduled_commencement_date",    _p_date),
    "lease_commencement_date":          ("term.lease_commencement_date",        _p_date),
    "lease_expiry_date":                ("term.lease_expiry_date",              _p_date),
    "lease_term_months":                ("term.lease_term_months",              _p_int),
    "rent_free_period_text":            ("term.rent_free_period_text",          _p_str),
    "fit_out_period_text":              ("term.fit_out_period_text",            _p_str),
    "option_to_renew_text":             ("term.option_to_renew_text",           _p_str),
    "trigger_date_text":                ("term.trigger_date_text",              _p_str),
    "right_of_expansion_text":          ("term.right_of_expansion_text",        _p_str),
    "tenant_termination_right_text":    ("term.tenant_termination_right_text",  _p_str),
    "monthly_rent_hkd":                 ("financials.monthly_rent_hkd",         _p_num),
    "monthly_rent_psf_hkd":             ("financials.monthly_rent_psf_hkd",     _p_num),
    "management_fee_monthly_hkd":       ("financials.management_fee_monthly_hkd", _p_num),
    "management_fee_psf_hkd":           ("financials.management_fee_psf_hkd",   _p_num),
    "rates_quarterly_hkd":              ("financials.rates_quarterly_hkd",      _p_num),
    "rates_monthly_hkd":                ("financials.rates_monthly_hkd",        _p_num),
    "government_rent_monthly_hkd":      ("financials.government_rent_monthly_hkd", _p_num),
    "operating_expense_note":           ("financials.operating_expense_note",   _p_str),
    "security_deposit_hkd":             ("financials.security_deposit_hkd",     _p_num),
    "security_deposit_multiple":        ("financials.security_deposit_multiple", _p_int),
    "security_deposit_note":            ("financials.security_deposit_note",    _p_str),
    "advance_rent_text":                ("financials.advance_rent_text",        _p_str),
    "permitted_use":                    ("clauses.user_clause_text",            _p_str),
    "handover_condition":               ("clauses.handover_condition_text",     _p_str),
    "break_clause_text":                ("clauses.break_clause_text",           _p_str),
    "subletting_text":                  ("clauses.subletting_text",             _p_str),
    "signage_text":                     ("clauses.signage_text",                _p_str),
    "parking_text":                     ("clauses.parking_text",                _p_str),
    "restoration_obligations_text":     ("clauses.restoration_obligations_text", _p_str),
}


# ── Public entry point ────────────────────────────────────────────────────────

def ai_primary_extract(
    summary: LeaseSummary,
    doc: DocumentText,
    split: SplitDocument,
    *,
    override_low_confidence: bool = True,
    pure_llm: bool = False,
) -> None:
    """
    Run full-document LLM extraction and write results to `summary`.
    No-op if the LLM client cannot be configured.
    """
    client, model, base_url = _build_client()
    if client is None:
        return

    use_chunked = _should_use_chunked(base_url)
    if use_chunked:
        data = _call_llm_chunked(client, model, _build_chunks(split, doc), base_url=base_url)
        if data:
            _apply(
                summary,
                doc,
                data,
                override_low_confidence=pure_llm,
                confidence=0.72,
            )
        return

    context = _build_context(split, doc)
    if not context:
        return
    data = _call_llm(client, model, context)
    if not data:
        data = _call_llm_chunked(client, model, _build_chunks(split, doc), base_url=base_url)
    if not data:
        return

    _apply(summary, doc, data, override_low_confidence=override_low_confidence)


# ── Internal ──────────────────────────────────────────────────────────────────

def _build_client():
    """Return (openai_client, model_name, base_url) using env vars or config file."""
    try:
        from openai import OpenAI
    except ImportError:
        return None, None, ""

    # 1. env vars (set by the FastAPI app)
    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("MOONSHOT_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    base_url = (
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("MOONSHOT_BASE_URL")
        or ""
    ).strip()
    model = (
        os.environ.get("LLM_MODEL")
        or os.environ.get("MOONSHOT_MODEL")
        or ""
    ).strip()

    if not api_key and base_url.startswith(_LOCAL_BASE_PREFIXES):
        api_key = "local"

    # 2. fallback: read from ~/.opus_lease_summary/config.json
    if not api_key and _CONFIG_PATH.exists():
        try:
            cfg = json.loads(_CONFIG_PATH.read_text())
            keys = cfg.get("api_keys", {})
            provider = cfg.get("llm_provider", "moonshot")
            api_key = keys.get(provider) or cfg.get("api_key", "")
            base_url = base_url or cfg.get("llm_base_url", "")
            model = model or cfg.get("llm_model", "")
        except Exception:
            pass

    api_key = (api_key or "").strip()
    base_url = (base_url or _DEFAULT_BASE_URL).strip()
    if base_url.startswith(_LOCAL_BASE_PREFIXES) and not model:
        return None, None, base_url
    model = (model or _DEFAULT_MODEL).strip()

    if not api_key and base_url.startswith(_LOCAL_BASE_PREFIXES):
        api_key = "local"

    if not api_key:
        return None, None, base_url

    return OpenAI(api_key=api_key, base_url=base_url), model, base_url


def _build_context(split: SplitDocument, doc: DocumentText) -> str:
    """
    Build a focused context that fits within _MAX_CONTEXT_CHARS.

    Priority order:
    1. Schedule sections (I / II / III) — contain all key terms in formal leases
    2. First 15 pages of principal_terms — preamble + definitions + key clauses
    3. Last 5 pages — often contain remaining schedules or special conditions
    """
    budget = _MAX_CONTEXT_CHARS
    parts: list[str] = []

    # Schedules first — highest density of extractable fields
    for attr in ("schedule_i", "schedule_ii", "schedule_iii"):
        chunk = getattr(split, attr, None) or ""
        if chunk and budget > 0:
            label = f"\n\n=== {attr.upper().replace('_', ' ')} ===\n"
            take = min(len(label) + len(chunk), budget)
            parts.append((label + chunk)[:take])
            budget -= take

    # Principal terms: first pages (preamble, parties, key terms)
    pt = getattr(split, "principal_terms", "") or ""
    if pt and budget > 0:
        first_chunk = pt[:min(40_000, budget)]
        parts.insert(0, first_chunk)  # Put before schedules
        budget -= len(first_chunk)

    # If budget remains, add last pages (special conditions, etc.)
    if pt and budget > 2000 and len(pt) > 40_000:
        tail = pt[-min(budget, 5_000):]
        parts.append(f"\n\n=== DOCUMENT TAIL ===\n{tail}")

    text = "".join(parts).strip()
    return text or doc.full_text[:_MAX_CONTEXT_CHARS]



def _call_llm(client, model: str, context: str) -> dict | None:
    user_prompt = (
        "Extract all lease fields from the document below and return them as "
        "a single JSON object matching the schema. Use null for missing fields.\n\n"
        f"SCHEMA:\n{_EXTRACTION_SCHEMA}\n\n"
        f"DOCUMENT TEXT:\n---\n{context}\n---"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]
    kwargs = dict(model=model, messages=messages, max_tokens=16000, temperature=1)

    for attempt in range(2):
        resp = _create_chat_completion(client, kwargs)
        if resp is None:
            return None

        raw = (resp.choices[0].message.content or "").strip()
        if raw:
            return _parse_json(raw)
        # Empty response — retry once with a shorter context
        if attempt == 0:
            context = context[:len(context) // 2]
            user_prompt = user_prompt.replace(
                f"DOCUMENT TEXT:\n---\n{context * 2}\n---",
                f"DOCUMENT TEXT:\n---\n{context}\n---",
            )
            # Rebuild prompt with halved context
            user_prompt = (
                "Extract all lease fields from the document below and return them as "
                "a single JSON object matching the schema. Use null for missing fields.\n\n"
                f"SCHEMA:\n{_EXTRACTION_SCHEMA}\n\n"
                f"DOCUMENT TEXT:\n---\n{context}\n---"
            )
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ]
            kwargs["messages"] = messages

    return None


def _call_llm_chunked(
    client,
    model: str,
    chunks: list[str],
    *,
    base_url: str = "",
) -> dict | None:
    merged: dict[str, Any] = {}
    for chunk in chunks:
        data = _call_llm_on_chunk(client, model, chunk, base_url=base_url)
        if not data:
            continue
        _merge_chunk_data(merged, data)

    return merged or None


def _call_llm_on_chunk(client, model: str, chunk: str, *, base_url: str = "") -> dict | None:
    user_prompt = (
        "Extract only the lease fields that are clearly present in this excerpt. "
        "Return a single JSON object using the schema keys below. Omit fields "
        "that are not present in this excerpt. Do not infer from outside this excerpt.\n\n"
        f"SCHEMA:\n{_COMPACT_EXTRACTION_SCHEMA}\n\n"
        f"EXCERPT:\n---\n{chunk}\n---"
    )
    if _should_use_native_lmstudio(base_url):
        raw = _call_lmstudio_native_chat(
            model,
            base_url,
            f"{_CHUNK_SYSTEM_PROMPT}\n\n{user_prompt}",
        )
        if raw:
            data = _parse_json(raw)
            if data:
                return data

    messages = [
        {"role": "system", "content": _CHUNK_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    kwargs = dict(model=model, messages=messages, max_tokens=900, temperature=0)
    resp = _create_chat_completion(client, kwargs)
    if resp is None:
        return None
    raw = (resp.choices[0].message.content or "").strip()
    return _parse_json(raw) if raw else None


def _merge_chunk_data(merged: dict[str, Any], candidate: dict) -> None:
    for key in _FIELD_MAP:
        value = candidate.get(key)
        if _is_missing_value(value):
            continue
        current = merged.get(key)
        if _is_missing_value(current) or _is_better_chunk_value(value, current):
            merged[key] = value


def _is_better_chunk_value(value: Any, current: Any) -> bool:
    if isinstance(value, str) and isinstance(current, str):
        normalized = value.strip().lower()
        current_normalized = current.strip().lower()
        if current_normalized in {"n/a", "na", "nil", "none"}:
            return True
        if normalized in {"n/a", "na", "nil", "none"}:
            return False
        return len(value.strip()) > len(current.strip()) * 1.2
    return False


def _build_chunks(split: SplitDocument, doc: DocumentText) -> list[str]:
    sources: list[str] = []
    for label, text in _iter_priority_sources(split, doc):
        clean = _clean_chunk_text(text)
        if clean:
            sources.append(f"=== {label} ===\n{clean}")

    chunks: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for chunk in _split_text(source, _local_chunk_chars(), _CHUNK_OVERLAP_CHARS):
            key = " ".join(chunk[:300].split()).lower()
            if key in seen:
                continue
            seen.add(key)
            chunks.append(chunk)
            if len(chunks) >= _local_max_chunks():
                return chunks
    return chunks


def _iter_priority_sources(split: SplitDocument, doc: DocumentText):
    for attr in ("schedule_i", "schedule_ii", "schedule_iii"):
        text = getattr(split, attr, None) or ""
        if text:
            yield attr.upper().replace("_", " "), text

    pages = list(getattr(doc, "pages", []) or [])
    emitted_pages: set[int] = set()
    for page in pages[:4]:
        emitted_pages.add(page.page_num)
        yield f"PAGE {page.page_num}", page.text

    keyword_pages = _select_keyword_pages(pages)
    for page in keyword_pages:
        if page.page_num in emitted_pages:
            continue
        emitted_pages.add(page.page_num)
        yield f"PAGE {page.page_num}", page.text

    for page in pages[-3:]:
        if page.page_num in emitted_pages:
            continue
        emitted_pages.add(page.page_num)
        yield f"PAGE {page.page_num}", page.text

    principal = getattr(split, "principal_terms", "") or ""
    if principal and not pages:
        yield "PRINCIPAL TERMS", principal


def _select_keyword_pages(pages: list) -> list:
    keywords = (
        "landlord", "lessor", "tenant", "lessee", "premises", "rentable",
        "commencement", "expiry", "term", "rent", "management fee", "service charge",
        "rates", "government rent", "deposit", "renew", "break", "termination",
        "sublet", "assignment", "signage", "parking", "reinstate", "restore",
        "fitting-out", "fit-out",
    )
    selected = []
    seen = set()
    for page in pages:
        text = page.text or ""
        lower = text.lower()
        if page.page_num in seen:
            continue
        hits = sum(1 for keyword in keywords if keyword in lower)
        if hits >= 2:
            selected.append(page)
            seen.add(page.page_num)
    return selected


def _split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            newline = text.rfind("\n", start + max_chars // 2, end)
            if newline > start:
                end = newline
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap_chars)
    return [chunk for chunk in chunks if chunk]


def _clean_chunk_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").splitlines()).strip()


def _local_chunk_chars() -> int:
    return _env_int("LLM_CHUNK_CHARS", _LOCAL_CHUNK_CHARS)


def _local_max_chunks() -> int:
    return _env_int("LLM_MAX_CHUNKS", _LOCAL_MAX_CHUNKS)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _should_use_chunked(base_url: str) -> bool:
    mode = os.environ.get("LLM_CHUNKED", "").strip().lower()
    if mode in {"1", "true", "yes", "always"}:
        return True
    if mode in {"0", "false", "no", "never"}:
        return False
    return (base_url or "").startswith(_LOCAL_BASE_PREFIXES)


def _should_use_native_lmstudio(base_url: str) -> bool:
    mode = os.environ.get("LLM_NATIVE_CHAT", "").strip().lower()
    if mode in {"0", "false", "no", "never"}:
        return False
    return (base_url or "").startswith(_LOCAL_BASE_PREFIXES)


def _call_lmstudio_native_chat(model: str, base_url: str, prompt: str) -> str | None:
    endpoint = f"{_native_lmstudio_base_url(base_url)}/api/v1/chat"
    payload = {
        "model": model,
        "input": prompt,
        "max_output_tokens": _env_int("LLM_NATIVE_MAX_OUTPUT_TOKENS", 2200),
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=_env_int("LLM_NATIVE_TIMEOUT", 180)) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return _extract_lmstudio_native_content(body)


def _native_lmstudio_base_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _extract_lmstudio_native_content(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    output = body.get("output")
    if isinstance(output, str):
        return output.strip() or None
    if not isinstance(output, list):
        return None

    fallback: str | None = None
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if item.get("type") == "message":
            return content.strip()
        if fallback is None and item.get("type") != "reasoning":
            fallback = content.strip()
    return fallback


def _create_chat_completion(client, kwargs: dict):
    try:
        return _safe_chat_create(
            client, **kwargs, response_format={"type": "json_object"}
        )
    except Exception as exc:
        if not _is_response_format_error(exc):
            return None

    try:
        return _safe_chat_create(client, **kwargs)
    except Exception:
        return None


def _is_response_format_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "response_format" in text or "json_object" in text


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                pass
    return None


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "null", "none", "n/a", "na", "nil"}
    return False


def _apply(
    summary: LeaseSummary,
    doc: DocumentText,
    data: dict,
    *,
    override_low_confidence: bool = True,  # kept for API compatibility
    confidence: float = 0.85,
) -> None:
    """
    Apply LLM results to summary.
    Overrides regex results unless they have confidence == 1.0
    (exact label match from a well-formatted schedule).
    """
    for json_key, (path, parser) in _FIELD_MAP.items():
        raw = data.get(json_key)
        if raw is None:
            continue
        if not override_low_confidence and json_key in _LOCAL_CHUNK_HIGH_RISK_FIELDS:
            continue
        if isinstance(raw, str) and raw.strip().lower() in ("null", "none", "n/a", "na", "nil", ""):
            continue

        parsed = parser(raw)
        if parsed is None:
            continue

        # Keep exact-label matches and, for local chunked extraction, avoid
        # replacing usable rule/regex values with weaker small-model guesses.
        existing = _get(summary, path)
        if existing is not None and existing.value is not None:
            existing_confidence = existing.confidence or 0
            if existing_confidence >= 1.0:
                continue
            if (
                not override_low_confidence
                and existing_confidence >= _LOW_CONFIDENCE_OVERRIDE_THRESHOLD
            ):
                continue

        page = _find_page(doc, parsed)
        result = ExtractionResult(
            value=parsed,
            confidence=confidence,
            evidence=[Evidence(
                page=page,
                quote=f"LLM ({json_key}): {str(parsed)[:180]}",
                method=ExtractionMethod.heuristic,
            )],
            review_flag=None,
        )
        _set(summary, path, result)


def _get(summary: LeaseSummary, path: str) -> ExtractionResult | None:
    group, field = path.split(".", 1)
    grp = getattr(summary, group, None)
    return getattr(grp, field, None) if grp else None


def _set(summary: LeaseSummary, path: str, value: ExtractionResult) -> None:
    group, field = path.split(".", 1)
    grp = getattr(summary, group, None)
    if grp is not None:
        setattr(grp, field, value)


def _find_page(doc: DocumentText, value: Any) -> int:
    if isinstance(value, str) and len(value) > 4:
        needle = value[:20].lower()
        for p in doc.pages:
            if needle in p.text.lower():
                return p.page_num
    elif isinstance(value, (int, float, Decimal)):
        needle = str(value).split(".")[0]
        if len(needle) >= 4:
            for p in doc.pages:
                if needle in p.text:
                    return p.page_num
    elif isinstance(value, datetime.date):
        for p in doc.pages:
            if str(value.year) in p.text:
                return p.page_num
    return 0
