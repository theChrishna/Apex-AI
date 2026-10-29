"""
baseline.py  –  Task 6
------------------------
Simple rule-based baseline:
  Flag a node as anomalous if its incoming p95 latency exceeds a threshold.

The threshold is chosen on the TRAINING data only (data before 2026-10-09)
by maximising F1 over a grid of candidate values (also training-data derived).

Then we report precision/recall on the same test sets as Experiment A:
  1. All 2026-10-09 data
  2. Lagged fault snapshots (first 90s of fault)
  3. Non-lagged fault snapshots

No model is loaded; everything is from raw graph feature vectors
(feature index 2 = in_lat after log1p scaling, same as snapshot_to_graph).

Usage:
    python baseline.py
"""

import json
import torch
import numpy as np
from datetime import datetime, timezone, timedelta
from build_graph_dataset import snapshot_to_graph, NODE_VOCAB, NODE_INDEX

# ── Time windows ──────────────────────────────────────────────────────────────
CUTOFF      = datetime(2026, 10, 9, 0, 0, 0, tzinfo=timezone.utc)
FAULT2_START = datetime(2026, 10, 9, 7, 43, 57, tzinfo=timezone.utc)
FAULT2_END   = datetime(2026, 10, 9, 7, 48, 25, tzinfo=timezone.utc)
RECOVERY_BUFFER = timedelta(seconds=75)
LAG_DURATION    = timedelta(seconds=90)
FAULT_NODE      = "details"
DATASET         = "labeled_dataset_v2.jsonl"

# Feature index for incoming latency (see snapshot_to_graph)
IN_LAT_IDX = 2   # [in_rate, in_err, in_lat, out_rate, out_err, out_lat]

# ── Step 1: collect training-set latencies to pick threshold ──────────────────
print("Loading training data (before 2026-10-09) to pick threshold ...")
train_lats   = []  # (in_lat, label) tuples
train_graphs = []
with open(DATASET) as f:
    for line in f:
        record = json.loads(line)
        ts = datetime.fromisoformat(record["timestamp"])
        if ts >= CUTOFF:
            continue
        graph = snapshot_to_graph(record)
        if graph is None:
            continue
        train_graphs.append(graph)
        for i, node in enumerate(NODE_VOCAB):
            lat = graph.x[i, IN_LAT_IDX].item()
            lbl = int(graph.y[i].item())
            train_lats.append((lat, lbl))

# Choose threshold that maximises F1 on training data
candidate_thresholds = sorted(set(lat for lat, _ in train_lats))
# Use percentile grid instead of every unique value (faster + avoids overfit)
candidate_thresholds = np.percentile(
    [lat for lat, _ in train_lats],
    np.arange(50, 100, 1)   # 50th to 99th percentile in 1% steps
).tolist()

best_f1 = -1.0
best_thresh = None
for thresh in candidate_thresholds:
    tp = fp = fn = tn = 0
    for lat, lbl in train_lats:
        pred = 1 if lat > thresh else 0
        if pred == 1 and lbl == 1: tp += 1
        elif pred == 1 and lbl == 0: fp += 1
        elif pred == 0 and lbl == 1: fn += 1
        else: tn += 1
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    if f1 > best_f1:
        best_f1 = f1
        best_thresh = thresh

print(f"  Best threshold (log1p-scaled in_lat): {best_thresh:.4f}  (train F1={best_f1:.3f})")

# ── Step 2: evaluate on 2026-10-09 ───────────────────────────────────────────
print("\n" + "=" * 55)
print("BASELINE – RULE-BASED THRESHOLD ON 2026-10-09")
print("=" * 55)

tp = fp = fn = tn = 0
tp_lag = fp_lag = fn_lag = tn_lag = 0
tp_nl  = fp_nl  = fn_nl  = tn_nl  = 0

fault_count = 0; normal_count = 0

with open(DATASET) as f:
    for line in f:
        record = json.loads(line)
        ts = datetime.fromisoformat(record["timestamp"])
        if ts.date().isoformat() != "2026-10-09":
            continue
        if FAULT2_END < ts <= FAULT2_END + RECOVERY_BUFFER:
            continue

        in_fault = FAULT2_START <= ts <= FAULT2_END
        is_lagged = in_fault and (ts < FAULT2_START + LAG_DURATION)

        graph = snapshot_to_graph(record)
        if graph is None:
            continue

        if in_fault:
            fault_count += 1
        else:
            normal_count += 1

        for i, node in enumerate(NODE_VOCAB):
            lat  = graph.x[i, IN_LAT_IDX].item()
            pred = 1 if lat > best_thresh else 0
            lbl  = int(graph.y[i].item())

            # Overall
            if pred == 1 and lbl == 1: tp += 1
            elif pred == 1 and lbl == 0: fp += 1
            elif pred == 0 and lbl == 1: fn += 1
            else: tn += 1

            # Lagged / non-lagged (fault only)
            if in_fault:
                if is_lagged:
                    if pred == 1 and lbl == 1: tp_lag += 1
                    elif pred == 1 and lbl == 0: fp_lag += 1
                    elif pred == 0 and lbl == 1: fn_lag += 1
                    else: tn_lag += 1
                else:
                    if pred == 1 and lbl == 1: tp_nl += 1
                    elif pred == 1 and lbl == 0: fp_nl += 1
                    elif pred == 0 and lbl == 1: fn_nl += 1
                    else: tn_nl += 1


def pr(tp_, fp_, fn_):
    prec = tp_ / (tp_ + fp_) if (tp_ + fp_) > 0 else 0.0
    rec  = tp_ / (tp_ + fn_) if (tp_ + fn_) > 0 else 0.0
    return prec, rec


print(f"\nSnapshots: {fault_count} during fault  |  {normal_count} normal")
prec, rec = pr(tp, fp, fn)
print(f"\nOverall  | TP={tp} FP={fp} FN={fn} TN={tn}")
print(f"          Precision={prec:.3f}  Recall={rec:.3f}")

prec_l, rec_l = pr(tp_lag, fp_lag, fn_lag)
print(f"\nLagged   | TP={tp_lag} FP={fp_lag} FN={fn_lag} TN={tn_lag}")
print(f"          Precision={prec_l:.3f}  Recall={rec_l:.3f}")

prec_nl, rec_nl = pr(tp_nl, fp_nl, fn_nl)
print(f"\nNon-lag  | TP={tp_nl} FP={fp_nl} FN={fn_nl} TN={tn_nl}")
print(f"          Precision={prec_nl:.3f}  Recall={rec_nl:.3f}")
