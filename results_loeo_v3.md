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
| 2 | 1 | reviews | 100ms | 0.594±0.287 | 0.887±0.130 | 1.000 | 1.000 | ✗ |
| 3 | 2 | details | 50ms | 0.720±0.260 | 0.949±0.050 | 1.000 | 1.000 | ✗ |
| 4 | 3 | ratings | 100ms | 1.000±0.000 | 1.000±0.000 | 0.376 | 0.776 | ✓ |
| 5 | 4 | reviews | 200ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 | ✗ |
| 6 | 5 | details | 200ms | 1.000±0.000 | 1.000±0.000 | 1.000 | 1.000 | ✗ |
| 7 | 6 | ratings | 50ms | 0.826±0.390 | 0.844±0.350 | 0.984 | 0.996 | ✗ |
| **Mean** | | | | **0.892 ± 0.161** | **0.960 ± 0.062** | **0.898** | **0.968** | **2/8** |

## 2. At-Threshold Metrics (Precision / Recall / FPR)

Threshold chosen per fold on the validation episode by best F1.

| Fold | Ep | GNN P | GNN R | GNN FPR(test) | GNN FPR(holdout) | BL P | BL R | BL FPR(test) | BL FPR(holdout) |
|------|----|-------|-------|----------------|------------------|------|------|--------------|-----------------|
| 0 | A | 0.689±0.260 | 1.000±0.000 | 0.204 | 0.030 | 0.500 | 1.000 | 0.333 | 0.022 |
| 1 | B | 1.000±0.000 | 1.000±0.000 | 0.000 | 0.025 | 1.000 | 1.000 | 0.000 | 0.022 |
| 2 | 1 | 0.400±0.332 | 0.677±0.463 | 0.222 | 0.046 | 0.867 | 1.000 | 0.036 | 0.022 |
| 3 | 2 | 0.200±0.447 | 0.200±0.447 | 0.007 | 0.014 | 1.000 | 1.000 | 0.000 | 0.022 |
| 4 | 3 | 0.497±0.008 | 1.000±0.000 | 0.245 | 0.043 | 0.438 | 1.000 | 0.310 | 0.040 |
| 5 | 4 | 0.969±0.062 | 1.000±0.000 | 0.009 | 0.029 | 1.000 | 1.000 | 0.000 | 0.040 |
| 6 | 5 | 0.914±0.158 | 1.000±0.000 | 0.031 | 0.022 | 0.438 | 1.000 | 0.310 | 0.134 |
| 7 | 6 | 0.800±0.447 | 0.800±0.447 | 0.048 | 0.035 | 0.000 | 0.000 | 0.000 | 0.014 |
| **Mean** | | **0.684 ± 0.292** | **0.835 ± 0.284** | **0.096** | **0.031** | **0.655** | **0.875** | **0.124** | **0.039** |

## 3. Root-Cause Top-1 Accuracy

Fraction of steady-fault snapshots where the faulted node has the highest score.
Ties are treated as failure. Results are suggestive given ~13-14 steady snapshots per fold.

| Fold | Ep | Node | Delay | GNN RC1 (mean±std) | BL RC1 | GNN wins RC1? |
|------|----|------|-------|---------------------|--------|---------------|
| 0 | A | ratings | 200ms | 1.000±0.000 | 0.942 | ✓ |
| 1 | B | details | 100ms | 1.000±0.000 | 1.000 | ✗ |
| 2 | 1 | reviews | 100ms | 0.615±0.381 | 1.000 | ✗ |
| 3 | 2 | details | 50ms | 0.814±0.186 | 1.000 | ✗ |
| 4 | 3 | ratings | 100ms | 1.000±0.000 | 0.071 | ✓ |
| 5 | 4 | reviews | 200ms | 1.000±0.000 | 1.000 | ✗ |
| 6 | 5 | details | 200ms | 1.000±0.000 | 1.000 | ✗ |
| 7 | 6 | ratings | 50ms | 0.800±0.447 | 0.929 | ✗ |
| **Mean** | | | | **0.904 ± 0.146** | **0.868** | **2/8** |

## 4. Persistence Rule (3-of-4 Snapshots Above Threshold)

