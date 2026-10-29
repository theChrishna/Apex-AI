# MeshHeal AI — LOEO Cross-Validation Results

## Experiment Setup

| Parameter | Value |
|-----------|-------|
| Folds | 8 (leave-one-episode-out) |
| Test window | [episode_start − 60 s, episode_end + 90 s] |
| Val window | same rule applied to next episode (k+1 mod 8) |
| Leakage buffer | 120 s before/after test and val windows removed from train |
| Lag exclusion | [start, start+90 s) excluded from all splits |
| Recovery exclusion | (end, end+90 s] excluded from all splits |
| GNN architecture | 2×GCNConv, hidden=16, LeakyReLU(0.1), Linear→1 |
| GNN pos_weight | 1.0 (fixed, no tuning) |
| GNN epochs | 100 |
| GNN seeds | [42, 7, 13, 99, 2024] |
| Baseline | in_lat score = log1p(in_latency_p95) |
| Threshold selection | val episode, best F1 |
| Normal holdout | latest 25% of pure-normal snapshots (never in train) |
| Persistence rule | flag only if above threshold in ≥3 of last 4 snapshots |

## Per-Episode Counts

| Fold | Ep | Node | Delay | Lag | Steady | Recovery |
|------|----|------|-------|-----|--------|----------|
| 0 | A | ratings | 200ms | (excl) | 52 steady in test | (excl) |
| 1 | B | details | 100ms | (excl) | 12 steady in test | (excl) |
| 2 | 1 | reviews | 100ms | (excl) | 13 steady in test | (excl) |
| 3 | 2 | details | 50ms | (excl) | 14 steady in test | (excl) |
| 4 | 3 | ratings | 100ms | (excl) | 14 steady in test | (excl) |
| 5 | 4 | reviews | 200ms | (excl) | 14 steady in test | (excl) |
| 6 | 5 | details | 200ms | (excl) | 14 steady in test | (excl) |
| 7 | 6 | ratings | 50ms | (excl) | 14 steady in test | (excl) |

> Lag and recovery periods are excluded from training and evaluation. They are reported separately as a detection-delay note (see below).

## 1. Threshold-Free Metrics (AP and AUROC)

| Fold | Ep | Node | Delay | GNN AP (mean±std) | GNN AUROC (mean±std) | BL AP | BL AUROC | GNN wins AP? |
|------|----|------|-------|-------------------|----------------------|-------|----------|--------------|
| 0 | A | ratings | 200ms | 1.000±0.000 | 1.000±0.000 | 0.821 | 0.972 | ✓ |
| 1 | B | details | 100ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 | ✗ |
| 2 | 1 | reviews | 100ms | 0.658±0.185 | 0.945±0.031 | 1.000 | 1.000 | ✗ |
| 3 | 2 | details | 50ms | 0.728±0.315 | 0.940±0.070 | 1.000 | 1.000 | ✗ |
| 4 | 3 | ratings | 100ms | 1.000±0.000 | 1.000±0.000 | 0.376 | 0.776 | ✓ |
| 5 | 4 | reviews | 200ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 | ✗ |
| 6 | 5 | details | 200ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 | ✗ |
| 7 | 6 | ratings | 50ms | 1.000±0.000 | 1.000±0.000 | 0.984 | 0.996 | ✓ |
| **Mean (excl. collapsed seeds)** | | | | **0.923 ± 0.143** | **0.986 ± 0.027** | **0.898** | **0.968** | **3/8** |
| **Mean (collapsed seeds = 0)** | | | | **0.905 ± 0.177** | — | — | — | — |

> Fold 3 seed 13 collapsed (prob_std=0.0005 < 0.01). Mean excluding collapse: AP=0.728 (4 seeds). Mean counting collapse as 0: AP=0.582 (= 0.728 × 4 / 5). Overall GNN AP mean: 0.923 (excl.) vs **0.905** (collapse=0). Calculation: fold values [1.000, 1.000, 0.658, **0.582**, 1.000, 1.000, 1.000, 1.000], mean=0.9050, sample std=0.1771. The previously reported 0.836 ± 0.283 was incorrect; it used fold 3 = 0.000 instead of 0.582.

## 2. At-Threshold Metrics (Precision / Recall / FPR)

Threshold chosen per fold on the validation episode by best F1.

