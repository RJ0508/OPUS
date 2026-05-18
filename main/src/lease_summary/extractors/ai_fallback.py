"""LLM fallback for MISSING fields — the generalization layer.

Unlike ai_clauses (which only refines low-confidence narrative clauses),
this module runs AFTER regex extraction and attempts to fill in any
structured field whose value is still None. It makes a single JSON-mode
call per field group, so a lease written in an unusual format still gets
the key facts extracted as long as the LLM can read the text.

Only fills gaps — never overrides a successful regex extraction.
"""
from __future__ import annotations

import datetime
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from ..llm_config import build_openai_client, _safe_chat_create
from ..models import (
    Evidence,
    ExtractionMethod,
    ExtractionResult,
    LeaseSummary,
)
from ..normalizers.dates import parse_date
from ..parsers.pdf_text import DocumentText
from ..parsers.section_splitter import SplitDocument

# ── Config ──────────────────────────────────────────────────────────────────
_DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
_DEFAULT_MODEL = "kimi-k2.5"
_MAX_CONTEXT_CHARS = 12000

_SYSTEM_PROMPT = (
    "You are a Hong Kong commercial lease extraction assistant. "
    "You will be given lease text and a JSON schema of fields to extract. "
    "Return ONLY a single JSON object with the requested keys. "
    "For any field you cannot determine from the text, use null. "
    "Do not invent values. Do not add commentary. "
    "Numbers must be plain JSON numbers (no commas, no currency symbols). "
    "Dates must be in YYYY-MM-DD format. "
    "Text fields should be concise (under 300 characters)."
)


# ── Field specs ──────────────────────────────────────────────────────────────
# Each spec maps a field path to (json_key, json_type, description, parser)
# - json_type: "string" | "number" | "date"
# - parser: converts the raw JSON value to the field's python type

def _parse_number(x: Any) -> Decimal | None:
    if x is None:
        return None
    try:
        if isinstance(x, (int, float, Decimal)):
            return Decimal(str(x))
        s = str(x).replace(",", "").replace("HK$", "").replace("$", "").strip()
        if not s:
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_int(x: Any) -> int | None:
    d = _parse_number(x)
    return int(d) if d is not None else None


