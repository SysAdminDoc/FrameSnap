[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $python = Get-Command python -ErrorAction Stop
    $pythonVersion = & $python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to query the selected Python interpreter."
    }
    Write-Host "Building with $($python.Source) (Python $pythonVersion)"
    & $python.Source -c "import cv2, numpy; from PIL import Image; import PyQt6"
    if ($LASTEXITCODE -ne 0) {
        throw "FrameSnap dependency import check failed. Install the declared runtime manifest first."
    }
    & $python.Source -m PyInstaller --noconfirm --onefile --windowed --name FrameSnap `
        --icon icon.ico `
        --add-data "translations;translations" `
        --hidden-import=numpy._core._exceptions `
        framesnap.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
