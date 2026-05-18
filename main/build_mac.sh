#!/usr/bin/env bash
# Build Opus Lease Summary Assistant for macOS.
# Run from the project root:  bash build_mac.sh
set -e

PYTHON="/Users/ryanjia/.local/share/mamba/envs/lease_summary/bin/python3.11"
PIP="$PYTHON -m pip"
PYINSTALLER="$PYTHON -m PyInstaller"

echo "=== Installing / upgrading PyInstaller ==="
$PIP install --quiet --upgrade pyinstaller pywebview

echo "=== Cleaning previous build ==="
rm -rf build dist

echo "=== Building .app bundle ==="
$PYINSTALLER --clean --noconfirm opus_lease.spec

echo "=== Creating DMG with Applications shortcut ==="
STAGING=$(mktemp -d)
cp -R dist/OpusLeaseSummary.app "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create \
  -volname "Opus Lease Summary" \
  -srcfolder "$STAGING" \
  -ov -format UDZO dist/OpusLeaseSummary.dmg
rm -rf "$STAGING"

echo ""
echo "=== Done ==="
echo "DMG: dist/OpusLeaseSummary.dmg"
