# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Opus Lease Summary Assistant.
Build:
  Mac  → bash build_mac.sh
  Win  → build_win.bat
"""
import sys
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden = []
hidden += collect_submodules('uvicorn')
hidden += collect_submodules('fastapi')
hidden += collect_submodules('starlette')
hidden += collect_submodules('anyio')
hidden += collect_submodules('multipart')
hidden += collect_submodules('openai')
hidden += collect_submodules('httpx')
hidden += collect_submodules('httpcore')
hidden += collect_submodules('webview')
hidden += collect_submodules('docx')  # python-docx
hidden += [
    'email.mime.text',
    'email.mime.multipart',
    'email.mime.application',
    'rapidfuzz',
    'dateutil',
    'docx',
    'docx.shared',
    'docx.enum',
    'docx.oxml',
    'fitz',
    'yaml',
]
hidden += collect_submodules('pymupdf')

# ── Data files ────────────────────────────────────────────────────────────────
datas = []
# Web frontend
datas += [('app/static', 'app/static')]
# Excel template (lives one level above the project root)
_template = os.path.abspath('../files/Opus Lease Summary Template - HK.xlsx')
datas += [(_template, 'files')]
# Document type detection config
datas += [('config/doc_type_signals.yaml', 'config')]
# fitz namespace package (PyMuPDF shim) — PyInstaller sometimes misses it
import fitz as _fitz_module
_fitz_dir = os.path.dirname(_fitz_module.__file__)
datas += [(_fitz_dir, 'fitz')]
# pymupdf ships compiled libs
datas += collect_data_files('pymupdf')
datas += collect_data_files('fitz')

a = Analysis(
    ['run_app.py'],
    pathex=['.', 'src'],          # find app.*  and  lease_summary.*
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL', 'cv2'],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ── Platform-specific output ──────────────────────────────────────────────────
if sys.platform == 'darwin':
    exe = EXE(
        pyz, a.scripts,
        [],
        exclude_binaries=True,
        name='OpusLeaseSummary',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        icon='app/static/assets/opus.icns',
        codesign_identity=None,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False,
        upx=True,
        name='OpusLeaseSummary',
    )
    app = BUNDLE(
        coll,
        name='OpusLeaseSummary.app',
        icon='app/static/assets/opus.icns',
        bundle_identifier='com.opus.leasesummary',
        info_plist={
            'CFBundleDisplayName': 'Opus Lease Summary',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
        },
    )
else:
    # Windows — single-folder build (faster startup than --onefile)
    exe = EXE(
        pyz, a.scripts,
        [],
        exclude_binaries=True,
        name='OpusLeaseSummary',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,            # no black terminal window
        icon='app/static/assets/opus.ico',
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False,
        upx=True,
        name='OpusLeaseSummary',
    )
