# Viva questions and honest answers

Every number is from a file in this repo, cited in square brackets. Where something was not tested, the answer says so; say that too. Paths are from the project root. See also `docs/REPORT_UPDATE_NOTES.md`.

## A. What it is and what the evidence shows

**1. What problem does MeshHeal AI solve?**
Silent degradation in a microservice mesh: a service gets slow but not down, and callers inherit the latency, so naive alerts blame the wrong service. The system reads per-edge latency from Istio, picks the culprit, checks that a reroute is safe, then shifts traffic and verifies recovery. It is a prototype on one Bookinfo testbed. [CLAUDE.md]

**2. Why a GNN if a no-graph MLP matches it?**
It does not need to: the MLP is at least as good. MLP mean AP 0.983 vs GNN 0.928; win/tie/loss for the GNN vs the MLP is 0/6/2 on AP and on root-cause top-1. I say plainly that message passing adds nothing measurable on 4 nodes. The graph is the representation for larger meshes, where it could matter; that is untested here. [results_controls.md, Control 3]

**3. Then what is the contribution?**
The pipeline and the safe action around it: collect snapshots, label from a fault log, train per deployment, score, apply persistence and safety checks, patch the VirtualService, probe and release, audit every decision. Also the honest evaluation: a simple culprit rule `in_lat - out_lat` scores about the same AP as the GNN (0.933 vs 0.928). On the ratings 100 ms fold both the p95 baseline and the culprit rule score only 0.071 root-cause top-1 (they blame the victim `reviews`), while the GNN and the MLP score 1.000, so the learned models' clearest advantage is that fold. Overall root-cause top-1: GNN 0.950 vs culprit rule 0.877 (log1p variant; the raw-millisecond variant the control plane runs is 0.868), MLP 1.000. [results_controls.md; meshheal_controlplane/README_controlplane.md]

**4. Which headline numbers can you defend?**
8-fold leave-one-episode-out, distinct-threshold AP: p95 baseline 0.930, culprit rule 0.933, MLP 0.983, GNN 0.928. Root-cause top-1: GNN 0.950, MLP 1.000, baseline 0.868. The GNN is a tie with the baseline on AP. [results_controls.md]

**5. Why do you have two AP numbers (0.923 and 0.928)?**
Two computation methods. 0.923 (baseline 0.898) is the older trapezoidal method in `results_loeo.md`; 0.928 (baseline 0.930) is the distinct-threshold method in `results_controls.md`. Distinct-threshold is the correct one: the p95 baseline has many tied zero scores, and the trapezoidal method depends on sort order among ties. So the earlier impression that the GNN beat the baseline (0.923 vs 0.898) was a method artifact. [results_controls.md, Control 4; results_loeo.md]

**6. Why leave-one-episode-out?**
With 8 fault episodes, each held out in turn, no episode is in both train and test; a 120 s leakage buffer separates windows and lag/recovery snapshots are excluded. A random snapshot split would leak because neighbouring 15 s snapshots are nearly identical. Each fold has only about 13 to 14 steady-fault positive readings (52 for the legacy ratings episode), so single misclassifications move the metrics a lot. [results_loeo.md, Assumptions]

**7. Is the deployed GNN evaluated on its own training data?**
Replaying the episodes through it is in-sample: the final model (5 seeds) is trained on all 8 episodes minus lag, recovery and the normal holdout. LOEO is the evaluation; replays with the final model are not accuracy results. [train_final.py; meshheal_controlplane/README_controlplane.md]

## B. False alarms, label noise

**8. What is the false-alarm rate?**
Two different measures, both needing a caveat. (1) Policy simulation, GNN, second half of the normal holdout (69 snapshots): 2.9% to 15.7% per fold on seed average, up to 20.3% for single seeds; the p95 baseline and culprit rule fire 2 of 69 (2.9%). (2) Shadow run soak, 30 minutes with no fault: 0 decision events from either scorer in 118 scored cycles each. The first measure includes contaminated holdout data (question 19). [results_policy.md; shadow_run/audit_rule.jsonl and audit_gnn.jsonl, computed]

**9. Why is the GNN's false-alarm rate unstable across seeds?**
Each seed has its own threshold, calibrated at the 95th percentile on the first half of the holdout, and seeds disagree on some folds (e.g. fold 1: 20.3% for seeds 42 and 99, 2.9% for seed 13). I have not established the cause beyond that. The final model therefore averages 5 seeds and the 0.85 threshold was set for the rule scorer. [results_policy.md, per-seed table]

