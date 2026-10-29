"""
loeo_diagnostics.py
====================
Diagnostics follow-up for the LOEO evaluation.
Must be run AFTER loeo_eval.py has completed and results_loeo.csv exists.

Writes all output to results_loeo_diagnostics.md.

Checks 1, 2, 5, 6 are answered purely from data + saved outputs + code inspection.
Checks 3 and 4 require a targeted retrain with the same seeds/config to collect
per-seed per-fold probability distributions (not saved by loeo_eval.py).
This script ANNOUNCES any retrain before doing it.
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

from build_dataset_v2 import (
    ALL_EPISODES, NODE_VOCAB, NODE_INDEX,
    load_all_records, build_normal_holdout_ts,
    record_to_graph, LAG_DURATION, RECOVERY_BUFFER, LEAKAGE_BUFFER,
)
from model import RiskGNN

# ─────────────────────────────────────────────────────────────────────────────
# Same config as loeo_eval.py  (copied verbatim for auditability)
# ─────────────────────────────────────────────────────────────────────────────
SEEDS        = [42, 7, 13, 99, 2024]
EPOCHS       = 100
LR           = 0.01
POS_WEIGHT   = 1.0
NUM_FEATURES = 6
IN_LAT_IDX   = 2
TEST_PRE_BUFFER = timedelta(seconds=60)
RESULT_CSV   = "results_loeo.csv"
OUT_MD       = "results_loeo_diagnostics.md"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def mean_std(lst):
    lst = [x for x in lst if x == x]
    if not lst: return float("nan"), float("nan")
    m = sum(lst)/len(lst)
    v = sum((x-m)**2 for x in lst)/max(len(lst)-1,1)
    return m, math.sqrt(v)

def fmt(v, d=3):
    if v != v: return "nan"
    return f"{v:.{d}f}"

def best_threshold_f1(probs, labels):
    if sum(labels) == 0:
        return 0.5, 0.0
    sorted_p = sorted(set(probs))
    lo, hi = sorted_p[0], sorted_p[-1]
    step = (hi - lo)/50 if hi > lo else 0.01
    candidates = [lo + i*step for i in range(51)]
    best_f1, best_t = -1.0, 0.5
    for t in candidates:
        tp = fp = fn = 0
        for p, l in zip(probs, labels):
            pred = 1 if p > t else 0
            if pred and l: tp += 1
            elif pred: fp += 1
            elif l: fn += 1
        prec = tp/(tp+fp) if (tp+fp) > 0 else 0.0
        rec  = tp/(tp+fn) if (tp+fn) > 0 else 0.0
        f1   = 2*prec*rec/(prec+rec) if (prec+rec) > 0 else 0.0
        if f1 > best_f1:
            best_f1 = f1; best_t = t
    return best_t, best_f1

def eval_at_threshold(probs, labels, thresh):
    tp = fp = fn = tn = 0
    for p, l in zip(probs, labels):
        pred = 1 if p > thresh else 0
        if pred and l: tp += 1
        elif pred: fp += 1
        elif l: fn += 1
        else: tn += 1
    prec = tp/(tp+fp) if (tp+fp) > 0 else 0.0
    rec  = tp/(tp+fn) if (tp+fn) > 0 else 0.0
    fpr  = fp/(fp+tn) if (fp+tn) > 0 else 0.0
    return tp, fp, fn, tn, prec, rec, fpr

def average_precision(probs, labels):
    if sum(labels) == 0: return 0.0
    paired = sorted(zip(probs, labels), key=lambda x: -x[0])
    tp = fp = 0; total_pos = sum(labels)
    prev_rec = 0.0; prev_prec = 1.0; ap = 0.0
    for prob, lbl in paired:
        if lbl == 1: tp += 1
        else: fp += 1
        prec = tp/(tp+fp); rec = tp/total_pos
        ap += (rec - prev_rec)*(prec + prev_prec)/2.0
        prev_rec = rec; prev_prec = prec
    return ap

def percentile(values, pct):
    if not values: return 0.0
    s = sorted(values)
    k = (len(s)-1) * pct / 100.0
    lo, hi = int(k), min(int(k)+1, len(s)-1)
    return s[lo] + (k-lo)*(s[hi]-s[lo])

# ─────────────────────────────────────────────────────────────────────────────
# Build LOEO splits (identical to loeo_eval.py)
# ─────────────────────────────────────────────────────────────────────────────

def build_loeo_split(all_records, fold_k, holdout_ts):
    ep_test = ALL_EPISODES[fold_k]
    ep_val  = ALL_EPISODES[(fold_k + 1) % len(ALL_EPISODES)]
    test_lo = ep_test["start"] - TEST_PRE_BUFFER
    test_hi = ep_test["end"]   + RECOVERY_BUFFER
    val_lo  = ep_val["start"]  - TEST_PRE_BUFFER
    val_hi  = ep_val["end"]    + RECOVERY_BUFFER

    train_graphs=[]; val_graphs=[]; test_graphs=[]; steady_test=[]
    # Also track phase-tagged test entries for FP breakdown
    test_tagged=[]  # list of (graph, phase_tag)

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
        g = record_to_graph(r)
        if g is None:
            continue
        if in_test:
            test_graphs.append(g)
            test_tagged.append((g, r))
            if phs == "steady" and r["episode_id"] == ep_test["episode_id"]:
                steady_test.append(g)
        elif in_val:
            val_graphs.append(g)
        elif not near_test and not near_val:
            train_graphs.append(g)

    return train_graphs, val_graphs, test_graphs, steady_test, test_tagged


def count_leakage_dropped(all_records, fold_k, holdout_ts):
    """Count non-lag/recovery records excluded by 120s leakage buffer for fold k."""
    ep_test = ALL_EPISODES[fold_k]
    ep_val  = ALL_EPISODES[(fold_k + 1) % len(ALL_EPISODES)]
    test_lo = ep_test["start"] - TEST_PRE_BUFFER
    test_hi = ep_test["end"]   + RECOVERY_BUFFER
    val_lo  = ep_val["start"]  - TEST_PRE_BUFFER
    val_hi  = ep_val["end"]    + RECOVERY_BUFFER

    dropped = 0
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
        if not in_test and not in_val and (near_test or near_val):
            dropped += 1
    return dropped


# ─────────────────────────────────────────────────────────────────────────────
# GNN train/eval helpers  (same as loeo_eval.py)
# ─────────────────────────────────────────────────────────────────────────────

def train_gnn(train_graphs, seed):
    torch.manual_seed(seed)
    model = RiskGNN(num_node_features=NUM_FEATURES)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    lf  = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([POS_WEIGHT]))
    model.train()
    for _ in range(EPOCHS):
        for g in train_graphs:
            opt.zero_grad()
            loss = lf(model(g.x, g.edge_index), g.y)
            loss.backward(); opt.step()
    return model

def gnn_probs(model, graphs):
    model.eval()
    p_all=[]; l_all=[]
    with torch.no_grad():
        for g in graphs:
            p = torch.sigmoid(model(g.x, g.edge_index)).tolist()
            p_all.extend(p); l_all.extend(g.y.tolist())
    return p_all, l_all

def gnn_scores(model, g):
    model.eval()
    with torch.no_grad():
        return torch.sigmoid(model(g.x, g.edge_index)).tolist()


# ─────────────────────────────────────────────────────────────────────────────
# Downstream topology: which nodes are downstream victims?
# Bookinfo call graph (directed): productpage->details, productpage->reviews,
#                                  reviews->ratings
# If fault_node=ratings  -> downstream of fault for INCOMING path: productpage, reviews
# If fault_node=reviews  -> downstream: productpage
# If fault_node=details  -> downstream: productpage
# "downstream" here means: nodes that call the faulted node (i.e. request goes
# through it). "Unrelated" = nodes with no edge to/from faulted node.
# ─────────────────────────────────────────────────────────────────────────────

DOWNSTREAM = {
    "ratings": {"reviews", "productpage"},   # reviews->ratings, productpage->reviews->ratings
    "reviews": {"productpage"},
    "details": {"productpage"},
    "productpage": set(),                    # root; no upstream callers in Bookinfo
}


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 1: Data counts
# ─────────────────────────────────────────────────────────────────────────────

def check1_data_counts(all_records, holdout_ts):
    lines = []
    A = lines.append

    A("## Check 1: Data Counts (All 8 Episodes)")
    A("")
    A("Labeling rules: lag=[start, start+90s), recovery=(end, end+90s], "
      "steady=[start+90s, end], normal=everything else.")
    A("Leakage buffer: 120 s before/after test and val windows excluded from train (shown per fold).")
    A("")

    # Per-episode phase counts
    from collections import Counter
    ep_phase = defaultdict(Counter)
    normal_total = 0
    for r in all_records:
        if r["episode_id"]:
            ep_phase[r["episode_id"]][r["phase"]] += 1
        else:
            normal_total += 1

    A("### Episode-level snapshot counts")
    A("")
    A("| Fold | EpID | Node | Delay (ms) | Source | Duration (s) | Lag | Steady | Recovery | Expected lag | Expected steady | Flag |")
    A("|------|------|------|------------|--------|-------------|-----|--------|----------|-------------|-----------------|------|")

    for ep in ALL_EPISODES:
        eid  = ep["episode_id"]
        dur  = (ep["end"] - ep["start"]).total_seconds()
        c    = ep_phase.get(eid, Counter())
        lag_n    = c.get("lag", 0)
        steady_n = c.get("steady", 0)
        rec_n    = c.get("recovery", 0)

        # Expected counts: one snapshot per ~15 s (Prometheus poll)
        if ep["source"] == "fault_log":
            exp_lag    = "5-6"
            exp_steady = "13-14"
            flag = ""
            if not (5 <= lag_n <= 7):
                flag += f" ⚠ lag={lag_n}"
            if not (13 <= steady_n <= 15):
                flag += f" ⚠ steady={steady_n}"
        else:
            # Legacy episodes: duration-based
            exp_lag_n    = min(6, int(LAG_DURATION.total_seconds() / 15) + 1)
            exp_steady_n = int((dur - LAG_DURATION.total_seconds()) / 15)
            exp_lag    = str(exp_lag_n)
            exp_steady = f"~{exp_steady_n}"
            flag = "(legacy)"

        A(f"| {ep['fold_index']} | {eid} | {ep['node']} | {ep['delay_ms']} | "
          f"{ep['source']} | {dur:.0f} | {lag_n} | {steady_n} | {rec_n} | "
          f"{exp_lag} | {exp_steady} | {flag} |")

    A("")
    A(f"Normal snapshots (phase='normal', not in any episode window): **{normal_total}**")
    holdout_n = sum(1 for r in all_records if r["timestamp"] in holdout_ts)
    A(f"Of which in normal-only holdout (latest 25%): **{holdout_n}**")
    A("")

    # Leakage buffer drops per fold
    A("### Snapshots dropped by 120 s leakage buffer (per fold)")
    A("")
    A("These are non-lag/recovery snapshots that fall within 120 s of the test or val windows "
      "and are excluded from training.")
    A("")
    A("| Fold | Test ep | Val ep | Dropped by buffer |")
    A("|------|---------|--------|-------------------|")
    for fold_k in range(len(ALL_EPISODES)):
        ep = ALL_EPISODES[fold_k]
        ep_v = ALL_EPISODES[(fold_k+1)%len(ALL_EPISODES)]
        d = count_leakage_dropped(all_records, fold_k, holdout_ts)
        A(f"| {fold_k} | {ep['episode_id']} | {ep_v['episode_id']} | {d} |")
    A("")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 2: Config confirmation
# ─────────────────────────────────────────────────────────────────────────────

def check2_config():
    lines = []
    A = lines.append

    A("## Check 2: Config Confirmation")
    A("")
    A("### loeo_eval.py actual config (lines 52-59)")
    A("")
    A("```python")
    A(f"SEEDS        = {SEEDS}           # line 52")
    A(f"EPOCHS       = {EPOCHS}                       # line 53")
    A(f"LR           = {LR}                    # line 54")
    A(f"POS_WEIGHT   = {POS_WEIGHT}                    # line 55")
    A(f"NUM_FEATURES = {NUM_FEATURES}                       # line 56")
    A(f"IN_LAT_IDX   = {IN_LAT_IDX}                       # line 57")
    A("optimizer    = torch.optim.Adam      # line in train_gnn()")
    A("loss         = BCEWithLogitsLoss(pos_weight=tensor([1.0]))  # line in train_gnn()")
    A("activation   = LeakyReLU(negative_slope=0.1)  # from model.py")
    A("hidden_dim   = 16                   # from RiskGNN default")
    A("feature_scale= log1p (rates+latencies), error_rate unscaled  # from record_to_graph()")
    A("```")
    A("")
    A("### experiment_b_v2.py config (for comparison)")
    A("")
    A("```python")
    A("SEEDS   = [42, 7, 13, 99, 2024]    # line 37")
    A("EPOCHS  = 100                       # line 38")
    A("# lr=0.01 (line 238: opt = torch.optim.Adam(mdl.parameters(), lr=0.01))")
    A("# pos_weight chosen on validation: pw=1 (1.0) selected (line 239)")
    A("# BCEWithLogitsLoss(pos_weight=torch.tensor([best_pw_val])) -- line 239/260")
    A("# best_pw_val resolved to 1.0 (from prior run output)")
    A("# RiskGNN(num_node_features=6)     -- line 237")
    A("# hidden_dim=16, LeakyReLU(0.1)   -- from model.py (same file)")
    A("# feature scale: log1p on rates and latencies (build_graph_dataset.py)")
    A("```")
    A("")
    A("### Differences")
    A("")
    A("| Parameter | loeo_eval.py | experiment_b_v2.py | Difference? |")
    A("|-----------|--------------|---------------------|-------------|")
    A("| Seeds | [42,7,13,99,2024] | [42,7,13,99,2024] | None |")
    A("| Epochs | 100 | 100 | None |")
    A("| Learning rate | 0.01 | 0.01 | None |")
    A("| pos_weight | 1.0 (fixed) | 1.0 (selected on val) | Procedural difference: exp_b_v2 selected pw=1 via val search; loeo_eval.py uses pw=1 directly without a search step |")
    A("| Loss | BCEWithLogitsLoss | BCEWithLogitsLoss | None |")
    A("| Architecture | RiskGNN (GCNConv×2, hidden=16, LeakyReLU) | Same | None |")
    A("| Feature scaling | log1p (rates+latencies), err unscaled | Same | None |")
    A("| Threshold selection | val episode (next episode) | val set (chronological tail of train block) | Different: loeo uses a held-out *episode* as val; exp_b_v2 uses a time-tail of the same data blocks |")
    A("| Recovery buffer | 90 s (build_dataset_v2.py) | 75 s (experiment_b_v2.py line 35) | **Different: loeo uses 90 s; exp_b_v2 uses 75 s** |")
    A("")
    A("> **Key difference:** recovery buffer is 90 s in `loeo_eval.py`/`build_dataset_v2.py` "
      "vs 75 s in `experiment_b_v2.py`. This affects which snapshots are excluded after each fault window.")
    A("")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 3: Per-fold thresholds and collapse check  (RETRAIN)
# ─────────────────────────────────────────────────────────────────────────────

def check3_thresholds_and_collapse(all_records, holdout_ts):
    lines = []
    A = lines.append

    A("## Check 3: Per-Fold Thresholds and Collapse Check")
    A("")
    A("> **RETRAIN NOTE:** `loeo_eval.py` does not save per-seed probability distributions. "
      "This check retrains all 8 folds × 5 seeds using identical config (same seeds, LR, "
      "epochs, pos_weight=1.0). Results should be deterministic.")
    A("")
    A("Collapse criterion: probability std across test-window node readings < 0.02 (flagged).")
    A("")

    for fold_k in range(len(ALL_EPISODES)):
        ep      = ALL_EPISODES[fold_k]
        ep_val  = ALL_EPISODES[(fold_k+1) % len(ALL_EPISODES)]
        train_g, val_g, test_g, steady_g, _ = build_loeo_split(all_records, fold_k, holdout_ts)

        n_val_pos = sum(int(g.y.sum()) for g in val_g)
        n_val_neg = sum(int((g.y == 0).all()) for g in val_g)*len(NODE_VOCAB)
        # More precise val neg count at node level
        val_node_pos = sum(int(l) for g in val_g for l in g.y.tolist())
        val_node_neg = sum(1-int(l) for g in val_g for l in g.y.tolist())

        A(f"### Fold {fold_k}: test=ep {ep['episode_id']} ({ep['node']} {ep['delay_ms']}ms)  "
          f"val=ep {ep_val['episode_id']} ({ep_val['node']} {ep_val['delay_ms']}ms)")
        A("")
        A(f"Val set: {len(val_g)} snapshots, **{val_node_pos} positive** node-readings, "
          f"**{val_node_neg} negative** node-readings")
        A("")

        # Baseline threshold
        bl_scores, bl_labels = [], []
        for g in val_g:
            bl_scores.extend(g.x[:, IN_LAT_IDX].tolist())
            bl_labels.extend(g.y.tolist())
        if sum(bl_labels) == 0:
            bl_scores, bl_labels = [], []
            for g in train_g:
                bl_scores.extend(g.x[:, IN_LAT_IDX].tolist())
                bl_labels.extend(g.y.tolist())
            A(f"Baseline threshold chosen on **train** (val has 0 positives).")
        bl_thresh, bl_f1 = best_threshold_f1(bl_scores, bl_labels)

        A(f"Baseline threshold (val best-F1): **{bl_thresh:.4f}** (F1={bl_f1:.3f})")
        A("")
        A("| Seed | GNN val thresh | Val F1 | Test prob std | Test mean(pos) | Test mean(neg) | Collapse? |")
        A("|------|----------------|--------|---------------|----------------|----------------|-----------|")

        for seed in SEEDS:
            if not train_g:
                A(f"| {seed} | — | — | — | — | — | no train data |")
                continue
            model = train_gnn(train_g, seed)

            # Val threshold
            gv_s, gv_l = gnn_probs(model, val_g)
            if sum(gv_l) == 0:
                gv_s, gv_l = gnn_probs(model, train_g)
            thresh, val_f1 = best_threshold_f1(gv_s, gv_l)

            # Test distribution
            gt_s, gt_l = gnn_probs(model, test_g)
            prob_std = torch.tensor(gt_s).std().item()
            pos_probs = [p for p, l in zip(gt_s, gt_l) if l == 1]
            neg_probs = [p for p, l in zip(gt_s, gt_l) if l == 0]
            mean_pos  = sum(pos_probs)/len(pos_probs) if pos_probs else float("nan")
            mean_neg  = sum(neg_probs)/len(neg_probs) if neg_probs else float("nan")
            collapsed = "**YES ⚠**" if prob_std < 0.02 else "no"

            A(f"| {seed} | {thresh:.4f} | {val_f1:.3f} | {prob_std:.4f} | "
              f"{fmt(mean_pos)} | {fmt(mean_neg)} | {collapsed} |")

        A("")
        print(f"  Fold {fold_k} done.", flush=True)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 4: Validation-free operating point (5% holdout FPR threshold)  (RETRAIN)
# ─────────────────────────────────────────────────────────────────────────────

def check4_validation_free_op(all_records, holdout_ts, holdout_graphs):
    lines = []
    A = lines.append

    A("## Check 4: Validation-Free Operating Point (5% Holdout FPR)")
    A("")
    A("> **RETRAIN NOTE:** Requires per-seed holdout scores. Retrains same folds/seeds.")
    A("")
    A("For each fold and each model, the threshold is set to the **95th percentile** of "
      "that model's scores across ALL node-readings in the normal-only holdout. "
      "By construction this gives FPR ≈ 5% on the holdout. "
      "We then measure recall on the test window's steady-fault node readings at that threshold.")
    A("")
    A("Holdout is **fixed** (same 137 snapshots = 548 node-readings for all folds; "
      "never used in training).")
    A("")
    A("| Fold | Ep | Node | Delay | GNN Recall@5%FPR (mean±std) | BL Recall@5%FPR |")
    A("|------|----|------|-------|------------------------------|-----------------|")

    gnn_5pct_recalls = []
    bl_5pct_recalls  = []

    for fold_k in range(len(ALL_EPISODES)):
        ep = ALL_EPISODES[fold_k]
        train_g, val_g, test_g, steady_g, _ = build_loeo_split(all_records, fold_k, holdout_ts)

        if not train_g or not test_g:
            A(f"| {fold_k} | {ep['episode_id']} | {ep['node']} | {ep['delay_ms']}ms "
              f"| no data | no data |")
            continue

        # ── Baseline operating point ──
        bl_holdout_scores = []
        for g in holdout_graphs:
            bl_holdout_scores.extend(g.x[:, IN_LAT_IDX].tolist())
        bl_thresh_5pct = percentile(bl_holdout_scores, 95)

        # Baseline recall on steady test
        bl_steady_scores = []
        bl_steady_labels = []
        for g in steady_g:
            bl_steady_scores.extend(g.x[:, IN_LAT_IDX].tolist())
            bl_steady_labels.extend(g.y.tolist())
        bl_tp, bl_fp, bl_fn, _, _, bl_rec, _ = eval_at_threshold(
            bl_steady_scores, bl_steady_labels, bl_thresh_5pct)

        # ── GNN operating point (retrain) ──
        seed_recalls = []
        for seed in SEEDS:
            model = train_gnn(train_g, seed)
            gnn_holdout_scores = []
            for g in holdout_graphs:
                gnn_holdout_scores.extend(gnn_scores(model, g))
            gnn_thresh_5pct = percentile(gnn_holdout_scores, 95)

            # Recall on steady test
            st_probs = []; st_labels = []
            for g in steady_g:
                st_probs.extend(gnn_scores(model, g))
                st_labels.extend(g.y.tolist())
            _, _, _, _, _, gnn_rec, _ = eval_at_threshold(st_probs, st_labels, gnn_thresh_5pct)
            seed_recalls.append(gnn_rec)

        m_rec, s_rec = mean_std(seed_recalls)
        gnn_5pct_recalls.append(m_rec)
        bl_5pct_recalls.append(bl_rec)

        A(f"| {fold_k} | {ep['episode_id']} | {ep['node']} | {ep['delay_ms']}ms "
          f"| {fmt(m_rec)}±{fmt(s_rec)} | {fmt(bl_rec)} |")
        print(f"  Fold {fold_k} done.", flush=True)

    gnn_m, gnn_s = mean_std(gnn_5pct_recalls)
    bl_m,  bl_s  = mean_std(bl_5pct_recalls)
    A(f"| **Mean** | | | | **{fmt(gnn_m)}±{fmt(gnn_s)}** | **{fmt(bl_m)}** |")
    A("")
    A("> Holdout FPR is 5% by construction for all folds and both models, because the "
      "threshold is set to the 95th percentile of holdout scores. Small deviations possible "
      "due to discrete score values.")
    A("")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 5: False-positive breakdown  (RETRAIN)
# ─────────────────────────────────────────────────────────────────────────────

def check5_fp_breakdown(all_records, holdout_ts):
    lines = []
    A = lines.append

    A("## Check 5: False-Positive Breakdown by Node and Phase")
    A("")
    A("> **RETRAIN NOTE:** Requires per-node per-snapshot scores at the F1 threshold. "
      "Retrains same folds/seeds. Results are averaged over seeds for GNN.")
    A("")
    A("Phase classification of test-window snapshots:")
    A("- **pre_60s**: [ep_start − 60s, ep_start)  (normal, before fault injection)")
    A("- **steady**: [ep_start + 90s, ep_end]  (fault active, post-lag)")
    A("- **recovery**: excluded from all splits (not in test_graphs)")
    A("")
    A("Node classification (Bookinfo call graph, direction = who calls whom):")
    A("- `productpage → details`, `productpage → reviews`, `reviews → ratings`")
    A("- **downstream**: node that calls the faulted node (receives elevated latency from it)")
    A("- **unrelated**: node with no direct call relationship to faulted node in this direction")
    A("- Note: 'downstream' here means upstream in the call graph (caller of the faulty node).")
    A("  Causal explanation of why downstream nodes are flagged was not tested.")
    A("")

    A("### GNN false positives (F1-threshold, mean over 5 seeds)")
    A("")
    A("| Fold | Ep | FaultNode | Phase | Node | FP count (mean/seed) | downstream? |")
    A("|------|----|-----------|-------|------|----------------------|-------------|")

    for fold_k in range(len(ALL_EPISODES)):
        ep      = ALL_EPISODES[fold_k]
        ep_val  = ALL_EPISODES[(fold_k+1) % len(ALL_EPISODES)]
        train_g, val_g, test_g, steady_g, test_tagged = build_loeo_split(
            all_records, fold_k, holdout_ts)
        if not train_g or not test_g:
            continue

        ep_start = ep["start"]
        fault_node = ep["node"]
        downstream_nodes = DOWNSTREAM.get(fault_node, set())

        # Classify each test snapshot into sub-phase
        def sub_phase(r):
            ts = datetime.fromisoformat(r["timestamp"])
            if ts < ep_start:
                return "pre_60s"
            # steady is [ep_start+90s, ep_end]; recovery excluded
            return "steady"

        # Accumulate FPs per (sub_phase, node) across seeds
        fp_accum = defaultdict(list)  # (phase, node) -> [fp_count_per_seed]

        for seed in SEEDS:
            model = train_gnn(train_g, seed)

            # Get F1 threshold from val
            gv_s, gv_l = gnn_probs(model, val_g)
            if sum(gv_l) == 0:
                gv_s, gv_l = gnn_probs(model, train_g)
            thresh, _ = best_threshold_f1(gv_s, gv_l)

            fp_this_seed = defaultdict(int)
            for (g, r) in test_tagged:
                sp = sub_phase(r)
                probs = gnn_scores(model, g)
                lbls  = g.y.tolist()
                for ni, (prob, lbl) in enumerate(zip(probs, lbls)):
                    node_name = NODE_VOCAB[ni]
                    if lbl == 0 and prob > thresh:
                        fp_this_seed[(sp, node_name)] += 1

            for k, v in fp_this_seed.items():
                fp_accum[k].append(v)

        # Print non-zero FPs
        for (sp, node_name), counts in sorted(fp_accum.items()):
            mean_fp = sum(counts) / len(counts)
            is_ds = "yes" if node_name in downstream_nodes else "no"
            if mean_fp > 0:
                A(f"| {fold_k} | {ep['episode_id']} | {fault_node} | {sp} | "
                  f"{node_name} | {mean_fp:.1f} | {is_ds} |")

        print(f"  GNN fold {fold_k} done.", flush=True)

    A("")
    A("### Baseline false positives (F1-threshold)")
    A("")
    A("| Fold | Ep | FaultNode | Phase | Node | FP count | downstream? |")
    A("|------|----|-----------|-------|------|----------|-------------|")

    for fold_k in range(len(ALL_EPISODES)):
        ep      = ALL_EPISODES[fold_k]
        _, _, test_g, _, test_tagged = build_loeo_split(all_records, fold_k, holdout_ts)
        if not test_g:
            continue

        fault_node      = ep["node"]
        downstream_nodes = DOWNSTREAM.get(fault_node, set())
        ep_start        = ep["start"]

        # Baseline val threshold
        train_g, val_g, _, _, _ = build_loeo_split(all_records, fold_k, holdout_ts)
        bl_v_s, bl_v_l = [], []
        for g in val_g:
            bl_v_s.extend(g.x[:, IN_LAT_IDX].tolist())
            bl_v_l.extend(g.y.tolist())
        if sum(bl_v_l) == 0:
            bl_v_s, bl_v_l = [], []
            for g in train_g:
                bl_v_s.extend(g.x[:, IN_LAT_IDX].tolist())
                bl_v_l.extend(g.y.tolist())
        bl_thresh, _ = best_threshold_f1(bl_v_s, bl_v_l)

        def sub_phase(r):
            ts = datetime.fromisoformat(r["timestamp"])
            return "pre_60s" if ts < ep_start else "steady"

        fp_bl = defaultdict(int)
        for (g, r) in test_tagged:
            sp = sub_phase(r)
            scores = g.x[:, IN_LAT_IDX].tolist()
            lbls   = g.y.tolist()
            for ni, (sc, lbl) in enumerate(zip(scores, lbls)):
                node_name = NODE_VOCAB[ni]
                if lbl == 0 and sc > bl_thresh:
                    fp_bl[(sp, node_name)] += 1

        for (sp, node_name), cnt in sorted(fp_bl.items()):
            is_ds = "yes" if node_name in downstream_nodes else "no"
            if cnt > 0:
                A(f"| {fold_k} | {ep['episode_id']} | {fault_node} | {sp} | "
                  f"{node_name} | {cnt} | {is_ds} |")

    A("")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 6: Fold variability
# ─────────────────────────────────────────────────────────────────────────────

def check6_fold_variability():
    lines = []
    A = lines.append

    A("## Check 6: Fold Variability (AP and Root-Cause Top-1)")
    A("")

    if not os.path.exists(RESULT_CSV):
        A(f"> `{RESULT_CSV}` not found — cannot report. Run loeo_eval.py first.")
        return lines

    rows = []
    with open(RESULT_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    def fv(r, k):
        try: return float(r[k])
        except: return float("nan")

    A("### Average Precision — sorted worst to best")
    A("")
    A("**GNN (mean over seeds):**")
    A("")
    gnn_ap = [(r["ep_id"], r["node"], r["delay_ms"], fv(r,"gnn_ap_mean"), fv(r,"gnn_ap_std")) for r in rows]
    gnn_ap_sorted = sorted(gnn_ap, key=lambda x: x[3])
    A("| Rank | Ep | Node | Delay | GNN AP mean | GNN AP std |")
    A("|------|----|------|-------|-------------|------------|")
    for rank, (eid, node, delay, m, s) in enumerate(gnn_ap_sorted, 1):
        worst_flag = " ← worst" if rank == 1 else ""
        A(f"| {rank} | {eid} | {node} | {delay}ms | {fmt(m)} | {fmt(s)} |{worst_flag}")
    A("")
    worst_gnn_ap = gnn_ap_sorted[0]
    A(f"Worst GNN fold for AP: **ep {worst_gnn_ap[0]}** ({worst_gnn_ap[1]}, {worst_gnn_ap[2]}ms) — AP={fmt(worst_gnn_ap[3])}")
    A("")

    A("**Baseline:**")
    A("")
    bl_ap = [(r["ep_id"], r["node"], r["delay_ms"], fv(r,"bl_ap")) for r in rows]
    bl_ap_sorted = sorted(bl_ap, key=lambda x: x[3])
    A("| Rank | Ep | Node | Delay | BL AP |")
    A("|------|----|------|-------|-------|")
    for rank, (eid, node, delay, m) in enumerate(bl_ap_sorted, 1):
        worst_flag = " ← worst" if rank == 1 else ""
        A(f"| {rank} | {eid} | {node} | {delay}ms | {fmt(m)} |{worst_flag}")
    A("")
    worst_bl_ap = bl_ap_sorted[0]
    A(f"Worst baseline fold for AP: **ep {worst_bl_ap[0]}** ({worst_bl_ap[1]}, {worst_bl_ap[2]}ms) — AP={fmt(worst_bl_ap[3])}")
    A("")

    A("### Root-Cause Top-1 — sorted worst to best")
    A("")
    A("**GNN (mean over seeds):**")
    A("")
    gnn_rc = [(r["ep_id"], r["node"], r["delay_ms"], fv(r,"gnn_rc1_mean"), fv(r,"gnn_rc1_std")) for r in rows]
    gnn_rc_sorted = sorted(gnn_rc, key=lambda x: x[3])
    A("| Rank | Ep | Node | Delay | GNN RC1 mean | GNN RC1 std |")
    A("|------|----|------|-------|--------------|-------------|")
    for rank, (eid, node, delay, m, s) in enumerate(gnn_rc_sorted, 1):
        worst_flag = " ← worst" if rank == 1 else ""
        A(f"| {rank} | {eid} | {node} | {delay}ms | {fmt(m)} | {fmt(s)} |{worst_flag}")
    A("")
    worst_gnn_rc = gnn_rc_sorted[0]
    A(f"Worst GNN fold for RC1: **ep {worst_gnn_rc[0]}** ({worst_gnn_rc[1]}, {worst_gnn_rc[2]}ms) — RC1={fmt(worst_gnn_rc[3])}")
    A("")

    A("**Baseline:**")
    A("")
    bl_rc = [(r["ep_id"], r["node"], r["delay_ms"], fv(r,"bl_rc1")) for r in rows]
    bl_rc_sorted = sorted(bl_rc, key=lambda x: x[3])
    A("| Rank | Ep | Node | Delay | BL RC1 |")
    A("|------|----|------|-------|--------|")
    for rank, (eid, node, delay, m) in enumerate(bl_rc_sorted, 1):
        worst_flag = " ← worst" if rank == 1 else ""
        A(f"| {rank} | {eid} | {node} | {delay}ms | {fmt(m)} |{worst_flag}")
    A("")
    worst_bl_rc = bl_rc_sorted[0]
    A(f"Worst baseline fold for RC1: **ep {worst_bl_rc[0]}** ({worst_bl_rc[1]}, {worst_bl_rc[2]}ms) — RC1={fmt(worst_bl_rc[3])}")
    A("")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Assumptions and limitations
# ─────────────────────────────────────────────────────────────────────────────

def assumptions():
    lines = []
    A = lines.append
    A("## Assumptions, Deviations, and Checks Not Run")
    A("")
    A("1. **Determinism assumption**: GNN retraining is assumed deterministic given same seeds. "
      "PyTorch does not guarantee bit-for-bit reproducibility across CPU/Python versions. "
      "Threshold values may differ from loeo_eval.py by floating-point epsilon.")
    A("2. **Downstream topology**: `productpage→details`, `productpage→reviews`, "
      "`reviews→ratings` inferred from Bookinfo documentation. "
      "Not verified from observed edge data in this run. "
      "Whether topology explains FP patterns was **not tested**.")
    A("3. **5% FPR by construction**: The percentile threshold on the holdout sets FPR=5% "
      "exactly on the holdout. Actual FPR on new data will differ.")
    A("4. **Baseline score = in_lat only**: Other features not tested as baseline scorers.")
    A("5. **Persistence window history**: Resets at fold boundary (no carry-over). "
      "Not applicable to checks 3-6 here.")
    A("6. **Check 5 recovery snapshots**: Recovery-phase snapshots are excluded from "
      "test_graphs (both in loeo_eval.py and here), so no FP breakdown for recovery phase "
      "is possible from the test split. Flagged in the table header.")
    A("")
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(RESULT_CSV):
        print(f"ERROR: {RESULT_CSV} not found. Run loeo_eval.py first.")
        sys.exit(1)

    print("Loading records and holdout ...")
    all_records  = load_all_records()
    holdout_ts   = build_normal_holdout_ts(all_records)
    holdout_graphs = [g for r in all_records
                      if r["timestamp"] in holdout_ts
                      for g in [record_to_graph(r)] if g is not None]
    print(f"  {len(all_records)} records, {len(holdout_graphs)} holdout graphs\n")

    all_lines = []
    A = all_lines.append

    A("# MeshHeal AI — LOEO Diagnostics")
    A("")
    A(f"*Generated by loeo_diagnostics.py | Same config as loeo_eval.py*")
    A("")

    print("Check 1: Data counts ...")
    all_lines += check1_data_counts(all_records, holdout_ts)

    print("Check 2: Config confirmation ...")
    all_lines += check2_config()

    print("Check 3: Per-fold thresholds (RETRAIN) ...")
    all_lines += check3_thresholds_and_collapse(all_records, holdout_ts)

    print("Check 4: 5% holdout FPR operating point (RETRAIN) ...")
    all_lines += check4_validation_free_op(all_records, holdout_ts, holdout_graphs)

    print("Check 5: FP breakdown (RETRAIN) ...")
    all_lines += check5_fp_breakdown(all_records, holdout_ts)

    print("Check 6: Fold variability (from CSV) ...")
    all_lines += check6_fold_variability()

    all_lines += assumptions()

    with open(OUT_MD, "w") as f:
        f.write("\n".join(all_lines) + "\n")
    print(f"\nDiagnostics written to {OUT_MD}")


if __name__ == "__main__":
    main()
