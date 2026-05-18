"""Regression tests for KLD renewal-transfer lease behaviour."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


PDF_PATH = (
    Path(__file__).parent.parent.parent
    / "files"
    / "Lease & Lease Summary examples _ Building Directories _ Building Information. "
    / "KLD 1702 Central Plaza Lease Scan 2025.pdf"
)


@pytest.fixture(scope="module")
def kld_doc():
    from lease_summary.parsers.pdf_text import extract_text
    return extract_text(PDF_PATH)


@pytest.fixture(scope="module")
def kld_split(kld_doc):
    from lease_summary.parsers.section_splitter import split
    return split(kld_doc)


@pytest.fixture(scope="module")
def kld_financials(kld_doc, kld_split):
    from lease_summary.extractors.financials import extract_financials
    return extract_financials(kld_doc, kld_split)


def test_kld_extracts_transferred_security_deposit(kld_financials):
    result = kld_financials.transferred_security_deposit_hkd
    assert result.is_found()
    assert abs(float(result.value) - 305680.8) < 0.01


def test_kld_extracts_balance_security_deposit(kld_financials):
    result = kld_financials.security_deposit_balance_hkd
    assert result.is_found()
    assert abs(float(result.value) - 28515.0) < 0.01


def test_kld_extracts_balance_note(kld_financials):
    result = kld_financials.security_deposit_balance_note
    assert result.is_found()
    assert "future monthly rental" in result.value.lower()
