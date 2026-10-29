# Demo script: 8 minutes, 31 October

Commands run from the project root unless noted. Verified on the real cluster: `live_demo/test_patch.py --yes` passed on 2026-10-28; `demo_up.sh` was run on 2026-10-28 and 2026-10-29; `live_demo/run_live.py` ran scenario A (GNN scores) and scenario B (kill file, rule fallback scores) on 2026-10-29, one run each (`live_demo/result_A_20261029T053627Z.json`, `live_demo/result_B_20261029T064550Z.json`). The talk below has not been rehearsed end to end as a whole, and the dashboard in LIVE mode has not been watched during a running controller. Keep the REPLAY fallback ready.

Observed timings (one run each, not averages): the reroute came 78.2 s (A) and 63.7 s (B) after the fault was applied; latency was back to baseline within about 2 s of the reroute (median 0.172 s faulted to 0.023 s in A, 0.182 s to 0.024 s in B); PROBE_START about 120 s after the reroute; RELEASE about 210 s after the reroute and 174 s (A) and 174.9 s (B) after the fault was removed. Say "about 60 to 80 seconds, set by the persistence rule" (3 of the last 4 cycles of 15 s, plus the 1-minute Prometheus rate window); the shadow run gave 60.5 to 76.4 s. Do not say one scorer is faster: A acted on the 4th high-risk cycle and B on the 3rd, and the 14 s gap is unexplained (probably one extra cycle).

## 1. Pre-demo checklist

Day before (about 30 minutes; steps 4 and 6 were already done once on 2026-10-28 and 2026-10-29, repeat them only if you want a fresh recording):
1. Laptop plugged in, lid open, Docker Desktop running. After a Docker restart: `k3d cluster stop meshheal && k3d cluster start meshheal`, then wait until `kubectl get pods -n aws-us-east` shows all 2/2 Running.
2. `./demo_up.sh --caffeinate` (starts the port-forwards, traffic generator, telemetry and caffeinate; it refuses to start if they already run). Wait about 30 s, then `tail -2 shadow_run/telemetry.log` should say `Saved 4 nodes, 3 edges`.
3. `kubectl get virtualservice,destinationrule -n aws-us-east`: only `reviews` (34/33/33) and its DestinationRule.
4. Patch test: `.venv/bin/python live_demo/test_patch.py` (read-only pre-flight) then `.venv/bin/python live_demo/test_patch.py --yes` (sets reviews to 100% v1, reads it back, restores 34/33/33). If this fails the controller cannot reroute; do not go on, use REPLAY.
5. `cd meshheal_controlplane && ../.venv/bin/python -m pytest -q` (35 passed expected).
6. Scenario A: `caffeinate -i .venv/bin/python live_demo/run_live.py --scenario A --yes` (the 2026-10-29 run took about 5 minutes: 05:36:27 to 05:41:31). Read `live_demo/result_A_*.json`. Then scenario B the same way with `--scenario B` (06:45:50 to 06:50:39). Keep both result files as a backup to show. `live_demo/latency.csv` is appended to by both scenarios (column `scenario`).
7. Build the dashboard: `cd Frontend_v2 && npm run build && cd ..` (a `dist/` already exists).

One hour before:
- `kubectl get pods -n aws-us-east` all 2/2; `kubectl get virtualservice -n aws-us-east` only `reviews`; battery charging; notifications off; close memory-heavy apps (16 GB machine).
- Start the dashboard in LIVE mode, following the newest live-demo audit file:
  ```bash
  .venv/bin/python Frontend_v2/api/meshheal_api.py --mode live --audit "gnn=live_demo/audit_*.jsonl"
  ```
  Open http://127.0.0.1:8765. Before the demo run it shows "none running" (no controller yet): that is correct. Open the Overview page.
- Terminals: (1) commands, (2) `tail -F live_demo/latency.csv` (the file appears when the run starts), (3) spare.
- Open `figures/fig_d_pipeline_light.png` (or the dark one) and `docs/VIVA_QA.md`.

## 2. The 8 minutes

