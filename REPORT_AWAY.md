# Report while you were away

Worked 2026-10-26 14:12 to about 14:22 UTC. All four steps are done. No git writes, no kubectl writes, and the telemetry, traffic,
port-forward and caffeinate processes were never touched (all 5 still alive at 14:20).

## Needs your attention
- **Battery:** at 14:12 the Mac was on battery at 5% (about 24 min left). At 14:20 it was charging at 17%. I could not plug it in; it looks like someone did.
  The telemetry file has gaps (below) from sleeps, so keep it plugged in for the next timed run.
- **Holdout label noise** (from the earlier investigation, still unfixed): the 10-06 details fault is inside the "normal" holdout. The v3 re-runs are still paused.
- **CLAUDE.md** says root-cause top-1 0.950 and AP 0.928 / 0.923. Both are now stated with methods (step 1).

## 1. CLAUDE.md: done
The AP line now gives GNN 0.928 (distinct-threshold, results_controls.md) and 0.923 (trapezoidal, results_loeo.md), the p95 baseline 0.930 and 0.898
respectively, and says to quote the distinct-threshold numbers because the p95 baseline has many tied zero scores. No other file changed for this.

## 2. State check at 14:12 UTC (as found)
- `shadow_run/pids.txt`: ALIVE: pf_productpage 43403, pf_prometheus 43404, traffic_gen 43428, telemetry 43430, caffeinate 72631.
  DEAD (expected, finished or stopped earlier): ctrl_rule 72686, ctrl_gnn 72687, run_schedule 72916, caffeinate_w 72917.
- Port 9080: productpage 200. Port 9090: "Prometheus Server is Ready."
- Pods in `aws-us-east`: 6 of 6 are 2/2 Running. Restarts: details, productpage, reviews-v1, reviews-v2 at 16 (last 18 h ago); ratings and reviews-v3 at 0.
- Istio: only the `reviews` VirtualService (34/33/33) and the `reviews` DestinationRule. No fault rule.
- `shadow_run/snapshots.jsonl`: 1722 lines; last snapshot 13 s old.
- Gaps over 60 s since 07:02:26Z: 10, all the Mac sleeping or on battery:
  07:09:34→07:36:21 (1607 s), 07:36:21→08:09:34 (1993 s), 08:09:34→08:25:39 (965 s), 08:25:39→08:39:11 (812 s), 08:39:11→08:52:01 (770 s),
  11:39:11→11:41:44 (153 s), 11:41:44→12:07:12 (1528 s), 12:07:12→12:23:05 (953 s), 12:23:05→13:10:24 (2839 s), 13:12:42→13:18:16 (334 s).
  Continuous since 13:18:16.
- Memory: macOS reports 52% free system-wide; only about 0.12 GB is strictly free (7860 pages of 16 KB).

## 3. Dashboard revamp: `Frontend_v2/` (the original `Frontend/` is untouched)
`git status` for `Frontend/` is exactly what it was before: `tsconfig.app.tsbuildinfo` modified and two `.bak-20261022` files untracked.

**What it is.** A fresh React + Vite + TypeScript app in a copy of the old folder (same toolchain, old `src` replaced; no new dependencies, plain CSS, Inter and
JetBrains Mono from the already installed @fontsource packages, nothing loaded from the network). Developer-docs look: sticky top nav, light/dark theme with a toggle
and `prefers-color-scheme` (saved in localStorage), large display headings, card grids (title, one-line description, action label), terminal-style code blocks with
a Copy button, primary/secondary buttons. Original branding only (the name MeshHeal AI and a simple four-node mark); no other company's logo, name, wording or artwork.
I also removed the template favicon and old replay data from the copy's `public/`.

**Pages** (hash routes): Overview (status strip: mode, scorer in use, GNN or fallback, last snapshot age; replay controls 1×/10×/Restart),
Live mesh (graph with per-node risk colours, edge p95 latency and rate, NORMAL/REROUTED/PROBING badge per controller, sparklines), Incidents (audit timeline
with filters; blamed node, risk, scorer source, fallback notes, dry-run tag), Evaluation (tables read from the repo files plus a "read this first" list of limits),
How it works (the loop, copy-able commands, safety reminders).

