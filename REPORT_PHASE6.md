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

## Canary rollback, live test (2026-11-25, `topo/canary_test.py`, `topo/results/phase6_canary_live.{json,out}`)
Setting: productcatalogservice as v1 and v2 behind a 50/50 VirtualService; the Boutique release in ACT mode with one
confirmed playbook entry (roll productcatalogservice back to v1); at 09:33:05 UTC v2 got EXTRA_LATENCY=300ms.

**Result: no rollback. The test failed at detection, not at the rollback logic.**
- Per-version evidence was there and correct: v1 p95 5 ms, v2 p95 488 ms, both with traffic (collector `subsets`).
- But the controller blamed **frontend**, not productcatalogservice, in all 34 checks after the bad release, and logged
  ACTION_BLOCKED `no_healthy_alternative` for frontend 8 times (frontend has no playbook entry). Nothing was written to
  the cluster by the controller; the safety checks did what they should with a wrong culprit.
- Why (the same snapshot scored offline with the deployed baseline, before saturation): frontend 175, productcatalogservice
  48. A page makes several sequential calls to productcatalogservice, so frontend's incoming latency rose to 2321 ms while
  its single worst outgoing edge was 476 ms; subtracting one edge does not cancel a fan-out of several. Both scores
  saturate to exactly 1.0, and the tie went to frontend.
- So the per-edge scorer, which did well on run3 (`REPORT_PHASE4.md`, Result 5), misplaces a slow service that the caller
  calls several times per request. Possible fixes, NOT built or tested: subtract the caller's outgoing excess weighted by
  calls per request; rank by unsaturated score to break ties; or, when a service has two versions and one is clearly worse,
  prefer it as the culprit. Any of these would need a fresh test, not this one.
- First attempt (`phase6_canary_attempt1_failed_setup.*`) failed in setup: the controller pod was stuck behind a node
  lost in a Docker Desktop crash. Nothing was injected; the cleanup ran.
- Cleanup both times: release back to shadow mode with an empty playbook, VirtualService, DestinationRule and v2 deleted,
  version label removed; nothing labelled `meshheal-test=canary` left.

What is shown about canary rollback, then: the per-version evidence collection works live, and the rollback decision
logic is covered by unit tests (4 tests in `test_canary.py`); a live rollback has NOT been demonstrated. The live
closed loop (reroute, probe, release, restart recovery) remains demonstrated on Bookinfo only (the 2026-10-29 runs in `CLAUDE.md`, and the Phase 5 acting test of
2026-11-25: REROUTE, expiry, pod restart with RECONCILED, RELEASE back to 34/33/33; that test has no report file of its own).

## Limits, stated plainly
- Both "clusters" are namespaces of ONE physical cluster. Transport, tokens and isolation are real; a second physical cluster
  was not set up.
- The Fleet page was not checked by eye in a signed-in browser here (reading the token into the browser was not allowed in
  this session); the API it calls and its layout code are tested.
- One fleet replica (SQLite has one writer). No user accounts, roles or audit of dashboard readers; tokens are shared secrets.
