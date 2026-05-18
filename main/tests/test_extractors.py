"""Unit tests for extractors against Tinygrad PDF."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from decimal import Decimal

import pytest

# Ensure package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PDF_PATH = (
    Path(__file__).parent.parent.parent
    / "files"
    / "Lease & Lease Summary examples _ Building Directories _ Building Information. "
    / "Offer to Lease_Hollywood Centre 1502 20260203.pdf"
)


@pytest.fixture(scope="module")
def tinygrad_doc():
    from lease_summary.parsers.pdf_text import extract_text
    return extract_text(PDF_PATH)


@pytest.fixture(scope="module")
def tinygrad_split(tinygrad_doc):
    from lease_summary.parsers.section_splitter import split
    return split(tinygrad_doc)


@pytest.fixture(scope="module")
def tinygrad_parties(tinygrad_doc, tinygrad_split):
    from lease_summary.extractors.parties import extract_parties
    return extract_parties(tinygrad_doc, tinygrad_split)


@pytest.fixture(scope="module")
def tinygrad_premises(tinygrad_doc, tinygrad_split):
    from lease_summary.extractors.premises import extract_premises
    return extract_premises(tinygrad_doc, tinygrad_split)


@pytest.fixture(scope="module")
def tinygrad_term(tinygrad_doc, tinygrad_split):
    from lease_summary.extractors.dates import extract_term
    return extract_term(tinygrad_doc, tinygrad_split)


@pytest.fixture(scope="module")
def tinygrad_financials(tinygrad_doc, tinygrad_split):
    from lease_summary.extractors.financials import extract_financials
    return extract_financials(tinygrad_doc, tinygrad_split)


@pytest.fixture(scope="module")
def tinygrad_clauses(tinygrad_doc, tinygrad_split):
    from lease_summary.extractors.clauses import extract_clauses
    return extract_clauses(tinygrad_doc, tinygrad_split)


# ── Parser tests ──────────────────────────────────────────────────────────────

class TestPDFParser:
    def test_page_count(self, tinygrad_doc):
        assert tinygrad_doc.pages[0].page_num == 1
        assert len(tinygrad_doc.pages) == 25

    def test_not_ocr(self, tinygrad_doc):
        assert not tinygrad_doc.parsed_with_ocr

    def test_page1_has_offer_text(self, tinygrad_doc):
        assert "OFFER TO LEASE" in tinygrad_doc.page(1)

    def test_page2_has_rent(self, tinygrad_doc):
        assert "15,015" in tinygrad_doc.page(2)


class TestSectionSplitter:
    def test_principal_terms_detected(self, tinygrad_split):
        assert "OFFER TO LEASE" in tinygrad_split.principal_terms

    def test_schedule_i_detected(self, tinygrad_split):
        assert tinygrad_split.schedule_i != ""
        assert "General Terms" in tinygrad_split.schedule_i

    def test_schedule_ii_detected(self, tinygrad_split):
        assert tinygrad_split.schedule_ii != ""

    def test_item_1_detected(self, tinygrad_split):
        # Item 1 should contain landlord info
        assert "1" in tinygrad_split.items
        assert "Capital Faith" in tinygrad_split.items.get("1", "")

    def test_item_5_has_rent(self, tinygrad_split):
        # Item 5 is Monthly Rent
        item5 = tinygrad_split.items.get("5", "")
        assert "15,015" in item5 or "15015" in item5


# ── Party extraction tests ────────────────────────────────────────────────────

class TestPartiesExtraction:
    def test_generic_party_label_rejects_offer_body_capture(self):
        from lease_summary.extractors.parties import _looks_like_generic_party_name

        bad = (
            "Offer to Lease Offices 1101 and 1102 on 11th Floor, LHT Tower, "
            "No.31 Queen's Road Central, Hong Kong We (the \"Tenant\") hereby "
            "offer to lease from you (the Landlord) the premises described"
        )
        assert not _looks_like_generic_party_name(bad)

    def test_numbered_schedule_parties(self):
        from lease_summary.extractors.parties import extract_parties
        from lease_summary.parsers.pdf_text import DocumentText, PageText
        from lease_summary.parsers.section_splitter import SplitDocument

        text = (
            "THE FIRST SCHEDULE\n"
            "The Landlord : HOLITA COMPANY LIMITED a company incorporated in the "
            "British Virgin Islands having a place of business in Hong Kong at "
            "Unit 3302, Henley Building, No.5 Queen's Road Central, Hong Kong.\n"
            "THE SECOND SCHEDULE\n"
            "The Tenant : SENGU CAPITAL LIMITED (BRN 76441406) a company "
            "incorporated in Hong Kong whose registered office is situate at "
            "Unit 2901, 29/F, The Centrium, No. 60 Wyndham Street, Central, Hong Kong.\n"
            "THE THIRD SCHEDULE"
        )
        doc = DocumentText(pages=[PageText(page_num=1, text=text)])
        split_doc = SplitDocument(principal_terms=text, full_text=text)

        result = extract_parties(doc, split_doc)

        assert result.landlord_name.value == "HOLITA COMPANY LIMITED"
        assert "Unit 3302" in result.landlord_registered_address.value
        assert result.tenant_name.value == "SENGU CAPITAL LIMITED"
        assert "The Centrium" in result.tenant_registered_address.value

    def test_landlord_name(self, tinygrad_parties):
        r = tinygrad_parties.landlord_name
        assert r.is_found()
        assert "Capital Faith" in r.value
        assert r.confidence >= 0.90

    def test_tenant_name(self, tinygrad_parties):
        r = tinygrad_parties.tenant_name
        assert r.is_found()
        assert "Tinygrad" in r.value
        assert r.confidence >= 0.90

    def test_tenant_address(self, tinygrad_parties):
        r = tinygrad_parties.tenant_registered_address
        assert r.is_found()
        assert "Lippo Centre" in r.value or "4002A" in r.value

    def test_landlord_solicitor(self, tinygrad_parties):
        r = tinygrad_parties.landlord_solicitor
        assert r.is_found()
        assert "Woo" in r.value


# ── Premises tests ────────────────────────────────────────────────────────────

class TestPremisesExtraction:
    def test_labeled_premises_rejects_offer_body_capture(self):
        from lease_summary.extractors.premises import _looks_like_labeled_premises_address

        bad = (
            'From AlixPartners Hong Kong, Limited 19th Floor, Golden Centre '
            '188 Des Voeux Road Central Hong Kong (the "Tenant") To The Luk Hoi '
            'Tong Company, Limited 8th Floor, Luk Kwok Centre, 72 Gloucester Road, '
            'Wanchai, Hong Kong (the "Landlord") Dear Sirs, Re: Offer to Lease '
            "Offices 1101 and 1102 on 11th Floor, LHT Tower"
        )
        assert not _looks_like_labeled_premises_address(bad)

    def test_full_address(self, tinygrad_premises):
        r = tinygrad_premises.full_address
        assert r.is_found()
        assert "Hollywood" in r.value
        assert "233" in r.value

    def test_building_name(self, tinygrad_premises):
        r = tinygrad_premises.building_name
        assert r.is_found()
        assert "Hollywood Centre" in r.value

    def test_area_not_found_flagged(self, tinygrad_premises):
        r = tinygrad_premises.rentable_area_sqft
        # Area not in principal terms text — should be flagged
        assert r.review_flag == "AREA_NOT_FOUND"


# ── Term / dates tests ────────────────────────────────────────────────────────

class TestTermExtraction:
    def test_formal_schedule_term_dates(self):
        from lease_summary.extractors.dates import extract_term
        from lease_summary.parsers.pdf_text import DocumentText, PageText
        from lease_summary.parsers.section_splitter import SplitDocument

        text = (
            "THE FIFTH SCHEDULE\n"
            "The term : Three (3) years fixed commencing on 15 April 2026 "
            "and expiring on 14 April 2029 (both days inclusive)."
        )
        doc = DocumentText(pages=[PageText(page_num=1, text=text)])
        split_doc = SplitDocument(principal_terms=text, full_text=text)

        result = extract_term(doc, split_doc)

        assert result.lease_commencement_date.value == datetime.date(2026, 4, 15)
        assert result.lease_expiry_date.value == datetime.date(2029, 4, 14)
        assert result.lease_term_months.value == 36

    def test_commencement_date(self, tinygrad_term):
        r = tinygrad_term.lease_commencement_date
        assert r.is_found()
        assert r.value == datetime.date(2026, 2, 11)
        assert r.confidence >= 0.90

    def test_expiry_date(self, tinygrad_term):
        r = tinygrad_term.lease_expiry_date
        assert r.is_found()
        assert r.value == datetime.date(2028, 2, 10)
        assert r.confidence >= 0.90

    def test_term_months_24(self, tinygrad_term):
        r = tinygrad_term.lease_term_months
        assert r.is_found()
        assert r.value == 24

    def test_rent_free_period(self, tinygrad_term):
        r = tinygrad_term.rent_free_period_text
        assert r.is_found()
        assert "28 days" in r.value.lower() or "28" in r.value

    def test_break_clause_na(self, tinygrad_term):
        r = tinygrad_term.tenant_termination_right_text
        assert r.is_found()
        assert r.value.lower() in ("n/a", "na")

    def test_option_to_renew_na(self, tinygrad_term):
        r = tinygrad_term.option_to_renew_text
        assert r.value.lower() == "n/a"


# ── Financials tests ──────────────────────────────────────────────────────────

class TestFinancialsExtraction:
    def test_formal_schedule_rent_and_service_charge_labels(self):
        from lease_summary.extractors.financials import extract_financials
        from lease_summary.parsers.pdf_text import DocumentText, PageText
        from lease_summary.parsers.section_splitter import SplitDocument

        text = (
            "THE SIXTH SCHEDULE\n"
            "The Rent : HONG KONG DOLLARS ONE HUNDRED THIRTY THOUSAND "
            "SIX HUNDRED AND ONE ONLY (HK$130,601.00) per calendar month "
            "payable on the 1st day of each month.\n"
            "The service charge : HONG KONG DOLLARS SIXTEEN THOUSAND FIFTY "
            "SEVEN AND CENTS FIFTY ONLY (HK$16,057.50) per calendar month."
        )
        doc = DocumentText(pages=[PageText(page_num=1, text=text)])
        split_doc = SplitDocument(principal_terms=text, full_text=text)

        result = extract_financials(doc, split_doc)

        assert result.monthly_rent_hkd.value == Decimal("130601.00")
        assert result.management_fee_monthly_hkd.value == Decimal("16057.50")

    def test_monthly_rent(self, tinygrad_financials):
        r = tinygrad_financials.monthly_rent_hkd
        assert r.is_found()
        assert abs(float(r.value) - 15015.0) < 0.01
        assert r.confidence >= 0.90

    def test_management_fee(self, tinygrad_financials):
        r = tinygrad_financials.management_fee_monthly_hkd
        assert r.is_found()
        assert abs(float(r.value) - 5253.0) < 0.01

    def test_rates_quarterly(self, tinygrad_financials):
        r = tinygrad_financials.rates_quarterly_hkd
        assert r.is_found()
        assert abs(float(r.value) - 2775.0) < 0.01

    def test_rates_monthly_derived(self, tinygrad_financials):
        r = tinygrad_financials.rates_monthly_hkd
        assert r.is_found()
        assert abs(float(r.value) - 925.0) < 0.01

    def test_govt_rent_na(self, tinygrad_financials):
        r = tinygrad_financials.government_rent_monthly_hkd
        assert r.value == "n/a"

    def test_security_deposit(self, tinygrad_financials):
        r = tinygrad_financials.security_deposit_hkd
        assert r.is_found()
        assert abs(float(r.value) - 63579.0) < 0.01

    def test_deposit_multiple_3(self, tinygrad_financials):
        r = tinygrad_financials.security_deposit_multiple
        assert r.is_found()
        assert r.value == 3

    def test_fitout_deposit(self, tinygrad_financials):
        r = tinygrad_financials.fit_out_deposit_hkd
        assert r.is_found()
        assert abs(float(r.value) - 5000.0) < 0.01


# ── Clause tests ──────────────────────────────────────────────────────────────

class TestClausesExtraction:
    def test_user_clause(self, tinygrad_clauses):
        r = tinygrad_clauses.user_clause_text
        assert r.is_found()
        assert "office" in r.value.lower()

    def test_handover_condition(self, tinygrad_clauses):
        r = tinygrad_clauses.handover_condition_text
        assert r.is_found()
        assert "Standard" in r.value or "Landlord" in r.value

    def test_subletting_prohibited(self, tinygrad_clauses):
        r = tinygrad_clauses.subletting_text
        assert r.is_found()
        assert "assign" in r.value.lower() or "transfer" in r.value.lower()

    def test_signage_approval_required(self, tinygrad_clauses):
        r = tinygrad_clauses.signage_text
        assert r.is_found()
        assert "approval" in r.value.lower()

    def test_parking_na(self, tinygrad_clauses):
        r = tinygrad_clauses.parking_text
        assert r.value == "n/a"
