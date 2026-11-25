# REPORT_PHASE6: fleet API and dashboard, multi-cluster agents, canary rollback, alerts

Written 2026-11-25. Everything below was run on the k3d cluster `meshheal` unless it says otherwise.

## What was built
- **Fleet API** (`dashboard/`, stdlib only): stores what each cluster pushes (snapshots and controller decisions) in SQLite
  (WAL, 14-day retention) and serves it for any mesh. Endpoints in `dashboard/server.py`. Per-service risk is computed in the
  API with the cluster's learned baseline when one is configured (edge scorer if the file has edges), else the hand-set rule,
  and is labelled with the scorer used. Pushed snapshots are validated with the controller's own parser; invalid ones are
  counted and dropped; resent data is ignored (unique per cluster and timestamp).
- **Auth**: two scopes. `read` tokens may read every cluster; `ingest` tokens may only push for ONE named cluster and cannot
  read. Only SHA-256 hashes are stored (`python -m dashboard.tokens`), compared in constant time. Token files live outside
  the repository. No TLS of its own: put it behind an ingress or TLS proxy before exposing it beyond the cluster.
- **Agent** (`dashboard/agent.py`): tails the files the collector and controller already write and pushes new lines in
  batches; keeps byte offsets in a state file, restarts from 0 after rotation, keeps the offset when a push fails (nothing
  lost; the API ignores duplicates), backs off up to 5 minutes. It runs as an optional third container of the controller pod
  (`fleet.url`, `fleet.tokenSecret`) and never talks to the Kubernetes API.
- **Fleet page** in Frontend_v3 (`#/fleet`): sign-in with a read token (kept for the browser tab only), cluster list,
  service graph laid out from the edges for any mesh (columns by call depth), risk table, per-version stats, controller
  decisions, risk history. The existing Bookinfo replay pages are unchanged and still use the old demo API.
- **Packaging**: `deploy/Dockerfile.fleet` (dashboard built in a Node stage, served by the Python API, uid 10001) and the
  `deploy/helm/meshheal-fleet` chart (one replica, Recreate, PVC, no service-account token, read-only root filesystem).
- **Canary rollback**: a playbook entry whose `virtual_service` is the culprit itself moves the culprit's own traffic to
  another of its versions. Allowed only with per-version evidence from the snapshot (the collector now writes `subsets` for
  services with two or more versions): the target must have traffic and be clearly better than another version.
- **Alert rules** for the controller itself, shipped by the chart (PrometheusRule with the Prometheus Operator, else a
  ConfigMap rules file).

## Verified live (2026-11-25)
- Three releases in `meshheal-system`: `meshheal-fleet`, `meshheal` (watches `aws-us-east`, Bookinfo) and `meshheal-boutique`
  (watches `boutique`), both controllers in shadow mode with the edge scorer and a baseline learned from that morning's
  fault-free traffic, each with an agent and its own ingest token.
- Both agents pushed every 15 s; the API listed both clusters, Bookinfo with 4 services and Online Boutique with 11, risk 0.00
  on normal traffic, controllers reported running in shadow mode. Without a token the API answered 401; an ingest token
  trying to read answered 403. The dashboard page was served from the same pod.
- Every alert expression parsed and evaluated on the live Prometheus, which already scrapes the controller (none firing on a
  healthy controller, as expected). Firing was not forced.
- Tests: 10 fleet API tests over real HTTP (scopes, validation, duplicates, two clusters kept apart, any service names,
  learned baseline, retention, agent resume and failure), 6 frontend layout tests (11-service Online Boutique layout with
  every card in its own cell, cycles, a single service), 4 canary tests (rollback only on per-version evidence).

## Canary rollback, live test (2026-11-25, `topo/canary_test.py`, `topo/results/phase6_canary_*`)
Setting: productcatalogservice as v1 and v2 behind a 50/50 VirtualService; the Boutique release in ACT mode with one
confirmed playbook entry (roll productcatalogservice back to v1); then v2 gets EXTRA_LATENCY=300ms, and is fixed after
5 minutes of probing. Three attempts; the cleanup ran after each (release back to shadow mode with an empty playbook,
VirtualService, DestinationRule and v2 deleted, version label removed; nothing labelled `meshheal-test=canary` left).

