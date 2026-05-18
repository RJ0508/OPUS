"""Regression tests for the provided JSG and KLD sample leases."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


EXAMPLES_DIR = (
    Path(__file__).parent.parent.parent
    / "files"
    / "Lease & Lease Summary examples _ Building Directories _ Building Information. "
)
JSG_PDF = EXAMPLES_DIR / "JSG Signed Lease + Deposit.pdf"
KLD_PDF = EXAMPLES_DIR / "KLD 1702 Central Plaza Lease Scan 2025.pdf"


@pytest.fixture(scope="module")
def jsg_doc():
    from lease_summary.parsers.pdf_text import extract_text

    return extract_text(JSG_PDF)


@pytest.fixture(scope="module")
def jsg_split(jsg_doc):
    from lease_summary.parsers.section_splitter import split

    return split(jsg_doc)


@pytest.fixture(scope="module")
def jsg_premises(jsg_doc, jsg_split):
    from lease_summary.extractors.premises import extract_premises

    return extract_premises(jsg_doc, jsg_split)


@pytest.fixture(scope="module")
def jsg_term(jsg_doc, jsg_split):
    from lease_summary.extractors.dates import extract_term

    return extract_term(jsg_doc, jsg_split)


@pytest.fixture(scope="module")
def kld_doc():
    from lease_summary.parsers.pdf_text import extract_text

    return extract_text(KLD_PDF)


@pytest.fixture(scope="module")
def kld_split(kld_doc):
    from lease_summary.parsers.section_splitter import split

    return split(kld_doc)


@pytest.fixture(scope="module")
def kld_parties(kld_doc, kld_split):
    from lease_summary.extractors.parties import extract_parties

    return extract_parties(kld_doc, kld_split)

@pytest.fixture(scope="module")
def kld_premises(kld_doc, kld_split):
    from lease_summary.extractors.premises import extract_premises

    return extract_premises(kld_doc, kld_split)


def test_jsg_building_name_comes_from_premises_address(jsg_premises):
    result = jsg_premises.building_name

    assert result.is_found()
    assert result.value == "Tai Yau Building"


def test_jsg_fit_out_is_not_incorrectly_mapped_from_rent_free(jsg_term):
    assert jsg_term.rent_free_period_text.is_found()
    assert jsg_term.fit_out_period_text.is_found()
    assert jsg_term.fit_out_period_text.value == "n/a"


def test_kld_extracts_landlord_registered_address_from_schedule(kld_parties):
    result = kld_parties.landlord_registered_address

    assert result.is_found()
    assert "Suite 2802" in result.value
    assert "Central Plaza" in result.value


def test_kld_extracts_landlord_agent_from_schedule(kld_parties):
    result = kld_parties.landlord_agent

    assert result.is_found()
    assert "CHEER CITY PROPERTIES LIMITED" in result.value
    assert "PROTASAN LIMITED" in result.value


def test_kld_extracts_tenant_registered_address_from_schedule(kld_parties):
    result = kld_parties.tenant_registered_address

    assert result.is_found()
    assert "Dominion Centre" in result.value
    assert "Queen's Road East" in result.value
    assert "THE PREMISES" not in result.value
    assert "TERM OF TENANCY" not in result.value


def test_kld_premises_are_normalized(kld_premises):
    result = kld_premises.full_address
    assert result.is_found()
    assert "Suite 1702" in result.value
    assert "Central Plaza" in result.value


def test_option_related_clauses_ignore_termination_references():
    from lease_summary.extractors.dates import (
        _extract_expansion,
        _extract_option_to_renew,
        _extract_trigger_date,
    )
    from lease_summary.parsers.pdf_text import DocumentText, PageText

    text = (
        "Any benefit of the Tenant including an option to renew, option to take "
        "expansion premises and right of first offer shall extinguish and determine "
        "upon the service of the said notice of termination. The Tenant having "
        "exercised its option shall not affect termination."
    )
    doc = DocumentText(pages=[PageText(page_num=1, text=text)])

    assert _extract_option_to_renew(text, doc).value == "n/a"
    assert _extract_expansion(text, doc).value == "n/a"
    assert _extract_trigger_date(text, doc).value == "n/a"
