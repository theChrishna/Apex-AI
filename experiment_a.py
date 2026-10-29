"""
experiment_a.py  –  Task 5 (Experiment A: zero-shot generalization)
---------------------------------------------------------------------
Train ONLY on data before 2026-10-09 (ratings fault + normal data).
Test on data from 2026-10-09 (details fault window + normal from that day).

Reports:
  - Per-node mean risk during fault vs normal periods
  - Overall precision / recall on the test day
  - Separate precision / recall for lagged vs non-lagged fault snapshots

Save model to models/ratings_only.pt
"""

import sys
import os
import json
import torch
import torch.nn as nn
from datetime import datetime, timezone, timedelta
from build_graph_dataset import (
    snapshot_to_graph, load_graphs_before_date, NODE_VOCAB
)
from model import RiskGNN

# ── Reproducibility ──────────────────────────────────────────────────────────
torch.manual_seed(42)

# ── Date cutoffs ──────────────────────────────────────────────────────────────
CUTOFF = datetime(2026, 10, 9, 0, 0, 0, tzinfo=timezone.utc)   # training ends here
FAULT2_START = datetime(2026, 10, 9, 7, 43, 57, tzinfo=timezone.utc)
FAULT2_END   = datetime(2026, 10, 9, 7, 48, 25, tzinfo=timezone.utc)
RECOVERY_BUFFER = timedelta(seconds=75)
LAG_DURATION    = timedelta(seconds=90)
FAULT_NODE      = "details"
DATASET         = "labeled_dataset_v2.jsonl"
SAVE_PATH       = "models/ratings_only.pt"

# ── Never overwrite ───────────────────────────────────────────────────────────
os.makedirs("models", exist_ok=True)
if os.path.exists(SAVE_PATH):
    print(f"ERROR: {SAVE_PATH} already exists. Delete it or use a new name.")
    sys.exit(1)

# ── Load training data (before 2026-10-09) ───────────────────────────────────
print(f"Loading training graphs (before {CUTOFF.date()}) from {DATASET} ...")
train_graphs = load_graphs_before_date(CUTOFF, path=DATASET)
print(f"  Training graphs: {len(train_graphs)}")

# Compute pos_weight from training data
total_nodes = sum(g.y.numel() for g in train_graphs)
pos_nodes   = sum(int(g.y.sum().item()) for g in train_graphs)
neg_nodes   = total_nodes - pos_nodes
pw = neg_nodes / pos_nodes if pos_nodes > 0 else 1.0
print(f"  pos_nodes={pos_nodes}  neg_nodes={neg_nodes}  pos_weight={pw:.1f}")

# ── Train ─────────────────────────────────────────────────────────────────────
model = RiskGNN(num_node_features=train_graphs[0].x.shape[1])
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pw]))

