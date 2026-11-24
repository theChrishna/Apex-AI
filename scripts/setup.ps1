# One-command setup (Windows PowerShell). Run from the repo root:  .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m venv .venv
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
& $py -m pip install -r requirements-dev.txt
& $py test_pyg.py
if (Test-Path Frontend\package.json) { foreach ($d in "Frontend","Frontend_v2","Frontend_v3") { Push-Location $d; npm ci --no-audit --no-fund; Pop-Location } }
Write-Host "Setup done. Run tests: cd meshheal_controlplane; ..\.venv\Scripts\python -m pytest -q"
