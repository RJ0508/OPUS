@echo off
REM Build Opus Lease Summary Assistant for Windows.
REM Run from the project root:  build_win.bat
REM Requires Python 3.11 with all dependencies installed.
REM Recommended: use the same mamba/conda environment as development.

setlocal

REM ── Adjust this to your Python path on Windows ──────────────────────────────
REM   e.g. C:\Users\YourName\miniconda3\envs\lease_summary\python.exe
set PYTHON=python

echo === Installing / upgrading PyInstaller ===
%PYTHON% -m pip install --quiet --upgrade pyinstaller pywebview

echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo === Building Windows executable ===
%PYTHON% -m PyInstaller --clean --noconfirm opus_lease.spec

echo.
echo === Done ===
echo Folder: dist\OpusLeaseSummary\
echo Executable: dist\OpusLeaseSummary\OpusLeaseSummary.exe
echo.
echo To distribute, zip the entire dist\OpusLeaseSummary\ folder.
endlocal
