"""
loeo_eval.py  --  Leave-One-Episode-Out (LOEO) cross-validation
================================================================
8 folds (one per fault episode). For each fold k:

  test       = snapshots in [start_k - 60s, end_k + 90s]
  validation = snapshots in [start_(k+1 mod 8) - 60s, end_(k+1 mod 8) + 90s]
  train      = everything else, minus snapshots within 120s before/after
               the test or val windows (leakage buffer).
               Lag and recovery phases are excluded from train & eval.

Models (fixed config, no hyperparameter tuning per fold):
  GNN      : RiskGNN (2x GCNConv, hidden=16, LeakyReLU), pos_weight=1,
             Adam lr=0.01, 100 epochs, 5 seeds.
  Baseline : in_lat score = log1p(in_latency). Threshold chosen on val
             episode by best-F1 (same as GNN threshold).

Metrics:
  1. AP (average precision) and AUROC  -- threshold-free
  2. Precision / Recall / FPR          -- at chosen threshold
  3. Root-cause top-1 accuracy         -- faulted node highest score?
  4. Persistence rule (3-of-4)         -- redo metric 2 after smoothing
  5. Win count GNN vs baseline         -- AP and root-cause top-1

Results saved to: results_loeo.md  and  results_loeo.csv

Assumptions / deviations / limitations listed at bottom of this file.
"""

import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import torch
import torch.nn as nn

# Local modules
from build_dataset_v2 import (
    ALL_EPISODES, NODE_VOCAB, NODE_INDEX,
    load_all_records, build_normal_holdout_ts,
    record_to_graph, print_episode_counts,
    LAG_DURATION, RECOVERY_BUFFER, LEAKAGE_BUFFER,
)
from model import RiskGNN

# ─────────────────────────────────────────────────────────────────────────────
# Config (fixed -- no tuning)
# ─────────────────────────────────────────────────────────────────────────────
SEEDS   = [42, 7, 13, 99, 2024]
EPOCHS  = 100
LR      = 0.01
POS_WEIGHT = 1.0
NUM_FEATURES = 6
IN_LAT_IDX   = 2      # feature index of log1p(in_latency)
TEST_PRE_BUFFER  = timedelta(seconds=60)
RESULT_MD  = os.environ.get("LOEO_RESULT_MD", "results_loeo.md")
RESULT_CSV = os.environ.get("LOEO_RESULT_CSV", "results_loeo.csv")

os.makedirs("models", exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Metric helpers (manual -- no sklearn)
# ─────────────────────────────────────────────────────────────────────────────

def average_precision(probs, labels):
    """Trapezoidal area under PR curve. Both are flat lists."""
    if sum(labels) == 0:
        return 0.0
    paired = sorted(zip(probs, labels), key=lambda x: -x[0])
    tp = fp = 0
    total_pos = sum(labels)
    prev_rec = 0.0; prev_prec = 1.0; ap = 0.0
    for prob, lbl in paired:
        if lbl == 1: tp += 1
        else:        fp += 1
        prec = tp / (tp + fp)
        rec  = tp / total_pos
        ap  += (rec - prev_rec) * (prec + prev_prec) / 2.0
        prev_rec = rec; prev_prec = prec
    return ap


def auroc(probs, labels):
    """Mann-Whitney U statistic (exact AUROC)."""
    pos = [p for p, l in zip(probs, labels) if l == 1]
    neg = [p for p, l in zip(probs, labels) if l == 0]
    if not pos or not neg:
        return float("nan")
    count = sum(1 for p in pos for n in neg if p > n) + \
            0.5 * sum(1 for p in pos for n in neg if p == n)
    return count / (len(pos) * len(neg))


def best_threshold_f1(probs, labels):
    """Return (threshold, f1) that maximises F1."""
    if sum(labels) == 0:
        return 0.5, 0.0
    sorted_p = sorted(set(probs))
    lo, hi = sorted_p[0], sorted_p[-1]
    step = (hi - lo) / 50 if hi > lo else 0.01
    candidates = [lo + i * step for i in range(51)]
    best_f1, best_t = -1.0, 0.5
    for t in candidates:
        tp = fp = fn = 0
        for p, l in zip(probs, labels):
            pred = 1 if p > t else 0
            if pred and l:     tp += 1
            elif pred and not l: fp += 1
            elif not pred and l: fn += 1
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2*prec*rec/(prec+rec) if (prec+rec) > 0 else 0.0
        if f1 > best_f1:
            best_f1 = f1; best_t = t
    return best_t, best_f1


def eval_at_threshold(probs, labels, thresh):
    tp = fp = fn = tn = 0
    for p, l in zip(probs, labels):
        pred = 1 if p > thresh else 0
        if pred and l:         tp += 1
        elif pred and not l:   fp += 1
        elif not pred and l:   fn += 1
        else:                  tn += 1
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr  = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    return tp, fp, fn, tn, prec, rec, fpr


def mean_std(lst):
    lst = [x for x in lst if x == x]  # drop NaN
    if not lst: return float("nan"), float("nan")
    m = sum(lst) / len(lst)
    v = sum((x - m)**2 for x in lst) / max(len(lst) - 1, 1)
    return m, math.sqrt(v)


# ─────────────────────────────────────────────────────────────────────────────
# Persistence rule helper
# ─────────────────────────────────────────────────────────────────────────────

def apply_persistence(records_in_order, probs_per_record, threshold, window=4, min_above=3):
    """
    For each snapshot (in chronological order), flag only if the node score
    exceeded threshold in >= min_above of the last `window` snapshots.
    Returns list of (persistent_flag, label) per node per snapshot.
    Each element of probs_per_record: list of (prob, label, node_name).
    """
    # node -> deque of last `window` binary flags
    from collections import deque
    node_history = {n: deque(maxlen=window) for n in NODE_VOCAB}
    results = []
    for snap_entries in probs_per_record:
        snap_result = []
        for prob, lbl, node in snap_entries:
            above = 1 if prob > threshold else 0
            node_history[node].append(above)
            persistent = int(sum(node_history[node]) >= min_above)
            snap_result.append((persistent, lbl))
        results.extend(snap_result)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Root-cause top-1
# ─────────────────────────────────────────────────────────────────────────────

def root_cause_top1(graphs_or_records, score_fn, fault_node):
    """
    For each snapshot in graphs_or_records (already filtered to steady fault):
      score_fn(g) -> list of 4 floats in NODE_VOCAB order
    Returns fraction where faulted node has the highest score.
    Ties broken as failure.
    """
    correct = total = 0
    for g in graphs_or_records:
        scores = score_fn(g)
        best_idx = max(range(len(NODE_VOCAB)), key=lambda i: scores[i])
        if NODE_VOCAB[best_idx] == fault_node:
            correct += 1
        total += 1
    return correct / total if total > 0 else float("nan")


# ─────────────────────────────────────────────────────────────────────────────
# GNN helpers
# ─────────────────────────────────────────────────────────────────────────────

def train_gnn(train_graphs, seed):
    torch.manual_seed(seed)
    model = RiskGNN(num_node_features=NUM_FEATURES)
    opt   = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([POS_WEIGHT]))
    model.train()
    for _ in range(EPOCHS):
        for g in train_graphs:
            opt.zero_grad()
            loss = loss_fn(model(g.x, g.edge_index), g.y)
            loss.backward()
            opt.step()
    return model


