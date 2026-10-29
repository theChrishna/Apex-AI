# REPORT_V3: training data cleaned (v3) vs the original (v1)

Written 2026-10-27 after the overnight job. Reports numbers only; it does not recommend changing any default. Nothing existing was overwritten:
the v1 results files, `models/gnn_final_*`, `build_dataset_v2.py`, `model.py` and `train.py` are untouched, and every v3 output is a new file.
Predictions written before anything ran: `docs/v3_predictions.md` (2026-10-26 17:44:23 UTC).

## 1. What was removed (`excluded_windows_v3.json`, built from the data)
sha256 `776c55321d772144...` of `snapshots.jsonl`; sha256 of the windows file itself is recorded in `models/gnn_final_v3_manifest.json` (`cf5d05c6a496440d5e94ab66bd770e9e202d3533898abdbeb3b9299c9153b832`).
Criterion (a): Sep 16 non-holdout snapshots with any edge p95 >= 97.5 ms at request_rate > 0.1, runs split where flagged snapshots are more than 120 s apart, each run padded by 120 s. Criterion (b): the 2026-10-06 holdout stretch 10:42:56 to 10:59:59, padded by 120 s.

| Window | Kind | Run (UTC, month-day) | Flagged snapshots | Max p95 (ms) | Window with 120 s padding | Snapshots excluded |
|---|---|---|---|---|---|---|
| A1 | sep16 | 09-16T09:46:31 to 09-16T09:53:43 | 22 | 241.9 | 09-16T09:44:31 to 09-16T09:55:43 | 26 |
| A2 | sep16 | 09-16T09:58:03 to 09-16T09:58:18 | 2 | 235.0 | 09-16T09:56:03 to 09-16T10:00:18 | 2 |
| A3 | sep16 | 09-16T10:06:29 to 09-16T10:23:48 | 69 | 241.9 | 09-16T10:04:29 to 09-16T10:25:48 | 77 |
| A4 | sep16 | 09-16T11:08:20 to 09-16T11:16:59 | 35 | 241.1 | 09-16T11:06:20 to 09-16T11:18:59 | 42 |
| B1 | oct6 | 10-06T10:42:56 to 10-06T10:59:59 |  |  | 10-06T10:40:56 to 10-06T11:01:59 | 68 |

Total excluded: 215 snapshots, all phase "normal" (asserted): 147 training normals (all Sep 16) and 68 holdout snapshots (all Oct 6).
Flagged Sep 16 snapshots: 128 (all `productpage>reviews`; the earlier count of 129 had no rate filter, one snapshot at 10:03:21 has p95 above 97.5 ms at rate 0.1 req/s or less and stays in the data).
Holdout: 137 to 69 snapshots. Final-model training graphs: 605 to 458 (positive node labels 147 in both). LOEO training sets shrink by 147 per fold (e.g. fold 0 529 to 382, fold 2 558 to 411).

How it is applied (`build_dataset_v3.py`): v2's own records, `record_to_graph` and phase rules; the excluded timestamps are dropped, and the holdout is v2's holdout minus them (not re-selected, so the other 69 holdout snapshots are the same ones as before). Six tests (`test_build_dataset_v3.py`) check that records and graphs outside the windows equal v2's exactly. The unchanged v2 scripts were run through `run_v3.py`, which swaps the two data functions in memory.
Same seeds [42, 7, 13, 99, 2024], same config, same folds. Run times: LOEO 22 min, policy 18 min, controls 30 min, final retrain 3 min.

## 2. Per-fold results, v1 to v3 (distinct-threshold AP; "v1 → v3 (change)")
v1 numbers are `results_controls.md` (its re-run matched exactly earlier); v3 numbers are `results_controls_v3.md`. "CS(raw)" is the raw-millisecond culprit rule the control plane runs; GNN is the 5-seed mean excluding collapsed seeds.

### Average precision per fold, distinct-threshold, v1 → v3 (Δ)

