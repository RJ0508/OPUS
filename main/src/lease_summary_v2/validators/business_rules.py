"""Cross-field business rule validation."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ..models import LeaseSummary
from ..normalizers.dates import compute_term_months


def validate_business_rules(summary: LeaseSummary) -> None:
    """Run all cross-field checks and add review flags where inconsistencies found."""
    _check_date_order(summary)
    _check_term_months(summary)
    _check_deposit_multiple(summary)
    _check_break_vs_termination(summary)
    _propagate_extraction_flags(summary)
    _update_overall_confidence(summary)


def _check_date_order(summary: LeaseSummary) -> None:
    start = summary.term.lease_commencement_date.value
    end = summary.term.lease_expiry_date.value
    if isinstance(start, datetime.date) and isinstance(end, datetime.date):
        if start >= end:
            summary.add_flag(
                "lease_expiry_date",
                "DATE_ORDER_INVALID",
                f"Commencement {start} is not before expiry {end}.",
            )


def _check_term_months(summary: LeaseSummary) -> None:
    start = summary.term.lease_commencement_date.value
    end = summary.term.lease_expiry_date.value
    stated = summary.term.lease_term_months.value

    if isinstance(start, datetime.date) and isinstance(end, datetime.date) and stated:
        computed = compute_term_months(start, end)
        if abs(computed - int(stated)) > 1:
            summary.add_flag(
                "lease_term_months",
                "TERM_MONTHS_MISMATCH",
                f"Stated term {stated} months does not match computed {computed} months "
                f"from {start} to {end}.",
            )


def _check_deposit_multiple(summary: LeaseSummary) -> None:
    deposit = summary.financials.security_deposit_hkd.value
    multiple = summary.financials.security_deposit_multiple.value
    rent = summary.financials.monthly_rent_hkd.value
    mgmt = summary.financials.management_fee_monthly_hkd.value
    rates = summary.financials.rates_monthly_hkd.value

    if deposit and multiple and rent:
        try:
            total_monthly = Decimal(str(rent))
            if mgmt and mgmt != "n/a":
                total_monthly += Decimal(str(mgmt))
            if rates and rates != "n/a":
                total_monthly += Decimal(str(rates))
            expected = total_monthly * int(multiple)
            actual = Decimal(str(deposit))
            # Allow 2% tolerance
            if abs(expected - actual) / max(expected, Decimal("1")) > Decimal("0.02"):
                summary.add_flag(
                    "security_deposit_hkd",
                    "DEPOSIT_COMPOSITION_NEEDS_CHECK",
                    f"Deposit {actual} does not match {multiple}x monthly charges {expected:.2f}.",
                )
        except Exception:
            pass


def _check_break_vs_termination(summary: LeaseSummary) -> None:
    break_val = summary.clauses.break_clause_text.value
    term_right = summary.term.tenant_termination_right_text.value
    if (break_val and str(break_val).lower() in ("n/a", "na") and
            term_right and str(term_right).lower() not in ("n/a", "na", "none")):
        summary.add_flag(
            "tenant_termination_right_text",
            "BREAK_INCONSISTENCY",
            "Break clause is N/A but tenant termination right has a value — please verify.",
        )


_FLAG_REASONS = {
    "AREA_NOT_FOUND": "Rentable area not found in text — likely stated only in floor plan image. Please fill in manually.",
    "COMMENCEMENT_NOT_FOUND": "Lease commencement date could not be extracted. Please verify.",
    "EXPIRY_NOT_FOUND": "Lease expiry date could not be extracted. Please verify.",
    "MONTHLY_RENT_NOT_FOUND": "Monthly rent could not be extracted. Please fill in manually.",
    "SECURITY_DEPOSIT_NOT_FOUND": "Security deposit amount not found. Please verify.",
    "TERM_COMPUTED_NOT_EXPLICIT": "Lease term was computed from commencement + years/months stated — not an explicit stated duration.",
    "EXPIRY_COMPUTED_FROM_TERM": "Expiry date was computed from commencement + stated term — not explicitly stated.",
    "RATES_CONVERTED_QUARTERLY_TO_MONTHLY": "Government rates figure was quarterly — divided by 3 to get monthly. Please confirm.",
    "FIT_OUT_MAPPED_FROM_RENT_FREE": "Fit-out period derived from rent-free period. Please confirm they are the same.",
    "SUBLETTING_UNCLEAR": "Subletting clause was not clearly labeled — extracted as best-effort. Please verify against lease.",
    "SIGNAGE_UNCLEAR": "Signage clause was not clearly labeled — extracted as best-effort. Please verify against lease.",
    "RESTORATION_UNCLEAR": "Restoration/reinstatement clause not clearly labeled — please verify against lease.",
    "PARKING_UNCLEAR": "Parking clause not clearly labeled — please verify against lease.",
    "CLAUSE_SUMMARY_LOW_CONFIDENCE": "One or more clause summaries are low-confidence heuristic extracts. Please verify.",
    "BREAK_INCONSISTENCY": "Break clause is N/A but tenant termination right has a value — please verify.",
    "DEPOSIT_COMPOSITION_NEEDS_CHECK": "Security deposit amount does not match the stated multiple × monthly charges. Please check.",
    "TERM_MONTHS_MISMATCH": "Stated lease term (months) does not match the difference between commencement and expiry dates.",
}


def _propagate_extraction_flags(summary: LeaseSummary) -> None:
    """Propagate review_flag from ExtractionResult objects to summary.review_flags."""
    field_map = {
        "premises.rentable_area_sqft": summary.premises.rentable_area_sqft,
        "term.lease_term_months": summary.term.lease_term_months,
        "term.lease_expiry_date": summary.term.lease_expiry_date,
        "financials.rates_monthly_hkd": summary.financials.rates_monthly_hkd,
        "clauses.subletting_text": summary.clauses.subletting_text,
        "clauses.signage_text": summary.clauses.signage_text,
        "clauses.parking_text": summary.clauses.parking_text,
        "clauses.restoration_obligations_text": summary.clauses.restoration_obligations_text,
        "term.tenant_termination_right_text": summary.term.tenant_termination_right_text,
    }
    for field_path, result in field_map.items():
        if result.review_flag:
            existing = {f.flag for f in summary.review_flags}
            if result.review_flag not in existing:
                evidence_snippet = result.evidence[0].quote[:100] if result.evidence else ""
                reason = _FLAG_REASONS.get(result.review_flag,
                                           f"Please review: {result.review_flag}")
                summary.add_flag(
                    field=field_path.split(".")[-1],
                    flag=result.review_flag,
                    reason=reason,
                    evidence_snippet=evidence_snippet,
                    page=result.first_page(),
                )


def _update_overall_confidence(summary: LeaseSummary) -> None:
    """Compute a simple average confidence across all extracted fields."""
    scores: list[float] = []
    for group in (summary.parties, summary.premises, summary.term,
                  summary.financials, summary.clauses):
        for field_name, field_val in group.__dict__.items():
            from ..models import ExtractionResult
            if isinstance(field_val, ExtractionResult):
                scores.append(field_val.confidence)
    summary.overall_confidence = sum(scores) / len(scores) if scores else 0.0
