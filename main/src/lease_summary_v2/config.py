"""Configuration: file paths and defaults."""
from __future__ import annotations

from pathlib import Path

# Project root
_HERE = Path(__file__).parent
PROJECT_ROOT = _HERE.parent.parent  # main/

# Template path (relative to project root)
DEFAULT_TEMPLATE = (
    PROJECT_ROOT.parent / "files" / "Opus Lease Summary Template - HK.xlsx"
)

# Fallback: allow env override
import os
TEMPLATE_PATH = Path(os.environ.get("LEASE_TEMPLATE", str(DEFAULT_TEMPLATE)))

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
