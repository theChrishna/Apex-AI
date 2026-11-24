#!/usr/bin/env bash
# One-command setup (macOS / Linux / Git Bash). Run from anywhere:  ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
"$PY" -m pip install --upgrade pip
"$PY" -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
"$PY" -m pip install -r requirements-dev.txt
"$PY" test_pyg.py
for d in Frontend Frontend_v2 Frontend_v3; do (cd "$d" && npm ci --no-audit --no-fund); done
echo "Setup done. Run tests: cd meshheal_controlplane && ../$PY -m pytest -q"
