# MeshHeal AI: project context (read first)

5th-semester CS mini project. **Submit 2026-10-30, present 2026-10-31.** Autonomous service-mesh orchestrator:
detect silent degradation / cascading failures in microservices early, then reroute traffic.

## Environment
- macOS, k3d cluster `meshheal` (1 server + 2 agents) on Docker Desktop, 16 GB RAM (memory pressure causes flaky errors).
- Istio demo profile + Prometheus addon. Bookinfo in namespace `aws-us-east` (gcp-asia / azure-eu are empty simulated regions).
- Python venv `.venv` in this folder. After a Docker restart: `k3d cluster stop meshheal && k3d cluster start meshheal`.
- Prometheus and Bookinfo need port-forwards (productpage on localhost:9080). If curl or telemetry fails, restart them.

## Bookinfo facts that matter
- productpage -> details, productpage -> reviews, reviews -> ratings.
- reviews has v1 / v2 / v3. **v1 does not call ratings; v2 and v3 do.** details/productpage have ONE version (nothing to reroute to).
- DestinationRule `reviews` (subsets v1/v2/v3) now exists. `reviews-normal.yaml` = 34/33/33, `reviews-reroute-v1.yaml` = 100% v1.
- Manual proof done: with a 100ms fault on ratings, 5/10 requests were slow (0.22-0.29 s, mean 0.134 s); after reroute 0/10 slow (mean 0.033 s). Istio needs ~a few seconds to propagate a route change.

## Data and models
- `snapshots.jsonl`: one JSON per line `{"timestamp": ISO UTC, "nodes":[{"id","region"}], "edges":[{"source","destination","request_rate","error_rate","latency_p95"}]}`; latency in ms, Prometheus histogram p95 is BUCKETED (97.5 / 241 / 242.5).
- Latency uses `reporter="source"` (Istio applies fault delay caller-side).
- Faults are injected with Istio VirtualService `fault.delay` (files `fault-*-delay.yaml`), NOT tc netem. ALWAYS delete fault VirtualServices afterwards and re-check `kubectl get virtualservice -n aws-us-east`.
- GNN: PyTorch Geometric 2-layer GCN, 6 node features `[in_rate, in_err, in_lat, out_rate, out_err, out_lat]`, log1p scaling, node order from `NODE_VOCAB` in `build_dataset_v2.py`. Code: `model.py`, `train.py`, `evaluate.py`, `loeo_eval.py`, `results_*.md`.

## Honest evaluation findings (do not overclaim; the viva will probe these)
- 8-fold leave-one-episode-out. GNN mean AP 0.928 (distinct-threshold AP, results_controls.md) or 0.923 (trapezoidal AP, results_loeo.md); p95 latency baseline 0.930 (distinct-threshold) or 0.898 (trapezoidal). Quote the distinct-threshold numbers: the trapezoidal method depends on sort order among tied scores, and the p95 baseline has many tied zero scores (log1p(0) for nodes with no incoming traffic). GNN root-cause top-1 0.950. No-graph MLP ablation beats or ties it on every fold (AP 0.983, RC1 1.000). A plain latency rule is about equal (AP ~0.93) but fails on the 100ms ratings fault by blaming the victim `reviews` (RC1 0.07).
- Policy simulation: GNN wrong-action rate 0.4% vs rule baseline 10.1%; but GNN false-alarm rate is unstable across seeds (3-20%) and thresholds vary per seed, so the GNN must be seed-averaged and gated by the rule detector.
- Only one testbed (Bookinfo), 8 episodes. The model is hardcoded to the 4 services; the *pipeline* (collect -> label -> train per deployment) is the deliverable.
- GNN-vs-MLP: say plainly that message passing adds nothing measurable on 4 nodes.

## Control plane (package `controlplane/`, tests in `tests/`)
Loop every 15 s: read newest snapshot (reject stale > 45 s / NaN / missing nodes) -> score -> persistence rule (top node risk > 0.85 in 3 of last 4) -> safety checks (playbook entry, target pod ready, no dependency on faulty node, alternative healthy, cooldown) -> patch VirtualService or log ACTION_BLOCKED -> after cooldown probe 70/15/15 (probe_share 30) -> release only if risk < 0.60 with real traffic (>= 0.05 req/s). Audit log `audit_log.jsonl` (live runs write `live_demo/audit_<scenario>_<time>.jsonl`).
- Only `ratings` has a reroute (reviews -> v1). Other culprits are blocked with `no_healthy_alternative`.
- `RuleScorer` = culprit rule `in_lat - out_lat` (victims cancel). `ResilientScorer` = primary scorer with 500 ms timeout, else rule fallback.
- `controlplane/gnn_adapter.py` (`GnnScorer`) loads the 5 seed models listed in `models/gnn_final_manifest.json` and averages sigmoid scores; `--gnn-kill-file` forces the rule fallback for the demo. Default demo model is v1 (v3 models exist but are not used).
- **Live closed-loop runs (2026-10-29, `live_demo/run_live.py`, ratings 150 ms fault, one run per scenario, no rates or averages):** A (GNN scores, `result_A_20261029T053627Z.json`): REROUTE of ratings 78.2 s after the fault, median latency 0.172 s faulted to 0.023 s, back to baseline within about 2 s of the reroute, probe 70/15/15, RELEASE 174 s after the fault was removed, 21 SCORED all primary. B (kill file, rule fallback scores, `result_B_20261029T064550Z.json`): REROUTE 63.7 s, 0.182 s to 0.024 s, RELEASE 174.9 s after fault removal, 19 SCORED all fallback. `live_demo/test_patch.py --yes` passed on 2026-10-28.
- Wording: detection is "about 60 to 80 s, set by the persistence rule". Do NOT say the fallback is faster than the GNN (A acted on the 4th high-risk cycle, B on the 3rd; the 14 s gap is unexplained). Do NOT quote 0.3 s / 1.8 s as recovery times (the script records the first of three consecutive fast samples 2 s apart). RELEASE shows the release logic works; the fault was removed before the probe started in both runs, so it does not show the probe catches a persisting fault.
- v3 data check (`REPORT_V3.md`): 215 snapshots excluded; baseline and culprit rule unchanged; GNN AP 0.928 to 0.898, MLP 0.983 to 0.955, about the size of seed noise; holdout FPR fell (baseline 0.140 to 0.039, GNN 0.128 to 0.031); v3 policy numbers are not comparable (split problem).
- Run: `python -m pytest -q` (35 tests in `meshheal_controlplane/`, no cluster) | `python -m controlplane.run --snapshots snapshots.jsonl --replay` | `--dry-run` (reads cluster, never writes) | no flag = acting.

## Rules for working here
- NEVER run kubectl write commands (apply/patch/delete) without the user's approval; always propose them first.
- Never commit under anyone else's identity. Teammates commit their own work.
- Don't overwrite uploaded data files (`snapshots.jsonl`, `fault_log.jsonl`, `labeled_dataset*.jsonl`); write new files.
- Report numbers you actually computed; flag anything untested. No marketing language ("+112%").
- Prefer small verifiable steps; run the tests after every change.
