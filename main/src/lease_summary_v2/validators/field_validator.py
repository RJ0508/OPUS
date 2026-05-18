"""Mandatory field presence checks."""
from __future__ import annotations

from ..models import LeaseSummary

MANDATORY_FIELDS = [
    ("parties.tenant_name", "TENANT_NAME_MISSING"),
    ("parties.landlord_name", "LANDLORD_NAME_MISSING"),
    ("premises.full_address", "PREMISES_ADDRESS_MISSING"),
    ("term.lease_commencement_date", "COMMENCEMENT_DATE_MISSING"),
    ("term.lease_expiry_date", "EXPIRY_DATE_MISSING"),
    ("financials.monthly_rent_hkd", "MONTHLY_RENT_MISSING"),
]


def validate_mandatory(summary: LeaseSummary) -> None:
    """Add review flags for any missing mandatory fields."""
    for dotpath, flag in MANDATORY_FIELDS:
        obj = summary
        for part in dotpath.split("."):
            obj = getattr(obj, part)
        # obj is now an ExtractionResult
        if not obj.is_found():
            summary.add_flag(
                field=dotpath.split(".")[-1],
                flag=flag,
                reason=f"Mandatory field '{dotpath}' not found in document.",
            )
