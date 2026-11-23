# MeshHeal AI: rebuild plan (simple version)

Written 2026-11-23. Read `CLAUDE.md` first for facts and honest evaluation numbers. Nothing from this plan is built yet.

## Why a rebuild
The first version grew too big to understand (3 frontends, shadow run, experiments, probe/cooldown logic). The rebuild keeps only what is needed for the final presentation and a live demo. Old code stays in the repo as an archive and is not used by the new version.

## One sentence
Watch Bookinfo; when `ratings` gets slow, notice, send `reviews` traffic to v1 (which does not call ratings); when it recovers, put traffic back.

## Reuse (do not redo)
- Data: `snapshots.jsonl`, `labeled_dataset_v2.jsonl` (read only, never overwrite).
- Trained model: `models/gnn_final_seed*.pt` (5 seeds, averaged) + `models/gnn_final_manifest.json` + `model.py`. No retraining.
- Cluster setup: k3d `meshheal`, Istio, Bookinfo, `reviews-normal.yaml`, `reviews-reroute-v1.yaml`, `fault-ratings-delay.yaml`, `destinationrule-reviews.yaml`, `traffic_gen.py`, `telemetry.py`.
- Existing measured results (quote, do not recompute).

## Design: model scores, a rule decides
- Model gives each service a risk score. A simple rule decides: `ratings` risky 3 checks in a row -> reroute; fine 3 checks in a row -> back to normal. One bad score alone cannot trigger a reroute. If the model fails, fall back to the simple latency rule (`in_lat - out_lat`).

## New code (small, about 5 files, new folder)
1. `watch.py`: read latest numbers from Prometheus.
2. `score.py`: model risk per service (seed-averaged), rule fallback.
3. `decide.py`: the 3-in-a-row rule.
4. `act.py`: apply the reroute or normal YAML, write a decision log.
5. `server.py`: run the loop every 15 s and serve the web page.
Replay mode (`--replay`, uses saved data, no cluster) must work first and is the demo backup.

## Web page (new, from scratch)
One page, plain HTML + JavaScript, no React, no build step. Shows the 4 services coloured by risk, risk over time, current routing (normal / rerouted), and a live decision list. Refreshes itself every couple of seconds.

## Live demo
1. Start cluster. 2. Port-forwards (Prometheus, productpage). 3. Traffic generator. 4. Start MeshHeal + open page (all green, routing normal). 5. Apply the ratings fault. 6. About a minute later `ratings` turns red and page says rerouted to v1; latency drops. 7. Remove the fault; page returns to normal. One start script should do steps 1 to 4.
Detection takes about a minute because of the 3-in-a-row rule; be ready to explain that trade-off.

## Build order
1. New folder, new branch.
2. Backend in replay mode, check on saved data.
3. Web page against replay mode.
4. Live dry run (reads cluster, never writes).
5. Live real run (ask before any kubectl write).
6. Demo checklist and fallback (replay if the cluster misbehaves).
7. Short "how it works" note and likely viva questions with honest answers.
8. A few small tests after each step.

## Suggested split between two people
- Person A: backend (steps 2, 4, 5).
- Person B: web page (step 3), working against replay mode so no cluster is needed.
Each works on their own branch, merges by pull request, commits under their own name.

## Open questions
- Final presentation date.
- Should the fault be injected by a terminal command (simpler, obvious to the teacher) or a page button?
- Add the one-command start script? (recommended: yes)
