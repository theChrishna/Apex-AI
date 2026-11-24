# Prompt for the teammate's Claude Code session: generate MeshHeal AI snapshots

Paste everything below the line into a new Claude Code session opened in the repo root (branch `Varun`).

---

You are helping me produce **labelled service-mesh snapshots** for MeshHeal AI (this repo, branch `Varun`), a project that detects silent degradation and cascading failure in an Istio service mesh, finds the root-cause service, and (only when safe) reroutes traffic. Read `CLAUDE.md`, `README.md`, `meshheal_controlplane/README_controlplane.md` and `topo/sim.py`, `topo/real.py`, `topo/run_boutique_faults.py` first and treat them as ground truth. Then give me a short plan and wait for my OK before running anything.

## What has been done (verified; do not redo)
- Phase 1: reproducible setup (`requirements.txt`, `scripts/setup.ps1|sh`), CI. Phase 2: generic service discovery, YAML playbooks, safer VirtualService patching. Both pushed; CI green.
- Phase 3 code in `topo/`: a graph builder for any set of services (identical to the old builder on the real Bookinfo data), a mesh **simulator** (`topo/sim.py`, `python -m topo.generate`), an evaluation harness (`topo/eval.py`), a real-data labeller (`topo/real.py`) and a fault runner (`topo/run_boutique_faults.py`).
- A snapshot = `{"timestamp", "nodes":[{"id","region"}], "edges":[{"source","destination","request_rate","error_rate","latency_p95"}]}`; latency in ms, p95 comes from Istio's bucketed histogram (so values like 97.5 and 242.5 are normal). Labelling rule (same as the original Bookinfo data): lag = first 90 s of a fault, excluded; steady = from 90 s to the end of the fault, only the faulted service is positive; recovery = 90 s after the fault, excluded; everything else is normal.
- Computed result on 5,760 simulated snapshots (5 seeds, 40 epochs, `topo/results/phase3_run1.md`): on meshes of unseen shapes and on bigger meshes the plain per-node MLP beat the GNN (AP 0.52 vs 0.33; 0.42 vs 0.16), and the GNN was **not adopted** under the rule we agreed in advance. On real Bookinfo the GNN reached AP 0.73 vs MLP 0.58, but that number is optimistic because the simulator was calibrated on Bookinfo. Do not claim the GNN generalizes.
- Second real app: Online Boutique (12 services, gRPC, no versions, so detection and root-cause only, no reroute) on a k3d cluster. A first fault run was discarded (load generator `USERS=10` saturated the frontend: 197m of its 200m CPU limit). The clean run was then done with `USERS=3`: 10 delay episodes, one per service, 354 snapshots in `topo/boutique_snapshots_clean.jsonl` with the log `topo/boutique_fault_log.jsonl`, plus 140 fault-free snapshots in `topo/boutique_snapshots_normal.jsonl`. `python -m topo.check_boutique` passed (10/10 faults visible, 10/10 isolated). Independent real test (`topo/results/phase3_boutique_run1.md`, 304 snapshots, 5 seeds): MLP AP 0.54 and root cause ranked first 78%; GNN 0.33 and 59%; the hand-set rule 0.30 and 42% with a 95% false-alarm rate on normal traffic; p95 baseline 0.28 and 30%. The test set is only 10 episodes, so small gaps are noise. Task B below is the procedure to repeat or extend that run.

## Honesty rules (non-negotiable)
- Every dataset must be labelled by origin: **simulated** (`topo.generate`), **load-generated real app** (Online Boutique with its own load generator and faults we injected), or **real company traffic** (we have none; never describe test data as company traffic). Create `topo/DATA_PROVENANCE.md` with one row per file: origin, how labels were made, date, counts, known limits.
- Report only numbers you actually computed. Flag anything untested. No marketing language.
- Never overwrite `snapshots.jsonl`, `fault_log.jsonl` or `labeled_dataset*.jsonl`; write new files. Do not commit under anyone else's identity; commit only when I ask.

