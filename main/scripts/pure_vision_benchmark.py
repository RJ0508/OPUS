"""Run pure vision LLM extraction against rendered PDF pages.

This is an evaluation tool, not the production extraction path. It renders each
PDF page to an image, asks a vision-capable model for structured JSON, merges
the page-level answers, and writes the normal summary Excel/JSON outputs.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import fitz

from lease_summary_v2.extractors import ai_primary
from lease_summary_v2.models import DocumentMeta, LeaseSummary, SummaryMeta
from lease_summary_v2.parsers.pdf_text import extract_text
from lease_summary_v2.parsers.section_splitter import split
from lease_summary_v2.pipeline import _detect_doc_type
from lease_summary_v2.validators.business_rules import validate_business_rules
from lease_summary_v2.validators.field_validator import validate_mandatory
from lease_summary_v2.writers.excel_writer import write_excel
from lease_summary_v2.writers.json_writer import write_json, write_review_json
from lease_summary_v2.config import TEMPLATE_PATH


_VISION_PROMPT = """\
Extract Hong Kong lease summary fields from this PDF page image.

Return one valid JSON object only. No markdown, no prose. Omit fields not visible
on this page. Do not guess from outside this page.

Use these keys when visible:
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
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--provider", choices=["local", "openai"], default="openai")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--zoom", type=float, default=1.35)
    args = parser.parse_args()

    input_pdf = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc_text = extract_text(input_pdf)
    sections = split(doc_text)
    doc_type = _detect_doc_type(sections.principal_terms)
    if doc_type == "not_a_lease":
        raise ValueError(f"Not a lease document: {input_pdf}")

    data: dict[str, Any] = {}
    page_results: list[dict[str, Any]] = []
    page_count = _page_count(input_pdf)
    max_pages = args.max_pages or page_count
    for page_num, image_url in _render_page_images(
        input_pdf,
        max_pages=min(max_pages, page_count),
        zoom=args.zoom,
    ):
        page_data = (
            _call_local_native(args.model, args.base_url, image_url, page_num)
            if args.provider == "local"
            else _call_openai_vision(args.model, args.base_url, args.api_key, image_url, page_num)
        )
        if page_data:
            page_results.append({"page": page_num, "data": page_data})
            _merge_vision_data(data, page_data)

    summary = LeaseSummary(
        document_meta=DocumentMeta(
            source_filename=input_pdf.name,
            document_type=doc_type,
            parsed_with_ocr=doc_text.parsed_with_ocr,
            pages=len(doc_text.pages),
        ),
        summary_meta=SummaryMeta(summary_date=datetime.date.today()),
    )
    ai_primary._apply(summary, doc_text, data, override_low_confidence=True, confidence=0.78)
    validate_mandatory(summary)
    validate_business_rules(summary)

    stem = input_pdf.stem
    excel_path = output_dir / f"{stem}.summary.xlsx"
    json_path = output_dir / f"{stem}.extraction.json"
    review_path = output_dir / f"{stem}.review.json"
    raw_path = output_dir / f"{stem}.vision_raw.json"

    write_excel(summary, TEMPLATE_PATH, excel_path)
    write_json(summary, json_path)
    write_review_json(summary, review_path)
    raw_path.write_text(
        json.dumps({"merged": data, "pages": page_results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(excel_path)
    return 0


def _page_count(input_pdf: Path) -> int:
    with fitz.open(input_pdf) as doc:
        return len(doc)


def _render_page_images(input_pdf: Path, *, max_pages: int, zoom: float):
    with fitz.open(input_pdf) as doc:
        for index, page in enumerate(doc[:max_pages], start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            encoded = base64.b64encode(pix.tobytes("jpeg", jpg_quality=72)).decode("ascii")
            yield index, f"data:image/jpeg;base64,{encoded}"


def _call_local_native(model: str, base_url: str, image_url: str, page_num: int) -> dict | None:
    endpoint = f"{_local_base(base_url)}/api/v1/chat"
    payload = {
        "model": model,
        "input": [
            {"type": "text", "content": f"Page {page_num}.\n{_VISION_PROMPT}"},
            {"type": "image", "data_url": image_url},
        ],
        "max_output_tokens": int(os.environ.get("VISION_MAX_OUTPUT_TOKENS", "2400")),
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=int(os.environ.get("VISION_TIMEOUT", "180"))) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"page {page_num}: local call failed: {exc}", file=sys.stderr)
        return None
    raw = ai_primary._extract_lmstudio_native_content(body)
    return ai_primary._parse_json(raw or "")


def _call_openai_vision(
    model: str,
    base_url: str,
    api_key: str,
    image_url: str,
    page_num: int,
) -> dict | None:
    from openai import OpenAI

    api_key = api_key or _load_config_api_key()
    base_url = base_url or _load_config_base_url() or "https://api.moonshot.cn/v1"
    client = OpenAI(api_key=api_key, base_url=base_url)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Page {page_num}.\n{_VISION_PROMPT}"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            max_tokens=int(os.environ.get("VISION_MAX_OUTPUT_TOKENS", "2400")),
            temperature=0,
        )
    except Exception as exc:
        print(f"page {page_num}: OpenAI-compatible call failed: {exc}", file=sys.stderr)
        return None
    raw = response.choices[0].message.content or ""
    return ai_primary._parse_json(raw)


def _merge_vision_data(merged: dict[str, Any], candidate: dict) -> None:
    long_text_fields = {
        "operating_expense_note",
        "security_deposit_note",
        "advance_rent_text",
        "rent_free_period_text",
        "fit_out_period_text",
        "option_to_renew_text",
        "trigger_date_text",
        "right_of_expansion_text",
        "tenant_termination_right_text",
        "handover_condition",
        "break_clause_text",
        "subletting_text",
        "signage_text",
        "parking_text",
        "restoration_obligations_text",
    }
    for key in ai_primary._FIELD_MAP:
        value = candidate.get(key)
        if ai_primary._is_missing_value(value):
            continue
        current = merged.get(key)
        if ai_primary._is_missing_value(current):
            merged[key] = value
            continue
        if key in long_text_fields and _better_long_text(value, current):
            merged[key] = value


def _better_long_text(value: Any, current: Any) -> bool:
    if not isinstance(value, str) or not isinstance(current, str):
        return False
    normalized = value.strip().lower()
    current_normalized = current.strip().lower()
    if current_normalized in {"n/a", "na", "nil", "none"}:
        return True
    if normalized in {"n/a", "na", "nil", "none"}:
        return False
    return len(value.strip()) > len(current.strip()) * 1.15


def _local_base(base_url: str) -> str:
    base = (base_url or "http://127.0.0.1:1234/v1").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _load_config_api_key() -> str:
    path = Path.home() / ".opus_lease_summary" / "config.json"
    if not path.exists():
        return os.environ.get("LLM_API_KEY") or os.environ.get("MOONSHOT_API_KEY") or ""
    config = json.loads(path.read_text(encoding="utf-8"))
    provider = config.get("llm_provider", "moonshot")
    return (config.get("api_keys", {}) or {}).get(provider) or config.get("api_key", "")


def _load_config_base_url() -> str:
    path = Path.home() / ".opus_lease_summary" / "config.json"
    if not path.exists():
        return os.environ.get("LLM_BASE_URL") or os.environ.get("MOONSHOT_BASE_URL") or ""
    config = json.loads(path.read_text(encoding="utf-8"))
    return config.get("llm_base_url", "")


if __name__ == "__main__":
    raise SystemExit(main())
