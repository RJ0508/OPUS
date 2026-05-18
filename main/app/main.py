"""FastAPI backend for Opus Lease Summary Assistant."""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import AsyncGenerator, Callable

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .state import normalise_api_keys, normalize_mode, state
from lease_summary.llm_config import (
    get_provider_catalog,
    get_provider_default_base_url,
    get_provider_default_model,
    list_available_models,
)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Opus Lease Summary Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_TEMP_DIR = Path(tempfile.mkdtemp(prefix="opus_lease_"))
_PROGRESS_LOCK = threading.Lock()
_PROGRESS_RUN_ID = ""
_PROGRESS_SEQ = 0
_PROGRESS_DONE = False
_PROGRESS_EVENTS: list[dict] = []


# ── Models ────────────────────────────────────────────────────────────────────

class SettingsPayload(BaseModel):
    api_key: str = ""
    api_keys: dict[str, str] | None = None
    mode: str  # "standard" | "ai_enhanced" | "pure_llm" plus legacy values
    llm_provider: str = ""
    llm_base_url: str = ""
    llm_model: str = ""


class ModelListPayload(BaseModel):
    api_key: str = ""
    llm_provider: str = ""
    llm_base_url: str = ""


class QAPayload(BaseModel):
    question: str

class FieldUpdate(BaseModel):
    section: str
    key: str
    value: str


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    provider = (state.llm_provider or "").strip().lower()
    return {
        "api_key": state.active_api_key(provider),
        "api_keys": state.api_keys,
        "mode": normalize_mode(state.mode),
        "llm_provider": provider,
        "llm_base_url": state.llm_base_url,
        "llm_model": state.llm_model,
    }


@app.post("/api/settings")
def save_settings(payload: SettingsPayload):
    provider = payload.llm_provider.strip().lower() or ""
    api_keys = (
        normalise_api_keys(payload.api_keys)
        if payload.api_keys is not None
        else dict(state.api_keys)
    )
    active_api_key = payload.api_key.strip()
    if active_api_key:
        api_keys[provider] = active_api_key
    else:
        api_keys.pop(provider, None)

    state.api_keys = api_keys
    state.mode = normalize_mode(payload.mode)
    state.llm_provider = provider
    state.llm_base_url = payload.llm_base_url.strip()
    state.llm_model = payload.llm_model.strip()
    _configure_llm_environment()
    # Rebuilding the Q&A engine can require re-reading the active PDF and may
    # take several seconds. Keep settings saves responsive and rebuild lazily
    # when the user actually opens Chat.
    state.qa_engine = None
    state.save_config()
    return {"ok": True}


@app.post("/api/llm/models")
def get_llm_models(payload: ModelListPayload):
    return {
        "models": list_available_models(
            provider=payload.llm_provider.strip() or "",
            api_key=payload.api_key.strip(),
            base_url=payload.llm_base_url.strip(),
        )
    }


@app.get("/api/llm/providers")
def get_llm_providers():
    return {"providers": get_provider_catalog()}


# ── Streaming Progress ───────────────────────────────────────────────────────

def _reset_progress(mode: str, run_id: str | None = None) -> str:
    global _PROGRESS_DONE, _PROGRESS_EVENTS, _PROGRESS_RUN_ID, _PROGRESS_SEQ
    progress_run_id = (run_id or "").strip() or f"progress_{uuid.uuid4().hex[:12]}"
    with _PROGRESS_LOCK:
        _PROGRESS_RUN_ID = progress_run_id
        _PROGRESS_SEQ = 0
        _PROGRESS_DONE = False
        _PROGRESS_EVENTS = []
    _publish_progress(
        "extract",
        "Preparing lease analysis",
        percent=1,
        status="active",
        mode=mode,
        run_id=progress_run_id,
    )
    return progress_run_id


