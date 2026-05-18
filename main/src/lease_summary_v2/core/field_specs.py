"""Canonical field paths and labels for AI Enhanced extraction."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FieldSpec(BaseModel):
    field_path: str
    label: str
    value_type: str = "string"
    aliases: list[str] = Field(default_factory=list)


FIELD_SPECS: list[FieldSpec] = [
    FieldSpec(field_path="parties.landlord_name", label="Landlord name"),
    FieldSpec(field_path="parties.landlord_registered_address", label="Landlord registered address"),
    FieldSpec(field_path="parties.tenant_name", label="Tenant name"),
    FieldSpec(field_path="parties.tenant_registered_address", label="Tenant registered address"),
    FieldSpec(field_path="premises.full_address", label="Premises full address"),
    FieldSpec(field_path="premises.building_name", label="Building name"),
    FieldSpec(field_path="premises.floor_suite", label="Floor / suite"),
    FieldSpec(field_path="premises.rentable_area_sqft", label="Rentable area", value_type="number"),
    FieldSpec(field_path="term.lease_signing_date", label="Lease signing date", value_type="date"),
    FieldSpec(field_path="term.scheduled_commencement_date", label="Scheduled commencement date", value_type="date"),
    FieldSpec(field_path="term.lease_commencement_date", label="Lease commencement date", value_type="date"),
    FieldSpec(field_path="term.lease_expiry_date", label="Lease expiry date", value_type="date"),
    FieldSpec(field_path="term.lease_term_months", label="Lease term months", value_type="integer"),
    FieldSpec(field_path="term.fit_out_period_text", label="Fit-out period"),
    FieldSpec(field_path="term.rent_free_period_text", label="Rent-free period"),
    FieldSpec(field_path="term.option_to_renew_text", label="Option to renew"),
    FieldSpec(field_path="term.trigger_date_text", label="Renewal trigger date"),
    FieldSpec(field_path="term.right_of_expansion_text", label="Right of expansion"),
    FieldSpec(field_path="term.tenant_termination_right_text", label="Tenant termination / break clause"),
    FieldSpec(field_path="financials.monthly_rent_hkd", label="Monthly rent HKD", value_type="number"),
    FieldSpec(field_path="financials.monthly_rent_psf_hkd", label="Monthly rent per sq ft HKD", value_type="number"),
    FieldSpec(field_path="financials.management_fee_monthly_hkd", label="Management fee monthly HKD", value_type="number"),
    FieldSpec(field_path="financials.management_fee_psf_hkd", label="Management fee per sq ft HKD", value_type="number"),
    FieldSpec(field_path="financials.rates_quarterly_hkd", label="Rates quarterly HKD", value_type="number"),
    FieldSpec(field_path="financials.rates_monthly_hkd", label="Rates monthly HKD", value_type="number"),
    FieldSpec(field_path="financials.government_rent_monthly_hkd", label="Government rent monthly HKD", value_type="number"),
    FieldSpec(field_path="financials.security_deposit_hkd", label="Security deposit HKD", value_type="number"),
    FieldSpec(field_path="financials.security_deposit_multiple", label="Security deposit multiple", value_type="integer"),
    FieldSpec(field_path="financials.security_deposit_note", label="Security deposit note"),
    FieldSpec(field_path="financials.advance_rent_text", label="Advance rent"),
    FieldSpec(field_path="clauses.user_clause_text", label="Permitted use"),
    FieldSpec(field_path="clauses.handover_condition_text", label="Handover condition"),
    FieldSpec(field_path="clauses.break_clause_text", label="Break clause"),
    FieldSpec(field_path="clauses.subletting_text", label="Subletting"),
    FieldSpec(field_path="clauses.signage_text", label="Signage"),
    FieldSpec(field_path="clauses.parking_text", label="Parking"),
    FieldSpec(field_path="clauses.restoration_obligations_text", label="Restoration obligations"),
]

FIELD_SPEC_BY_PATH = {spec.field_path: spec for spec in FIELD_SPECS}
