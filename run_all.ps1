1193# Run all steps: create venv, install deps, scrape, fallback if needed, analyze
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force
cd $PSScriptRoot

# Create venv if missing
if (-not (Test-Path .venv)) {
  python -m venv .venv
}

# Activate venv for this session
. .\.venv\Scripts\Activate.ps1

# Upgrade pip and install deps
python -m pip install --upgrade pip
pip install -r requirements.txt

# Run scraper (limit pages to 3 to be quick)
$env:SCRAPER_MAX_PAGES = "3"
Write-Host "Running scraper..."
python scraper\scraper.py

# Check results file
$resultFile = Join-Path $PSScriptRoot "data\jokker_results.json"
if (Test-Path $resultFile) {
  $json = Get-Content $resultFile -Raw | ConvertFrom-Json
  if ($json.draws -and $json.draws.Count -gt 0) {
    Write-Host "Scraper produced $($json.draws.Count) draws. Running analyzer..."
    python analyzer\analyzer.py
    exit 0
  }
  else {
    Write-Host "No draws found by scraper. Generating synthetic draws and running analyzer..."
    python tools\generate_synthetic_draws.py
    python analyzer\analyzer.py
    exit 0
  }
} else {
  Write-Host "No results file found. Generating synthetic draws and running analyzer..."
  python tools\generate_synthetic_draws.py
  python analyzer\analyzer.py
  exit 0
}