def gnn_probs(model, graphs):
    """Return flat (probs, labels) across all graphs."""
    model.eval()
    probs_all = []; labels_all = []
    with torch.no_grad():
        for g in graphs:
            p = torch.sigmoid(model(g.x, g.edge_index)).tolist()
            probs_all.extend(p)
            labels_all.extend(g.y.tolist())
    return probs_all, labels_all


def gnn_probs_per_snap(model, graphs):
    """Return list of per-snapshot [(prob, label, node_name), ...] for persistence."""
    model.eval()
    result = []
    with torch.no_grad():
        for g in graphs:
            p = torch.sigmoid(model(g.x, g.edge_index)).tolist()
            l = g.y.tolist()
            result.append([(p[i], l[i], NODE_VOCAB[i]) for i in range(len(NODE_VOCAB))])
    return result


def gnn_scores_for_graph(model, g):
    model.eval()
    with torch.no_grad():
        return torch.sigmoid(model(g.x, g.edge_index)).tolist()


# ─────────────────────────────────────────────────────────────────────────────
# Baseline helpers
# ─────────────────────────────────────────────────────────────────────────────

def baseline_probs(graphs):
    """Score = in_lat (feature index IN_LAT_IDX). Returns flat (scores, labels)."""
    scores = []; labels = []
    for g in graphs:
        scores.extend(g.x[:, IN_LAT_IDX].tolist())
        labels.extend(g.y.tolist())
    return scores, labels


def baseline_probs_per_snap(graphs):
    result = []
    for g in graphs:
        s = g.x[:, IN_LAT_IDX].tolist()
        l = g.y.tolist()
        result.append([(s[i], l[i], NODE_VOCAB[i]) for i in range(len(NODE_VOCAB))])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# LOEO split logic
# ─────────────────────────────────────────────────────────────────────────────

def build_loeo_split(all_records, fold_k, holdout_ts):
    """
    Returns (train_graphs, val_graphs, test_graphs, steady_test_graphs)
    for fold k.
    Excludes lag, recovery, and holdout from train; excludes lag and recovery
    from val/test evaluation.
    """
    ep_test = ALL_EPISODES[fold_k]
    ep_val  = ALL_EPISODES[(fold_k + 1) % len(ALL_EPISODES)]

    def episode_window(ep):
        return ep["start"] - TEST_PRE_BUFFER, ep["end"] + RECOVERY_BUFFER

    test_lo, test_hi = episode_window(ep_test)
    val_lo,  val_hi  = episode_window(ep_val)

    train_graphs = []
    val_graphs   = []
    test_graphs  = []
    steady_test  = []

    for r in all_records:
        ts  = datetime.fromisoformat(r["timestamp"])
        phs = r["phase"]

        # Exclude lag and recovery everywhere
        if phs in ("lag", "recovery"):
            continue
        # Exclude holdout from train
        if r["timestamp"] in holdout_ts:
            # holdout goes into neither train nor any fold split -- evaluated separately
            continue

        in_test = test_lo <= ts <= test_hi
        in_val  = val_lo  <= ts <= val_hi

        # Leakage buffer: within 120 s of test or val window -> excluded from train
        near_test = (test_lo - LEAKAGE_BUFFER) <= ts <= (test_hi + LEAKAGE_BUFFER)
        near_val  = (val_lo  - LEAKAGE_BUFFER) <= ts <= (val_hi  + LEAKAGE_BUFFER)

        g = record_to_graph(r)
        if g is None:
            continue

        if in_test:
            test_graphs.append(g)
            if phs == "steady" and r["episode_id"] == ep_test["episode_id"]:
                steady_test.append(g)
        elif in_val:
            val_graphs.append(g)
        elif not near_test and not near_val:
            train_graphs.append(g)

    return train_graphs, val_graphs, test_graphs, steady_test