| Fold | Ep | GNN P | GNN R | GNN FPR(test) | GNN FPR(holdout) | BL P | BL R | BL FPR(test) | BL FPR(holdout) |
|------|----|-------|-------|----------------|------------------|------|------|--------------|-----------------|
| 0 | A | 0.500±0.000 | 1.000±0.000 | 0.333 | 0.135 | 0.500 | 1.000 | 0.333 | 0.139 |
| 1 | B | 1.000±0.000 | 1.000±0.000 | 0.000 | 0.123 | 1.000 | 1.000 | 0.000 | 0.124 |
| 2 | 1 | 0.603±0.190 | 0.831±0.269 | 0.193 | 0.168 | 0.867 | 1.000 | 0.036 | 0.139 |
| 3 | 2 | 0.000±0.000 | 0.000±0.000 | 0.000 | 0.062 | 1.000 | 1.000 | 0.000 | 0.139 |
| 4 | 3 | 0.483±0.017 | 1.000±0.000 | 0.259 | 0.188 | 0.438 | 1.000 | 0.310 | 0.148 |
| 5 | 4 | 1.000±0.000 | 1.000±0.000 | 0.000 | 0.121 | 1.000 | 1.000 | 0.000 | 0.148 |
| 6 | 5 | 0.811±0.206 | 1.000±0.000 | 0.076 | 0.123 | 0.438 | 1.000 | 0.310 | 0.268 |
| 7 | 6 | 1.000±0.000 | 1.000±0.000 | 0.000 | 0.104 | 0.000 | 0.000 | 0.000 | 0.015 |
| **Mean** | | **0.675 ± 0.351** | **0.854 ± 0.350** | **0.108** | **0.128** | **0.655** | **0.875** | **0.124** | **0.140** |

## 3. Root-Cause Top-1 Accuracy

Fraction of steady-fault snapshots where the faulted node has the highest score.
Ties are treated as failure. Results are suggestive given ~13-14 steady snapshots per fold.

| Fold | Ep | Node | Delay | GNN RC1 (mean±std) | BL RC1 | GNN wins RC1? |
|------|----|------|-------|---------------------|--------|---------------|
| 0 | A | ratings | 200ms | 1.000±0.000 | 0.942 | ✓ |
| 1 | B | details | 100ms | 1.000±0.000 | 1.000 | ✗ |
| 2 | 1 | reviews | 100ms | 0.815±0.103 | 1.000 | ✗ |
| 3 | 2 | details | 50ms | 0.786±0.274 | 1.000 | ✗ |
| 4 | 3 | ratings | 100ms | 1.000±0.000 | 0.071 | ✓ |
| 5 | 4 | reviews | 200ms | 1.000±0.000 | 1.000 | ✗ |
| 6 | 5 | details | 200ms | 1.000±0.000 | 1.000 | ✗ |
| 7 | 6 | ratings | 50ms | 1.000±0.000 | 0.929 | ✓ |
| **Mean** | | | | **0.950 ± 0.093** | **0.868** | **3/8** |

## 4. Persistence Rule (3-of-4 Snapshots Above Threshold)

Flag a node only if it exceeded the threshold in ≥ 3 of the last 4 snapshots.

| Fold | GNN P (persist) | GNN R (persist) | GNN FPR (persist) | BL P (persist) | BL R (persist) | BL FPR (persist) |
|------|-----------------|-----------------|-------------------|----------------|----------------|------------------|
| 0 | 0.500 | 0.962 | 0.321 | 0.500 | 0.962 | 0.321 |
| 1 | 1.000 | 0.833 | 0.000 | 1.000 | 0.833 | 0.000 |
| 2 | 0.545 | 0.600 | 0.124 | 1.000 | 0.846 | 0.000 |
| 3 | 0.000 | 0.000 | 0.000 | 1.000 | 0.857 | 0.000 |
| 4 | 0.492 | 0.857 | 0.214 | 0.429 | 0.857 | 0.276 |
| 5 | 1.000 | 0.857 | 0.000 | 1.000 | 0.857 | 0.000 |
| 6 | 0.820 | 0.857 | 0.062 | 0.429 | 0.857 | 0.276 |
| 7 | 1.000 | 0.857 | 0.000 | 0.000 | 0.000 | 0.000 |
| **Mean** | **0.670** | **0.728** | **0.090** | **0.670** | **0.759** | **0.109** |

## 5. Win Count: GNN vs Baseline

| Metric | GNN wins (out of 8 folds) |
|--------|-----------------------------------|
| Average Precision | 3/8 |
| Root-Cause Top-1 | 3/8 |

> Results are suggestive, not conclusive. Each fold has approximately 13-14 steady-fault positive node readings. With only ~14 positives per fold, metrics can swing substantially from a single misclassification.

## Detection-Delay Note (Lag Period)

Snapshots in [start, start+90s) are in the lag period where the 1-minute Prometheus rate window has not yet fully captured the injected delay. Excluded from training and evaluation.

