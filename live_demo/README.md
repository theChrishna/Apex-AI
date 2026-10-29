# Closed-loop live demo

`run_live.py` starts the real, ACTING controller (no `--dry-run`, `--scorer gnn`, `--gnn-kill-file`),
injects the ratings 150 ms fault and records what happens. It was run once per scenario on 2026-10-29 (results below).

## What it does

| Step | Scenario A (GNN acts) | Scenario B (rule fallback acts) |
|---|---|---|
| 1 | no kill file; controller must log `SCORED source=primary` | kill file `live_demo/gnn.off` touched first; controller must log `SCORED source=fallback` with the kill-file note |
| 2 | `kubectl apply -f shadow_run/fault-ratings-150.yaml`; time recorded | same |
| 3 | first `REROUTE` in the audit file (detection time after the fault) | same |
| 4 | `curl` productpage every 2 s into `live_demo/latency.csv`; recovered = 3 consecutive samples below 0.1 s after the REROUTE | same |
| 5 | fault held 30 s after recovery, then `kubectl delete virtualservice ratings` | same |
| 6 | wait for `RELEASE` (cooldown 120 s, then a 90 s probe at 70/15/15 with `probe_share` 30; earliest about 210 s after the REROUTE; with the fault removed before the first probe, expect roughly 2.5 to 4 min after removal (computed from the config, not observed)) | same |
| 7 | cleanup, `result_<scenario>_<time>.json` | same, kill file removed |

Total per scenario: about 8 to 12 minutes. Outputs (all in `live_demo/`): `latency.csv` (appended), `audit_<scenario>_<time>.jsonl`,
`controller_<scenario>_<time>.log`, `result_<scenario>_<time>.json`.

## kubectl writes it makes (and nothing else)

- `apply -f shadow_run/fault-ratings-150.yaml` and `delete virtualservice ratings` (the fault)
- in cleanup, always: `delete virtualservice ratings` and `details` with `--ignore-not-found`, and `apply -f reviews-normal.yaml`
- it never deletes the `reviews` VirtualService. The acting controller itself patches `reviews` weights (that is its job: reroute, probe, release).

Cleanup also runs on Ctrl-C and SIGTERM and removes the kill file. If the Mac loses power mid-run the fault stays applied: run the check below.

## Before you run it

1. Plug the laptop in and keep the lid open (`caffeinate` below). A sleep mid-run leaves the fault applied.
2. Telemetry, traffic generator and both port-forwards (9080, 9090) must be running (`shadow_run/pids.txt`).
3. Pre-flight (read-only, no `--yes`): checks only `reviews` exists at 34/33/33 with no fault, all pods 2/2 Running, productpage 200, newest snapshot under 45 s old, not on battery.

```bash
.venv/bin/python live_demo/run_live.py --scenario A
```

## Run

```bash
caffeinate -i .venv/bin/python live_demo/run_live.py --scenario A --yes
caffeinate -i .venv/bin/python live_demo/run_live.py --scenario B --yes
```

Run B after A has finished and `kubectl get virtualservice -n aws-us-east` shows only `reviews`.

## What to watch

In a second terminal (all read-only):

```bash
tail -f live_demo/audit_A_*.jsonl | grep -v SCORED          # REROUTE, PROBE_START, RELEASE as they happen
tail -f live_demo/latency.csv                                # productpage time_total_s; slow is above 0.1
watch -n 5 "kubectl get virtualservice reviews -n aws-us-east -o jsonpath='{range .spec.http[*].route[*]}{.destination.subset}={.weight} {end}'"
```

Expect the first REROUTE about 60 to 80 s after the fault, set by the persistence rule (shadow run 60.5 to 76.4 s; live runs 63.7 s and 78.2 s).
Latency with the fault was about 0.17 to 0.18 s (median) and back to about 0.02 s after the reroute in the live runs. Istio needs a few seconds to propagate a route change.
In scenario B the audit lines should show `source: "fallback"` with a note containing `GNN disabled by kill file`.

## After the run

```bash
kubectl get virtualservice,destinationrule -n aws-us-east    # only reviews (34/33/33) and its DestinationRule
```

If a `ratings`/`details` fault VirtualService is still there: `kubectl delete virtualservice ratings -n aws-us-east` (and `details`). If `reviews` is not 34/33/33: `kubectl apply -f reviews-normal.yaml`.

## Results (2026-10-29, one run per scenario, ratings 150 ms fault; no rates or averages)

| | A: GNN scores (`result_A_20261029T053627Z.json`) | B: kill file, rule fallback scores (`result_B_20261029T064550Z.json`) |
|---|---|---|
| REROUTE of ratings | 78.2 s after the fault | 63.7 s after the fault |
| Median productpage latency, faulted then after reroute | 0.172 s then 0.023 s | 0.182 s then 0.024 s |
| PROBE_START (70/15/15) | 05:40:00Z | 06:49:07Z |
| RELEASE | 174 s after the fault was removed | 174.9 s after the fault was removed |
| SCORED events | 21, all `primary` | 19, all `fallback` with the kill-file note |

`live_demo/test_patch.py --yes` passed on 2026-10-28 (reviews moved to v1=100, read back, restored to 34/33/33). After both runs only `reviews` (34/33/33) and its DestinationRule remained and the kill file was gone.

Reading the numbers:
- Detection is about 60 to 80 s, set by the persistence rule. Do not say the fallback is faster than the GNN: A acted on the 4th high-risk cycle and B on the 3rd; the 14 s gap is unexplained and probably one extra cycle, not a scorer effect.
- "Recovery" is the script's first of three consecutive productpage samples under 0.1 s, taken 2 s apart, so say latency was back to baseline within about 2 seconds of the reroute, not 1.8 s or 0.3 s.
- RELEASE shows the release logic works. The fault was removed before the probe started in both runs, so it does not show that the probe catches a fault that is still present.
- `latency.csv` is opened in append mode and shared by both scenarios (column `scenario`); when checked after the runs it held 150 rows for A and 143 for B.

## Not tested

The probe share was raised from 10 to 30 so the probe sees at least 0.05 req/s into ratings (about 0.27 req/s x 30% = 0.08); both live runs released, but with the fault already removed.

Not verified: the probe while the fault is still on, repeatability (one run per scenario), the cause of the 14 s detection gap, and the dashboard in LIVE mode while a controller is running.