def _publish_progress(
    step: str,
    label: str,
    *,
    percent: int | float | None = None,
    status: str = "active",
    detail: str = "",
    mode: str | None = None,
    run_id: str | None = None,
    event_type: str = "progress",
    **extra,
) -> None:
    global _PROGRESS_DONE, _PROGRESS_SEQ
    with _PROGRESS_LOCK:
        target_run_id = (run_id or _PROGRESS_RUN_ID or "").strip()
        if not target_run_id:
            return
        _PROGRESS_SEQ += 1
        event = {
            "type": event_type,
            "run_id": target_run_id,
            "seq": _PROGRESS_SEQ,
            "step": step,
            "label": label,
            "detail": detail,
            "percent": percent,
            "status": status,
            "mode": mode,
            "ts": time.time(),
        }
        event.update({key: value for key, value in extra.items() if value is not None})
        _PROGRESS_EVENTS.append(event)
        if event_type in {"done", "error"}:
            _PROGRESS_DONE = True


def _progress_events_since(run_id: str, last_seq: int) -> tuple[list[dict], bool]:
    with _PROGRESS_LOCK:
        if run_id and _PROGRESS_RUN_ID != run_id:
            return [], False
        events = [event for event in _PROGRESS_EVENTS if event["seq"] > last_seq]
        done = _PROGRESS_DONE
    return events, done


def _make_progress_callback(run_id: str, mode: str) -> Callable[..., None]:
    def callback(
        step: str,
        label: str,
        percent: int | float | None = None,
        status: str = "active",
        detail: str = "",
        **extra,
    ) -> None:
        _publish_progress(
            step,
            label,
            percent=percent,
            status=status,
            detail=detail,
            mode=mode,
            run_id=run_id,
            **extra,
        )

    return callback


@app.get("/api/progress/stream")
async def stream_progress(run_id: str = ""):
    async def event_stream() -> AsyncGenerator[str, None]:
        last_seq = 0
        idle_ticks = 0
        while True:
            events, done = _progress_events_since(run_id, last_seq)
            if events:
                idle_ticks = 0
                for event in events:
                    last_seq = max(last_seq, int(event.get("seq") or 0))
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            elif done:
                break
            else:
                idle_ticks += 1
                if idle_ticks % 100 == 0:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Upload & Extract ──────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    progress_run_id: str = Form(""),
):
    from lease_summary.parsers.document_converter import (
        is_convertible_document,
        get_converted_pdf_path,
    )

    filename = file.filename or ""
    is_pdf = filename.lower().endswith(".pdf")
    is_word = is_convertible_document(filename)

    if not (is_pdf or is_word):
        raise HTTPException(400, "Only PDF and Word (.docx) files are supported.")

    requested_mode = normalize_mode(state.mode)
    run_id = _reset_progress(requested_mode, progress_run_id)
    progress = _make_progress_callback(run_id, requested_mode)
    state.clear_session()

    # Save uploaded file
    progress("extract", "Saving uploaded file", percent=3, detail=filename)
    upload_path = _TEMP_DIR / filename
    with upload_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # Convert Word to PDF if needed
    if is_word:
        try:
            progress("extract", "Converting Word document to PDF", percent=6, detail=filename)
            pdf_path = await asyncio.get_event_loop().run_in_executor(
                None, get_converted_pdf_path, upload_path, _TEMP_DIR
            )
            if pdf_path is None:
                raise HTTPException(500, "Failed to convert Word document to PDF.")
            state.pdf_path = pdf_path
            # Store original filename for display
            state.original_filename = filename
        except Exception as e:
            progress("finalize", f"Document conversion failed: {e}", percent=100, status="error", event_type="error")
            raise HTTPException(500, f"Document conversion failed: {e}")
    else:
        state.pdf_path = upload_path
        state.original_filename = filename

    # Run extraction in thread (CPU-bound + I/O)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _run_extraction, state.pdf_path, progress)
    except ValueError as e:
        progress("finalize", str(e), percent=100, status="error", event_type="error")
        raise HTTPException(400, str(e))
    except Exception as e:
        progress("finalize", f"Analysis failed: {e}", percent=100, status="error", event_type="error")
        raise
    progress("finalize", "Analysis complete", percent=100, status="done", event_type="done")
    return result