| Time | Do | Say |
|---|---|---|
| 0:00 to 0:50 | Show `figures/fig_d_pipeline_*.png`. | "Microservices degrade silently: one slow service makes its callers look slow. MeshHeal reads Istio latency every 15 s, scores which service is the culprit, checks the reroute is safe, patches the traffic split, probes, and releases. Every decision is audited. One testbed, Bookinfo, one reroute: reviews to v1 when ratings is slow." |
| 0:50 to 1:10 | Terminal: `kubectl get pods -n aws-us-east` and `kubectl get virtualservice -n aws-us-east`. | "Healthy, 2/2, and only the normal reviews traffic split." |
| 1:10 | Terminal: `caffeinate -i .venv/bin/python live_demo/run_live.py --scenario A --yes` | "This starts the real acting controller with the GNN as scorer, waits until it scores, then injects a 150 ms delay on ratings." (Pre-flight output scrolls by: it checks cluster state, snapshot age, battery.) |
| 1:15 to 2:15 | Dashboard Overview. | Point at the strip: "Mode LIVE, scorer in use GNN, source GNN not fallback, snapshot age a few seconds." Open Live mesh: nodes green. "Node colour here is the rule score computed from the snapshot; the audit logs only keep the top node's risk." The fault goes on around 1:35. |
| about 1:35 to 2:50 | Live mesh: ratings turns red; terminal 2 shows `time_total_s` rising from about 0.03 to about 0.13 to 0.3 s. | "reviews looks slow too, but it is a victim waiting on ratings. The culprit rule subtracts the downstream latency, so only ratings is blamed. The controller waits for 3 of the last 4 cycles above 0.85, so about a minute." |
| about 2:50 | Incidents page: REROUTE, blamed ratings, scorer GNN. | "Safety checks passed: playbook entry, target pod ready, no dependency on ratings, alternative healthy, cooldown. It patched reviews to 100% v1, which does not call ratings." |
| about 3:00 to 3:30 | Terminal 2: latency falls below 0.1 s. | "Latency is back under 0.1 s. The script waits 30 s, then removes the fault." (Script prints fault removal about 3:30.) |
| 3:30 to 5:15 | Evaluation page. | "Honest numbers: GNN AP 0.928, baseline 0.930, a no-graph MLP 0.983. So a graph adds nothing measurable on 4 nodes. 8 episodes, one testbed, final model in-sample. Two AP methods exist; distinct-threshold is the correct one because the baseline has many tied zero scores. Label noise is a listed limitation: the normal holdout included an unlogged-looking fault on October 6 and some Sep 16 training-normal data show about 242 ms reviews latency. A v3 check that excludes 215 snapshots leaves the baseline unchanged, moves GNN AP 0.928 to 0.898 and MLP 0.983 to 0.955 by about the seed noise, and lowers the holdout false-positive rate; the demo still uses the v1 model." |
| 5:15 to 5:50 | Overview, then `figures/fig_b_detection_time_*.png`. | "Shadow run, dry-run: 4 of 4 correct, identical decisions from rule and GNN, 0 false events in a 30-minute soak. Detection about 60 to 80 s, set by the persistence rule, not by the scorer." |
| about 6:15 to 6:45 | Incidents: PROBE_START then RELEASE appear. | "After the cooldown it sends 30% of traffic back to the suspect path, 70/15/15, and releases only if risk is under 0.60 with enough real traffic. Back to 34/33/33." (Observed: RELEASE came 210 s (A) and 209 s (B) after the REROUTE, so about 6:15 if the fault goes on at 1:35; if it has not appeared by 7:00 say so and move on, it will finish after the demo. Say that the fault was already removed before the probe started, so RELEASE shows the release logic works, not that the probe catches a fault that is still present.) |
| 6:45 to 7:20 | Scenario B, from the recorded `live_demo/result_B_*.json` and the Incidents page filtered to "FALLBACK SCORING" (re-run the dashboard on that audit file if needed). | "Second scenario: we touch a kill file so the GNN raises and the rule fallback scores. The audit line says source fallback with the note, and the controller still reroutes. Removing the file brings the GNN back. A full live run takes about 5 minutes, so this is the recorded run of 2026-10-29: all 19 SCORED events are fallback, REROUTE 63.7 s after the fault, one run." (Do not say the fallback is faster than the GNN; the 14 s difference from A is unexplained.) |
| 7:20 to 8:00 | Close. | "What we do not claim: not production-ready, one testbed, 8 episodes, and what you saw live is a single trial per scenario with no repeated-run statistics. Not yet done, and listed as limitations: the probe against a fault that is still present, repeatability of the timings, and the cause of the Sep 16 label noise. Next steps: gate the GNN with the rule, test a second application." |