| Fold | Ep | Node | Delay | p95-BL | CS(log1p) | CS(raw) | MLP | GNN |
|---|---|---|---|---|---|---|---|---|
| 0 | A | ratings | 200ms | 0.918 → 0.918 (+0.000) | 0.943 → 0.943 (+0.000) | 0.935 → 0.935 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 1 | B | details | 100ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 2 | 1 | reviews | 100ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 0.861 → 0.827 (-0.034) | 0.683 → 0.617 (-0.066) |
| 3 | 2 | details | 50ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 0.742 → 0.737 (-0.005) |
| 4 | 3 | ratings | 100ms | 0.536 → 0.536 (+0.000) | 0.536 → 0.536 (+0.000) | 0.536 → 0.536 (+0.000) | 1.000 → 0.811 (-0.189) | 1.000 → 1.000 (+0.000) |
| 5 | 4 | reviews | 200ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 6 | 5 | details | 200ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 7 | 6 | ratings | 50ms | 0.985 → 0.985 (+0.000) | 1.000 → 1.000 (+0.000) | 0.995 → 0.995 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 0.827 (-0.173) |
| Mean |  |  |  | 0.930 → 0.930 (+0.000) | 0.935 → 0.935 (+0.000) | 0.933 → 0.933 (+0.000) | 0.983 → 0.955 (-0.028) | 0.928 → 0.898 (-0.030) |

### Root-cause top-1 per fold, v1 → v3 (Δ)

| Fold | Ep | Node | Delay | p95-BL | CS(log1p) | CS(raw) | MLP | GNN |
|---|---|---|---|---|---|---|---|---|
| 0 | A | ratings | 200ms | 0.942 → 0.942 (+0.000) | 0.942 → 0.942 (+0.000) | 0.942 → 0.942 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 1 | B | details | 100ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 2 | 1 | reviews | 100ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 0.815 → 0.615 (-0.200) |
| 3 | 2 | details | 50ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 0.786 → 0.814 (+0.028) |
| 4 | 3 | ratings | 100ms | 0.071 → 0.071 (+0.000) | 0.071 → 0.071 (+0.000) | 0.071 → 0.071 (+0.000) | 1.000 → 0.771 (-0.229) | 1.000 → 1.000 (+0.000) |
| 5 | 4 | reviews | 200ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 6 | 5 | details | 200ms | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 1.000 (+0.000) |
| 7 | 6 | ratings | 50ms | 0.929 → 0.929 (+0.000) | 1.000 → 1.000 (+0.000) | 0.929 → 0.929 (+0.000) | 1.000 → 1.000 (+0.000) | 1.000 → 0.800 (-0.200) |
| Mean |  |  |  | 0.868 → 0.868 (+0.000) | 0.877 → 0.877 (+0.000) | 0.868 → 0.868 (+0.000) | 1.000 → 0.971 (-0.029) | 0.950 → 0.904 (-0.046) |

Win/tie/loss for the GNN (tie = difference of at most 0.01), v1 then v3:

| Comparison | AP v1 | AP v3 | Root-cause v1 | Root-cause v3 |
|---|---|---|---|---|
| GNN vs p95 baseline | 3/3/2 | 2/3/3 | 3/3/2 | 2/3/3 |
| GNN vs culprit rule (log1p) | 2/4/2 | 2/3/3 | 2/4/2 | 2/3/3 |
| GNN vs no-graph MLP | 0/6/2 | 1/4/3 | 0/6/2 | 1/4/3 |

Seed spread (the only noise estimate I have): GNN trapezoidal AP, mean ± std over seeds, from the LOEO CSVs, plus the baseline's trapezoidal AP.

### GNN trapezoidal AP, mean ± seed std (results_loeo csv; collapsed seeds excluded), and baseline trapezoidal AP