def _run_extraction(pdf_path: Path, progress_callback: Callable[..., None] | None = None) -> dict:
    """Run the appropriate pipeline and return JSON-serialisable summary."""
    _configure_llm_environment()

    output_dir = _TEMP_DIR / "output"
    output_dir.mkdir(exist_ok=True)

    mode = normalize_mode(state.mode)
    llm_enabled = state.llm_enabled()
    provider = (state.llm_provider or "").strip().lower()
    model = state.llm_model or get_provider_default_model(provider)
    base_url = state.llm_base_url or get_provider_default_base_url(provider)
    engine_info = {
        "requested_mode": mode,
        "effective_mode": mode,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "llm_enabled": llm_enabled,
        "fallback_reason": "",
        "semantic_candidates_count": 0,
        "final_decisions_count": 0,
        "warnings": [],
    }

    if mode == "standard" or not llm_enabled:
        from lease_summary.pipeline import run
        if mode != "standard" and not llm_enabled:
            engine_info["effective_mode"] = "standard_regex_fallback"
            engine_info["fallback_reason"] = _llm_fallback_reason(provider, model, base_url)
            if progress_callback:
                progress_callback(
                    "rule",
                    "LLM unavailable; using Standard Rule/Regex extraction",
                    percent=15,
                    status="active",
                    detail=engine_info["fallback_reason"],
                    fallback_reason=engine_info["fallback_reason"],
                )
        result = run(pdf_path, output_dir=output_dir, progress_callback=progress_callback)
    else:
        from lease_summary_v2.pipeline import run
        extraction_mode = "pure_llm" if mode == "pure_llm" else "ai_enhanced"
        result = run(
            pdf_path,
            output_dir=output_dir,
            extraction_mode=extraction_mode,
            progress_callback=progress_callback,
        )
        trace = result.get("trace")
        engine_info["effective_mode"] = extraction_mode
        if trace is not None:
            engine_info["semantic_candidates_count"] = getattr(trace, "semantic_candidates_count", 0)
            engine_info["final_decisions_count"] = getattr(trace, "final_decisions_count", 0)
            engine_info["warnings"] = list(getattr(trace, "warnings", []) or [])
            trace.requested_mode = mode
            trace.effective_mode = extraction_mode
            trace.provider = provider
            trace.model = model
            if getattr(trace, "semantic_candidates_count", 0) == 0 and extraction_mode != "standard":
                reason = (
                    "AI Enhanced ran, but the AI scan returned no evidence-backed fields; "
                    "visible values are from Rule/Regex extraction."
                )
                engine_info["effective_mode"] = "ai_enhanced_rule_fallback"
                engine_info["fallback_reason"] = reason
                trace.effective_mode = "ai_enhanced_rule_fallback"
                trace.fallback_reason = reason
                if reason not in trace.warnings:
                    trace.warnings.append(reason)
                if reason not in engine_info["warnings"]:
                    engine_info["warnings"].append(reason)

    state.summary = result["summary"]
    state.excel_path = result["excel"]
    state.doc_index = result.get("doc_index")
    state.evidence_index = result.get("evidence_index")
    state.extraction_trace = result.get("trace")
    state.engine_info = engine_info
    doc_text = result.get("doc_text")
    state.ocr_word_data = doc_text.word_bboxes if doc_text else None
    _refresh_qa_engine(prebuilt_qa=result.get("qa"))

    return _serialise_summary(result["summary"])


def _llm_fallback_reason(provider: str, model: str, base_url: str) -> str:
    provider_label = provider or "provider"
    if not provider:
        return "AI Enhanced is selected, but no LLM provider is configured."
    if not model:
        return f"AI Enhanced is selected for {provider_label}, but no model is configured."
    if provider in {"custom", "lmstudio"} and not base_url:
        return f"AI Enhanced is selected for {provider_label}, but no base URL is configured."
    return f"AI Enhanced is selected for {provider_label}, but the provider is missing an API key or is not reachable."


def _configure_llm_environment() -> None:
    provider = (state.llm_provider or "").strip().lower()
    api_key = state.active_api_key(provider)
    base_url = state.llm_base_url or get_provider_default_base_url(provider)
    model = state.llm_model or get_provider_default_model(provider)
    _set_env("LLM_API_KEY", api_key)
    _set_env("LLM_PROVIDER", provider)
    _set_env("LLM_BASE_URL", base_url)
    _set_env("LLM_MODEL", model)
    _set_env("MOONSHOT_API_KEY", api_key if provider == "moonshot" else "")
    _set_env("MOONSHOT_BASE_URL", base_url if provider == "moonshot" else "")
    _set_env("MOONSHOT_MODEL", model if provider == "moonshot" else "")


