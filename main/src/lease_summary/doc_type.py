"""Shared document type detection from external signal config."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


_FALLBACK_SIGNALS = {
    "lease_signals": [
        "landlord", "tenant", "lessor", "lessee",
        "lease", "tenancy", "let and hire",
        "demised premises", "rent", "security deposit",
    ],
    "non_lease_signals": [
        "invoice", "invoice no", "invoice date", "fee payable",
        "quotation", "receipt", "payment receipt",
        "floor plan", "site plan",
        "management accounts", "financial statement",
        "business registration", "company search", "writ of summons",
    ],
    "specific_types": {
        "offer_to_lease": ["offer to lease"],
        "tenancy_offer_letter": ["tenancy offer letter", "offer letter"],
        "lease": ["tenancy agreement"],
        "signed_lease": ["signed lease", "lease agreement"],
    },
    "non_lease_threshold": 2,
    "lease_threshold": 1,
}


def load_doc_type_signals() -> dict:
    """Load lease / non-lease signal keywords from YAML, with safe defaults."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent.parent

    config_path = base / "config" / "doc_type_signals.yaml"
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or dict(_FALLBACK_SIGNALS)
    return dict(_FALLBACK_SIGNALS)


def detect_doc_type(text: str) -> str:
    signals = load_doc_type_signals()
    lease_signals = signals.get("lease_signals", [])
    non_lease_signals = signals.get("non_lease_signals", [])
    non_lease_threshold = signals.get("non_lease_threshold", 2)
    lease_threshold = signals.get("lease_threshold", 1)
    specific_types = signals.get("specific_types", {})

    text_lower = (text or "").lower()
    lease_hits = sum(1 for signal in lease_signals if signal in text_lower)
    non_lease_hits = sum(1 for signal in non_lease_signals if signal in text_lower)

    if non_lease_hits >= non_lease_threshold and lease_hits <= lease_threshold:
        return "not_a_lease"

    for doc_type, keywords in specific_types.items():
        if any(keyword in text_lower for keyword in keywords):
            return doc_type

    return "unknown"
