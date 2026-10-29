# Notes for updating the report

What changed or was added since the report was written (items 1 to 10 are as of 2026-10-26; items 7 and 8 and new items 11 to 13 were updated on 2026-10-29 with the live runs, the patch test and the v3 check). I did not have the report text, so check each item against what it currently says.
Every number is copied from the file named next to it, or was computed by a script I ran on the files and is marked "computed". Status: **verified** = read or computed from a file in this repo; **not verified live** = true on paper or in tests, never seen on the running cluster.

## 1. AP method correction
| Fact | Number | Source | Status |
|---|---|---|---|
| Trapezoidal AP (old method), GNN mean | 0.923 ± 0.143 (collapsed seed excluded); 0.905 ± 0.177 if the collapsed seed counts as 0 | `results_loeo.md` | verified |
| Trapezoidal AP, p95 baseline mean | 0.898 | `results_loeo.md` | verified |
| Distinct-threshold AP (correct method), mean | p95 baseline 0.930, culprit rule 0.933 (raw) / 0.935 (log1p), no-graph MLP 0.983, GNN 0.928 | `results_controls.md`, Control 3 | verified |
| Why the method matters | the p95 baseline has many tied zero scores (log1p(0) for nodes with no incoming traffic); the trapezoidal method depends on sort order among ties. Largest changes: fold 0 baseline 0.821 to 0.918, fold 4 (ep 3) 0.376 to 0.536 | `results_controls.md`, Control 4 | verified |
| GNN vs p95 baseline (AP) | 0.928 vs 0.930: a tie (the file's tie rule is a difference of at most 0.01). Win/tie/loss per fold: 3/3/2 | `results_controls.md` | verified |
| GNN vs culprit rule (log1p) | 2/4/2 | `results_controls.md` | verified |
| GNN vs no-graph MLP (AP and root-cause top-1) | 0/6/2 in both: the MLP wins 2 folds and ties 6; MLP mean AP 0.983 vs GNN 0.928 | `results_controls.md` | verified |

Claim that must change: "the GNN beats the baseline" is not supported. With the correct AP method the GNN and the p95 baseline tie, and a no-graph MLP is better.

## 2. Root-cause top-1 (8 folds)
GNN 0.950, MLP 1.000, p95 baseline 0.868, culprit rule raw 0.868 / log1p 0.877 (`results_controls.md`, Root-Cause Top-1). Fold 4 (ep 3, ratings 100 ms): baseline and both culprit-score variants 0.071 (they blame the victim `reviews`); GNN and MLP 1.000. GNN loses on fold 2 (reviews 100 ms, 0.815) and fold 3 (details 50 ms, 0.786). Status: verified.

## 3. Shadow run, 2026-10-26 (rule and GNN, dry-run, live data)
Design: 30 min soak with no fault, then four 5-minute faults each followed by a 6-minute rest, run 05:48:25Z to 07:02:26Z. Both controllers read the same snapshot file; neither wrote to the cluster (`shadow_run/results_shadow.md`, written by `shadow_run/compare.py`).
- Blame was correct in 4 of 4 windows, for both scorers, and the two scorers produced identical decisions: ratings 150 ms REROUTE ratings at 76.4 s; details 75 ms ACTION_BLOCKED `no_healthy_alternative` details at 75.6 s; reviews 150 ms ACTION_BLOCKED reviews at 75.5 s; ratings 75 ms REROUTE ratings at 60.5 s. Status: verified.
- Detection times: 60.5 to 76.4 s; median over the 8 correct detections 75.5 s. They sit on 15 s controller cycles, which looks like the persistence rule setting the timing, not the scorer (my reading; the cause was not tested separately).
- Soak: 118 SCORED events per scorer, 0 decision events (0 false events, 0 REROUTE) (computed from `shadow_run/audit_rule.jsonl`, `audit_gnn.jsonl`).
- Over the run: 291 SCORED events per scorer, 0 with source fallback, no LOOP_ERROR, no telemetry gap above 30 s (`shadow_run/results_shadow.md`).
- Each scorer also logged 3 decision events inside the 120 s after a fault ended; they count neither as detections nor as false events. One of them (reviews, 75 s after the fault ended, risk 0.128 rule / 0.0 GNN) was the persistence bug (item 4).
- RELEASE in dry-run: 195.7 s after the ratings 150 ms fault ended and 180.5 s after the ratings 75 ms fault ended. **This is not recovery**: nothing was applied, so it only shows the culprit's score fell after the fault was removed.
- Predictions written before the run (`shadow_run/predictions_shadow.md`): details and reviews blocks and the soak prediction were right; "ratings 150 ms detected 30 to 75 s after start" was wrong (76.4 s); "ratings 75 ms: rule may blame reviews" was wrong (the rule rerouted ratings); "median about 60 s" was wrong (75.5 s).

## 4. Persistence bug, found and fixed
The old rule returned the top node when 3 of the last 4 cycles were hits, even if the current cycle was not. `_persistent_top` (`meshheal_controlplane/controlplane/controller.py`) now also requires the current cycle to be a hit. Thresholds, scorers and safety logic are unchanged. Replay effect (8 episodes plus holdout, computed): first-event times and blamed nodes did not change; 5 late repeat ACTION_BLOCKED events disappeared, each on a cycle where the top node's risk was below 0.85 (rule ep 1: 0.371, rule ep 2: 0.675, GNN ep 1: 0.753, GNN ep 2: 0.838, rule holdout: 0.650). Tests: `test_persistence_needs_a_hit_in_the_current_cycle`, `test_recovered_node_is_not_acted_on`, `test_sustained_fault_triggers_on_the_same_cycle`. Status: verified by tests and replay.

## 5. Duplicate-read fix
`step_from_file` skipped no repeats before; a snapshot read twice counted twice in the 3-of-4 history. It now skips a snapshot whose timestamp equals the last one processed (test `test_step_from_file_skips_already_processed_snapshot`). How often it happened in practice was not measured.

## 6. Label noise: the Oct 6 holdout, and Sep 16 "normal" training data
All counts below are computed from `snapshots.jsonl` with the dataset code's own phase and holdout assignment (`build_dataset_v2.py`); "flagged" means an edge p95 of at least 97.5 ms unless stated.
- **2026-10-06 holdout (contaminated).** Of the 70 holdout snapshots, 50 have details p95 above 50 ms from 10:45:29 to 10:57:57 UTC, plus a 175 ms ratings spike in 3 snapshots (10:57:42 to 10:58:12); 51 snapshots in total (criterion: details or ratings edge above 50 ms at more than 0.1 req/s). `fault-details-delay.yaml` was last saved at 10:44:44 UTC that day. No log records a fault; I infer an unlogged details fault. 12 of these snapshots fall in the first half of the holdout (threshold calibration) and 38 in the second (false-action evaluation).
- **2026-09-16 holdout (clean).** All 42 holdout snapshots (11:35:31 to 11:46:00) have no edge at or above 97.5 ms, checked across all three edges including productpage to reviews. (The holdout snapshots of 10-04 (2), 10-09 (12) and 10-18 (11) were only checked on the details and ratings edges: none flagged.)
- **2026-09-16 training-normal data (label noise in training).** Sep 16 has 409 snapshots (09:17:53 to 11:46:00), all phase "normal": 42 in the holdout, 367 not. **129 of them have productpage to reviews p95 of about 241 to 242.5 ms, all outside the holdout**, in three stretches: 09:46:31 to 10:03:21 (25 snapshots), 10:06:29 to 10:23:48 (69) and 11:08:20 to 11:16:59 (35). No other edge on Sep 16 reaches 97.5 ms. Every one is labelled normal (label 0 for all nodes) in LOEO training and in the final model.
  - **Start-up or restart?** It does not look like a start-up transient: each stretch lasts 8 to 17 minutes at the normal 15 s spacing and the request rate is 0.0 to 0.38 req/s, mostly 0.17 to 0.31. The first stretch begins about a minute after telemetry resumed from a 650 s gap (09:34:41 to 09:45:31), and the third follows a 175 s gap (11:05:25 to 11:08:20). Whether a pod restart or something else caused it I cannot say: the data hold no pod events and I did not query the cluster.
  - **Effect (computed, normal-only replay).** Replaying the 431 non-holdout normal snapshots (14 runs, a new run when the gap exceeds 300 s, fresh controller per run, dry-run): the rule scorer logs 33 ACTION_BLOCKED events and has 128 snapshots whose top node scores above 0.85, all on Sep 16. The final GNN has 129 snapshots on Sep 16 with a top-node score above 0.85 (131 in total, 2 more on 10-18) and also 33 ACTION_BLOCKED events, all on Sep 16, even though it was trained on these snapshots as normal (in-sample). An earlier count of 31 rule events differs from my 33; the number of events depends on how the replay is split into runs and on the repeat-block throttle.
  - **What this means.** The training data contain a labelling problem: about 240 ms reviews latency labelled "normal". **Whether it explains the GNN's weakness on the reviews 100 ms fold (fold 2: AP 0.683, root-cause top-1 0.815, `results_controls.md`) is untested.**
- **Effect on the reported numbers.** The holdout false-positive and false-action figures in `results_loeo.md` and `results_policy.md` include the Oct 6 snapshots; e.g. the policy second-half false-action share is 2.9% for the baseline and culprit rule and 2.9% to 15.7% for the GNN (per seed up to 20.3%), on a half-holdout of 69 snapshots (`results_policy.md`). The v1 files have not been changed; the re-run with the window excluded is the v3 check in item 12 (`results_loeo_v3.md`, `results_policy_v3.md`). LOEO AP and root-cause numbers are not affected by the Oct 6 holdout problem (the holdout is excluded from training and the re-run reproduced `results_loeo.csv` exactly), but they may be affected by the Sep 16 training-normal noise; that is untested.
- With the 10-06 window and a 120 s buffer excluded, the holdout shrinks from 137 to 69 snapshots (7 short runs) and a per-run replay gives 1 rule event (a start-up ACTION_BLOCKED on 10-18 at 12:20:16, productpage to reviews p95 444 ms at 0.13 req/s) and 0 GNN events (computed). This is a thin test: three of the seven runs have 3 or fewer snapshots.

## 7. Probe evidence fix
`probe_share` default changed from 10 to 30 (`config.py`): the probe now sends 70/15/15 instead of 90/5/5. With about 0.27 req/s into reviews, 30% gives about 0.08 req/s into ratings, above `min_evidence_rate` 0.05; at 10% it was about 0.027 req/s, so a closed-loop RELEASE could never fire. Test: `test_probe_share_gives_enough_traffic_for_evidence`. The 0.27 req/s is the approximate rate seen in the snapshots, not a measured constant. **Verified live, once per scenario (2026-10-29):** the probe at 70/15/15 started 120 s (A) and 119 s (B) after the REROUTE and RELEASE followed 90 s later (item 11). The fault was already removed when the probe started, so this shows the release logic works, not that the probe holds back a release while the fault persists.

## 8. Control-plane changes since the shadow run
- `--gnn-kill-file PATH`: while the file exists the GNN raises and the rule fallback scores; the audit line says `source: fallback`. Default off. Tests in `meshheal_controlplane/tests/test_gnn_adapter.py`. **Verified live (scenario B, 2026-10-29):** with the kill file present all 19 SCORED events had `source: fallback` with the note `GNN disabled by kill file`, the controller still rerouted, and the kill file was removed in cleanup.
- `KubeClient.set_weights` now states `application/merge-patch+json` explicitly (`cluster.py`); tests with a mocked API in `tests/test_cluster.py`; the installed kubernetes client (37.0.1) accepts `_content_type`. **Verified against the real cluster:** `live_demo/test_patch.py --yes` passed on 2026-10-28 (reviews moved to v1=100, read back as `{'v1': 100}`, restored to 34/33/33), and both live runs patched `reviews` through the same client.
- Test count: 35 passed (`python -m pytest -q` in `meshheal_controlplane/`).

## 9. Limitations to state
- One testbed (Istio Bookinfo), 4 services hardcoded in the model, 8 fault episodes (2 legacy, 6 new). The deliverable is the pipeline (collect, label, train per deployment), not a transferable model.
- The deployed GNN (5 seeds, `train_final.py`) is trained on all 8 episodes, so replaying them is in-sample and not an accuracy result; LOEO is the evaluation.
- Message passing adds nothing measurable on 4 nodes: the MLP ties or beats the GNN (item 1).
- Only `ratings` has a reroute (reviews to v1); faults on details, reviews and productpage end as ACTION_BLOCKED.
- Label noise: the Oct 6 holdout contains an unlogged-looking details fault, and 129 Sep 16 training-normal snapshots (128 with the rate filter) show about 242 ms reviews latency labelled normal (item 6). The v3 check (item 12) re-ran training and holdout without them; the v1 figures in `results_loeo.md` and `results_policy.md` are unchanged and still include the noisy data.
- GNN false-alarm rate varies across seeds and folds (item 6), and its thresholds vary per seed, so it must be seed-averaged and gated by the rule detector.
- The shadow run is dry-run: RELEASE and probe events show score behaviour, not recovery. The only recovery evidence is the earlier manual test with a 100 ms ratings fault: 5 of 10 requests slow (mean 0.134 s) before the reroute, 0 of 10 after (mean 0.033 s) (`CLAUDE.md`).

## 10. Not yet verified
Whether the Sep 16 label noise explains the GNN's weak reviews 100 ms fold (untested); the probe against a fault that is still present (in both live runs the fault was removed before the probe started); repeatability of the live timings (one run per scenario); why detection took 14 s longer in A than in B; the dashboard in LIVE mode while a controller is running (not watched); the cause of the Sep 16 and Oct 6 label noise. Verified live once: closed-loop REROUTE and RELEASE with the acting controller, the merge patch, the kill switch (items 11 and 8).

## 11. Live closed-loop runs and patch test (2026-10-28 and 2026-10-29)
Source: `live_demo/result_A_20261029T053627Z.json`, `live_demo/result_B_20261029T064550Z.json`, the matching `audit_*.jsonl` files. Ratings 150 ms delay (`shadow_run/fault-ratings-150.yaml`), real acting controller, one run per scenario. **One run each: do not quote a rate or an average.**
| | A: GNN scores | B: kill file, rule fallback scores |
|---|---|---|
| Fault applied (UTC) | 05:36:41.9 | 06:46:04.9 |
| REROUTE of ratings | 78.2 s after the fault | 63.7 s after the fault |
| High-risk cycle that acted | 4th | 3rd |
| Median productpage latency, faulted to after reroute | 0.172 s to 0.023 s (baseline 0.023 s) | 0.182 s to 0.024 s (baseline 0.029 s) |
| PROBE_START (70/15/15) | 05:40:00 | 06:49:07 |
| RELEASE | 05:41:30, 174 s after the fault was removed | 06:50:37, 174.9 s after the fault was removed |
| SCORED events | 21, all `primary`, 0 fallback | 19, all `fallback` with the kill-file note |
- `live_demo/test_patch.py --yes` passed on 2026-10-28: reviews moved to v1=100, read back, restored to 34/33/33. After both runs only `reviews` (34/33/33) and its DestinationRule remained; the kill file was gone.
- Wording rules: say "back to baseline within about 2 seconds of the reroute", not "1.8 s" or "0.3 s": the script reports the first of three consecutive fast samples taken 2 s apart. Say detection is "about 60 to 80 seconds, set by the persistence rule" (observed 63.7 s and 78.2 s; shadow run 60.5 to 76.4 s). Do not say the fallback is faster than the GNN: A acted on the 4th high-risk cycle and B on the 3rd, the 14 s gap is unexplained and probably one extra cycle, not a scorer effect. RELEASE shows the release logic works; the fault was removed before the probe started in both runs, so it does not show that the probe catches a fault that is still present.
- `live_demo/latency.csv` is opened in append mode and shared by both scenarios (column `scenario`); it holds the raw rows of both runs (150 for A, 143 for B when checked).

## 12. v3 data-cleanup check (`REPORT_V3.md`)
215 snapshots excluded (147 Sep 16 training normals and 68 Oct 6 holdout snapshots), models retrained as `models/gnn_final_v3_*`. The p95 baseline and the culprit rule are unchanged. GNN mean AP 0.928 to 0.898 and MLP 0.983 to 0.955 (distinct-threshold); the changes are about the size of the seed noise (GNN seed std up to 0.39 in one fold), so I cannot say the removal caused them. Holdout false-positive rate fell (p95 baseline 0.140 to 0.039, GNN 0.128 to 0.031) on holdouts of 137 and 69 snapshots. The v3 policy false-action numbers are **not comparable** with v1: the holdout split differs. The default demo model stays v1.

## 13. Items that were "written, not run" and now are
`live_demo/run_live.py`, `live_demo/test_patch.py` and `demo_up.sh` have all been run (2026-10-28 and 2026-10-29). `demo_up.sh` now starts telemetry with `PYTHONUNBUFFERED=1` so `shadow_run/telemetry.log` updates live.