def _refresh_qa_engine(*, prebuilt_qa=None) -> None:
    if not state.llm_enabled() or not state.summary or not state.pdf_path:
        state.qa_engine = None
        return

    if prebuilt_qa is not None and prebuilt_qa.available():
        state.qa_engine = prebuilt_qa
        return

    try:
        from lease_summary_v2.parsers.pdf_text import DocumentText, PageText, extract_text as _et
        from lease_summary_v2.qa.engine import QAEngine

        if state.doc_index is not None:
            doc = DocumentText(
                pages=list(state.doc_index.pages),
                source_path=state.pdf_path,
                parsed_with_ocr=bool(state.summary.document_meta.parsed_with_ocr),
            )
        else:
            doc = _et(state.pdf_path)
        # Inject structured summary as page 0 so the LLM has validated data.
        ctx = _make_summary_context(state.summary)
        if ctx:
            doc.pages.insert(0, PageText(page_num=0, text=ctx, has_text=True))
        state.qa_engine = QAEngine(doc)
    except Exception:
        state.qa_engine = None


def _serialise_summary(summary) -> dict:
    """Convert LeaseSummary model to a flat JSON dict for the frontend."""
    def field(f):
        # Expose evidence (page + quote) so the frontend can jump to and
        # highlight the source location when the user clicks a field.
        ev = f.evidence[0] if f.evidence else None
        evidence = [
            {
                "page": item.page,
                "quote": item.quote,
                "method": str(item.method.value if hasattr(item.method, "value") else item.method),
                "chunk_id": getattr(item, "chunk_id", None),
                "tool_call_id": getattr(item, "tool_call_id", None),
            }
            for item in (f.evidence or [])
            if item.quote
        ]
        ev_method = None
        if ev is not None:
            ev_method = str(ev.method.value if hasattr(ev.method, "value") else ev.method)
        source = getattr(f, "source", None) or ev_method
        sources = list(getattr(f, "sources", []) or ([source] if source else []))
        return {
            "value": _fmt(f.value),
            "confidence": round(f.confidence, 2),
            "flag": f.review_flag,
            "page": ev.page if ev else None,
            "quote": ev.quote if ev else None,
            "source": source,
            "sources": sources,
            "needs_review": bool(getattr(f, "needs_review", False)),
            "reason_summary": getattr(f, "reason_summary", "") or "",
            "trace_id": getattr(f, "trace_id", None) or getattr(state.extraction_trace, "run_id", None),
            "evidence": evidence,
        }

    s = summary
    result: dict = {
        "document": {
            "filename": s.document_meta.source_filename,
            "original_filename": getattr(state, 'original_filename', None) or s.document_meta.source_filename,
            "type": s.document_meta.document_type,
            "pages": s.document_meta.pages,
            "ocr": s.document_meta.parsed_with_ocr,
        },
        "engine": _serialise_engine_info(),
        "trace": _serialise_trace(state.extraction_trace),
        "parties": {
            "landlord_name": field(s.parties.landlord_name),
            "landlord_address": field(s.parties.landlord_registered_address),
            "landlord_agent": field(s.parties.landlord_agent),
            "landlord_solicitor": field(s.parties.landlord_solicitor),
            "tenant_name": field(s.parties.tenant_name),
            "tenant_address": field(s.parties.tenant_registered_address),
        },
        "premises": {
            "full_address": field(s.premises.full_address),
            "building_name": field(s.premises.building_name),
            "floor_suite": field(s.premises.floor_suite),
            "area_sqft": field(s.premises.rentable_area_sqft),
            "area_comment": field(s.premises.area_comment),
        },
        "term": {
            "signing_date": field(s.term.lease_signing_date),
            "scheduled_commencement": field(s.term.scheduled_commencement_date),
            "commencement": field(s.term.lease_commencement_date),
            "expiry": field(s.term.lease_expiry_date),
            "term_months": field(s.term.lease_term_months),
            "rent_free": field(s.term.rent_free_period_text),
            "fit_out": field(s.term.fit_out_period_text),
            "option_to_renew": field(s.term.option_to_renew_text),
            "trigger_date": field(s.term.trigger_date_text),
            "right_of_expansion": field(s.term.right_of_expansion_text),
            "break_clause": field(s.term.tenant_termination_right_text),
        },
        "financials": {
            "monthly_rent": field(s.financials.monthly_rent_hkd),
            "monthly_rent_psf": field(s.financials.monthly_rent_psf_hkd),
            "management_fee": field(s.financials.management_fee_monthly_hkd),
            "management_fee_psf": field(s.financials.management_fee_psf_hkd),
            "rates_quarterly": field(s.financials.rates_quarterly_hkd),
            "rates_monthly": field(s.financials.rates_monthly_hkd),
            "govt_rent": field(s.financials.government_rent_monthly_hkd),
            "security_deposit": field(s.financials.security_deposit_hkd),
            "deposit_note": field(s.financials.security_deposit_note),
            "transferred_deposit": field(s.financials.transferred_security_deposit_hkd),
            "deposit_balance": field(s.financials.security_deposit_balance_hkd),
            "fitout_deposit": field(s.financials.fit_out_deposit_hkd),
            "advance_rent": field(s.financials.advance_rent_text),
        },
        "clauses": {
            "permitted_use": field(s.clauses.user_clause_text),
            "handover": field(s.clauses.handover_condition_text),
            "subletting": field(s.clauses.subletting_text),
            "signage": field(s.clauses.signage_text),
            "parking": field(s.clauses.parking_text),
            "restoration": field(s.clauses.restoration_obligations_text),
        },
    }
    # Apply user edits
    for full_key, value in state.field_overrides.items():
        section, fkey = full_key.split(".", 1)
        if section in result and fkey in result[section]:
            result[section][fkey]["value"] = value
    return result