**10. What did the shadow run show?**
On 2026-10-26 both scorers ran dry-run on live data through 4 injected faults (ratings 150 ms, details 75 ms, reviews 150 ms, ratings 75 ms): 4 of 4 correct blames, identical decisions, 0 fallbacks in 291 scored cycles each, no telemetry gap over 30 s. Ratings faults produced REROUTE (first at 76.4 s and 60.5 s), details and reviews produced ACTION_BLOCKED `no_healthy_alternative` (75.6 s, 75.5 s). It is one run, 4 faults. [shadow_run/results_shadow.md]

**11. Why does detection take 60 to 80 seconds?**
Observed: 60.5 to 76.4 s in the shadow run, 63.7 s and 78.2 s in the two live runs. Snapshots arrive every 15 s, the controller needs the top node above 0.85 in 3 of the last 4 cycles, and Prometheus uses a 1-minute rate window so the first 90 s of a fault are partly invisible (the "lag" period excluded from training). The observed times land on controller cycles, which fits the persistence rule setting the timing. I did not test that separately. [results_shadow.md; build_dataset_v2.py]

**12. What does the persistence rule do?**
It only lets the controller act on a node that was the top-risk node above 0.85 in at least 3 of the last 4 cycles and is a hit in the current cycle. It trades speed for fewer false actions from single noisy snapshots. [meshheal_controlplane/controlplane/controller.py, `_persistent_top`]

**13. You mentioned a persistence bug. What was it?**
It used to ignore the current cycle: 3 old hits plus a recovered reading still returned the node, so a block could be logged after the fault had cleared (seen in the shadow run at 06:46:42, reviews risk 0.128). Fixed to require the current cycle too; first-event times in the 8-episode replay did not change, 5 late repeat events disappeared. [docs/REPORT_UPDATE_NOTES.md item 4; tests/test_controller.py]

**14. Why does only `ratings` have a reroute?**
Bookinfo `reviews` v1 does not call `ratings`, v2 and v3 do, so sending all reviews traffic to v1 bypasses a slow ratings. `details` and `productpage` have one version each, so there is nothing to reroute to, and a fault on `reviews` has no alternative either. Those culprits are ACTION_BLOCKED with `no_healthy_alternative`, by design. [meshheal_controlplane/controlplane/playbook.py]

**15. What does dry-run prove and not prove?**
It proves detection and decision logic on live data, and that nothing was written. It does not prove recovery: the reroute is never applied, so latency does not improve, and the PROBE_START / RELEASE events only show the culprit's score falling after the fault was removed. [shadow_run/results_shadow.md, RELEASE section]

**16. Have you seen a closed-loop recovery?**
Yes, once per scenario, on 2026-10-29, with a 150 ms delay on ratings and the real acting controller. Scenario A (GNN scores): REROUTE of ratings 78.2 s after the fault, median productpage latency 0.172 s faulted and back to baseline (0.023 s) within about 2 s of the reroute, probe at 70/15/15, RELEASE 174 s after the fault was removed. Scenario B (kill file, rule fallback scores): REROUTE 63.7 s after the fault, median 0.182 s to 0.024 s, RELEASE 174.9 s after the fault was removed. One run each, so no rates or averages. Earlier, a manual test with a 100 ms fault gave 5 of 10 slow requests (mean 0.134 s) before and 0 of 10 (mean 0.033 s) after routing to v1. [live_demo/result_A_20261029T053627Z.json; live_demo/result_B_20261029T064550Z.json; CLAUDE.md]

## C. Fallback, safety, security

**17. What does the fallback do?**
The GNN gets a 500 ms budget per cycle. On a timeout, an exception or non-finite scores, the culprit rule scores that cycle instead and the audit line says `source: fallback` with a note. A kill file (`--gnn-kill-file`) forces this for the demo. Unit tests cover timeouts, errors and the kill file; the shadow run saw 0 fallbacks in 291 cycles, and in the live scenario B run with the kill file all 19 SCORED events were fallback and the controller still rerouted (one run). A fallback caused by a real timeout or error, rather than the kill file, has only been seen in tests. [controlplane/scorer.py, gnn_adapter.py; tests/]

**18. Is the GNN gated by the rule detector?**
No. The results recommend it (seed-averaged and gated), but the control plane uses the GNN alone and the rule only as a failure fallback. This is a known gap. [meshheal_controlplane/controlplane/run.py `build_scorer`; CLAUDE.md]

