# Start PostGIS, GraphHopper, and FastAPI (Windows)
# Usage:
#   .\start.ps1              Full stack (Docker + GraphHopper + FastAPI)
#   .\start.ps1 -BackendOnly UI/API only — skips Docker and GraphHopper
#   .\start.ps1 -NoBackend   Docker + GraphHopper only
param(
    [switch]$NoBackend,
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$GhDir = Join-Path $RepoRoot "graphhopper"

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "$Name is not installed or not on PATH."
    }
}

function Start-FastApi {
    $python = $null
    foreach ($cmd in @("python", "py")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $python = $cmd
            break
        }
    }
    if (-not $python) { Write-Error "Python 3.10+ is required. Install from https://www.python.org/downloads/" }

    $venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "[start] Creating virtual environment..." -ForegroundColor Green
        Push-Location $BackendDir
        & $python -m venv .venv
        & .\.venv\Scripts\pip install -r requirements.txt
        Pop-Location
    }

    Push-Location $BackendDir
    $env:PYTHONPATH = "."

    Write-Host "[start] Running Alembic migrations (optional)..." -ForegroundColor Green
    & $venvPython -m alembic upgrade head 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[start] Alembic skipped or failed — UI still works; live run save needs PostGIS." -ForegroundColor Yellow
    }

    Write-Host "[start] FastAPI at http://localhost:8000 (keep this window open)" -ForegroundColor Green
    Write-Host "[OK] Backend starting — open http://localhost:8000 in your browser" -ForegroundColor Green
    & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
}

if ($BackendOnly) {
    Start-FastApi
    exit 0
}

Require-Command docker
Require-Command java

# 1. PostGIS
Write-Host "[start] Starting PostGIS (Docker)..." -ForegroundColor Green
docker compose -f (Join-Path $BackendDir "docker-compose.yml") up -d db
Write-Host "[start] Waiting for PostGIS..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    docker exec routegen-db pg_isready -U routegen -d routegen_db -q 2>$null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { Write-Error "PostGIS did not become ready in time. Use .\start-backend.ps1 for API-only, or start Docker Desktop." }
Write-Host "[start] PostGIS is ready." -ForegroundColor Green

# 2. GraphHopper (background job)
$ghJar = Join-Path $GhDir "graphhopper-web-10.0.jar"
if (-not (Test-Path $ghJar)) {
    Write-Error "Run .\graphhopper\setup_graphhopper.ps1 first."
}

$ghRunning = $false
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8989/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $ghRunning = $true }
} catch {}

if (-not $ghRunning) {
    Write-Host "[start] Starting GraphHopper on port 8989 (background)..." -ForegroundColor Green
    $ghConfig = Join-Path $GhDir "config.yml"
    Start-Process -FilePath "java" -ArgumentList @(
        "-Xmx4g", "-Xms1g", "-jar", $ghJar, "server", $ghConfig
    ) -WorkingDirectory $GhDir -WindowStyle Hidden

    for ($i = 1; $i -le 60; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8989/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) {
                Write-Host "[start] GraphHopper is ready." -ForegroundColor Green
                break
            }
        } catch {}
        if ($i -eq 60) {
            Write-Host "[start] GraphHopper still indexing — backend will start anyway. See graphhopper\graphhopper.log" -ForegroundColor Yellow
        }
        Start-Sleep -Seconds 5
    }
} else {
    Write-Host "[start] GraphHopper already running." -ForegroundColor Green
}

# 3. FastAPI
if (-not $NoBackend) {
    Start-FastApi
}
