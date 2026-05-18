"""Pydantic data models for lease summary extraction."""
from __future__ import annotations

import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ExtractionMethod(str, Enum):
    regex = "regex"
    rule = "rule"
    computed = "computed"
    heuristic = "heuristic"
    manual_default = "manual_default"


class Evidence(BaseModel):
    page: int
    quote: str
    method: ExtractionMethod


class ExtractionResult(BaseModel):
    value: Any = None
    confidence: float = 0.0
    evidence: list[Evidence] = Field(default_factory=list)
    review_flag: Optional[str] = None

    def is_found(self) -> bool:
        return self.value is not None and self.value != ""

    def first_page(self) -> Optional[int]:
        return self.evidence[0].page if self.evidence else None


class ReviewFlag(BaseModel):
    field: str
    flag: str
    reason: str
    evidence_snippet: str = ""
    page: Optional[int] = None


class DocumentMeta(BaseModel):
    source_filename: str = ""
    document_type: str = "unknown"
    parsed_with_ocr: bool = False
    pages: int = 0


class SummaryMeta(BaseModel):
    summary_date: datetime.date = Field(default_factory=datetime.date.today)
    property_type: str = "Office"
    opportunity_name: Optional[str] = None
    opportunity_owner: Optional[str] = None
    opportunity_office: str = "Hong Kong"


class Parties(BaseModel):
    landlord_name: ExtractionResult = Field(default_factory=ExtractionResult)
    landlord_registered_address: ExtractionResult = Field(default_factory=ExtractionResult)
    landlord_agent: ExtractionResult = Field(default_factory=ExtractionResult)
    landlord_solicitor: ExtractionResult = Field(default_factory=ExtractionResult)
    tenant_name: ExtractionResult = Field(default_factory=ExtractionResult)
    tenant_registered_address: ExtractionResult = Field(default_factory=ExtractionResult)
    tenant_correspondence_address: ExtractionResult = Field(default_factory=ExtractionResult)
    tenant_contact_person: ExtractionResult = Field(default_factory=ExtractionResult)


class Premises(BaseModel):
    full_address: ExtractionResult = Field(default_factory=ExtractionResult)
    building_name: ExtractionResult = Field(default_factory=ExtractionResult)
    floor_suite: ExtractionResult = Field(default_factory=ExtractionResult)
    rentable_area_sqft: ExtractionResult = Field(default_factory=ExtractionResult)
    area_comment: ExtractionResult = Field(default_factory=ExtractionResult)


class Term(BaseModel):
    lease_signing_date: ExtractionResult = Field(default_factory=ExtractionResult)
    scheduled_commencement_date: ExtractionResult = Field(default_factory=ExtractionResult)
    lease_commencement_date: ExtractionResult = Field(default_factory=ExtractionResult)
    lease_expiry_date: ExtractionResult = Field(default_factory=ExtractionResult)
    lease_term_months: ExtractionResult = Field(default_factory=ExtractionResult)
    fit_out_period_text: ExtractionResult = Field(default_factory=ExtractionResult)
    rent_free_period_text: ExtractionResult = Field(default_factory=ExtractionResult)
    option_to_renew_text: ExtractionResult = Field(default_factory=ExtractionResult)
    trigger_date_text: ExtractionResult = Field(default_factory=ExtractionResult)
    right_of_expansion_text: ExtractionResult = Field(default_factory=ExtractionResult)
    tenant_termination_right_text: ExtractionResult = Field(default_factory=ExtractionResult)


class DepositComponent(BaseModel):
    label: str
    amount: Decimal


class Financials(BaseModel):
    monthly_rent_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    monthly_rent_psf_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    management_fee_monthly_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    management_fee_psf_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    rates_quarterly_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    rates_monthly_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    government_rent_monthly_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    operating_expense_note: ExtractionResult = Field(default_factory=ExtractionResult)
    security_deposit_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    security_deposit_multiple: ExtractionResult = Field(default_factory=ExtractionResult)
    security_deposit_note: ExtractionResult = Field(default_factory=ExtractionResult)
    security_deposit_components: list[DepositComponent] = Field(default_factory=list)
    transferred_security_deposit_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    transferred_security_deposit_note: ExtractionResult = Field(default_factory=ExtractionResult)
    security_deposit_balance_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    security_deposit_balance_note: ExtractionResult = Field(default_factory=ExtractionResult)
    fit_out_deposit_hkd: ExtractionResult = Field(default_factory=ExtractionResult)
    advance_rent_text: ExtractionResult = Field(default_factory=ExtractionResult)


class Clauses(BaseModel):
    user_clause_text: ExtractionResult = Field(default_factory=ExtractionResult)
    handover_condition_text: ExtractionResult = Field(default_factory=ExtractionResult)
    break_clause_text: ExtractionResult = Field(default_factory=ExtractionResult)
    signage_text: ExtractionResult = Field(default_factory=ExtractionResult)
    subletting_text: ExtractionResult = Field(default_factory=ExtractionResult)
    parking_text: ExtractionResult = Field(default_factory=ExtractionResult)
    restoration_obligations_text: ExtractionResult = Field(default_factory=ExtractionResult)


class LeaseSummary(BaseModel):
    document_meta: DocumentMeta = Field(default_factory=DocumentMeta)
    summary_meta: SummaryMeta = Field(default_factory=SummaryMeta)
    parties: Parties = Field(default_factory=Parties)
    premises: Premises = Field(default_factory=Premises)
    term: Term = Field(default_factory=Term)
    financials: Financials = Field(default_factory=Financials)
    clauses: Clauses = Field(default_factory=Clauses)
    review_flags: list[ReviewFlag] = Field(default_factory=list)
    overall_confidence: float = 0.0

    def add_flag(self, field: str, flag: str, reason: str,
                 evidence_snippet: str = "", page: Optional[int] = None) -> None:
        self.review_flags.append(ReviewFlag(
            field=field, flag=flag, reason=reason,
            evidence_snippet=evidence_snippet, page=page,
        ))

    def review_required(self) -> bool:
        return len(self.review_flags) > 0