# ─────────────────────────────────────────────────────────────────────────────
# Holdout FPR
# ─────────────────────────────────────────────────────────────────────────────

def eval_holdout_fpr(all_records, holdout_ts, score_fn_or_none, threshold, use_baseline=False):
    """
    Returns FPR on normal-only holdout.
    score_fn_or_none: callable(graph) -> list[float] for GNN; None to use in_lat.
    """
    fp = tn = 0
    for r in all_records:
        if r["timestamp"] not in holdout_ts:
            continue
        g = record_to_graph(r)
        if g is None:
            continue
        if use_baseline:
            scores = g.x[:, IN_LAT_IDX].tolist()
        else:
            scores = score_fn_or_none(g)
        for s in scores:
            if s > threshold: fp += 1
            else:             tn += 1
    return fp / (fp + tn) if (fp + tn) > 0 else float("nan")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOEO LOOP
# ─────────────────────────────────────────────────────────────────────────────

def run_loeo():
    print("=" * 70)
    print("MeshHeal AI  --  LOEO Cross-Validation (8 folds)")
    print("=" * 70)

    print("\nLoading all records ...")
    all_records = load_all_records()
    holdout_ts  = build_normal_holdout_ts(all_records)

    print_episode_counts(all_records, holdout_ts)

    # Load holdout graphs once
    holdout_graphs = []
    for r in all_records:
        if r["timestamp"] in holdout_ts:
            g = record_to_graph(r)
            if g: holdout_graphs.append(g)
    print(f"Normal-only holdout: {len(holdout_graphs)} graphs\n")

    # Per-fold result storage
    fold_results = []  # list of dicts

    for fold_k in range(len(ALL_EPISODES)):
        ep = ALL_EPISODES[fold_k]
        ep_val = ALL_EPISODES[(fold_k + 1) % len(ALL_EPISODES)]
        print(f"\n{'─'*70}")
        print(f"FOLD {fold_k}  |  test=ep {ep['episode_id']} ({ep['node']} {ep['delay_ms']}ms)"
              f"  val=ep {ep_val['episode_id']} ({ep_val['node']} {ep_val['delay_ms']}ms)")

        train_g, val_g, test_g, steady_test_g = build_loeo_split(
            all_records, fold_k, holdout_ts)

        n_train_pos = sum(int(g.y.sum()) for g in train_g)
        n_test_pos  = sum(int(g.y.sum()) for g in test_g)
        n_val_pos   = sum(int(g.y.sum()) for g in val_g)
        print(f"  train={len(train_g)} graphs ({n_train_pos} pos)  "
              f"val={len(val_g)} graphs ({n_val_pos} pos)  "
              f"test={len(test_g)} graphs ({n_test_pos} pos)  "
              f"steady_test={len(steady_test_g)}")

        if not train_g:
            print("  SKIP: no training data for this fold.")
            continue
        if not test_g:
            print("  SKIP: no test data for this fold.")
            continue

        # ── Baseline ──────────────────────────────────────────────────────
        # Threshold chosen on validation by best F1
        bl_val_scores, bl_val_labels = baseline_probs(val_g)
        if sum(bl_val_labels) == 0:
            # val has no positives (can happen for legacy eps with few steady snaps in window)
            # Fall back: use training set positives to choose threshold
            print("  NOTE: val has 0 positives; baseline threshold chosen on train set.")
            bl_val_scores, bl_val_labels = baseline_probs(train_g)

        bl_thresh, bl_val_f1 = best_threshold_f1(bl_val_scores, bl_val_labels)
        bl_test_scores, bl_test_labels = baseline_probs(test_g)
        bl_ap    = average_precision(bl_test_scores, bl_test_labels)
        bl_auroc = auroc(bl_test_scores, bl_test_labels)
        bl_tp, bl_fp, bl_fn, bl_tn, bl_prec, bl_rec, bl_fpr_test = eval_at_threshold(
            bl_test_scores, bl_test_labels, bl_thresh)
        bl_holdout_fpr = eval_holdout_fpr(all_records, holdout_ts, None, bl_thresh,
                                          use_baseline=True)
        # Root-cause top-1
        bl_rc1 = root_cause_top1(
            steady_test_g,
            lambda g: g.x[:, IN_LAT_IDX].tolist(),
            ep["node"],
        )

        print(f"  Baseline: thresh={bl_thresh:.4f}  val_F1={bl_val_f1:.3f}  "
              f"AP={bl_ap:.3f}  AUROC={bl_auroc:.3f}  "
              f"P={bl_prec:.3f}  R={bl_rec:.3f}  FPR_test={bl_fpr_test:.3f}  "
              f"FPR_holdout={bl_holdout_fpr:.3f}  RC1={bl_rc1:.3f}")

        # Persistence for baseline
        bl_per_snap = baseline_probs_per_snap(test_g)
        bl_pers_flat = apply_persistence(test_g, bl_per_snap, bl_thresh)
        if bl_pers_flat:
            bl_pers_flags = [x[0] for x in bl_pers_flat]
            bl_pers_lbls  = [x[1] for x in bl_pers_flat]
            _, _, _, _, bl_pers_prec, bl_pers_rec, bl_pers_fpr = eval_at_threshold(
                [float(f) for f in bl_pers_flags], bl_pers_lbls, 0.5)
        else:
            bl_pers_prec = bl_pers_rec = bl_pers_fpr = float("nan")

        # ── GNN (5 seeds) ─────────────────────────────────────────────────
        gnn_seed_ap    = []; gnn_seed_auroc = []
        gnn_seed_prec  = []; gnn_seed_rec   = []; gnn_seed_fpr_test = []
        gnn_seed_holdout_fpr = []
        gnn_seed_rc1   = []
        gnn_seed_thresh = []
        gnn_seed_pers_prec = []; gnn_seed_pers_rec = []; gnn_seed_pers_fpr = []

        for seed in SEEDS:
            model = train_gnn(train_g, seed)

            # Threshold on validation
            gnn_val_p, gnn_val_l = gnn_probs(model, val_g)
            if sum(gnn_val_l) == 0:
                # No positives in val -- choose threshold on train
                gnn_val_p, gnn_val_l = gnn_probs(model, train_g)
            thresh, _ = best_threshold_f1(gnn_val_p, gnn_val_l)

            # Collapse check
            gnn_tp, gnn_tl = gnn_probs(model, test_g)
            prob_std = torch.tensor(gnn_tp).std().item()
            if prob_std < 0.01:
                print(f"    Seed {seed}: COLLAPSE (std={prob_std:.4f}) -- skipped")
                continue

            ap_val    = average_precision(gnn_tp, gnn_tl)
            auroc_val = auroc(gnn_tp, gnn_tl)
            tp_, fp_, fn_, tn_, prec_, rec_, fpr_ = eval_at_threshold(gnn_tp, gnn_tl, thresh)

            holdout_fpr = eval_holdout_fpr(
                all_records, holdout_ts,
                lambda g, m=model: gnn_scores_for_graph(m, g),
                thresh,
            )

            # Root-cause top-1
            rc1 = root_cause_top1(
                steady_test_g,
                lambda g, m=model: gnn_scores_for_graph(m, g),
                ep["node"],
            )

            # Persistence
            gnn_per_snap = gnn_probs_per_snap(model, test_g)
            gnn_pers_flat = apply_persistence(test_g, gnn_per_snap, thresh)
            if gnn_pers_flat:
                gp_flags = [float(x[0]) for x in gnn_pers_flat]
                gp_lbls  = [x[1] for x in gnn_pers_flat]
                _, _, _, _, gp_prec, gp_rec, gp_fpr = eval_at_threshold(gp_flags, gp_lbls, 0.5)
            else:
                gp_prec = gp_rec = gp_fpr = float("nan")

            gnn_seed_ap.append(ap_val)
            gnn_seed_auroc.append(auroc_val)
            gnn_seed_prec.append(prec_)
            gnn_seed_rec.append(rec_)
            gnn_seed_fpr_test.append(fpr_)
            gnn_seed_holdout_fpr.append(holdout_fpr)
            gnn_seed_rc1.append(rc1)
            gnn_seed_thresh.append(thresh)
            gnn_seed_pers_prec.append(gp_prec)
            gnn_seed_pers_rec.append(gp_rec)
            gnn_seed_pers_fpr.append(gp_fpr)

        if not gnn_seed_ap:
            print("  GNN: all seeds collapsed -- skipping fold.")
            continue

        gnn_ap_m,   gnn_ap_s   = mean_std(gnn_seed_ap)
        gnn_au_m,   gnn_au_s   = mean_std(gnn_seed_auroc)
        gnn_pr_m,   gnn_pr_s   = mean_std(gnn_seed_prec)
        gnn_re_m,   gnn_re_s   = mean_std(gnn_seed_rec)
        gnn_fpr_m,  gnn_fpr_s  = mean_std(gnn_seed_fpr_test)
        gnn_hfpr_m, gnn_hfpr_s = mean_std(gnn_seed_holdout_fpr)
        gnn_rc1_m,  gnn_rc1_s  = mean_std(gnn_seed_rc1)
        gnn_thresh_m = sum(gnn_seed_thresh)/len(gnn_seed_thresh)
        gnn_ppr_m, gnn_ppr_s = mean_std(gnn_seed_pers_prec)
        gnn_pre_m, gnn_pre_s = mean_std(gnn_seed_pers_rec)
        gnn_pfr_m, gnn_pfr_s = mean_std(gnn_seed_pers_fpr)

        print(f"  GNN:      thresh={gnn_thresh_m:.4f} (mean)  "
              f"AP={gnn_ap_m:.3f}±{gnn_ap_s:.3f}  AUROC={gnn_au_m:.3f}±{gnn_au_s:.3f}  "
              f"P={gnn_pr_m:.3f}±{gnn_pr_s:.3f}  R={gnn_re_m:.3f}±{gnn_re_s:.3f}  "
              f"FPR_test={gnn_fpr_m:.3f}  FPR_holdout={gnn_hfpr_m:.3f}  "
              f"RC1={gnn_rc1_m:.3f}±{gnn_rc1_s:.3f}")

        wins_ap  = 1 if gnn_ap_m  > bl_ap  else 0
        wins_rc1 = 1 if gnn_rc1_m > bl_rc1 else 0

        fold_results.append({
            "fold": fold_k,
            "ep_id": ep["episode_id"],
            "node": ep["node"],
            "delay_ms": ep["delay_ms"],
            "n_train": len(train_g),
            "n_val": len(val_g),
            "n_test": len(test_g),
            "n_steady_test": len(steady_test_g),
            # Baseline
            "bl_thresh": bl_thresh,
            "bl_ap": bl_ap,
            "bl_auroc": bl_auroc,
            "bl_prec": bl_prec,
            "bl_rec": bl_rec,
            "bl_fpr_test": bl_fpr_test,
            "bl_fpr_holdout": bl_holdout_fpr,
            "bl_rc1": bl_rc1,
            "bl_pers_prec": bl_pers_prec,
            "bl_pers_rec": bl_pers_rec,
            "bl_pers_fpr": bl_pers_fpr,
            # GNN (means)
            "gnn_thresh_mean": gnn_thresh_m,
            "gnn_ap_mean": gnn_ap_m, "gnn_ap_std": gnn_ap_s,
            "gnn_auroc_mean": gnn_au_m, "gnn_auroc_std": gnn_au_s,
            "gnn_prec_mean": gnn_pr_m, "gnn_prec_std": gnn_pr_s,
            "gnn_rec_mean": gnn_re_m, "gnn_rec_std": gnn_re_s,
            "gnn_fpr_test_mean": gnn_fpr_m, "gnn_fpr_test_std": gnn_fpr_s,
            "gnn_fpr_holdout_mean": gnn_hfpr_m, "gnn_fpr_holdout_std": gnn_hfpr_s,
            "gnn_rc1_mean": gnn_rc1_m, "gnn_rc1_std": gnn_rc1_s,
            "gnn_pers_prec_mean": gnn_ppr_m, "gnn_pers_rec_mean": gnn_pre_m,
            "gnn_pers_fpr_mean": gnn_pfr_m,
            # Win flags
            "gnn_wins_ap": wins_ap,
            "gnn_wins_rc1": wins_rc1,
        })

    return fold_results, holdout_ts


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