def _serialise_engine_info() -> dict:
    info = dict(getattr(state, "engine_info", {}) or {})
    if not info:
        mode = normalize_mode(state.mode)
        provider = (state.llm_provider or "").strip().lower()
        info = {
            "requested_mode": mode,
            "effective_mode": mode,
            "provider": provider,
            "model": state.llm_model or get_provider_default_model(provider),
            "base_url": state.llm_base_url or get_provider_default_base_url(provider),
            "llm_enabled": state.llm_enabled(),
            "fallback_reason": "",
            "semantic_candidates_count": getattr(state.extraction_trace, "semantic_candidates_count", 0) if state.extraction_trace else 0,
            "final_decisions_count": getattr(state.extraction_trace, "final_decisions_count", 0) if state.extraction_trace else 0,
            "warnings": list(getattr(state.extraction_trace, "warnings", []) or []) if state.extraction_trace else [],
        }
    info.pop("base_url", None)
    return info


@app.get("/api/trace")
def get_trace():
    if not state.extraction_trace:
        raise HTTPException(404, "No extraction trace available.")
    return _serialise_trace(state.extraction_trace)


def _serialise_trace(trace) -> dict | None:
    if trace is None:
        return None
    if hasattr(trace, "model_dump"):
        data = trace.model_dump()
    elif isinstance(trace, dict):
        data = dict(trace)
    else:
        return None
    return data


def _fmt(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, float):
        return f"{val:,.2f}"
    from decimal import Decimal
    if isinstance(val, Decimal):
        return f"{val:,.2f}"
    import datetime
    if isinstance(val, datetime.date):
        return val.strftime("%d %b %Y")
    return str(val)


def _set_env(name: str, value: str) -> None:
    if value:
        os.environ[name] = value
    elif name in os.environ:
        del os.environ[name]


