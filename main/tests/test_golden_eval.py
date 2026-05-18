"""Small golden evals for lease summary extraction quality."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


PDF_PATH = (
    Path(__file__).parent.parent.parent
    / "files"
    / "Lease & Lease Summary examples _ Building Directories _ Building Information. "
    / "Offer to Lease_Hollywood Centre 1502 20260203.pdf"
)
TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "files"
    / "Opus Lease Summary Template - HK.xlsx"
)
EXPECTED_PATH = Path(__file__).parent / "golden" / "hollywood_centre.expected.json"


def test_hollywood_centre_golden_eval(tmp_path):
    from lease_summary.pipeline import run

    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    result = run(PDF_PATH, output_dir=tmp_path, template_path=TEMPLATE_PATH)
    summary = result["summary"]

    assert expected["tenant_name_contains"] in summary.parties.tenant_name.value
    assert expected["landlord_name_contains"] in summary.parties.landlord_name.value
    assert abs(float(summary.financials.monthly_rent_hkd.value) - expected["monthly_rent_hkd"]) < 0.01
    assert summary.overall_confidence >= expected["minimum_confidence"]
    assert summary.parties.tenant_name.evidence
    assert summary.financials.monthly_rent_hkd.evidence