If anything looks wrong during the run: Ctrl-C in the run terminal. The script's cleanup deletes the ratings and details fault rules and re-applies `reviews-normal.yaml`. Then check:
```bash
kubectl get virtualservice,destinationrule -n aws-us-east
```
Only `reviews` (34/33/33) should remain. If not: `kubectl delete virtualservice ratings details -n aws-us-east --ignore-not-found` then `kubectl apply -f reviews-normal.yaml`. Never delete the `reviews` VirtualService.

## 3. Showing scenario A and B (reference)

Summarised from `live_demo/README.md`.
- **A**: no kill file; controller must log SCORED source primary; apply `shadow_run/fault-ratings-150.yaml`; first REROUTE; 3 consecutive productpage samples under 0.1 s after the REROUTE; hold 30 s; remove the fault; RELEASE.
- **B**: kill file `live_demo/gnn.off` touched first; controller must log SCORED source fallback with the note; the rest is identical. The kill file is removed in cleanup.
- Outputs in `live_demo/`: `latency.csv`, `audit_<scenario>_<time>.jsonl`, `controller_<scenario>_<time>.log`, `result_<scenario>_<time>.json`.

## 4. Fallbacks

**Docker or the cluster fails (before or during the demo)**
1. Do not debug on stage. Stop any run with Ctrl-C and, if the cluster still answers, confirm with `kubectl get virtualservice -n aws-us-east` that only `reviews` is present.
2. Switch the dashboard to the recorded shadow run (needs no cluster, only the files):
   ```bash
   .venv/bin/python Frontend_v2/api/meshheal_api.py --mode replay --speed 10
   ```
   Open http://127.0.0.1:8765. The page is labelled REPLAY. At 10× the run from 05:48 to 07:02 takes about 7.4 minutes; use "Restart" on the Overview page. Approximate offsets from the start: ratings 150 ms fault begins about 3:00, REROUTE about 3:08, PROBE_START about 3:20, RELEASE about 3:50, details block about 4:14, reviews block about 5:20 (computed from the audit timestamps). Say clearly that this is a recording of a dry-run.
3. Text replay without any cluster: `cd meshheal_controlplane && ../.venv/bin/python -m controlplane.run --snapshots ../snapshots.jsonl --replay`.
4. If the dashboard or node fail too: show `figures/*.png`, `shadow_run/results_shadow.md` and `results_controls.md`.

**Port-forwards or telemetry drop** (snapshot age on the Overview page turns red): `kubectl get pods -n aws-us-east`; if healthy, kill the old forwards (`kill $(awk '/pf_/{print $2}' shadow_run/pids.txt)`) and run `./demo_up.sh` again (it refuses while any old process is alive, so stop those first). Telemetry gaps happen when the Mac sleeps: keep it plugged in and awake.

**The reroute does not happen within 4 minutes**: the script times out, removes the fault and cleans up. Say "the controller did not act in the window"; show the dry-run table instead. Do not retry on stage.

**Latency does not recover after the reroute**: same; show `live_demo/result_A_20261029T053627Z.json` (latency median 0.172 s faulted, 0.023 s after the reroute).

## 5. Not verified
Verified once on the real cluster (2026-10-28 and 2026-10-29): the JSON merge patch (`test_patch.py --yes`), the reroute of ratings to v1, latency back to baseline within about 2 s of the reroute, the 70/15/15 probe and RELEASE, and the kill-file fallback (19 of 19 SCORED events fallback in B). Each is one run.

Still unverified:
- The probe against a fault that is still present: in both runs the fault was removed before the probe started, so RELEASE shows the release logic works, not that the probe holds back a release while the fault persists.
- Repeatability: one run per scenario, so no spread. The 14 s difference in detection time (78.2 s in A, 63.7 s in B) is unexplained; A acted on the 4th high-risk cycle and B on the 3rd.
- The dashboard in LIVE mode during a running acting controller: it was started before the runs and, afterwards, its API served scenario B's audit events (REROUTE, PROBE_START, RELEASE) with "controllers not running", but nobody watched it while a controller ran.
- Recovery time to the second: the script reports the first of three consecutive fast samples taken 2 s apart, so say "within about 2 seconds of the reroute".
- Why the Sep 16 label noise occurred, and whether it explains the GNN's weak reviews 100 ms fold.