**Attempt 1 (09:10, `phase6_canary_attempt1_failed_setup.*`)**: failed in setup. The controller pod was stuck behind a
node lost in a Docker Desktop crash. Nothing was injected.

**Attempt 2 (09:28, image 0.7.0, `phase6_canary_attempt2_frontend_blamed.*`): no rollback, wrong culprit.**
- Per-version evidence was there and correct: v1 p95 5 ms, v2 p95 488 ms, both with traffic.
- The controller blamed **frontend** in all 34 checks after the bad release (09:33:05), and logged ACTION_BLOCKED
  `no_healthy_alternative` for it 8 times. Nothing was written. Before the fault frontend was normal (page p95 92 ms).
- Cause (same snapshot scored offline): frontend 175, productcatalogservice 48, before saturation. A page calls
  productcatalogservice several times in a row, so the page p95 rose to 2321 ms while the worst single outgoing edge was
  476 ms. Subtracting one edge does not cancel a fan-out. Both saturated to 1.0; the tie went to frontend.

**The fix (image and chart 0.7.1).** The per-edge scorer now subtracts the larger of the worst outgoing excess and the
sum over outgoing edges of excess x calls per incoming request (capped at 10). Calls made in parallel make this
over-subtract, which can only lower a caller's score. On the attempt-2 snapshot: frontend 175 -> 0, productcatalogservice
48 (unchanged). Regression check on the data the design was developed on (NOT fresh evidence): Boutique run2 AP 0.648 ->
0.693, root cause first 0.821 -> 0.827; Bookinfo and the persistence replays unchanged; run3 unchanged (28/32 caught,
0 false alarms; `topo/results/*_fanout.*`). Ablation kept (`fanout=False`), 3 new unit tests.

**Attempt 3 (10:09, image 0.7.1, `phase6_canary_live.*`): the rollback worked.**

| UTC | event |
|---|---|
| 10:17:56 | bad release: v2 +300 ms |
| 10:19:47 | REROUTE productcatalogservice: v1 100, v2 0 (111 s after the bad release); reroute state recorded on the VirtualService |
| 10:21:47 / 10:23:17 | probe 70/30, failed (risk 1.00), back to 100/0 |
| 10:25:01 | v2 fixed |
| 10:25:17 / 10:26:47 | probe, failed (risk 0.98): the rate window still held slow requests from before the fix |
| 10:28:47 / 10:30:18 | probe, passed; RELEASE back to 50/50, state annotation removed (5 min 17 s after the fix) |

A complication, reported as it happened: from 10:12:03, **before** the fault, the whole Boutique slowed down (every
frontend call 3-5x slower, page p95 95 ms -> 1.7-3.9 s) until about 10:30. The cause was not established (CPU
contention on the laptop is the likely one; it started when the test switched the release to act mode, which restarts
the controller pod, and that should not slow the mesh). The controller flagged frontend for it (ACTION_BLOCKED, no
remedy) before and after the fault: frontend was in fact the most degraded service, so this is not a scoring error, but
the test did not run on clean traffic. The rollback still went to the right service.

What this shows: one live canary rollback, with probes that held the rollback while v2 was bad and a release after the
fix. One run, one fault size, one service, partly on degraded traffic; the fix was made after seeing attempt 2 fail,
and attempt 3 is its only live test. A new fault run would be needed to measure the fix on unseen data.

## Limits, stated plainly
- Both "clusters" are namespaces of ONE physical cluster. Transport, tokens and isolation are real; a second physical cluster
  was not set up.
- The Fleet page was not checked by eye in a signed-in browser here (reading the token into the browser was not allowed in
  this session); the API it calls and its layout code are tested.
- One fleet replica (SQLite has one writer). No user accounts, roles or audit of dashboard readers; tokens are shared secrets.