## Task A: simulated snapshots (no cluster, instant)
```
python -m topo.generate --out topo/data/sim_seed1.jsonl --seed 1 --per-family 2
python -m topo.generate --out topo/data/chain12.jsonl --seed 5 --families chain --per-family 1 --min-nodes 12 --max-nodes 12
```
Same seed gives the same files. It writes labelled snapshots plus `<out>.topologies.json` and refuses to overwrite. These are synthetic: it models delay faults only (no error, CPU or memory faults, retries or load-dependent latency).

## Task B: real snapshots from Online Boutique (needs the cluster; slow)
Setup on a new machine (Docker Desktop, k3d, kubectl, istioctl 1.32.0): `k3d cluster create meshheal --image rancher/k3s:v1.33.5-k3s1 --servers 1 --agents 2 --k3s-arg "--disable=traefik@server:0" --wait` (k3s v1.35 fails on cgroup v1), `istioctl install --set profile=demo -y`, apply Istio's Prometheus addon, create namespace `boutique` with `istio-injection=enabled`, apply the Online Boutique `kubernetes-manifests.yaml` with its `LoadBalancer` service changed to `ClusterIP`. On Windows, if kubectl cannot reach the cluster, point the kubeconfig server at `https://127.0.0.1:<port>`.
**Propose every kubectl write (apply, patch, set env, delete) and wait for my approval. Never touch a namespace other than `boutique`.**

1. Load: `kubectl set env deployment/loadgenerator -n boutique USERS=3` (10 users saturates the 200m-limited frontend). Check `kubectl top pods -n boutique --containers`: no server container should be near its CPU limit.
2. Port-forward Prometheus (`kubectl port-forward -n istio-system svc/prometheus 9090:9090`) and start the collector, writing to a NEW file: `python -m controlplane.collect --namespace boutique --out topo/boutique_snapshots_clean.jsonl` (run from `meshheal_controlplane/`). It writes one snapshot every 15 s and counts gRPC failures.
3. Wait 10 minutes after any load change, then check the baseline before injecting anything: on busy edges (frontend to productcatalogservice, currencyservice, cartservice) p95 should mostly be under 50 ms, and `loadgenerator -> frontend` well under 1 s (the discarded run sat near 2.3 s). If not, stop and investigate.
4. Show the plan with `python -m topo.run_boutique_faults --namespace boutique --episodes 10 --plan`, wait for my approval, then run it with `--yes` (about 80 minutes: 5 min fault, 3 min gap per episode). It applies a 100% delay VirtualService named `<service>-fault-inj`, deletes it afterwards even on error, and logs to `topo/boutique_fault_log.jsonl`. Do not run training, evaluation or other heavy jobs on the same machine meanwhile. Afterwards run `kubectl get virtualservice -n boutique` and confirm none is left.
5. Label: `topo.real.label_records("topo/boutique_snapshots_clean.jsonl", "topo/boutique_fault_log.jsonl", "boutique")`. Use only snapshots taken after the baseline check passed.

## Acceptance checks before the data is used
- Each fault is visible: the faulted service's incoming edge p95 in steady state is clearly above its baseline median (by about the delay), and unrelated branches are not slowed.
- Counts per episode are about 5 to 7 lag, 13 to 14 steady snapshots; no fault VirtualService remains.
- Edges on the checkout path (payment, email, shipping, checkout) get only about 0.04 to 0.1 requests per second, so their p95 rests on a few samples per minute and is noisy: state this limit and do not hide it.
- If any check fails, tell me and leave that data out of the results.

## Deliverables
The new snapshot and fault-log files, `topo/DATA_PROVENANCE.md`, a short written summary of what was run and what the checks showed, and the exact commands used. Then propose (do not run) re-evaluating with `python -m topo.eval` using the Boutique data as an independent real test.

## What it can and cannot do
- Simulated snapshots: any number, any seed and size, instantly, reproducible; delay faults only; synthetic by definition.
- Real snapshots: one every 15 s while the cluster and load run; each fault episode takes about 8 minutes of wall-clock time; only delay faults are implemented; needs the cluster up.
- Not available: real company traffic, error/CPU/memory faults, or any way to make test data count as production data.