**19. What is the label-noise problem?**
Two separate problems, both found after the report, both in "normal" data. (1) The Oct 6 holdout: 50 of its 70 snapshots (10:45 to 10:58 UTC) show details p95 above 50 ms, consistent with an unlogged details fault, plus a 3-snapshot ratings spike; 12 sit in the threshold-calibration half and 38 in the false-action half, so the v1 holdout false-alarm figures include them (the v3 check in question 32 re-ran without them). (2) Sep 16 training data: the Sep 16 holdout is clean (42 snapshots, no edge at 97.5 ms or more), but 129 of the 367 non-holdout Sep 16 snapshots have productpage to reviews p95 of about 242 ms in three stretches of 8 to 17 minutes, and all are labelled normal. In a normal-only replay the rule logs 33 ACTION_BLOCKED events and the final GNN also 33, with 129 Sep 16 snapshots scored above 0.85, even though it trained on them. I do not know the cause (no pod events in the data, cluster not queried), and whether this label noise explains the GNN's weakness on the reviews 100 ms fold is untested. LOEO AP and root-cause numbers are not affected by problem (1) (holdout is excluded from training), but may be by problem (2). [docs/REPORT_UPDATE_NOTES.md item 6]

**20. Why retrain per deployment?**
The model is tied to the 4 Bookinfo services (`NODE_VOCAB`), to this mesh's latency bucketing and to these fault patterns. The thing that transfers is the pipeline. I have not tested any transfer to another application. [build_dataset_v2.py; CLAUDE.md]

**21. What does retraining need?**
Fault episodes with start and end logged (`fault_log.jsonl`), snapshots from the same period, and a held-out normal stretch. Lag (first 90 s) and recovery (90 s after the end) snapshots are excluded, labels are the faulted node during the steady phase. Training 5 seeds took roughly 3 minutes on this laptop (from file times: script saved 00:47:38, last weight 00:50:38; not timed with a stopwatch). [build_dataset_v2.py; train_final.py; models/]

**22. What safety checks stop a bad reroute?**
Before patching: a playbook entry exists, the target pod is ready, the target path does not depend on the faulty node, the alternative service is itself healthy, and a cooldown since the last action. Otherwise ACTION_BLOCKED with the reason. Stale (over 45 s), NaN or incomplete snapshots are rejected. After rerouting it probes at 70/15/15 and releases only if risk is under 0.60 with at least 0.05 req/s of real traffic into the node. [controller.py; config.py]

**23. Security: what permissions does the controller have?**
It patches `VirtualService` objects through the Kubernetes API using the local kubeconfig, which on this laptop is full access. I did not write or test a minimal RBAC role, authentication for the audit log, or protection of the snapshot file. In a real deployment it should run with a role limited to patching VirtualServices in one namespace. [controlplane/cluster.py; not implemented otherwise]

**24. Why a Python control plane?**
Fast to build and test (35 unit tests, no cluster needed), the GNN stack is PyTorch, and a 15 s loop is not latency critical. An Istio operator in Go would be the production choice; nothing here depends on Python for correctness. [meshheal_controlplane/tests/]

## D. Limits and honesty

**25. What are the scaling limits?**
Model hardcoded to 4 nodes; one namespace; one playbook entry; polling a snapshot file every 15 s written by a single telemetry process; no multi-replica controller. A larger mesh needs a new vocabulary, new episodes and a new playbook. Not tested at any other size. [build_dataset_v2.py; playbook.py]

**26. Why are some latency values 97.5, 241 or 242.5 ms?**
Prometheus histogram p95 is bucketed, so latencies jump between bucket edges. A 50 ms fault can read as 97.5 ms (the README warns the 50 ms detections may be due to the bucket edge, not sensitivity). [CLAUDE.md; meshheal_controlplane/README_controlplane.md]

**27. You mention three regions. Are they real?**
No. Only `aws-us-east` runs Bookinfo; `gcp-asia` and `azure-eu` are empty simulated regions. Do not claim multi-region behaviour. [CLAUDE.md]

**28. How do you know the reroute actually helps?**
From the two live runs in question 16 (median latency 0.172 s and 0.182 s while faulted, 0.023 s and 0.024 s after the reroute) and the earlier manual test, each once, on one fault type. Istio needs a few seconds to propagate a route change. [live_demo/result_*_20261029T*.json; CLAUDE.md]

**29. What if the controller dies mid-reroute?**
The VirtualService stays at whatever weights were last patched (for example 100% v1), and a restarted controller starts with empty in-memory state, so it would not release on its own. This is my reading of `Controller.active` being in memory; I have not tested a crash. The cleanup commands (`kubectl apply -f reviews-normal.yaml`) are in the demo docs. [controller.py; live_demo/README.md]

