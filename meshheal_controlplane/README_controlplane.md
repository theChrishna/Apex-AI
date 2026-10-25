# MeshHeal control plane

Loop (every 15 s): read newest snapshot -> validate (stale/NaN/missing = rejected) -> score
(rule detector; GNN plugs in behind the same interface with a 500 ms timeout, else rule fallback)
-> persistence rule (top node > 0.85 in 3 of last 4) -> safety checks (playbook exists, target pod
ready, no dependency on the faulty node, alternative healthy, cooldown) -> patch Istio VirtualService
or log ACTION_BLOCKED -> probe (90/5/5) after cooldown -> release if risk < 0.60 with real traffic.
Every decision is appended to audit_log.jsonl.

Run (from the project folder, venv active):
  pip install kubernetes pytest
  python -m pytest -q                                             # 13 tests, no cluster needed
  python -m controlplane.run --snapshots snapshots.jsonl --replay # decisions on your stored data
  python -m controlplane.run --snapshots snapshots.jsonl --dry-run  # live shadow mode: never writes
  python -m controlplane.run --snapshots snapshots.jsonl            # live, acting

Known limits (say them in the viva): only `ratings` has a reroute (reviews v1 skips it); details /
productpage / reviews faults are logged ACTION_BLOCKED (no_healthy_alternative); the rule detector
caught both 50 ms replay episodes (ep 2 details, ep 6 ratings), probably because the bucketed p95 reads 97.5 ms at the histogram bucket edge, so do not read this as sensitivity to smaller faults (untested); a node that depends on a rerouted culprit is logged SUPPRESSED_VICTIM instead of acted on; replay shows decisions only (no feedback loop);
GnnScorer is a stub until wired to model.py.
