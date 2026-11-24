# Operating MeshHeal

For whoever installs and runs the control plane. Read the "What it can change" section before enabling acting.

## What it can change (and nothing else)
In **shadow mode** (the default) the controller only reads; the chart's Role has no write verb, so it could not change anything even by mistake.
In **act mode** it may do exactly one kind of write: `update` a `VirtualService` in the watched namespace, changing
1. the destination **weights** of that VirtualService's single catch-all route (no `match`), and
2. one annotation, `meshheal.io/state`, that records the reroute (culprit, mode, start time, the weights to restore).

Both happen in the same API call, so the recorded state and the weights cannot disagree. Match rules, retries, timeouts, ports and every other field are left as they were. If the catch-all route is missing or ambiguous, the change is refused (`ACTION_FAILED`). It never deletes anything, never touches pods, secrets or other namespaces, and has no cluster-wide permission. It reads pods, DestinationRules, VirtualServices and one ConfigMap (the pause switch).

## Install (shadow first)
Build the image (not pushed anywhere) and install:
```
docker build -f deploy/Dockerfile -t meshheal-controlplane:0.5.1 .
helm install meshheal deploy/helm/meshheal -n meshheal-system --create-namespace --set targetNamespace=<app-namespace>
kubectl logs -n meshheal-system deploy/meshheal-controlplane -c controller -f
```
With a local k3d cluster, import the image first: `k3d image import meshheal-controlplane:0.5.1 -c <cluster>`.
`targetNamespace` is required. Prometheus must reach Istio's metrics (default `http://prometheus.istio-system.svc:9090`).

## Give it a playbook, then read it
The controller can only act on reroutes in its playbook, and only those marked `confirmed: true`.
```
python -m controlplane.playbook_gen --namespace <app-namespace> --out playbook.yaml      # drafts, all confirmed: false
helm upgrade meshheal deploy/helm/meshheal -n meshheal-system --reuse-values --set-file playbook=playbook.yaml
```
A generated draft is evidence, not a decision: a version that "never called X" may simply have had no traffic. Read each reroute, check it against how the application really works, and only then set `confirmed: true`.

## Run in shadow mode long enough to trust it
Watch the audit log (`SCORED`, `REROUTE`, `ACTION_BLOCKED`) and `/metrics` (`meshheal_events_total`). In shadow mode a `REROUTE` line means "it would have rerouted". Count how many would have been wrong before you let it act. The thresholds (act at risk > 0.85 in 3 of the last 4 checks, release below 0.60) were tuned on Bookinfo with the rule scorer; check them on your own application.

## Enable acting
```
helm upgrade meshheal deploy/helm/meshheal -n meshheal-system --reuse-values --set mode=act
```
This adds `--act` and the `update` verb on VirtualServices. Nothing else changes.

## Pause and resume (any time, no redeploy)
```
kubectl create configmap meshheal-control --from-literal=paused=true -n <app-namespace>     # pause
kubectl delete configmap meshheal-control -n <app-namespace>                                 # resume
```
While paused the controller keeps scoring and logging but writes nothing, **including releases**: a reroute that is already in place stays in place until you resume or release it yourself. If the controller cannot read the ConfigMap (any error other than "not found") it behaves as paused.

## What it does when things go wrong
| Situation | Behaviour |
|---|---|
| Controller restarts during a reroute | On start it reads the `meshheal.io/state` annotations and takes the reroute over (`RECONCILED`); the cooldown, probe and release logic carry on. |
| Reroute is older than `max_reroute_s` (default 1 h), running or discovered at restart | Released (`RELEASE` with `why: expired`); if the fault persists the normal rules may reroute again, subject to the rate limit. A reroute is never permanent. |
| Recorded state no longer matches a confirmed playbook entry | The recorded normal weights are restored (`RELEASE`, `no_confirmed_playbook_entry_on_restart`). |
| Recorded state is corrupt or incomplete | `RECONCILE_ORPHAN`: reported, nothing written, a person must fix it. |
| More than `max_actions_per_hour` (default 6) new reroutes | Further ones are blocked (`ACTION_BLOCKED`, `rate_limited`). Releases are never rate-limited. |
| Someone else edits the VirtualService meanwhile | The write fails with HTTP 409 (`ACTION_FAILED`); nothing is overwritten. |
| Prometheus or the snapshot is stale or has bad values | The snapshot is rejected (`SNAPSHOT_REJECTED`) and nothing is decided on it. |
| Controller loop stalls | `/healthz` returns 503 and Kubernetes restarts the container. |

## Limits you must know
- One replica and no leader election: the Deployment uses `Recreate`. Do not scale it up.
- The container ships the **rule scorer only**. The trained GNN needs torch and is not in the image. On the real Online Boutique test the plain per-node MLP beat the GNN and your hand-set rule false-alarmed on 95% of normal snapshots (`topo/results/phase3_boutique_run1.md`), so do not treat the default scorer as production-grade; run in shadow mode and measure.
- Only delay faults have been tested. A reroute needs a service with versions to switch between; applications without versions can be detected and ranked but not remediated.
- The live closed loop has been demonstrated on Bookinfo only. The snapshot file and audit log live on a scratch volume and are lost when the pod is replaced (the reroute state is not: it is in the cluster).

## Metrics
`meshheal_loops_total`, `meshheal_loop_errors_total`, `meshheal_last_loop_timestamp_seconds`, `meshheal_active_reroutes`, `meshheal_paused`, `meshheal_shadow_mode`, `meshheal_events_total{event=...}` on the metrics port (default 9102).

## Uninstall
`helm uninstall meshheal -n meshheal-system`. If a reroute was active, release it first (or pause, then restore the weights yourself): uninstalling does not touch VirtualServices. The annotation `meshheal.io/state` can be removed with `kubectl annotate virtualservice <name> meshheal.io/state- -n <app-namespace>`.