def _make_summary_context(summary) -> str:
    """Serialise extracted summary into readable text for QA context injection.
    Each field is annotated with its source page so the LLM can cite correctly."""
    def v(f):
        return _fmt(f.value) if f.value is not None else "—"

    def src(f):
        ev = f.evidence[0] if f.evidence else None
        return f" [p.{ev.page}]" if ev and ev.page else ""

    s = summary
    lines = [
        "=== EXTRACTED LEASE SUMMARY (validated structured data) ===",
        "When citing information from this summary, use the [p.N] annotation as the page reference.",
        "",
        f"Landlord: {v(s.parties.landlord_name)}{src(s.parties.landlord_name)}",
        f"Landlord Address: {v(s.parties.landlord_registered_address)}{src(s.parties.landlord_registered_address)}",
        f"Landlord Agent: {v(s.parties.landlord_agent)}{src(s.parties.landlord_agent)}",
        f"Landlord Solicitor: {v(s.parties.landlord_solicitor)}{src(s.parties.landlord_solicitor)}",
        f"Tenant: {v(s.parties.tenant_name)}{src(s.parties.tenant_name)}",
        f"Tenant Address: {v(s.parties.tenant_registered_address)}{src(s.parties.tenant_registered_address)}",
        f"Premises: {v(s.premises.full_address)}{src(s.premises.full_address)}",
        f"Building: {v(s.premises.building_name)}{src(s.premises.building_name)}",
        f"Floor/Suite: {v(s.premises.floor_suite)}{src(s.premises.floor_suite)}",
        f"Rentable Area (sq ft): {v(s.premises.rentable_area_sqft)}{src(s.premises.rentable_area_sqft)}",
        f"Lease Signing Date: {v(s.term.lease_signing_date)}{src(s.term.lease_signing_date)}",
        f"Lease Commencement: {v(s.term.lease_commencement_date)}{src(s.term.lease_commencement_date)}",
        f"Lease Expiry: {v(s.term.lease_expiry_date)}{src(s.term.lease_expiry_date)}",
        f"Lease Term (months): {v(s.term.lease_term_months)}{src(s.term.lease_term_months)}",
        f"Rent Free Period: {v(s.term.rent_free_period_text)}{src(s.term.rent_free_period_text)}",
        f"Fit-Out Period: {v(s.term.fit_out_period_text)}{src(s.term.fit_out_period_text)}",
        f"Option to Renew: {v(s.term.option_to_renew_text)}{src(s.term.option_to_renew_text)}",
        f"Break Clause: {v(s.term.tenant_termination_right_text)}{src(s.term.tenant_termination_right_text)}",
        f"Monthly Rent (HKD): {v(s.financials.monthly_rent_hkd)}{src(s.financials.monthly_rent_hkd)}",
        f"Monthly Rent PSF (HKD): {v(s.financials.monthly_rent_psf_hkd)}{src(s.financials.monthly_rent_psf_hkd)}",
        f"Management Fee Monthly (HKD): {v(s.financials.management_fee_monthly_hkd)}{src(s.financials.management_fee_monthly_hkd)}",
        f"Management Fee PSF (HKD): {v(s.financials.management_fee_psf_hkd)}{src(s.financials.management_fee_psf_hkd)}",
        f"Rates Quarterly (HKD): {v(s.financials.rates_quarterly_hkd)}{src(s.financials.rates_quarterly_hkd)}",
        f"Rates Monthly (HKD): {v(s.financials.rates_monthly_hkd)}{src(s.financials.rates_monthly_hkd)}",
        f"Government Rent Monthly (HKD): {v(s.financials.government_rent_monthly_hkd)}{src(s.financials.government_rent_monthly_hkd)}",
        f"Security Deposit (HKD): {v(s.financials.security_deposit_hkd)}{src(s.financials.security_deposit_hkd)}",
        f"Security Deposit Note: {v(s.financials.security_deposit_note)}{src(s.financials.security_deposit_note)}",
        f"Transferred Deposit (HKD): {v(s.financials.transferred_security_deposit_hkd)}{src(s.financials.transferred_security_deposit_hkd)}",
        f"Deposit Balance (HKD): {v(s.financials.security_deposit_balance_hkd)}{src(s.financials.security_deposit_balance_hkd)}",
        f"Fit-Out Deposit (HKD): {v(s.financials.fit_out_deposit_hkd)}{src(s.financials.fit_out_deposit_hkd)}",
        f"Advance Rent: {v(s.financials.advance_rent_text)}{src(s.financials.advance_rent_text)}",
        f"Permitted Use: {v(s.clauses.user_clause_text)}{src(s.clauses.user_clause_text)}",
        f"Handover Condition: {v(s.clauses.handover_condition_text)}{src(s.clauses.handover_condition_text)}",
        f"Subletting: {v(s.clauses.subletting_text)}{src(s.clauses.subletting_text)}",
        f"Signage: {v(s.clauses.signage_text)}{src(s.clauses.signage_text)}",
        f"Parking: {v(s.clauses.parking_text)}{src(s.clauses.parking_text)}",
        f"Restoration: {v(s.clauses.restoration_obligations_text)}{src(s.clauses.restoration_obligations_text)}",
        "=== END OF EXTRACTED SUMMARY ===",
    ]
    return "\n".join(lines)