def fmt(v, decimals=3):
    if v != v: return "nan"
    return f"{v:.{decimals}f}"


def write_csv(fold_results):
    if not fold_results:
        return
    with open(RESULT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fold_results[0].keys()))
        writer.writeheader()
        writer.writerows(fold_results)
    print(f"\nRaw per-fold numbers saved to {RESULT_CSV}")


def write_markdown(fold_results):
    if not fold_results:
        print("No fold results to report.")
        return

    wins_ap  = sum(r["gnn_wins_ap"]  for r in fold_results)
    wins_rc1 = sum(r["gnn_wins_rc1"] for r in fold_results)
    n_folds  = len(fold_results)

    def col_mean_std(key_m, key_s=None):
        vals = [r[key_m] for r in fold_results if r[key_m] == r[key_m]]
        m, s = mean_std(vals)
        if key_s:
            return f"{fmt(m)} ± {fmt(s)}"
        return fmt(m)

    lines = []
    A = lines.append

    A("# MeshHeal AI — LOEO Cross-Validation Results")
    A("")
    A("## Experiment Setup")
    A("")
    A("| Parameter | Value |")
    A("|-----------|-------|")
    A(f"| Folds | 8 (leave-one-episode-out) |")
    A(f"| Test window | [episode_start − 60 s, episode_end + 90 s] |")
    A(f"| Val window | same rule applied to next episode (k+1 mod 8) |")
    A(f"| Leakage buffer | 120 s before/after test and val windows removed from train |")
    A(f"| Lag exclusion | [start, start+90 s) excluded from all splits |")
    A(f"| Recovery exclusion | (end, end+90 s] excluded from all splits |")
    A(f"| GNN architecture | 2×GCNConv, hidden=16, LeakyReLU(0.1), Linear→1 |")
    A(f"| GNN pos_weight | {POS_WEIGHT} (fixed, no tuning) |")
    A(f"| GNN epochs | {EPOCHS} |")
    A(f"| GNN seeds | {SEEDS} |")
    A(f"| Baseline | in_lat score = log1p(in_latency_p95) |")
    A(f"| Threshold selection | val episode, best F1 |")
    A(f"| Normal holdout | latest 25% of pure-normal snapshots (never in train) |")
    A(f"| Persistence rule | flag only if above threshold in ≥3 of last 4 snapshots |")
    A("")

    A("## Per-Episode Counts")
    A("")
    A("| Fold | Ep | Node | Delay | Lag | Steady | Recovery |")
    A("|------|----|------|-------|-----|--------|----------|")
    for ep in ALL_EPISODES:
        fi = ep["fold_index"]
        r = next((x for x in fold_results if x["fold"] == fi), None)
        if r:
            A(f"| {fi} | {ep['episode_id']} | {ep['node']} | {ep['delay_ms']}ms | "
              f"(excl) | {r['n_steady_test']} steady in test | (excl) |")
    A("")
    A("> Lag and recovery periods are excluded from training and evaluation. "
      "They are reported separately as a detection-delay note (see below).")
    A("")

    A("## 1. Threshold-Free Metrics (AP and AUROC)")
    A("")
    A("| Fold | Ep | Node | Delay | GNN AP (mean±std) | GNN AUROC (mean±std) | BL AP | BL AUROC | GNN wins AP? |")
    A("|------|----|------|-------|-------------------|----------------------|-------|----------|--------------|")
    for r in fold_results:
        A(f"| {r['fold']} | {r['ep_id']} | {r['node']} | {r['delay_ms']}ms "
          f"| {fmt(r['gnn_ap_mean'])}±{fmt(r['gnn_ap_std'])} "
          f"| {fmt(r['gnn_auroc_mean'])}±{fmt(r['gnn_auroc_std'])} "
          f"| {fmt(r['bl_ap'])} | {fmt(r['bl_auroc'])} "
          f"| {'✓' if r['gnn_wins_ap'] else '✗'} |")
    A(f"| **Mean** | | | | **{col_mean_std('gnn_ap_mean','gnn_ap_std')}** "
      f"| **{col_mean_std('gnn_auroc_mean','gnn_auroc_std')}** "
      f"| **{col_mean_std('bl_ap')}** | **{col_mean_std('bl_auroc')}** "
      f"| **{wins_ap}/{n_folds}** |")
    A("")

    A("## 2. At-Threshold Metrics (Precision / Recall / FPR)")
    A("")
    A("Threshold chosen per fold on the validation episode by best F1.")
    A("")
    A("| Fold | Ep | GNN P | GNN R | GNN FPR(test) | GNN FPR(holdout) | BL P | BL R | BL FPR(test) | BL FPR(holdout) |")
    A("|------|----|-------|-------|----------------|------------------|------|------|--------------|-----------------|")
    for r in fold_results:
        A(f"| {r['fold']} | {r['ep_id']} "
          f"| {fmt(r['gnn_prec_mean'])}±{fmt(r['gnn_prec_std'])} "
          f"| {fmt(r['gnn_rec_mean'])}±{fmt(r['gnn_rec_std'])} "
          f"| {fmt(r['gnn_fpr_test_mean'])} "
          f"| {fmt(r['gnn_fpr_holdout_mean'])} "
          f"| {fmt(r['bl_prec'])} | {fmt(r['bl_rec'])} "
          f"| {fmt(r['bl_fpr_test'])} | {fmt(r['bl_fpr_holdout'])} |")
    A(f"| **Mean** | | "
      f"**{col_mean_std('gnn_prec_mean','gnn_prec_std')}** "
      f"| **{col_mean_std('gnn_rec_mean','gnn_rec_std')}** "
      f"| **{col_mean_std('gnn_fpr_test_mean')}** "
      f"| **{col_mean_std('gnn_fpr_holdout_mean')}** "
      f"| **{col_mean_std('bl_prec')}** "
      f"| **{col_mean_std('bl_rec')}** "
      f"| **{col_mean_std('bl_fpr_test')}** "
      f"| **{col_mean_std('bl_fpr_holdout')}** |")
    A("")

    A("## 3. Root-Cause Top-1 Accuracy")
    A("")
    A("Fraction of steady-fault snapshots where the faulted node has the highest score.")
    A("Ties are treated as failure. Results are suggestive given ~13-14 steady snapshots per fold.")
    A("")
    A("| Fold | Ep | Node | Delay | GNN RC1 (mean±std) | BL RC1 | GNN wins RC1? |")
    A("|------|----|------|-------|---------------------|--------|---------------|")
    for r in fold_results:
        A(f"| {r['fold']} | {r['ep_id']} | {r['node']} | {r['delay_ms']}ms "
          f"| {fmt(r['gnn_rc1_mean'])}±{fmt(r['gnn_rc1_std'])} "
          f"| {fmt(r['bl_rc1'])} "
          f"| {'✓' if r['gnn_wins_rc1'] else '✗'} |")
    A(f"| **Mean** | | | | **{col_mean_std('gnn_rc1_mean','gnn_rc1_std')}** "
      f"| **{col_mean_std('bl_rc1')}** | **{wins_rc1}/{n_folds}** |")
    A("")

    A("## 4. Persistence Rule (3-of-4 Snapshots Above Threshold)")
    A("")
    A("Flag a node only if it exceeded the threshold in ≥ 3 of the last 4 snapshots.")
    A("")
    A("| Fold | GNN P (persist) | GNN R (persist) | GNN FPR (persist) | BL P (persist) | BL R (persist) | BL FPR (persist) |")
    A("|------|-----------------|-----------------|-------------------|----------------|----------------|------------------|")
    for r in fold_results:
        A(f"| {r['fold']} "
          f"| {fmt(r['gnn_pers_prec_mean'])} | {fmt(r['gnn_pers_rec_mean'])} | {fmt(r['gnn_pers_fpr_mean'])} "
          f"| {fmt(r['bl_pers_prec'])} | {fmt(r['bl_pers_rec'])} | {fmt(r['bl_pers_fpr'])} |")
    A(f"| **Mean** "
      f"| **{col_mean_std('gnn_pers_prec_mean')}** "
      f"| **{col_mean_std('gnn_pers_rec_mean')}** "
      f"| **{col_mean_std('gnn_pers_fpr_mean')}** "
      f"| **{col_mean_std('bl_pers_prec')}** "
      f"| **{col_mean_std('bl_pers_rec')}** "
      f"| **{col_mean_std('bl_pers_fpr')}** |")
    A("")

    A("## 5. Win Count: GNN vs Baseline")
    A("")
    A(f"| Metric | GNN wins (out of {n_folds} folds) |")
    A("|--------|-----------------------------------|")
    A(f"| Average Precision | {wins_ap}/{n_folds} |")
    A(f"| Root-Cause Top-1 | {wins_rc1}/{n_folds} |")
    A("")
    A("> Results are suggestive, not conclusive. Each fold has approximately 13–14 steady-fault "
      "positive node readings. With only ~14 positives per fold, metrics can swing substantially "
      "from a single misclassification.")
    A("")

    A("## Detection-Delay Note (Lag Period)")
    A("")
    A("Snapshots in [start, start+90s) are in the lag period where the 1-minute Prometheus "
      "rate window has not yet fully captured the injected delay. These snapshots are **excluded** "
      "from both training and evaluation. A production system could still produce alerts during "
      "this period, but they are not counted here. Approximate counts:")
    A("")
    for ep in ALL_EPISODES:
        A(f"- Episode {ep['episode_id']} ({ep['node']} {ep['delay_ms']}ms): "
          f"~5–6 lag snapshots ≈ 75–90 s of unaccounted detection window")
    A("")

    A("## Assumptions, Deviations, and Limitations")
    A("")
    A("1. **No hyperparameter tuning per fold.** pos_weight, lr, epochs, and architecture "
      "are fixed from Experiment B v2 to avoid fold-level overfitting.")
    A("2. **Validation-based thresholding.** Both GNN and baseline thresholds are chosen "
      "on the next episode's window (k+1 mod 8). When the val episode has 0 positive "
      "node readings in its test window (can happen for legacy episodes or small windows), "
      "the threshold falls back to the training set. This is flagged in per-fold output.")
    A("3. **Snapshot timestamp granularity.** Prometheus polls every 15 s. Lag/steady "
      "boundary at +90 s may miss the first qualifying snapshot by up to 14 s.")
    A("4. **Only log1p(in_latency_p95) used as baseline score.** Other features (out-latency, "
      "error rate) are not tested as baseline scorers. Not tested.")
    A("5. **Root-cause top-1 with 4 nodes.** Random chance = 25%. Ties are failures. "
      "With ~13-14 snapshots per fold, this metric has high variance.")
    A("6. **Persistence rule resets** at fold boundary (no history carried across folds).")
    A("7. **latency_mean not included** in the 8-fold LOEO experiment "
      "(available only for new episodes). Used only in the optional 6-fold extension.")
    A("8. **No causal topology analysis** performed. Whether node position in the service graph "
      "explains detection difficulty is not tested here.")
    A("9. **Legacy episode A** (ratings, 886 s duration) has 52 steady snapshots vs. ~13-14 "
      "for new episodes. This imbalance is reflected in per-fold positive counts.")
    A("")
    A("---")
    A(f"*Generated by loeo_eval.py*")

    with open(RESULT_MD, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Results markdown saved to {RESULT_MD}")


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL: 6-fold LOEO with latency_mean as 7th feature
# ─────────────────────────────────────────────────────────────────────────────

def run_loeo_6fold_with_mean():
    """
    Run LOEO on the 6 new episodes only, adding log1p(latency_mean) as a 7th feature.
    Results appended to results_loeo.md as a separate, clearly labeled section.
    """
    print("\n" + "=" * 70)
    print("OPTIONAL: 6-fold LOEO (new episodes only, 7 features incl. latency_mean)")
    print("=" * 70)

    from build_dataset_v2 import load_latency_mean
    mean_index_raw = load_latency_mean()
    if not mean_index_raw:
        print("latency_mean.jsonl not found or empty -- skipping optional experiment.")
        return

    new_eps = [ep for ep in ALL_EPISODES if ep["source"] == "fault_log"]
    if len(new_eps) != 6:
        print(f"Expected 6 new episodes, found {len(new_eps)} -- skipping.")
        return

    # Reassign fold indices for 6-fold
    for i, ep in enumerate(new_eps):
        ep["_six_fold_index"] = i

    all_records = load_all_records()
    holdout_ts  = build_normal_holdout_ts(all_records)

    # Build nearest-neighbour index (≤10s) from mean_index_raw.
    # snapshots.jsonl and latency_mean.jsonl are separate Prometheus queries;
    # their timestamps are offset ~3–7 s (confirmed: exact match rate = 0%).
    # NN-10s match rate = 100% for in-window snapshots.
    import bisect as _bisect
    _mean_times = sorted(datetime.fromisoformat(k) for k in mean_index_raw.keys())
    _mean_keys  = [k for k in sorted(mean_index_raw.keys(),
                                     key=lambda x: datetime.fromisoformat(x))]
    NN_MAX_GAP  = 10.0  # seconds

    def _nn_lookup(ts_str):
        """Return mean_lat dict for nearest neighbour within NN_MAX_GAP, else None."""
        ts  = datetime.fromisoformat(ts_str)
        idx = _bisect.bisect_left(_mean_times, ts)
        best_dt, best_key = None, None
        for ci in [max(0, idx-1), min(idx, len(_mean_times)-1)]:
            dt = abs((_mean_times[ci] - ts).total_seconds())
            if best_dt is None or dt < best_dt:
                best_dt, best_key = dt, _mean_keys[ci]
        if best_dt is not None and best_dt <= NN_MAX_GAP:
            return mean_index_raw[best_key]
        return None

    def record_to_graph_7f(record):
        """Returns 7-feature graph using NN-matched mean_lat, or None if no match."""
        extra = _nn_lookup(record["timestamp"])
        if extra is None:
            return None  # caller must drop this snapshot
        return record_to_graph(record, scale=True, extra_mean_lat=extra)

    def build_split_6fold(fold_k):
        ep_test = new_eps[fold_k]
        ep_val  = new_eps[(fold_k + 1) % len(new_eps)]

        def win(ep):
            return ep["start"] - TEST_PRE_BUFFER, ep["end"] + RECOVERY_BUFFER

        test_lo, test_hi = win(ep_test)
        val_lo,  val_hi  = win(ep_val)

        train_g = []; val_g = []; test_g = []; steady_test_g = []
        for r in all_records:
            ts  = datetime.fromisoformat(r["timestamp"])
            phs = r["phase"]
            if phs in ("lag", "recovery"):
                continue
            if r["timestamp"] in holdout_ts:
                continue

            in_test = test_lo <= ts <= test_hi
            in_val  = val_lo  <= ts <= val_hi
            near_test = (test_lo - LEAKAGE_BUFFER) <= ts <= (test_hi + LEAKAGE_BUFFER)
            near_val  = (val_lo  - LEAKAGE_BUFFER) <= ts <= (val_hi  + LEAKAGE_BUFFER)

            g = record_to_graph_7f(r)
            if g is None:
                continue

            if in_test:
                test_g.append(g)
                if phs == "steady" and r["episode_id"] == ep_test["episode_id"]:
                    steady_test_g.append(g)
            elif in_val:
                val_g.append(g)
            elif not near_test and not near_val:
                train_g.append(g)
        return train_g, val_g, test_g, steady_test_g

    fold6_results = []
    for fi in range(6):
        ep = new_eps[fi]
        ep_val = new_eps[(fi + 1) % 6]
        print(f"\nFOLD {fi}  test=ep {ep['episode_id']} ({ep['node']} {ep['delay_ms']}ms)  "
              f"val=ep {ep_val['episode_id']}")
        train_g, val_g, test_g, steady_test_g = build_split_6fold(fi)
        if not train_g or not test_g:
            print("  SKIP.")
            continue

        # GNN
        seed_ap = []; seed_rc1 = []
        for seed in SEEDS:
            torch.manual_seed(seed)
            model = RiskGNN(num_node_features=7)
            opt = torch.optim.Adam(model.parameters(), lr=LR)
            lf  = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([POS_WEIGHT]))
            model.train()
            for _ in range(EPOCHS):
                for g in train_g:
                    opt.zero_grad()
                    loss = lf(model(g.x, g.edge_index), g.y)
                    loss.backward(); opt.step()
            gv, gl = gnn_probs(model, val_g if sum(int(g.y.sum()) for g in val_g) > 0 else train_g)
            thresh, _ = best_threshold_f1(gv, gl)
            gt, gtl = gnn_probs(model, test_g)
            if torch.tensor(gt).std().item() < 0.01:
                continue
            seed_ap.append(average_precision(gt, gtl))
            seed_rc1.append(root_cause_top1(
                steady_test_g,
                lambda g, m=model: gnn_scores_for_graph(m, g),
                ep["node"],
            ))

        if not seed_ap:
            print("  GNN (7f): all collapsed.")
            continue

        m_ap,  s_ap  = mean_std(seed_ap)
        m_rc1, s_rc1 = mean_std(seed_rc1)

        # Baseline (score still = in_lat, feature idx 2)
        bl_s, bl_l = baseline_probs(test_g)
        bl_ap = average_precision(bl_s, bl_l)
        bl_rc1 = root_cause_top1(
            steady_test_g,
            lambda g: g.x[:, IN_LAT_IDX].tolist(),
            ep["node"],
        )
        print(f"  GNN(7f) AP={m_ap:.3f}±{s_ap:.3f}  RC1={m_rc1:.3f}±{s_rc1:.3f}  "
              f"BL_AP={bl_ap:.3f}  BL_RC1={bl_rc1:.3f}")
        fold6_results.append({
            "fold": fi, "ep_id": ep["episode_id"], "node": ep["node"],
            "delay_ms": ep["delay_ms"],
            "gnn7_ap_mean": m_ap, "gnn7_ap_std": s_ap,
            "gnn7_rc1_mean": m_rc1, "gnn7_rc1_std": s_rc1,
            "bl_ap": bl_ap, "bl_rc1": bl_rc1,
        })

    if fold6_results:
        wins_ap  = sum(1 for r in fold6_results if r["gnn7_ap_mean"] > r["bl_ap"])
        wins_rc1 = sum(1 for r in fold6_results if r["gnn7_rc1_mean"] > r["bl_rc1"])
        n = len(fold6_results)
        with open(RESULT_MD, "a") as f:
            f.write("\n\n---\n\n")
            f.write("# Optional: 6-Fold LOEO — New Episodes Only (7 Features, incl. latency_mean)\n\n")
            f.write("log1p(latency_mean) is added as a 7th node feature. "
                    "Available only for the 6 new episodes. "
                    "Baseline score remains in_lat (feature 2); the 7th feature only affects the GNN.\n\n")
            f.write("| Fold | Ep | Node | Delay | GNN AP (7f) | GNN RC1 (7f) | BL AP | BL RC1 |\n")
            f.write("|------|----|------|-------|-------------|--------------|-------|--------|\n")
            for r in fold6_results:
                f.write(f"| {r['fold']} | {r['ep_id']} | {r['node']} | {r['delay_ms']}ms "
                        f"| {fmt(r['gnn7_ap_mean'])}±{fmt(r['gnn7_ap_std'])} "
                        f"| {fmt(r['gnn7_rc1_mean'])}±{fmt(r['gnn7_rc1_std'])} "
                        f"| {fmt(r['bl_ap'])} | {fmt(r['bl_rc1'])} |\n")
            m_ap_all, s_ap_all = mean_std([r["gnn7_ap_mean"] for r in fold6_results])
            m_rc1_all, s_rc1_all = mean_std([r["gnn7_rc1_mean"] for r in fold6_results])
            m_bl_ap, _ = mean_std([r["bl_ap"] for r in fold6_results])
            m_bl_rc1, _ = mean_std([r["bl_rc1"] for r in fold6_results])
            f.write(f"| **Mean** | | | "
                    f"| **{fmt(m_ap_all)}±{fmt(s_ap_all)}** "
                    f"| **{fmt(m_rc1_all)}±{fmt(s_rc1_all)}** "
                    f"| **{fmt(m_bl_ap)}** | **{fmt(m_bl_rc1)}** |\n\n")
            f.write(f"GNN (7f) wins AP: {wins_ap}/{n}  |  RC1: {wins_rc1}/{n}\n\n")
            f.write("> These results are suggestive. Adding latency_mean as a feature "
                    "changes the input distribution but uses the same fixed architecture. "
                    "Whether latency_mean improves detection is not conclusive from this "
                    "small dataset.\n")
        print(f"\n6-fold results appended to {RESULT_MD}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    fold_results, holdout_ts = run_loeo()
    write_csv(fold_results)
    write_markdown(fold_results)
    # Optional: 6-fold with 7th feature
    run_loeo_6fold_with_mean()
    print("\nDone.")
