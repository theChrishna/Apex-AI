# MeshHeal control plane

Loop (every 15 s): read newest snapshot -> validate (stale/NaN/missing = rejected) -> score
(rule detector; GNN plugs in behind the same interface with a 500 ms timeout, else rule fallback)
-> persistence rule (top node > 0.85 in 3 of last 4) -> safety checks (playbook exists, target pod
ready, no dependency on the faulty node, alternative healthy, cooldown) -> patch Istio VirtualService
or log ACTION_BLOCKED -> probe (70/15/15, `probe_share`=30: ~0.27 req/s x 30% = 0.08 req/s into ratings, above the 0.05 evidence minimum) after cooldown -> release if risk < 0.60 with real traffic.
Every decision is appended to audit_log.jsonl.

Run (from the project folder, venv active):
  pip install -r ../requirements-dev.txt   # or run ../scripts/setup.ps1 (Windows) / ../scripts/setup.sh
  python -m pytest -q                                             # 117 tests, all pass on a clean install (torch + kubernetes installed), no cluster needed
  python -m controlplane.run --snapshots snapshots.jsonl --replay # decisions on your stored data
  python -m controlplane.run --snapshots snapshots.jsonl            # live SHADOW mode (the default): reads, never writes
  python -m controlplane.run --snapshots snapshots.jsonl --act      # live, acting: the only way to write to the cluster

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

## Using it on a mesh that is not Bookinfo (Phase 2)
1. Collect: `python -m controlplane.collect --namespace shop --out live_shop.jsonl` finds the services and edges from Istio
   metrics in Prometheus (no service names to configure). It only appends to `--out` and refuses `snapshots.jsonl`.
2. Playbook: `python -m controlplane.playbook_gen --namespace shop --out playbooks/shop.yaml` reads DestinationRules,
   VirtualServices and Prometheus (read-only) and drafts reroutes. Every draft has `confirmed: false` and the controller
   refuses it (`ACTION_BLOCKED reason=playbook_unconfirmed`) until a person checks it and sets `confirmed: true`.
   A version that "never calls X" in the metrics may simply have had no traffic, so the generator only gives evidence.
3. Settings: copy `meshheal.example.yaml`, then `python -m controlplane.run --config meshheal.yaml --snapshots live_shop.jsonl --dry-run`.
4. Scorer: the GNN only knows the four Bookinfo services. On any other mesh it raises and the rule scorer is used
   (audit log: `SCORED source=fallback`, note `model does not know service(s): ...`). A topology-agnostic model is Phase 3.

Changes to how the cluster is written (acting mode): `KubeClient.set_weights` used to send a merge patch that replaced the
whole `spec.http` list. It now reads the VirtualService and changes only the destination weights of the one catch-all
(`match`-less) route, keeping match rules, retries, timeouts and ports, and sends it with the `resourceVersion` it read,
so a concurrent edit makes the API server refuse (409) instead of being overwritten. If there is not exactly one
catch-all route the change is refused and logged as `ACTION_FAILED`; dry-run reports the same refusal without writing.
Verified: unit tests, and a read-only check against the live Bookinfo VirtualService. The real write (`replace`) has
not yet been run against a live cluster.

## Running it for real (Phase 5)
Shadow mode is the default; `--act` is required to write. Reroutes are recorded on the VirtualService (annotation `meshheal.io/state`) in the same
write as the weights, so a restart picks them up (`RECONCILED`) and a reroute is never permanent (`max_reroute_s`, default 1 h). `max_actions_per_hour`
(default 6) limits new reroutes, and a `meshheal-control` ConfigMap with `paused: "true"` freezes all writes. `--metrics-port` serves `/healthz` and
`/metrics`. Container image: `deploy/Dockerfile`; Helm chart: `deploy/helm/meshheal` (shadow mode has a Role without any write verb).
The full runbook, failure behaviour and limits are in `docs/OPERATIONS.md`.
