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
docker build -f deploy/Dockerfile -t meshheal-controlplane:0.7.1 .
helm install meshheal deploy/helm/meshheal -n meshheal-system --create-namespace --set targetNamespace=<app-namespace>
kubectl logs -n meshheal-system deploy/meshheal-controlplane -c controller -f
```
With a local k3d cluster, import the image first: `k3d image import meshheal-controlplane:0.7.1 -c <cluster>`.
`targetNamespace` is required. Prometheus must reach Istio's metrics (default `http://prometheus.istio-system.svc:9090`).

## Give it a playbook, then read it
The controller can only act on reroutes in its playbook, and only those marked `confirmed: true`.
```
python -m controlplane.playbook_gen --namespace <app-namespace> --out playbook.yaml      # drafts, all confirmed: false
helm upgrade meshheal deploy/helm/meshheal -n meshheal-system --reuse-values --set-file playbook=playbook.yaml
```
A generated draft is evidence, not a decision: a version that "never called X" may simply have had no traffic. Read each reroute, check it against how the application really works, and only then set `confirmed: true`.

## Optional: a learned baseline instead of the hand-set rule
The default rule scorer uses a fixed 100 ms scale tuned on Bookinfo; on Online Boutique it false-alarmed on 92% of normal snapshots. Learn a per-service baseline from about 20 minutes of fault-free traffic and pass it to the chart:
```
python -m controlplane.learn_baseline --snapshots normal.jsonl --out baseline.yaml
helm upgrade meshheal deploy/helm/meshheal -n meshheal-system --reuse-values --set-file baseline=baseline.yaml
```
Measured results and limits are in `REPORT_PHASE4.md` (Boutique false alarms 92% -> 10.5%, still too high to act on alone). Learn it from traffic you know was healthy: an incident inside the learning window becomes part of "normal".

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
- The container ships the rule, learned-baseline and per-edge scorers (`scorer: rule|baseline|edge`; baseline and edge need a learned baseline file and fall back to the rule on error). The trained GNN needs torch and is not in the image. On the real Online Boutique test the plain per-node MLP beat the GNN and your hand-set rule false-alarmed on 95% of normal snapshots (`topo/results/phase3_boutique_run1.md`), so do not treat the default scorer as production-grade; run in shadow mode and measure.
- Detection was evaluated on injected delay faults (Bookinfo, Online Boutique) and, in run3, on aborts, CPU starvation and pod crashes on Online Boutique (`topo/results/phase4_fresh_run3.md`). Reroutes were tested live for delay faults only. A reroute needs a service with versions to switch between; applications without versions can be detected and ranked but not remediated.
- The live closed loop has been demonstrated on Bookinfo only. The snapshot file and audit log live on a scratch volume and are lost when the pod is replaced (the reroute state is not: it is in the cluster).

## Metrics
`meshheal_loops_total`, `meshheal_loop_errors_total`, `meshheal_last_loop_timestamp_seconds`, `meshheal_active_reroutes`, `meshheal_paused`, `meshheal_shadow_mode`, `meshheal_events_total{event=...}` on the metrics port (default 9102).

## Canary rollback (a service with two versions)
The usual remedy reroutes the CALLER of a failing service to a version that does not call it (Bookinfo: `reviews` v1 skips
`ratings`). For a service that runs a stable and a new version, the remedy is to move its OWN traffic back to the stable
one. A playbook entry whose `virtual_service` is the culprit itself means exactly that:
```yaml
reroutes:
  - {culprit: cartservice, virtual_service: cartservice, target_subset: v1,
     normal_weights: {v1: 50, v2: 50}, reason: roll back to the stable version, confirmed: true}
```
The controller only does it with per-version evidence from the snapshot (collector 0.7+ writes `subsets` for services with
two or more versions): the target version must have traffic and be clearly better than another version (p95 under half and at
least `rollback_margin_ms` (50) lower, or at least 10 points fewer failures). Otherwise it logs `ACTION_BLOCKED` with
`no_subset_evidence`, `target_subset_no_traffic` or `target_subset_not_better`: rolling back cannot help when every version
is slow.

Live test on Online Boutique (`REPORT_PHASE6.md`): with 0.7.0 the per-edge scorer blamed the caller (frontend calls the
bad service several times per page) and nothing was rolled back; 0.7.1 weights outgoing excess by calls per request,
and the rerun rolled v2 back 111 s after the bad release, held it while v2 stayed bad and released 5 min after the fix.
One run; treat it as a demonstration, not a measured success rate.

## Fleet dashboard (several clusters in one place)
One `meshheal-fleet` API stores what each cluster's agent pushes (snapshots and decisions; SQLite on a volume, 14 days) and
serves the dashboard (Fleet page). It never talks to the Kubernetes API.
```
python -m dashboard.tokens --file tokens.json add-read --label you          # prints a read token once; only hashes are stored
python -m dashboard.tokens --file tokens.json add-ingest <cluster>          # one per cluster; may only push for that cluster
kubectl create secret generic meshheal-fleet-tokens --from-file=tokens.json -n meshheal-system
helm install meshheal-fleet deploy/helm/meshheal-fleet -n meshheal-system --set tokensSecret=meshheal-fleet-tokens \
     --set-file baselines.<cluster>=baseline.yaml
kubectl create secret generic meshheal-fleet-ingest-<cluster> --from-literal=token=<ingest token> -n meshheal-system
helm upgrade meshheal deploy/helm/meshheal -n meshheal-system --reuse-values \
     --set fleet.url=http://meshheal-fleet.meshheal-system.svc:8780 --set fleet.tokenSecret=meshheal-fleet-ingest-<cluster>
kubectl port-forward -n meshheal-system svc/meshheal-fleet 8780:8780      # then open http://127.0.0.1:8780/#/fleet
```
Keep token files out of the repository. The API has no TLS of its own: put it behind your ingress or a TLS proxy before
exposing it beyond the cluster. A controller in another cluster pushes the same way, as long as it can reach the URL.

## Alerts
The chart ships Prometheus alert rules for the controller itself (`alerts.enabled`, on by default): controller down, loop
stalled, loop errors, refused writes, four or more reroutes in an hour, a reroute in place for 45 minutes, paused for 30
minutes, unreadable reroute state, most snapshots rejected. With the Prometheus Operator they become a `PrometheusRule`;
otherwise a ConfigMap `<release>-controlplane-alerts` holds `meshheal-rules.yaml` for your Prometheus `rule_files`. Every
expression was checked against a live Prometheus scraping the controller.

## Uninstall
`helm uninstall meshheal -n meshheal-system`. If a reroute was active, release it first (or pause, then restore the weights yourself): uninstalling does not touch VirtualServices. The annotation `meshheal.io/state` can be removed with `kubectl annotate virtualservice <name> meshheal.io/state- -n <app-namespace>`.