| Fold | Ep | Node | Delay | n_train v1 → v3 | GNN AP mean±std v1 | GNN AP mean±std v3 | BL AP v1 → v3 |
|---|---|---|---|---|---|---|---|
| 0 | A | ratings | 200ms | 529 → 382 | 1.000±0.000 | 1.000±0.000 | 0.821 → 0.821 |
| 1 | B | details | 100ms | 556 → 409 | 1.000±0.000 | 1.000±0.000 | 1.000 → 1.000 |
| 2 | 1 | reviews | 100ms | 558 → 411 | 0.658±0.185 | 0.594±0.287 | 1.000 → 1.000 |
| 3 | 2 | details | 50ms | 559 → 412 | 0.728±0.315 | 0.720±0.260 | 1.000 → 1.000 |
| 4 | 3 | ratings | 100ms | 559 → 412 | 1.000±0.000 | 1.000±0.000 | 0.376 → 0.376 |
| 5 | 4 | reviews | 200ms | 559 → 412 | 1.000±0.000 | 1.000±0.000 | 1.000 → 1.000 |
| 6 | 5 | details | 200ms | 563 → 416 | 1.000±0.000 | 1.000±0.000 | 1.000 → 1.000 |
| 7 | 6 | ratings | 50ms | 529 → 382 | 1.000±0.000 | 0.826±0.390 | 0.984 → 0.984 |

Collapsed seeds (probability std under 0.01, excluded from means): v1 LOEO fold 3 seed 13; v3 LOEO fold 5 seed 42. MLP per-seed AP in fold 4 (ratings 100 ms) in v3: 0.885, 0.433, 0.850, 0.885, 1.000 (v1: 1.000 for all five seeds; `results_controls_v3.md` Control 2).
Holdout false-positive rate at the validation-chosen threshold (not tuned on the holdout), mean over the 8 folds, `results_loeo*.csv`: p95 baseline 0.140 to 0.039; GNN 0.128 to 0.031. These are on different holdouts (137 vs 69 snapshots).

## 3. Policy simulation (`results_policy_v3.md`)
### Policy simulation: false-action share in the second half of the normal holdout (BL = p95 baseline, CS = culprit rule)

| Fold | Ep | Node | Delay | BL fires v1 → v3 | CS fires v1 → v3 | GNN mean share v1 → v3 |
|---|---|---|---|---|---|---|
| 0 | A | ratings | 200ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 2.9% → 35.4% |
| 1 | B | details | 100ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 10.7% → 23.4% |
| 2 | 1 | reviews | 100ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 7.0% → 29.7% |
| 3 | 2 | details | 50ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 4.0% → 41.1% |
| 4 | 3 | ratings | 100ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 3.5% → 26.9% |
| 5 | 4 | reviews | 200ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 15.7% → 42.9% |
| 6 | 5 | details | 200ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 4.3% → 49.7% |
| 7 | 6 | ratings | 50ms | 2 (2.9%) → 19 (54.3%) | 2 (2.9%) → 19 (54.3%) | 4.9% → 45.1% |

(second-half holdout size per fold: v1 n=69, v3 n=35)

This is **not a like-for-like comparison**, and the jump is mostly an artifact of how the policy script splits the holdout, not evidence that the cleaned data made false actions worse. The script calibrates thresholds on the first half of the holdout (95th percentile) and counts false actions in the second half. v1: first half 68 snapshots (Sep 16: 42, Oct 4: 2, Oct 6: 24), second half 69 (Oct 6: 46, Oct 9: 12, Oct 18: 11). v3: first half 34 snapshots, **all Sep 16**; second half 35 (Sep 16: 8, Oct 4: 2, Oct 6: 2, Oct 9: 12, Oct 18: 11). So v3 calibrates on a single quiet day and is tested on other days. Thresholds fell accordingly (baseline 5.081 to 3.584 in log1p ms, i.e. about 160 ms to 35 ms; GNN per-seed thresholds from between 0.11 and 1.0 down to 0.000 to 0.081 in all but one seed, which is 0.853, with one collapsed seed). 21 of the 35 second-half snapshots exceed the new baseline threshold (Oct 4: 2 of 2, Oct 6: 2 of 2, Oct 9: 11 of 12, Oct 18: 6 of 11, Sep 16: 0 of 8; computed). The second half now contains post-recovery and pre-episode tails around Oct 9 and Oct 18, which neither v1 nor v3 labels as fault. The policy numbers need a different split (for example calibration and evaluation interleaved across days) before they mean anything; that was not done.

