#!/usr/bin/env python3
"""Evaluate extraction JSON outputs against manual lease ground truth."""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


FIELD_MAP = {
    "landlord_name": "parties.landlord_name",
    "landlord_registered_address": "parties.landlord_registered_address",
    "landlord_agent": "parties.landlord_agent",
    "landlord_solicitor": "parties.landlord_solicitor",
    "tenant_name": "parties.tenant_name",
    "tenant_registered_address": "parties.tenant_registered_address",
    "tenant_contact_person": "parties.tenant_contact_person",
    "premises_full_address": "premises.full_address",
    "building_name": "premises.building_name",
    "floor_suite": "premises.floor_suite",
    "rentable_area_sqft": "premises.rentable_area_sqft",
    "lettable_area_sqft": "premises.rentable_area_sqft",
    "term_start": "term.lease_commencement_date",
    "term_end": "term.lease_expiry_date",
    "term_months": "term.lease_term_months",
    "lease_signing_or_offer_date": "term.lease_signing_date",
    "monthly_rent_hkd": "financials.monthly_rent_hkd",
    "monthly_rent_psf_hkd": "financials.monthly_rent_psf_hkd",
    "management_fee_monthly_hkd": "financials.management_fee_monthly_hkd",
    "service_charge_monthly_hkd": "financials.management_fee_monthly_hkd",
    "operating_charges_monthly_hkd": "financials.management_fee_monthly_hkd",
    "management_fee_psf_hkd": "financials.management_fee_psf_hkd",
    "service_charge_psf_hkd": "financials.management_fee_psf_hkd",
    "rates_quarterly_hkd": "financials.rates_quarterly_hkd",
    "rates_monthly_hkd": "financials.rates_monthly_hkd",
    "government_rates_monthly_hkd": "financials.rates_monthly_hkd",
    "government_rent_monthly_hkd": "financials.government_rent_monthly_hkd",
    "security_deposit_hkd": "financials.security_deposit_hkd",
    "security_deposit_multiple": "financials.security_deposit_multiple",
    "transferred_security_deposit_hkd": "financials.transferred_security_deposit_hkd",
    "security_deposit_balance_hkd": "financials.security_deposit_balance_hkd",
    "fitout_deposit_hkd": "financials.fit_out_deposit_hkd",
    "rent_free_period_text": "term.rent_free_period_text",
    "option_to_renew_text": "term.option_to_renew_text",
    "conditional_termination_text": "term.tenant_termination_right_text",
    "break_clause_text": "clauses.break_clause_text",
    "permitted_use": "clauses.user_clause_text",
    "handover_condition_text": "clauses.handover_condition_text",
    "subletting_text": "clauses.subletting_text",
    "signage_text": "clauses.signage_text",
    "parking_text": "clauses.parking_text",
    "restoration_obligations_text": "clauses.restoration_obligations_text",
}

NUMERIC_FIELDS = {
    "rentable_area_sqft",
    "lettable_area_sqft",
    "term_months",
    "monthly_rent_hkd",
    "monthly_rent_psf_hkd",
    "management_fee_monthly_hkd",
    "service_charge_monthly_hkd",
    "operating_charges_monthly_hkd",
    "management_fee_psf_hkd",
    "service_charge_psf_hkd",
    "rates_quarterly_hkd",
    "rates_monthly_hkd",
    "government_rates_monthly_hkd",
    "government_rent_monthly_hkd",
    "security_deposit_hkd",
    "security_deposit_multiple",
    "transferred_security_deposit_hkd",
    "security_deposit_balance_hkd",
    "fitout_deposit_hkd",
}

DATE_FIELDS = {
    "term_start",
    "term_end",
    "lease_signing_or_offer_date",
}

CLAUSE_FIELDS = {
    "rent_free_period_text",
    "option_to_renew_text",
    "conditional_termination_text",
    "break_clause_text",
    "permitted_use",
    "handover_condition_text",
    "subletting_text",
    "signage_text",
    "parking_text",
    "restoration_obligations_text",
}