# ── PDF Serve ─────────────────────────────────────────────────────────────────

@app.get("/api/pdf")
def serve_pdf():
    if not state.pdf_path or not state.pdf_path.exists():
        raise HTTPException(404, "No PDF loaded.")
    return FileResponse(state.pdf_path, media_type="application/pdf")


@app.get("/api/pdf/words")
def get_pdf_words():
    """Return OCR word bounding boxes for all pages (only populated for scanned PDFs).

    Each word entry is [x0, y0, x1, y1, word] in PyMuPDF page coordinates
    (top-left origin, y increases downward, units = PDF points). The frontend
    converts to canvas pixels by multiplying by pdfScale.
    """
    if not state.ocr_word_data:
        return {"pages": {}}
    return {"pages": {str(k): v for k, v in state.ocr_word_data.items()}}


# ── Q&A (SSE streaming) ───────────────────────────────────────────────────────

@app.post("/api/qa")
async def ask_question(payload: QAPayload):
    if not state.summary:
        raise HTTPException(400, "No lease loaded.")
    if not state.llm_enabled():
        raise HTTPException(400, "LLM provider required for Q&A.")
    _configure_llm_environment()  # ensure env vars are current before every chat call
    if not state.qa_engine or not state.qa_engine.available():
        _refresh_qa_engine()
    if not state.qa_engine or not state.qa_engine.available():
        raise HTTPException(
            400,
            "Q&A engine not available — check provider settings and runtime dependencies.",
        )

    async def generate() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, state.qa_engine.ask, payload.question
        )
        if result.error:
            yield f"data: {json.dumps({'type': 'error', 'content': result.error})}\n\n"
            return

        # Stream answer word by word for a natural feel
        words = result.answer.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
            await asyncio.sleep(0.03)

        # Send metadata at the end
        yield f"data: {json.dumps({'type': 'done', 'pages': result.page_references, 'quote': result.quote})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Batch export ──────────────────────────────────────────────────────────────

@app.post("/api/batch")
async def batch_export(
    files: list[UploadFile] = File(...),
    mode: str = Form("standard"),
):
    from lease_summary.parsers.document_converter import (
        is_convertible_document,
        get_converted_pdf_path,
    )

    if not files:
        raise HTTPException(400, "No files provided.")

    loop = asyncio.get_event_loop()
    batch_dir = _TEMP_DIR / "batch"
    batch_dir.mkdir(exist_ok=True)

    def _prepare_pdf(uploaded: UploadFile) -> Path | None:
        """Save and convert if necessary, return PDF path or None."""
        filename = uploaded.filename or ""
        is_pdf = filename.lower().endswith(".pdf")
        is_word = is_convertible_document(filename)

        if not (is_pdf or is_word):
            return None

        # Save uploaded file
        upload_path = batch_dir / filename
        with upload_path.open("wb") as f:
            shutil.copyfileobj(uploaded.file, f)

        # Convert if needed
        if is_word:
            pdf_path = get_converted_pdf_path(upload_path, batch_dir)
            return pdf_path
        return upload_path

    # Single file → return Excel directly (no zip)
    if len(files) == 1:
        uploaded = files[0]
        pdf_path = await loop.run_in_executor(None, _prepare_pdf, uploaded)
        if pdf_path is None:
            raise HTTPException(400, "Only PDF and Word (.docx) files are supported.")
        batch_mode = normalize_mode(mode or state.mode)
        excel_path = await loop.run_in_executor(None, _run_batch_single, pdf_path, batch_mode)
        if not excel_path or not Path(excel_path).exists():
            raise HTTPException(500, "Failed to process the document.")
        stem = Path(uploaded.filename).stem
        return FileResponse(
            excel_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"'},
        )

    # Multiple files → return ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for uploaded in files:
            pdf_path = await loop.run_in_executor(None, _prepare_pdf, uploaded)
            if pdf_path is None:
                continue
            batch_mode = normalize_mode(mode or state.mode)
            excel_path = await loop.run_in_executor(None, _run_batch_single, pdf_path, batch_mode)
            if excel_path and Path(excel_path).exists():
                zf.write(excel_path, Path(uploaded.filename).stem + ".xlsx")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="opus_lease_summaries.zip"'},
    )