## 4. Replays (fresh controller per run, dry-run, simulated clock)
**Normal-only replay.** Runs are split where snapshots are more than 300 s apart (holdouts: more than 30 s). "Top score > 0.85" counts snapshots whose highest node score is above the 0.85 act threshold. The rule scorer is not trained, so its zero on the cleaned pool follows from the cleaning criterion (the removed snapshots are the ones with high reviews latency); that row is not independent evidence.

| Pool | n | rule | v1 GNN | v3 GNN |
|---|---|---|---|---|
| Normal non-holdout, v1 pool (all 431) | 431 | decision events: 33 ACTION_BLOCKED; snapshots with top score > 0.85: 128 (09-16: 128) | decision events: 33 ACTION_BLOCKED; snapshots with top score > 0.85: 131 (09-16: 129, 10-18: 2) | decision events: 33 ACTION_BLOCKED; snapshots with top score > 0.85: 129 (09-16: 129) |
| Normal non-holdout, cleaned v3 pool | 284 | decision events: none; snapshots with top score > 0.85: 0 | decision events: none; snapshots with top score > 0.85: 3 (09-16: 1, 10-18: 2) | decision events: none; snapshots with top score > 0.85: 1 (09-16: 1) |
| The 215 excluded snapshots themselves | 215 | decision events: 46 ACTION_BLOCKED, 1 REROUTE; snapshots with top score > 0.85: 183 (09-16: 128, 10-06: 55) | decision events: 46 ACTION_BLOCKED, 1 REROUTE; snapshots with top score > 0.85: 182 (09-16: 128, 10-06: 54) | decision events: 45 ACTION_BLOCKED, 1 REROUTE; snapshots with top score > 0.85: 182 (09-16: 128, 10-06: 54) |
| Holdout v1 (137) | 137 | decision events: 14 ACTION_BLOCKED, 1 REROUTE; snapshots with top score > 0.85: 60 (10-06: 57, 10-18: 3) | decision events: 13 ACTION_BLOCKED, 1 REROUTE; snapshots with top score > 0.85: 58 (10-06: 56, 10-18: 2) | decision events: 12 ACTION_BLOCKED, 1 REROUTE; snapshots with top score > 0.85: 58 (10-06: 56, 10-18: 2) |
| Holdout v3 (69) | 69 | decision events: 1 ACTION_BLOCKED; snapshots with top score > 0.85: 5 (10-06: 2, 10-18: 3) | decision events: none; snapshots with top score > 0.85: 4 (10-06: 2, 10-18: 2) | decision events: none; snapshots with top score > 0.85: 4 (10-06: 2, 10-18: 2) |

**8-episode replay** (in-sample for both final GNNs, so this is not an accuracy result): the v3 final model gives the same first event, blamed node, time and event counts as the v1 final model in all 8 episodes.