SCORED_STATUSES = {"found", "computed"}
NEGATIVE_STATUSES = {"not_stated", "not_applicable"}


@dataclass
class EvalRow:
    document_id: str
    field: str
    output_path: str
    expected: Any
    actual: Any
    status: str
    score: float
    note: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groundtruth", required=True)
    parser.add_argument("--outputs", required=True, help="Directory containing *.extraction.json")
    parser.add_argument("--out", required=True, help="Output directory for evaluation files")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    gt_path = Path(args.groundtruth)
    outputs_dir = Path(args.outputs)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    rows: list[EvalRow] = []
    doc_summaries = []

    for doc in gt["documents"]:
        if doc.get("exclude_from_lease_accuracy"):
            continue
        source_pdf = Path(doc["source_pdf"])
        extraction_path = outputs_dir / f"{source_pdf.stem}.extraction.json"
        if not extraction_path.exists():
            doc_rows = [
                EvalRow(doc["document_id"], "__document__", "", None, None, "output_missing", 0.0)
            ]
            rows.extend(doc_rows)
            doc_summaries.append(_summarize_doc(doc["document_id"], doc_rows))
            continue
        extracted = json.loads(extraction_path.read_text(encoding="utf-8"))
        doc_rows = evaluate_doc(doc, extracted)
        rows.extend(doc_rows)
        doc_summaries.append(_summarize_doc(doc["document_id"], doc_rows))

    summary = summarize(rows, doc_summaries, label=args.label)
    detail_path = out_dir / f"{args.label or 'evaluation'}_details.csv"
    summary_path = out_dir / f"{args.label or 'evaluation'}_summary.json"
    docs_path = out_dir / f"{args.label or 'evaluation'}_docs.csv"
    write_details(detail_path, rows)
    write_docs(docs_path, doc_summaries)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"details={detail_path}")
    print(f"docs={docs_path}")
    return 0


def evaluate_doc(doc: dict, extracted: dict) -> list[EvalRow]:
    rows: list[EvalRow] = []
    for field, gt_result in doc.get("fields", {}).items():
        if field not in FIELD_MAP or not isinstance(gt_result, dict):
            continue
        gt_status = gt_result.get("status", "found")
        expected = gt_result.get("value")
        output_path = FIELD_MAP[field]
        actual = _extract_value(extracted, output_path)

        if gt_status in SCORED_STATUSES and expected is not None:
            status, score, note = compare_value(field, expected, actual)
            rows.append(EvalRow(doc["document_id"], field, output_path, expected, actual, status, score, note))
        elif gt_status in NEGATIVE_STATUSES:
            if _is_missing(actual):
                rows.append(EvalRow(doc["document_id"], field, output_path, expected, actual, "correctly_missing", 1.0))
            else:
                rows.append(EvalRow(doc["document_id"], field, output_path, expected, actual, "false_positive", 0.0))
        elif gt_status == "multi_unit":
            rows.append(EvalRow(doc["document_id"], field, output_path, expected, actual, "skipped_multi_unit", 0.0, "see unit_terms"))
        elif gt_status in {"not_fixed", "present_not_fully_transcribed"}:
            rows.append(EvalRow(doc["document_id"], field, output_path, expected, actual, "informational", 0.0, gt_status))
    return rows