**Read-only API:** `Frontend_v2/api/meshheal_api.py`, stdlib only, serves the built dashboard and JSON (`/api/state`, `/api/evaluation`, `/api/replay/control` for REPLAY speed only).
It never writes a file. It reuses the control plane's `node_stats` and `RuleScorer` (import only).
- LIVE: tails `shadow_run/snapshots.jsonl` and `shadow_run/audit_gnn.jsonl` / `audit_rule.jsonl`; ages are real, so stopped telemetry or controllers show as stale.
- REPLAY: plays `snapshots.jsonl` plus both audit files for 2026-10-26 05:48:25Z–07:02:26Z at 1× or 10× in a loop (74 min at 1×, 7.4 min at 10×); always labelled REPLAY.
- No mock data anywhere: if the API is down you get an error banner, not placeholder numbers.

**Exact start commands** (project root):
```bash
cd Frontend_v2 && npm install && npm run build && cd ..        # dist/ is already built
.venv/bin/python Frontend_v2/api/meshheal_api.py --mode live                 # http://127.0.0.1:8765
.venv/bin/python Frontend_v2/api/meshheal_api.py --mode replay --speed 10    # http://127.0.0.1:8765 (stop the other one first, or add --port 8766)
# development with hot reload:
.venv/bin/python Frontend_v2/api/meshheal_api.py --mode live &  cd Frontend_v2 && npm run dev
```

**Verified:** `npm run build` (tsc + vite) passes with no errors. I ran the API in both modes against the real files and looked at the pages in the browser
(dark and light, 375 px width, no horizontal scroll, no console errors, 6 copy buttons, all 8 evaluation tables found). Then I stopped my two API servers.
What I saw: LIVE: the strip says "none running" because the controllers are dead, the snapshot age was a few seconds, and the Incidents list holds 46 historic
events (including stale-snapshot rejections from the sleep gaps). REPLAY: GNN in use, 6 s snapshot age, node colours and badges from the replayed position.

**Not verified / limits:**
- Per-node risk on the graph is the **rule** score computed from the snapshot, labelled as such; the audit files hold only the top node's risk per scorer, so no per-node GNN risk exists to show.
- Contrast was chosen from the token values, not measured with a tool; no screen-reader test; the REROUTE/PROBING badges were not seen live in the browser (the replay loop was only checked near its start). The same fold logic runs on the real events and gave the right state in the API check.
- The Evaluation page's limits text is static and comes from CLAUDE.md and my holdout investigation (the 50-of-70, 12/38 split numbers); the tables are unmodified file contents.
- Importing `controlplane` from the API may write `__pycache__` files inside `meshheal_controlplane/controlplane/`; no source file there was edited.
- `Frontend_v2/node_modules` is a 190 MB copy (gitignored), so the copy builds offline.

## 4. Closed-loop demo: `live_demo/run_live.py` and `live_demo/README.md` (written, NOT run)
Only a syntax check was done; I did not run it, not even its read-only pre-flight.
- Starts the real **acting** controller (`--scorer gnn`, `--gnn-kill-file live_demo/gnn.off`, no `--dry-run`) with a new audit file per run.
- Scenario A: apply `shadow_run/fault-ratings-150.yaml`; record fault start, first REROUTE, and when 3 consecutive productpage samples (curl every 2 s into `live_demo/latency.csv`) are below 0.1 s after it; hold 30 s; remove the fault; record the RELEASE.
- Scenario B: same with the kill file touched first; it refuses to inject unless the controller logs SCORED source=fallback.
- kubectl writes: apply of the fault YAML, delete of the `ratings` VirtualService, and cleanup (delete `ratings` and `details` with `--ignore-not-found`, apply `reviews-normal.yaml`) in a `finally` block and on Ctrl-C / SIGTERM. It never deletes `reviews`. The controller patches `reviews` itself (that is its job).
- Safety: needs `--yes`; pre-flight checks only `reviews` at 34/33/33 without a fault, pods 2/2, productpage 200, snapshot under 45 s old, not on battery.
- Expected timing is from the dry-run shadow run (first REROUTE 60 to 76 s after the fault), not a closed-loop measurement. Release needs cooldown 120 s plus probe 90 s, so budget 8 to 12 minutes per scenario.

## Not done / skipped
- Nothing needed approval I did not have. I did not touch `controlplane/`, `models/`, `build_dataset_v2.py`, `model.py`, `train.py`, any `results_*` file or data file.
- Still paused from before: the holdout exclusion in `build_dataset_v2.py` and the v3 LOEO/policy re-runs.
