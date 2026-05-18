"""
Frozen entry point for PyInstaller bundles.
In dev, run:  python -m app.launcher
"""
import sys
import os

if getattr(sys, 'frozen', False):
    # Running inside a PyInstaller bundle.
    # sys._MEIPASS is the temp dir where everything is extracted.
    _base = sys._MEIPASS
    os.environ.setdefault(
        'LEASE_TEMPLATE',
        os.path.join(_base, 'files', 'Opus Lease Summary Template - HK.xlsx'),
    )
    # Ensure bundled src packages (lease_summary, lease_summary_v2) are importable
    _src = os.path.join(_base, 'src')
    if _src not in sys.path:
        sys.path.insert(0, _src)

# Explicit imports for PyInstaller module discovery
import fitz  # noqa: F401  (PyMuPDF namespace package)
import pymupdf  # noqa: F401

from app.launcher import main

if __name__ == '__main__':
    main()
