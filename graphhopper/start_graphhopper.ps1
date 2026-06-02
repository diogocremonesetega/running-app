# Start GraphHopper server (foreground; use start.ps1 for full stack)
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$GhVersion = "10.0"
$GhJar = Join-Path $ScriptDir "graphhopper-web-$GhVersion.jar"
$Config = Join-Path $ScriptDir "config.yml"
$OsmPath = Join-Path $ScriptDir "data\norcal-latest.osm.pbf"

if (-not (Test-Path $GhJar)) {
    Write-Error "GraphHopper JAR not found. Run: .\graphhopper\setup_graphhopper.ps1"
}
if (-not (Test-Path $OsmPath)) {
    Write-Error "OSM data not found. Run: .\graphhopper\setup_graphhopper.ps1"
}

$CacheDir = Join-Path $ScriptDir "data\graph-cache"
if (-not (Test-Path $CacheDir)) {
    Write-Host "First launch: building routing graph with elevation (~5-10 min for NorCal)..." -ForegroundColor Yellow
}

Write-Host "Starting GraphHopper at http://localhost:8989" -ForegroundColor Cyan
Set-Location $ScriptDir
java -Xmx4g -Xms1g -jar $GhJar server $Config
