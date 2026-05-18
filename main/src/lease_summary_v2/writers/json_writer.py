"""Serialize LeaseSummary to JSON."""
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..models import LeaseSummary


class _Encoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def write_json(summary: LeaseSummary, output_path: str | Path) -> Path:
    """Write LeaseSummary to a JSON file and return the path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = summary.model_dump()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, cls=_Encoder, ensure_ascii=False)
    return output_path


def write_review_json(summary: LeaseSummary, output_path: str | Path) -> Path:
    """Write only the review/flag portion to a JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    review_data = {
        "overall_confidence": summary.overall_confidence,
        "review_required": summary.review_required(),
        "flag_count": len(summary.review_flags),
        "flags": [f.model_dump() for f in summary.review_flags],
        "field_confidence": _field_confidence_report(summary),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(review_data, f, indent=2, cls=_Encoder, ensure_ascii=False)
    return output_path


def _field_confidence_report(summary: LeaseSummary) -> dict[str, Any]:
    from ..models import ExtractionResult
    report: dict[str, Any] = {}
    for group_name in ("parties", "premises", "term", "financials", "clauses"):
        group = getattr(summary, group_name)
        for field_name, field_val in group.__dict__.items():
            if isinstance(field_val, ExtractionResult):
                key = f"{group_name}.{field_name}"
                report[key] = {
                    "value": _safe_repr(field_val.value),
                    "confidence": field_val.confidence,
                    "found": field_val.is_found(),
                }
    return report


def _safe_repr(value: Any) -> Any:
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