**30. What would you do with more time?**
Repeat the closed loop to get a spread, test the probe against a fault that is still present, and explain the 14 s detection difference between the two runs; re-run the policy simulation on v3 data with a split that is comparable with v1; gate the GNN with the rule; test on a second application and a larger mesh; add more fault types and episodes (only 8 now); add RBAC and a restart-safe controller state; compare against a simple Prometheus alert rule with a persistence window. [docs/REPORT_UPDATE_NOTES.md]

**31. Why did detection take 78 seconds in the live run?**
Three delays add up: Prometheus uses a 1-minute rate window, so the first part of a fault is only partly visible; the controller loop runs every 15 s; and the persistence rule needs the top node above 0.85 in 3 of the last 4 cycles with the current cycle a hit. In scenario A the GNN's risk was 0.911 at 05:37:15 and 1.0 afterwards, so the fourth high-risk cycle (05:38:00) acted, 78.2 s after the fault at 05:36:41.9. Scenario B acted on the third high-risk cycle, at 63.7 s. The 14 s gap is unexplained; I think it is one extra controller cycle, not a scorer effect, and I did not test that. So: "about 60 to 80 seconds, set by the persistence rule", one run each. Do not say the fallback is faster. [live_demo/result_A_20261029T053627Z.json, result_B_20261029T064550Z.json, audit_*.jsonl]

**32. What does the v3 check show?**
It removes 215 snapshots from the "normal" data (147 Sep 16 training normals, 68 Oct 6 holdout snapshots) and retrains. The p95 baseline and the culprit rule are unchanged. GNN mean AP goes 0.928 to 0.898 and the MLP 0.983 to 0.955, but the GNN's seed std is up to 0.39 in one fold, so those changes are about the size of seed noise and I cannot say the removal caused them. The holdout false-positive rate falls (baseline 0.140 to 0.039, GNN 0.128 to 0.031) on holdouts of 137 and 69 snapshots. The v3 policy false-action numbers are not comparable with v1 because the holdout split differs. The demo keeps the v1 model. [REPORT_V3.md]

**33. What does RELEASE prove, and what does it not?**
It proves the release logic works on the real cluster: after the cooldown the controller sent 70/15/15, saw the ratings risk below 0.60 with real traffic, and restored 34/33/33 (RELEASE 174 s and 174.9 s after the fault was removed, one run each). It does not prove the probe catches a fault that is still present: in both runs the fault was removed before the probe started. It is also not the recovery measurement; recovery is the latency returning to baseline within about 2 s of the reroute, which happened earlier. [live_demo/result_*_20261029T*.json]

## Things we must not claim

- "The GNN beats the baseline / the MLP." It ties the baseline (0.928 vs 0.930) and the MLP is better (0.983).
- "GNN AP is 0.923 vs baseline 0.898" as a win: that is the trapezoidal artifact.
- "The system recovers the mesh automatically, reliably." It did so once per scenario (2026-10-29): one run each, no rates or averages. The shadow run was dry-run, and RELEASE there is not recovery.
- "The fallback is faster than the GNN." B rerouted at 63.7 s and A at 78.2 s, but A acted on the 4th high-risk cycle and B on the 3rd; the gap is unexplained and probably one extra cycle.
- "Latency recovered in 0.3 s / 1.8 s." Say "back to baseline within about 2 seconds of the reroute": the script reports the first of three consecutive fast samples taken 2 s apart.
- "RELEASE proves the probe catches a persisting fault." The fault was removed before the probe started in both runs.
- "0 false alarms." True for the 30-minute soak (118 cycles per scorer), but the holdout figures are contaminated and GNN false-action rates reach 20.3% for single seeds.
- "The normal data is clean." The Oct 6 holdout contains a faulted-looking stretch and 129 Sep 16 training-normal snapshots show about 242 ms reviews latency labelled normal.
- "It generalises to other applications / larger meshes / other regions." One testbed, 8 episodes, 4 hardcoded nodes, two empty simulated regions.
- "The final model's replay results are accuracy." They are in-sample.
- "Detects 50 ms faults." Probably bucket-edge effects, untested for sensitivity.
- "Production-ready" or "secure." No RBAC, no restart-safe state, and the live closed-loop validation is one run per scenario on one testbed.
- Numbers that are not in a file in this repo (for example the "+112%" figure in `meshheal_results_v2.md`, an older results file): do not quote it; CLAUDE.md bans marketing figures like it.