| Ep | Fault | rule: first event, s after start (counts) | v1 GNN | v3 GNN |
|---|---|---|---|---|
| A | ratings 200ms | REROUTE ratings at 31.4 (1 REROUTE, 4 PROBE_START, 4 PROBE_FAILED) | REROUTE ratings at 31.4 (1 REROUTE, 4 PROBE_START, 4 PROBE_FAILED) | REROUTE ratings at 31.4 (1 REROUTE, 4 PROBE_START, 4 PROBE_FAILED) |
| B | details 100ms | ACTION_BLOCKED details at 64.1 (5 ACTION_BLOCKED) | ACTION_BLOCKED details at 64.1 (5 ACTION_BLOCKED) | ACTION_BLOCKED details at 64.1 (5 ACTION_BLOCKED) |
| 1 | reviews 100ms | ACTION_BLOCKED reviews at 71.7 (5 ACTION_BLOCKED) | ACTION_BLOCKED reviews at 71.7 (4 ACTION_BLOCKED) | ACTION_BLOCKED reviews at 71.7 (4 ACTION_BLOCKED) |
| 2 | details 50ms | ACTION_BLOCKED details at 49.9 (5 ACTION_BLOCKED) | ACTION_BLOCKED details at 49.9 (5 ACTION_BLOCKED) | ACTION_BLOCKED details at 49.9 (5 ACTION_BLOCKED) |
| 3 | ratings 100ms | REROUTE ratings at 60.3 (1 REROUTE, 3 SUPPRESSED_VICTIM, 2 PROBE_START, 1 PROBE_FAILED) | REROUTE ratings at 60.3 (1 REROUTE, 2 PROBE_START, 1 PROBE_FAILED) | REROUTE ratings at 60.3 (1 REROUTE, 2 PROBE_START, 1 PROBE_FAILED) |
| 4 | reviews 200ms | ACTION_BLOCKED reviews at 53.9 (6 ACTION_BLOCKED) | ACTION_BLOCKED reviews at 114.9 (5 ACTION_BLOCKED) | ACTION_BLOCKED reviews at 114.9 (5 ACTION_BLOCKED) |
| 5 | details 200ms | ACTION_BLOCKED details at 61.4 (5 ACTION_BLOCKED) | ACTION_BLOCKED details at 61.4 (5 ACTION_BLOCKED) | ACTION_BLOCKED details at 61.4 (5 ACTION_BLOCKED) |
| 6 | ratings 50ms | REROUTE ratings at 53.6 (1 REROUTE, 2 PROBE_START, 1 PROBE_FAILED) | REROUTE ratings at 53.6 (1 REROUTE, 2 PROBE_START, 1 PROBE_FAILED) | REROUTE ratings at 53.6 (1 REROUTE, 2 PROBE_START, 1 PROBE_FAILED) |

