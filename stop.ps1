# Stop PostGIS, GraphHopper, and FastAPI (Windows)
$ErrorActionPreference = "Continue"
$RepoRoot = $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"

Write-Host "[stop] Stopping FastAPI (port 8000)..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "uvicorn app\.main:app" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "[stop] Stopping PostGIS..." -ForegroundColor Yellow
docker compose -f (Join-Path $BackendDir "docker-compose.yml") down 2>$null

Write-Host "[stop] Stopping GraphHopper (Java)..." -ForegroundColor Yellow
Get-CimInstance Win32_Process -Filter "Name = 'java.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "graphhopper-web" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "[stop] Done." -ForegroundColor Green
