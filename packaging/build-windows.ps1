[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    & pyinstaller --noconfirm --onefile --windowed --name FrameSnap `
        --icon icon.ico `
        --hidden-import=numpy._core._exceptions `
        framesnap.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