## 5. Final v3 model and parity
`models/gnn_final_v3_seed{42,7,13,99,2024}.pt` and `models/gnn_final_v3_manifest.json` (records the windows-file hash, 458 training graphs, 69 holdout snapshots, 215 excluded). Defaults unchanged: `controlplane` still points at `../models/gnn_final_manifest.json`.
Live-path parity (`python check_parity_v3.py models/gnn_final_v3_manifest.json`): 808 stored snapshots compared (29 rejected by the control plane's validator), **max absolute difference 0.0** (exactly zero, same for the v1 manifest). This checks the adapter plumbing against an independent load of the same weights and `record_to_graph`; it says nothing about model quality, and an exact zero is expected because both paths run the same feature code.

## 6. What changed, what did not
Did not change (exactly equal in every fold): the p95 baseline and the culprit rule, in AP and root-cause top-1 (they are not trained; AP is threshold-free). The 8-episode replay decisions of all three scorers. Parity (0.0 in both).
Changed:
- GNN mean AP 0.928 to 0.898 and root-cause top-1 0.950 to 0.904; MLP mean AP 0.983 to 0.955 and root-cause top-1 1.000 to 0.971 (distinct-threshold).
- GNN vs baseline AP win/tie/loss 3/3/2 to 2/3/3; vs MLP 0/6/2 to 1/4/3. The v1 ordering (MLP 0.983 above baseline 0.930 above GNN 0.928) becomes MLP 0.955, baseline 0.930, GNN 0.898.
- Holdout false-positive rate at validation-chosen thresholds fell (baseline 0.140 to 0.039, GNN 0.128 to 0.031), consistent with the contaminated Oct 6 stretch having inflated the v1 number.
- Policy false-action shares rose sharply, for the reason in section 3 (calibration split), not shown to be a model effect.
- On the cleaned normal pool the v3 final GNN has 1 snapshot above 0.85 (v1 final GNN: 3, two of them on Oct 18); both logged no decision events.
- Both final GNNs score the 215 removed snapshots just as high (182 of 215 above 0.85 each; rule 183): the v3 model never saw them and the v1 model saw them as normal, yet both call them faults.

## 7. Predictions that were wrong (`docs/v3_predictions.md`)
1. "GNN AP on the reviews folds goes up": **wrong.** Fold 2 (reviews 100 ms): AP 0.683 to 0.617, root-cause top-1 0.815 to 0.615. Fold 5 (reviews 200 ms) stayed at 1.000 (ceiling).
2. "Other folds change within noise": **partly wrong.** In AP, fold 3 changes by 0.005 and the folds at 1.000 do not change, but fold 7 (ratings 50 ms) fell from 1.000 to 0.827 AP and 1.000 to 0.800 root-cause, and the GNN mean dropped by 0.030. Its seed std is 0.390, so a seed effect is plausible but was not tested.
3. "MLP and baseline barely change": baseline right (exactly unchanged); MLP **wrong**: mean AP 0.983 to 0.955, fold 4 (ratings 100 ms) 1.000 to 0.811 (seed values 0.885, 0.433, 0.850, 0.885, 1.000).
4. (mine) "Policy false-action share drops on the cleaned holdout": **wrong** (section 3, calibration split artifact).
5. (mine) Baseline and rule unchanged: right. v3 GNN scoring fewer Sep 16 snapshots high: true on the cleaned pool (1 vs 3) but trivially, and on the removed snapshots it still scores 182 of 215 high ("still scores some of them high": right, and more than "some").
6. (mine) "Fold 2 may not improve": right. "Several GNN folds move by more than 0.01 AP; judge with the seed std": right (folds 2 and 7; both within one seed std).
The prediction that held clearly: the baseline and culprit rule do not change.

## 8. What I could not verify
- Whether the GNN and MLP changes are an effect of removing the noisy snapshots or seed and training-set noise. The seed std (up to 0.39 for the GNN, 0.22 for the MLP in fold 4) is as large as the changes; I did not run extra seed sets or a repeated-split noise estimate, and 8 folds with about 13 to 14 positives each are small. Removing 147 normals also changes the class balance of the training set (positives 147 of 605 graphs to 147 of 458 in the final model); not tested as a cause.
- Why the Sep 16 reviews stretches happened (no pod events in the data; the cluster was not queried).
- The cause of the policy jump is shown by the composition and threshold numbers in section 3, but I did not re-run the policy with an interleaved split.
- That the v3 model behaves differently from v1 in a live dry-run or closed loop: not run. No live_demo script was run.
- The 8-episode replay with either final GNN is in-sample.
- The two remaining Oct 6 snapshots (10:37:05 and 10:37:21, start-up readings at very low traffic) stay in the v3 holdout's second half, and so do the Oct 18 start-up and decay snapshots, which are not label noise by the criteria used.

## 9. Files created
`docs/v3_predictions.md`, `excluded_windows_v3.json`, `make_excluded_windows_v3.py`, `build_dataset_v3.py`, `run_v3.py`, `test_build_dataset_v3.py`, `train_final_v3.py`, `check_parity_v3.py`, `results_loeo_v3.md`, `results_loeo_v3.csv`, `results_policy_v3.md`, `results_controls_v3.md`, `models/gnn_final_v3_seed*.pt`, `models/gnn_final_v3_manifest.json`, this report. One existing file edited: `controls_eval.py` got two env-var overrides (`CONTROLS_RESULT_MD`, and the old-results CSV path via `LOEO_RESULT_CSV`); defaults are unchanged.
