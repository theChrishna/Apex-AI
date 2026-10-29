# MeshHeal control plane

Loop (every 15 s): read newest snapshot -> validate (stale/NaN/missing = rejected) -> score
(rule detector; GNN plugs in behind the same interface with a 500 ms timeout, else rule fallback)
-> persistence rule (top node > 0.85 in 3 of last 4) -> safety checks (playbook exists, target pod
ready, no dependency on the faulty node, alternative healthy, cooldown) -> patch Istio VirtualService
or log ACTION_BLOCKED -> probe (70/15/15, `probe_share`=30: ~0.27 req/s x 30% = 0.08 req/s into ratings, above the 0.05 evidence minimum) after cooldown -> release if risk < 0.60 with real traffic.
Every decision is appended to audit_log.jsonl.

Run (from the project folder, venv active):
  pip install kubernetes pytest
  python -m pytest -q                                             # 24 tests, no cluster needed (6 GNN tests skip without torch/weights)
  python -m controlplane.run --snapshots snapshots.jsonl --replay # decisions on your stored data
  python -m controlplane.run --snapshots snapshots.jsonl --dry-run  # live shadow mode: never writes
  python -m controlplane.run --snapshots snapshots.jsonl            # live, acting

GNN scorer (default is --scorer rule):
  --scorer gnn            GNN is the primary scorer; rule fallback on timeout (500 ms) or error
  --gnn-manifest PATH     default ../models/gnn_final_manifest.json (seed weights sit next to it);
                          created by `python train_final.py` run from the project root

Known limits (say them in the viva): only `ratings` has a reroute (reviews v1 skips it); details /
productpage / reviews faults are logged ACTION_BLOCKED (no_healthy_alternative); the rule detector
caught both 50 ms replay episodes (ep 2 details, ep 6 ratings), probably because the bucketed p95 reads 97.5 ms at the histogram bucket edge, so do not read this as sensitivity to smaller faults (untested); a node that depends on a rerouted culprit is logged SUPPRESSED_VICTIM instead of acted on; replay shows decisions only (no feedback loop);
the final GNN is 5 seeds (seed-averaged) trained on all 8 episodes (lag/recovery and the 137-snapshot
normal holdout excluded), so any replay with it is in-sample and not an accuracy result (LOEO is the
evaluation); the 0.85 / 0.60 thresholds were set for the rule scorer and are unchanged for the GNN.
