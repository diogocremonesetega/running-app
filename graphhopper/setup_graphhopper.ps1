# Downloads GraphHopper JAR and NorCal OSM data (Windows)
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$DataDir = Join-Path $ScriptDir "data"
$GhVersion = "10.0"
$GhJar = "graphhopper-web-$GhVersion.jar"
$GhJarUrl = "https://repo1.maven.org/maven2/com/graphhopper/graphhopper-web/$GhVersion/$GhJar"
$OsmUrl = "https://download.geofabrik.de/north-america/us/california/norcal-latest.osm.pbf"
$OsmFile = "norcal-latest.osm.pbf"

Write-Host "=== GraphHopper Setup (Windows) ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir "elevation-cache") | Out-Null

$JarPath = Join-Path $ScriptDir $GhJar
if (-not (Test-Path $JarPath)) {
    Write-Host "Downloading GraphHopper $GhVersion..."
    Invoke-WebRequest -Uri $GhJarUrl -OutFile $JarPath
    Write-Host "GraphHopper JAR downloaded." -ForegroundColor Green
} else {
    Write-Host "GraphHopper JAR already exists." -ForegroundColor Green
}

$OsmPath = Join-Path $DataDir $OsmFile
if (-not (Test-Path $OsmPath)) {
    Write-Host "Downloading NorCal OSM PBF (~450 MB). This may take several minutes..."
    Invoke-WebRequest -Uri $OsmUrl -OutFile $OsmPath
    Write-Host "OSM data downloaded." -ForegroundColor Green
} else {
    Write-Host "OSM data already exists." -ForegroundColor Green
}

Write-Host ""
Write-Host "Setup complete. Start GraphHopper with:" -ForegroundColor Cyan
Write-Host "  .\graphhopper\start_graphhopper.ps1"