def _run_batch_single(pdf_path: Path, mode: str = "standard"):
    """Run the selected pipeline for a single PDF; returns Excel path or None."""
    output_dir = _TEMP_DIR / "batch_output"
    output_dir.mkdir(exist_ok=True)
    try:
        mode = normalize_mode(mode)
        if mode in {"ai_enhanced", "pure_llm"} and state.llm_enabled():
            from lease_summary_v2.pipeline import run
            result = run(pdf_path, output_dir=output_dir, extraction_mode=mode)
        else:
            from lease_summary.pipeline import run
            result = run(pdf_path, output_dir=output_dir)
        return result.get("excel")
    except Exception:
        return None


# ── Field edits ───────────────────────────────────────────────────────────────

@app.patch("/api/fields")
def patch_fields(updates: list[FieldUpdate]):
    """Store user-edited field values; applied on top of extracted data."""
    if not state.summary:
        raise HTTPException(400, "No lease loaded.")
    for u in updates:
        state.field_overrides[f"{u.section}.{u.key}"] = u.value
    return {"ok": True}


# ── Export ────────────────────────────────────────────────────────────────────

@app.get("/api/export")
def export_excel():
    if not state.excel_path or not state.excel_path.exists():
        raise HTTPException(404, "No Excel file generated yet.")

    # If user has edited fields, regenerate Excel with overrides applied
    if state.field_overrides:
        try:
            from copy import deepcopy
            from lease_summary.config import TEMPLATE_PATH
            from lease_summary.writers.excel_writer import write_excel

            summary = deepcopy(state.summary)
            _apply_field_overrides(summary, state.field_overrides)

            export_path = state.excel_path.with_suffix(".export.xlsx")
            write_excel(summary, TEMPLATE_PATH, export_path)
            filename = state.excel_path.name
            return FileResponse(
                export_path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as exc:
            import traceback
            print("Export regeneration failed:")
            traceback.print_exc()
            raise HTTPException(500, f"Export failed: {exc}")

    filename = state.excel_path.name
    return FileResponse(
        state.excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Maps frontend field keys (used in _serialise_summary / app.js) to Pydantic model field names
_FIELD_KEY_MAP = {
    "term": {
        "signing_date": "lease_signing_date",
        "scheduled_commencement": "scheduled_commencement_date",
        "commencement": "lease_commencement_date",
        "expiry": "lease_expiry_date",
        "term_months": "lease_term_months",
        "rent_free": "rent_free_period_text",
        "fit_out": "fit_out_period_text",
        "option_to_renew": "option_to_renew_text",
        "trigger_date": "trigger_date_text",
        "right_of_expansion": "right_of_expansion_text",
        "break_clause": "tenant_termination_right_text",
    },
    "premises": {
        "area_sqft": "rentable_area_sqft",
    },
    "financials": {
        "monthly_rent": "monthly_rent_hkd",
        "monthly_rent_psf": "monthly_rent_psf_hkd",
        "management_fee": "management_fee_monthly_hkd",
        "management_fee_psf": "management_fee_psf_hkd",
        "rates_quarterly": "rates_quarterly_hkd",
        "rates_monthly": "rates_monthly_hkd",
        "govt_rent": "government_rent_monthly_hkd",
        "security_deposit": "security_deposit_hkd",
        "deposit_note": "security_deposit_note",
    },
    "clauses": {
        "signage": "signage_text",
        "subletting": "subletting_text",
        "parking": "parking_text",
        "restoration": "restoration_obligations_text",
    },
}


def _apply_field_overrides(summary, overrides: dict[str, str]) -> None:
    """Apply user-edited values to the LeaseSummary model for export."""
    for full_key, value in overrides.items():
        section, key = full_key.split(".", 1)
        # Map frontend key to Pydantic model field name
        model_key = _FIELD_KEY_MAP.get(section, {}).get(key, key)
        try:
            section_obj = getattr(summary, section, None)
            if section_obj is None:
                continue
            result_obj = getattr(section_obj, model_key, None)
            if result_obj is None:
                continue
            if hasattr(result_obj, "value"):
                result_obj.value = value
        except Exception:
            pass


# ── Static frontend ───────────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


# ── Entry point ───────────────────────────────────────────────────────────────

def start(port: int = 7842):
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
