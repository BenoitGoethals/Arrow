<#
    Build the Arrow Front Windows installer end-to-end.

    Run from anywhere in a PowerShell prompt on Windows:
        powershell -ExecutionPolicy Bypass -File front\packaging\build_windows.ps1

    Steps:
      1. uv sync --extra front         (install the GUI dependency stack)
      2. PyInstaller                   (freeze -> dist\ArrowFront\)
      3. Inno Setup (ISCC)             (wrap -> dist\installer\ArrowFront-Setup-*.exe)

    Prerequisites:
      * uv           https://docs.astral.sh/uv/   (provides Python 3.14)
      * Inno Setup 6 https://jrsoftware.org/isdl.php
#>

$ErrorActionPreference = "Stop"

# Repo root = two levels up from this script (front\packaging -> repo).
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
Write-Host "Repo root: $Root"

Write-Host "`n==> [1/3] Installing front dependencies (uv sync --extra front)"
uv sync --extra front

Write-Host "`n==> [2/3] Freezing app with PyInstaller"
# Clean prior artifacts so stale files can't leak into the bundle.
Remove-Item -Recurse -Force "$Root\build", "$Root\dist\ArrowFront" -ErrorAction SilentlyContinue
uv run --extra front --with pyinstaller pyinstaller --noconfirm --clean `
    "front\packaging\arrow-front.spec"

if (-not (Test-Path "$Root\dist\ArrowFront\ArrowFront.exe")) {
    throw "PyInstaller did not produce dist\ArrowFront\ArrowFront.exe"
}

Write-Host "`n==> [3/3] Building installer with Inno Setup"
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    # Fall back to PATH (choco/scoop installs put iscc on PATH).
    $iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
}
if (-not $iscc) {
    throw "Inno Setup (ISCC.exe) not found. Install from https://jrsoftware.org/isdl.php"
}
& $iscc "front\packaging\arrow-front.iss"

Write-Host "`n==> Done. Installer:"
Get-ChildItem "$Root\dist\installer\*.exe" | ForEach-Object { Write-Host "    $($_.FullName)" }