EPOCHS = 100
print(f"\nTraining for {EPOCHS} epochs ...")
for epoch in range(EPOCHS):
    model.train()
    total_loss = 0.0
    for graph in train_graphs:
        optimizer.zero_grad()
        out = model(graph.x, graph.edge_index)
        loss = loss_fn(out, graph.y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    if epoch % 20 == 0 or epoch == EPOCHS - 1:
        print(f"  Epoch {epoch:3d} | loss={total_loss/len(train_graphs):.4f}")

# ── Collapse check ────────────────────────────────────────────────────────────
model.eval()
train_probs = []
with torch.no_grad():
    for g in train_graphs:
        train_probs.extend(torch.sigmoid(model(g.x, g.edge_index)).tolist())
prob_std = torch.tensor(train_probs).std().item()
print(f"\nTrain-set probability std: {prob_std:.4f}")
if prob_std < 0.01:
    print("COLLAPSE DETECTED – not saving model.")
    sys.exit(2)

torch.save(model.state_dict(), SAVE_PATH)
print(f"Model saved to {SAVE_PATH}\n")

# ── Evaluate on 2026-10-09 test data ─────────────────────────────────────────
# We load directly from snapshots.jsonl to get lagged information as well.
print("=" * 55)
print("EXPERIMENT A – ZERO-SHOT GENERALIZATION ON 2026-10-09")
print("=" * 55)

THRESHOLD = 0.5

# Track results by category
fault_probs        = []   # list of per-node prob tensors
normal_probs       = []
lagged_probs       = []   # fault snapshots in the first 90s (lagged)
nonlagged_probs    = []   # fault snapshots after 90s

tp = fp = fn = tn = 0
tp_lag = fp_lag = fn_lag = tn_lag = 0      # for lagged
tp_nl  = fp_nl  = fn_nl  = tn_nl  = 0     # for non-lagged

model.eval()
with open(DATASET) as f:
    for line in f:
        record = json.loads(line)
        ts = datetime.fromisoformat(record["timestamp"])

        # Only 2026-10-09 data
        if ts.date().isoformat() != "2026-10-09":
            continue

        # Skip recovery blur
        if FAULT2_END < ts <= FAULT2_END + RECOVERY_BUFFER:
            continue

        in_fault = FAULT2_START <= ts <= FAULT2_END
        is_lagged = in_fault and (ts < FAULT2_START + LAG_DURATION)

        graph = snapshot_to_graph(record)
        if graph is None:
            continue

        with torch.no_grad():
            probs = torch.sigmoid(model(graph.x, graph.edge_index))

        if in_fault:
            fault_probs.append(probs)
            if is_lagged:
                lagged_probs.append(probs)
            else:
                nonlagged_probs.append(probs)
        else:
            normal_probs.append(probs)

        # Overall confusion matrix
        for p, true in zip(probs, graph.y):
            pred = 1 if p.item() > THRESHOLD else 0
            t = int(true.item())
            if pred == 1 and t == 1: tp += 1
            elif pred == 1 and t == 0: fp += 1
            elif pred == 0 and t == 1: fn += 1
            else: tn += 1

        # Lagged / non-lagged breakdown (fault snapshots only)
        if in_fault:
            cm = (tp_lag, fp_lag, fn_lag, tn_lag) if is_lagged else (tp_nl, fp_nl, fn_nl, tn_nl)
            for p, true in zip(probs, graph.y):
                pred = 1 if p.item() > THRESHOLD else 0
                t = int(true.item())
                if is_lagged:
                    if pred == 1 and t == 1: tp_lag += 1
                    elif pred == 1 and t == 0: fp_lag += 1
                    elif pred == 0 and t == 1: fn_lag += 1
                    else: tn_lag += 1
                else:
                    if pred == 1 and t == 1: tp_nl += 1
                    elif pred == 1 and t == 0: fp_nl += 1
                    elif pred == 0 and t == 1: fn_nl += 1
                    else: tn_nl += 1


def mean_by_node(plist):
    if not plist:
        return None
    return torch.stack(plist).mean(dim=0)


def pr(tp_, fp_, fn_):
    prec = tp_ / (tp_ + fp_) if (tp_ + fp_) > 0 else 0.0
    rec  = tp_ / (tp_ + fn_) if (tp_ + fn_) > 0 else 0.0
    return prec, rec


print(f"\nSnapshots: {len(fault_probs)} during fault  |  {len(normal_probs)} normal")
print(f"  Lagged (first 90s): {len(lagged_probs)}  |  Non-lagged: {len(nonlagged_probs)}\n")

for label, plist in [("DURING details fault", fault_probs), ("NORMAL (2026-10-09)", normal_probs)]:
    means = mean_by_node(plist)
    print(label)
    if means is None:
        print("  (no snapshots)")
    else:
        for name, m in zip(NODE_VOCAB, means):
            print(f"  {name:15s} mean risk = {m.item():.3f}")
    print()

prec, rec = pr(tp, fp, fn)
print(f"Overall  | TP={tp} FP={fp} FN={fn} TN={tn}")
print(f"          Precision={prec:.3f}  Recall={rec:.3f}")

prec_l, rec_l = pr(tp_lag, fp_lag, fn_lag)
print(f"\nLagged snaps    | TP={tp_lag} FP={fp_lag} FN={fn_lag} TN={tn_lag}")
print(f"                  Precision={prec_l:.3f}  Recall={rec_l:.3f}")

prec_nl, rec_nl = pr(tp_nl, fp_nl, fn_nl)
print(f"\nNon-lagged snaps| TP={tp_nl} FP={fp_nl} FN={fn_nl} TN={tn_nl}")
print(f"                  Precision={prec_nl:.3f}  Recall={rec_nl:.3f}")
