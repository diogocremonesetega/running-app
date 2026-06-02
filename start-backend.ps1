# Start FastAPI only (no Docker / GraphHopper). Use for the UI at http://localhost:8000
# Usage: .\start-backend.ps1
$ErrorActionPreference = "Stop"
$BackendDir = Join-Path $PSScriptRoot "backend"
$venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual env not found. Run: cd backend; python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}

Push-Location $BackendDir
$env:PYTHONPATH = "."
Write-Host "[start-backend] http://localhost:8000 (Ctrl+C to stop)" -ForegroundColor Green
Write-Host "[start-backend] Route generation requires GraphHopper on :8989 — run .\start.ps1 or .\graphhopper\start_graphhopper.ps1 in another terminal." -ForegroundColor Yellow
& $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