def compare_value(field: str, expected: Any, actual: Any) -> tuple[str, float, str]:
    if isinstance(expected, str) and _is_missing(expected):
        return ("exact", 1.0, "") if _is_missing(actual) else ("mismatch", 0.0, "")
    if _is_missing(actual):
        return "missing", 0.0, ""

    if field in NUMERIC_FIELDS:
        exp_num = _to_number(expected)
        act_num = _to_number(actual)
        if exp_num is None or act_num is None:
            return "mismatch", 0.0, "non_numeric"
        tolerance = max(1.0, abs(exp_num) * 0.005)
        if abs(exp_num - act_num) <= tolerance:
            return "exact", 1.0, ""
        return "mismatch", 0.0, f"delta={act_num - exp_num:.2f}"

    if field in DATE_FIELDS:
        if str(expected) == str(actual):
            return "exact", 1.0, ""
        return "mismatch", 0.0, ""

    exp = _normalize_text(str(expected))
    act = _normalize_text(str(actual))
    if not exp:
        return ("exact", 1.0, "") if not act else ("false_positive", 0.0, "")
    if exp == act or exp in act or act in exp:
        return "exact", 1.0, ""

    ratio = SequenceMatcher(None, exp, act).ratio()
    token_score = _token_overlap(exp, act)
    threshold = 0.42 if field in CLAUSE_FIELDS else 0.72
    score_basis = max(ratio, token_score)
    if score_basis >= threshold:
        return "close", 0.75, f"similarity={score_basis:.2f}"
    return "mismatch", 0.0, f"similarity={score_basis:.2f}"


def summarize(rows: list[EvalRow], doc_summaries: list[dict], *, label: str) -> dict:
    scored = [r for r in rows if r.status not in {"skipped_multi_unit", "informational"}]
    positives = [r for r in scored if r.status not in {"correctly_missing", "false_positive"}]
    field_score = sum(r.score for r in scored)
    positive_score = sum(r.score for r in positives)
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    return {
        "label": label,
        "documents": len(doc_summaries),
        "scored_fields": len(scored),
        "positive_fields": len(positives),
        "score": round(field_score / len(scored), 4) if scored else 0.0,
        "positive_score": round(positive_score / len(positives), 4) if positives else 0.0,
        "exact_or_close": sum(1 for r in positives if r.status in {"exact", "close"}),
        "missing": status_counts.get("missing", 0),
        "mismatch": status_counts.get("mismatch", 0),
        "false_positive": status_counts.get("false_positive", 0),
        "status_counts": status_counts,
        "docs": doc_summaries,
    }


def _summarize_doc(document_id: str, rows: list[EvalRow]) -> dict:
    scored = [r for r in rows if r.status not in {"skipped_multi_unit", "informational"}]
    positives = [r for r in scored if r.status not in {"correctly_missing", "false_positive"}]
    return {
        "document_id": document_id,
        "fields": len(scored),
        "positive_fields": len(positives),
        "score": round(sum(r.score for r in scored) / len(scored), 4) if scored else 0.0,
        "positive_score": round(sum(r.score for r in positives) / len(positives), 4) if positives else 0.0,
        "missing": sum(1 for r in rows if r.status == "missing"),
        "mismatch": sum(1 for r in rows if r.status == "mismatch"),
        "false_positive": sum(1 for r in rows if r.status == "false_positive"),
    }


def write_details(path: Path, rows: list[EvalRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(["document_id", "field", "output_path", "expected", "actual", "status", "score", "note"])
        for row in rows:
            writer.writerow([
                row.document_id,
                row.field,
                row.output_path,
                _jsonish(row.expected),
                _jsonish(row.actual),
                row.status,
                row.score,
                row.note,
            ])


def write_docs(path: Path, docs: list[dict]) -> None:
    if not docs:
        return
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(docs[0].keys()))
        writer.writeheader()
        writer.writerows(docs)


def _extract_value(extracted: dict, path: str) -> Any:
    current: Any = extracted
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    if isinstance(current, dict) and "value" in current:
        return current.get("value")
    return current


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"", "n/a", "n.a.", "na", "none", "null", "nil", "string"}:
            return True
        return _normalize_text(value) in {"", "na", "none", "null", "nil", "string"}
    return False


def _to_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.\-]", "", value)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return None
    return None


def _normalize_text(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _token_overlap(expected: str, actual: str) -> float:
    expected_tokens = {t for t in expected.split() if len(t) > 2}
    actual_tokens = {t for t in actual.split() if len(t) > 2}
    if not expected_tokens:
        return 0.0
    return len(expected_tokens & actual_tokens) / len(expected_tokens)


def _jsonish(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
