"""Regression tests for clause extraction on the Trade Desk full lease sample."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


PDF_PATH = (
    Path(__file__).parent.parent.parent
    / "files"
    / "Lease and Summary"
    / "Leases"
    / "Stamped Lease for 22F & 23F HP_The Trade Desk FULLY SIGNED AND STAMPED.pdf"
)


@pytest.fixture(scope="module")
def td_doc():
    from lease_summary.parsers.pdf_text import extract_text

    return extract_text(PDF_PATH)


@pytest.fixture(scope="module")
def td_split(td_doc):
    from lease_summary.parsers.section_splitter import split

    return split(td_doc)


def test_trade_desk_clauses_have_signage_subletting_parking(td_doc, td_split):
    from lease_summary.extractors.clauses import extract_clauses

    clauses = extract_clauses(td_doc, td_split)

    assert clauses.signage_text.value != "n/a"
    assert clauses.subletting_text.value != "n/a"
    assert clauses.parking_text.value != "n/a"