Flag a node only if it exceeded the threshold in ≥ 3 of the last 4 snapshots.

| Fold | GNN P (persist) | GNN R (persist) | GNN FPR (persist) | BL P (persist) | BL R (persist) | BL FPR (persist) |
|------|-----------------|-----------------|-------------------|----------------|----------------|------------------|
| 0 | 0.692 | 0.962 | 0.195 | 0.500 | 0.962 | 0.321 |
| 1 | 1.000 | 0.833 | 0.000 | 1.000 | 0.833 | 0.000 |
| 2 | 0.401 | 0.508 | 0.164 | 1.000 | 0.846 | 0.000 |
| 3 | 0.200 | 0.171 | 0.000 | 1.000 | 0.857 | 0.000 |
| 4 | 0.500 | 0.857 | 0.207 | 0.429 | 0.857 | 0.276 |
| 5 | 1.000 | 0.893 | 0.000 | 1.000 | 0.857 | 0.000 |
| 6 | 0.950 | 0.857 | 0.014 | 0.429 | 0.857 | 0.276 |
| 7 | 0.800 | 0.686 | 0.041 | 0.000 | 0.000 | 0.000 |
| **Mean** | **0.693** | **0.721** | **0.078** | **0.670** | **0.759** | **0.109** |

## 5. Win Count: GNN vs Baseline

| Metric | GNN wins (out of 8 folds) |
|--------|-----------------------------------|
| Average Precision | 2/8 |
| Root-Cause Top-1 | 2/8 |

> Results are suggestive, not conclusive. Each fold has approximately 13–14 steady-fault positive node readings. With only ~14 positives per fold, metrics can swing substantially from a single misclassification.

## Detection-Delay Note (Lag Period)

Snapshots in [start, start+90s) are in the lag period where the 1-minute Prometheus rate window has not yet fully captured the injected delay. These snapshots are **excluded** from both training and evaluation. A production system could still produce alerts during this period, but they are not counted here. Approximate counts:

- Episode A (ratings 200ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window
- Episode B (details 100ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window
- Episode 1 (reviews 100ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window
- Episode 2 (details 50ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window
- Episode 3 (ratings 100ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window
- Episode 4 (reviews 200ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window
- Episode 5 (details 200ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window
- Episode 6 (ratings 50ms): ~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window

## Assumptions, Deviations, and Limitations

1. **No hyperparameter tuning per fold.** pos_weight, lr, epochs, and architecture are fixed from Experiment B v2 to avoid fold-level overfitting.
2. **Validation-based thresholding.** Both GNN and baseline thresholds are chosen on the next episode's window (k+1 mod 8). When the val episode has 0 positive node readings in its test window (can happen for legacy episodes or small windows), the threshold falls back to the training set. This is flagged in per-fold output.
3. **Snapshot timestamp granularity.** Prometheus polls every 15 s. Lag/steady boundary at +90 s may miss the first qualifying snapshot by up to 14 s.
4. **Only log1p(in_latency_p95) used as baseline score.** Other features (out-latency, error rate) are not tested as baseline scorers. Not tested.
5. **Root-cause top-1 with 4 nodes.** Random chance = 25%. Ties are failures. With ~13-14 snapshots per fold, this metric has high variance.
6. **Persistence rule resets** at fold boundary (no history carried across folds).
7. **latency_mean not included** in the 8-fold LOEO experiment (available only for new episodes). Used only in the optional 6-fold extension.
8. **No causal topology analysis** performed. Whether node position in the service graph explains detection difficulty is not tested here.
9. **Legacy episode A** (ratings, 886 s duration) has 52 steady snapshots vs. ~13-14 for new episodes. This imbalance is reflected in per-fold positive counts.

---
*Generated by loeo_eval.py*


---

# Optional: 6-Fold LOEO — New Episodes Only (7 Features, incl. latency_mean)

log1p(latency_mean) is added as a 7th node feature. Available only for the 6 new episodes. Baseline score remains in_lat (feature 2); the 7th feature only affects the GNN.

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

> These results are suggestive. Adding latency_mean as a feature changes the input distribution but uses the same fixed architecture. Whether latency_mean improves detection is not conclusive from this small dataset.
