# MeshHeal AI

Detects silent degradation and cascading failures in an Istio service mesh, finds the root-cause service,
and (only when safe) reroutes traffic, then releases it once the culprit recovers.
Read `CLAUDE.md` for the project facts and the honest evaluation numbers, and `PLAN.md` for the roadmap.

## Quickstart (no cluster needed)
Python 3.10+ and Node 22+.

Windows (PowerShell):
```powershell
.\scripts\setup.ps1
cd meshheal_controlplane
..\.venv\Scripts\python -m pytest -q
..\.venv\Scripts\python -m controlplane.run --snapshots ..\snapshots.jsonl --replay
```
macOS / Linux / Git Bash:
```bash
./scripts/setup.sh
cd meshheal_controlplane
../.venv/bin/python -m pytest -q          # on Windows Git Bash use ../.venv/Scripts/python
../.venv/bin/python -m controlplane.run --snapshots ../snapshots.jsonl --replay
```

## Dashboards
`Frontend` (browser-only simulation), `Frontend_v2` and `Frontend_v3` (read a Python API). Each: `npm install && npm run dev` (v2/v3 also need the API, see their READMEs).
Replay without a cluster: `python Frontend_v3/api/meshheal_api.py --mode replay --speed 10 --port 8766`.

## Live mode (needs a cluster)
Needs Docker, k3d, kubectl and istioctl; see `live_demo/README.md` and `docs/DEMO_SCRIPT.md`.
On Windows/WSL2 with cgroup v1 use a k3s image up to v1.33 (`k3d cluster create meshheal --image rancher/k3s:v1.33.5-k3s1 ...`); k3s v1.35 refuses to start there.
Never run kubectl write commands against a cluster you care about without reading the command first. The controller defaults to acting unless you pass `--dry-run`.