def _parse_string(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None


def _parse_iso_date(x: Any) -> datetime.date | None:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    # Try ISO first
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        pass
    # Fall back to dateutil
    return parse_date(s)


# Groups keep prompts small and focused
_PARTIES_SPEC = {
    "parties.landlord_name": {
        "key": "landlord_name",
        "type": "string",
        "desc": "Full legal name of the landlord/lessor company",
        "parser": _parse_string,
    },
    "parties.landlord_registered_address": {
        "key": "landlord_registered_address",
        "type": "string",
        "desc": "Registered office address of the landlord",
        "parser": _parse_string,
    },
    "parties.tenant_name": {
        "key": "tenant_name",
        "type": "string",
        "desc": "Full legal name of the tenant/lessee company",
        "parser": _parse_string,
    },
    "parties.tenant_registered_address": {
        "key": "tenant_registered_address",
        "type": "string",
        "desc": "Registered office address of the tenant",
        "parser": _parse_string,
    },
    "parties.landlord_solicitor": {
        "key": "landlord_solicitor",
        "type": "string",
        "desc": "Name of the landlord's solicitor firm",
        "parser": _parse_string,
    },
}

_PREMISES_SPEC = {
    "premises.full_address": {
        "key": "full_address",
        "type": "string",
        "desc": "Full street address of the leased premises including building, floor, unit, district",
        "parser": _parse_string,
    },
    "premises.building_name": {
        "key": "building_name",
        "type": "string",
        "desc": "Name of the building only (e.g. 'Central Plaza')",
        "parser": _parse_string,
    },
    "premises.floor_suite": {
        "key": "floor_suite",
        "type": "string",
        "desc": "Floor and unit identifier (e.g. 'Unit 1702, 17/F' or 'Room 1308, 13/F')",
        "parser": _parse_string,
    },
    "premises.rentable_area_sqft": {
        "key": "rentable_area_sqft",
        "type": "number",
        "desc": "Rentable/lettable/gross area of the premises in square feet (number only)",
        "parser": _parse_number,
    },
}

_TERM_SPEC = {
    "term.lease_commencement_date": {
        "key": "lease_commencement_date",
        "type": "date",
        "desc": "Lease commencement date (YYYY-MM-DD)",
        "parser": _parse_iso_date,
    },
    "term.lease_expiry_date": {
        "key": "lease_expiry_date",
        "type": "date",
        "desc": "Lease expiry date (YYYY-MM-DD)",
        "parser": _parse_iso_date,
    },
    "term.lease_term_months": {
        "key": "lease_term_months",
        "type": "number",
        "desc": "Total lease term in months (integer)",
        "parser": _parse_int,
    },
    "term.lease_signing_date": {
        "key": "lease_signing_date",
        "type": "date",
        "desc": "Date the lease was signed/executed (YYYY-MM-DD)",
        "parser": _parse_iso_date,
    },
    "term.rent_free_period_text": {
        "key": "rent_free_period_text",
        "type": "string",
        "desc": "Rent-free period description (e.g. '2 months' or 'Nil')",
        "parser": _parse_string,
    },
    "term.fit_out_period_text": {
        "key": "fit_out_period_text",
        "type": "string",
        "desc": "Fit-out period description (e.g. '1 month' or 'Nil')",
        "parser": _parse_string,
    },
}

_FINANCIALS_SPEC = {
    "financials.monthly_rent_hkd": {
        "key": "monthly_rent_hkd",
        "type": "number",
        "desc": "Total monthly rent in HKD (number only, no commas or currency symbol)",
        "parser": _parse_number,
    },
    "financials.management_fee_monthly_hkd": {
        "key": "management_fee_monthly_hkd",
        "type": "number",
        "desc": "Monthly management fee / service charge in HKD",
        "parser": _parse_number,
    },
    "financials.security_deposit_hkd": {
        "key": "security_deposit_hkd",
        "type": "number",
        "desc": "Total security deposit amount in HKD",
        "parser": _parse_number,
    },
    "financials.security_deposit_multiple": {
        "key": "security_deposit_multiple",
        "type": "number",
        "desc": "Security deposit as a multiple of monthly rent (e.g. 3)",
        "parser": _parse_int,
    },
    "financials.rates_quarterly_hkd": {
        "key": "rates_quarterly_hkd",
        "type": "number",
        "desc": "Government rates per quarter in HKD",
        "parser": _parse_number,
    },
}

_CLAUSES_SPEC = {
    "clauses.user_clause_text": {
        "key": "user_clause_text",
        "type": "string",
        "desc": "Permitted use of the premises (one sentence)",
        "parser": _parse_string,
    },
    "clauses.handover_condition_text": {
        "key": "handover_condition_text",
        "type": "string",
        "desc": "Condition the premises are handed over in (e.g. 'Bare shell', 'As-is')",
        "parser": _parse_string,
    },
}

_SPECS: list[tuple[str, dict]] = [
    ("parties", _PARTIES_SPEC),
    ("premises", _PREMISES_SPEC),
    ("term", _TERM_SPEC),
    ("financials", _FINANCIALS_SPEC),
    ("clauses", _CLAUSES_SPEC),
]


# ── Public entry point ──────────────────────────────────────────────────────

def ai_fallback_extract(
    summary: LeaseSummary,
    doc: DocumentText,
    split: SplitDocument,
) -> None:
    """
    Run LLM fallback for any structured field still missing after regex extraction.
    Mutates `summary` in place. No-op if the LLM client cannot be configured.
    """
    client, settings = build_openai_client(_DEFAULT_BASE_URL, _DEFAULT_MODEL)
    if client is None or settings is None:
        return

    context = _build_context(split, doc)
    if not context:
        return

    for group_name, spec in _SPECS:
        missing = _missing_fields(summary, spec)
        if not missing:
            continue
        data = _ask_for_fields(client, settings.model, context, group_name, missing)
        if not data:
            continue
        _apply_results(summary, doc, missing, data)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _build_context(split: SplitDocument, doc: DocumentText) -> str:
    """Build a compact lease-text context for the LLM."""
    parts: list[str] = []
    if getattr(split, "principal_terms", ""):
        parts.append(split.principal_terms)
    if getattr(split, "schedule_i", None):
        parts.append("\n\n--- SCHEDULE I ---\n" + split.schedule_i)
    if getattr(split, "schedule_ii", None):
        parts.append("\n\n--- SCHEDULE II ---\n" + split.schedule_ii)
    text = "\n".join(parts).strip()
    if not text:
        # Fall back to raw document text
        text = doc.full_text
    return text[:_MAX_CONTEXT_CHARS]


def _missing_fields(summary: LeaseSummary, spec: dict) -> dict:
    """Return spec entries whose corresponding field on `summary` is still missing."""
    missing: dict = {}
    for path, entry in spec.items():
        result = _get_field(summary, path)
        if result is None:
            continue
        # Missing if value is None. Do NOT treat "n/a" as missing — that's a
        # valid determined outcome.
        if result.value is None:
            missing[path] = entry
    return missing


def _get_field(summary: LeaseSummary, path: str) -> ExtractionResult | None:
    group_name, field_name = path.split(".", 1)
    group = getattr(summary, group_name, None)
    if group is None:
        return None
    return getattr(group, field_name, None)


def _set_field(summary: LeaseSummary, path: str, value: ExtractionResult) -> None:
    group_name, field_name = path.split(".", 1)
    group = getattr(summary, group_name, None)
    if group is None:
        return
    setattr(group, field_name, value)


def _ask_for_fields(
    client,
    model: str,
    context: str,
    group_name: str,
    missing: dict,
) -> dict | None:
    """Call the LLM asking for the listed missing fields. Returns parsed JSON dict."""
    # Build schema description
    schema_lines = []
    for _, entry in missing.items():
        schema_lines.append(f'  "{entry["key"]}": {entry["type"]},  // {entry["desc"]}')
    schema_block = "{\n" + "\n".join(schema_lines) + "\n}"

    user_prompt = (
        f"Lease text ({group_name} section focus):\n"
        f"---\n{context}\n---\n\n"
        f"Extract the following fields from the lease text and return them as JSON. "
        f"Use null for any field you cannot determine. "
        f"Do not invent values that are not clearly supported by the text.\n\n"
        f"Schema:\n{schema_block}"
    )

    try:
        resp = _safe_chat_create(
            client,
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=800,
            temperature=1,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
    except TypeError:
        # Some providers don't support response_format — retry without it
        try:
            resp = _safe_chat_create(
                client,
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=800,
                temperature=1,
            )
            text = resp.choices[0].message.content or ""
        except Exception:
            return None
    except Exception:
        return None

    return _parse_json_response(text)


def _parse_json_response(text: str) -> dict | None:
    """Parse the LLM response, tolerating code fences and surrounding prose."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        # Try to extract the first JSON object substring
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def _apply_results(
    summary: LeaseSummary,
    doc: DocumentText,
    missing: dict,
    data: dict,
) -> None:
    """Parse each returned value and write it back to the summary."""
    for path, entry in missing.items():
        raw = data.get(entry["key"])
        if raw is None:
            continue
        # Some models return the sentinel string "null"
        if isinstance(raw, str) and raw.strip().lower() in ("null", "none", "n/a", "na", ""):
            continue
        parser: Callable[[Any], Any] = entry["parser"]
        parsed = parser(raw)
        if parsed is None:
            continue
        # Sanity filter: reject absurdly long strings that suggest hallucination
        if isinstance(parsed, str) and len(parsed) > 400:
            parsed = parsed[:400]
        page = _find_evidence_page(doc, parsed, entry["key"])
        quote = _build_quote(entry["key"], parsed)
        result = ExtractionResult(
            value=parsed,
            confidence=0.75,
            evidence=[Evidence(
                page=page,
                quote=quote,
                method=ExtractionMethod.heuristic,
            )],
            review_flag="AI_FALLBACK_EXTRACTION",
        )
        _set_field(summary, path, result)


def _find_evidence_page(doc: DocumentText, value: Any, key: str) -> int:
    """Best-effort: find a page whose text contains a substring of the value."""
    if isinstance(value, str) and len(value) > 4:
        needle = value[:20].lower()
        for p in doc.pages:
            if needle in p.text.lower():
                return p.page_num
    elif isinstance(value, (int, float, Decimal)):
        needle = str(value).split(".")[0]
        if len(needle) >= 3:
            for p in doc.pages:
                if needle in p.text:
                    return p.page_num
    elif isinstance(value, datetime.date):
        year_str = str(value.year)
        for p in doc.pages:
            if year_str in p.text:
                return p.page_num
    return 0


def _build_quote(key: str, value: Any) -> str:
    if isinstance(value, datetime.date):
        text = value.isoformat()
    else:
        text = str(value)
    return f"AI fallback ({key}): {text[:180]}"
