# P2P AgentOps - one-command local launcher (Windows PowerShell).
#   .\run.ps1           build the SPA and serve everything from :8000
#   .\run.ps1 -Dev      API on :8000 + Vite dev server on :5173
#   .\run.ps1 -Reset    rebuild the demo dataset from scratch
param([switch]$Dev, [switch]$Reset)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($Reset) { $env:P2P_RESET_DATABASE_ON_STARTUP = '1' }

if (-not (Test-Path .venv)) {
  Write-Host "> Creating virtualenv..."
  python -m venv .venv
}
Write-Host "> Installing backend dependencies..."
.\.venv\Scripts\pip.exe install -q --upgrade pip
.\.venv\Scripts\pip.exe install -q -r backend\requirements.txt

if (Get-Command npm -ErrorAction SilentlyContinue) {
  if (-not (Test-Path frontend\node_modules)) {
    Write-Host "> Installing frontend dependencies..."
    Push-Location frontend; npm install --silent; Pop-Location
  }
  if (-not $Dev) {
    Write-Host "> Building the UI..."
    Push-Location frontend; npm run build; Pop-Location
  } else {
    Start-Process -FilePath "npm" -ArgumentList "run","dev" -WorkingDirectory "frontend"
    Write-Host ""
    Write-Host "  UI  -> http://localhost:5173   (hot reload)"
  }
} else {
  Write-Host "! npm not found - serving the API only. Install Node 18+ for the UI."
}

Write-Host ""
Write-Host "  P2P AgentOps -> http://localhost:8000"
Write-Host "  API docs     -> http://localhost:8000/api/docs"
Write-Host ""

Push-Location backend
& ..\.venv\Scripts\python.exe -m app.main
Pop-Location
