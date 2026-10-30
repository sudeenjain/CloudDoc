# CloudDoc AI — One-click launcher for Windows PowerShell
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    & $VenvPython (Join-Path $RootDir "run.py")
} else {
    python (Join-Path $RootDir "run.py")
}