- Episode A (ratings 200ms): 6 lag snapshots (~90 s)
- Episode B (details 100ms): 6 lag snapshots (~90 s)
- Episodes 1-6: 5-6 lag snapshots each (~75-90 s)

## Normal Holdout: Date Range and Snapshot Counts

The 137 holdout snapshots are the **latest 25%** of pure-normal snapshots not within 120 s of any episode window.

| Date | Count |
|------|-------|
| 2026-09-16 | 42 |
| 2026-10-04 | 2 |
| 2026-10-06 | 70 |
| 2026-10-09 | 12 |
| 2026-10-18 | 11 |
| **Total** | **137** |

First: `2026-09-16T11:35:31 UTC` | Last: `2026-10-18T13:10:57 UTC`

**Oct-18 normal snapshots outside episode windows, not in holdout: 40** (available for training where outside leakage buffer).

## Assumptions, Deviations, and Limitations

1. **No hyperparameter tuning per fold.** pos_weight, lr, epochs, and architecture fixed from Experiment B v2.
2. **Validation-based thresholding.** Both thresholds chosen on next episode window (k+1 mod 8). Falls back to train if val has 0 positives.
3. **Snapshot timestamp granularity.** Prometheus polls every 15 s; lag/steady boundary at +90 s may miss first qualifying snapshot by up to 14 s.
4. **Only log1p(in_latency_p95) used as baseline score.** Other features not tested as baseline scorers.
5. **Root-cause top-1 with 4 nodes.** Random chance = 25%. Ties = failure. High variance with ~13-14 snapshots per fold.
6. **Persistence rule resets** at fold boundary.
7. **latency_mean** only available for Oct-18 episodes; not used in 8-fold experiment.
8. **No causal topology analysis** performed.
9. **Legacy episode A** (886 s) has 52 steady snapshots vs ~13-14 for new episodes.

---
*Generated by loeo_eval.py; fixes applied per post-run review*

---

# Optional: 6-Fold LOEO — New Episodes Only (7 Features, incl. latency_mean) — NN-Matched

> **CONFOUNDED: feature is zero for pre-Oct-18 training data.** Only 14-23% of training rows per fold receive a real latency_mean value via nearest-neighbour matching (<=10 s gap); the remaining 77-86% are pre-Oct-18 rows with mean-lat=0. Test-set rows receive real values (100% NN match). This train/test distribution mismatch is not corrected here.

> **INVALID first run (zero-fill) archived in `results_loeo_invalid_zerofill.md`.** The run below uses NN-matched values and drops unmatched snapshots.

**NN matching:** exact timestamp match = 0%; NN-10s match = 100% for in-window snapshots (gaps 0-7.5 s, median 3.6 s).

### Training-set composition per fold

| 6f Fold | Test Ep | Train rows (total) | With real mean-lat (NN<=10s) | With mean-lat=0 (pre-Oct-18) |
|---------|---------|-------------------|-----------------------------|------------------------------|
| 0 | ep 1 (reviews 100ms) | 531 | 123 (23%) | 408 (77%) |
| 1 | ep 2 (details 50ms) | 558 | 96 (17%) | 462 (83%) |
| 2 | ep 3 (ratings 100ms) | 560 | 76 (14%) | 484 (86%) |
| 3 | ep 4 (reviews 200ms) | 561 | 77 (14%) | 484 (86%) |
| 4 | ep 5 (details 200ms) | 561 | 77 (14%) | 484 (86%) |
| 5 | ep 6 (ratings 50ms) | 561 | 77 (14%) | 484 (86%) |

Legacy episodes A, B are in training. Oct-18 normal outside episode windows not in holdout: 40.

### Results (NN-matched)

| Fold | Ep | Node | Delay | GNN AP (7f) | GNN RC1 (7f) | BL AP | BL RC1 |
|------|----|------|-------|-------------|--------------|-------|--------|
| 0 | 1 | reviews | 100ms | 0.925±0.093 | 0.923±0.109 | 1.000 | 1.000 |
| 1 | 2 | details | 50ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 |
| 2 | 3 | ratings | 100ms | 1.000±0.000 | 1.000±0.000 | 0.376 | 0.071 |
| 3 | 4 | reviews | 200ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 |
| 4 | 5 | details | 200ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 |
| 5 | 6 | ratings | 50ms | 1.000±0.000 | 1.000±0.000 | 0.984 | 0.929 |
| **Mean** | | | | **0.987±0.031** | **0.987±0.031** | **0.893** | **0.833** |

GNN (7f) wins AP: 2/6  |  RC1: 2/6

> Suggestive only. The 7th feature = 0 for 77-86% of training rows; a clean test requires Oct-18-only training data (see controls experiment item 5).
