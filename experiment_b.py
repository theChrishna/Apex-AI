"""
experiment_b.py  –  Task 7 (Experiment B: final model on both faults)
-----------------------------------------------------------------------
Train on both fault windows + normal data using a CHRONOLOGICAL split
within each contiguous data block (no shuffling to avoid data leakage
from near-duplicate adjacent snapshots).

Split strategy:
  - Normal data before Oct 9: 80% train / 20% test (chronological order)
  - Oct 4 fault window (ratings): 80% train / 20% test
  - Normal data on Oct 9: 80% train / 20% test
  - Oct 9 fault window (details): 80% train / 20% test

Save model to models/v2_both.pt
"""

import sys
import os
import json
import torch
import torch.nn as nn
from datetime import datetime, timezone, timedelta
from build_graph_dataset import snapshot_to_graph, NODE_VOCAB
from model import RiskGNN

# ── Reproducibility ──────────────────────────────────────────────────────────
torch.manual_seed(42)

# ── Time boundaries ───────────────────────────────────────────────────────────
FAULT1_START = datetime(2026, 10, 4, 9, 49, 2,  tzinfo=timezone.utc)
FAULT1_END   = datetime(2026, 10, 4, 10, 3, 48, tzinfo=timezone.utc)
FAULT2_START = datetime(2026, 10, 9, 7, 43, 57, tzinfo=timezone.utc)
FAULT2_END   = datetime(2026, 10, 9, 7, 48, 25, tzinfo=timezone.utc)
RECOVERY_BUFFER = timedelta(seconds=75)
DATASET         = "labeled_dataset_v2.jsonl"
SAVE_PATH       = "models/v2_both.pt"

os.makedirs("models", exist_ok=True)
if os.path.exists(SAVE_PATH):
    print(f"ERROR: {SAVE_PATH} already exists. Delete it or use a new name.")
    sys.exit(1)


def is_recovery(ts, fault_end):
    return fault_end < ts <= fault_end + RECOVERY_BUFFER


def chrono_split(graphs, test_fraction=0.2):
    """Take last test_fraction% as test, the rest as train. Never shuffle."""
    n = len(graphs)
    split = int(n * (1 - test_fraction))
    return graphs[:split], graphs[split:]


# ── Partition snapshots into contiguous blocks ────────────────────────────────
# Blocks: normal_pre, fault1, normal_post (Oct4 normal after fault), normal_oct9, fault2
blocks = {
    "normal_pre":    [],
    "fault1":        [],
    "normal_post_4": [],  # normal data on Oct 4 after fault window
    "normal_oct9":   [],  # normal data on Oct 9
    "fault2":        [],
}

print(f"Partitioning {DATASET} into contiguous blocks ...")
with open(DATASET) as f:
    for line in f:
        record = json.loads(line)
        ts = datetime.fromisoformat(record["timestamp"])

        # Skip both recovery buffers
        if is_recovery(ts, FAULT1_END) or is_recovery(ts, FAULT2_END):
            continue

        graph = snapshot_to_graph(record)
        if graph is None:
            continue

        # Classify into block
        if FAULT1_START <= ts <= FAULT1_END:
            blocks["fault1"].append(graph)
        elif FAULT2_START <= ts <= FAULT2_END:
            blocks["fault2"].append(graph)
        elif ts.date().isoformat() == "2026-10-04" and ts > FAULT1_END:
            blocks["normal_post_4"].append(graph)
        elif ts.date().isoformat() == "2026-10-09":
            blocks["normal_oct9"].append(graph)
        else:
            blocks["normal_pre"].append(graph)

for name, g in blocks.items():
    print(f"  {name:20s}: {len(g)} graphs")

# ── Chronological split within each block ─────────────────────────────────────
train_graphs = []
test_graphs  = []
for name, g in blocks.items():
    tr, te = chrono_split(g, test_fraction=0.2)
    train_graphs.extend(tr)
    test_graphs.extend(te)

print(f"\nTotal  train: {len(train_graphs)}  test: {len(test_graphs)}")
train_pos = sum(int(g.y.sum().item()) for g in train_graphs)
test_pos  = sum(int(g.y.sum().item()) for g in test_graphs)
print(f"Positive labels  train: {train_pos}  test: {test_pos}")

# ── Compute pos_weight from training data ─────────────────────────────────────
total_nodes = sum(g.y.numel() for g in train_graphs)
pos_nodes   = sum(int(g.y.sum().item()) for g in train_graphs)
neg_nodes   = total_nodes - pos_nodes
pw = neg_nodes / pos_nodes if pos_nodes > 0 else 1.0
print(f"pos_weight = {pw:.2f}\n")

# ── Train ─────────────────────────────────────────────────────────────────────
model = RiskGNN(num_node_features=train_graphs[0].x.shape[1])
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pw]))

EPOCHS = 100
print(f"Training for {EPOCHS} epochs ...")
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
all_probs = []
with torch.no_grad():
    for g in test_graphs:
        all_probs.extend(torch.sigmoid(model(g.x, g.edge_index)).tolist())

prob_std = torch.tensor(all_probs).std().item()
print(f"\nTest-set probability std: {prob_std:.4f}")
if prob_std < 0.01:
    print("COLLAPSE DETECTED – not saving model.")
    sys.exit(2)

torch.save(model.state_dict(), SAVE_PATH)
print(f"Model saved to {SAVE_PATH}\n")

# ── Evaluation ────────────────────────────────────────────────────────────────
THRESHOLD = 0.5
tp = fp = fn = tn = 0

# Per-node mean risk tracking
fault_probs  = []
normal_probs = []

with torch.no_grad():
    for graph in test_graphs:
        probs = torch.sigmoid(model(graph.x, graph.edge_index))
        if graph.y.sum().item() > 0:
            fault_probs.append(probs)
        else:
            normal_probs.append(probs)
        for p, true in zip(probs, graph.y):
            pred = 1 if p.item() > THRESHOLD else 0
            t = int(true.item())
            if pred == 1 and t == 1: tp += 1
            elif pred == 1 and t == 0: fp += 1
            elif pred == 0 and t == 1: fn += 1
            else: tn += 1

print("=" * 55)
print("EXPERIMENT B – FINAL MODEL RESULTS (HELD-OUT TEST SET)")
print("=" * 55)
print(f"\nTest snapshots: {len(fault_probs)} with fault  |  {len(normal_probs)} normal\n")

for label, plist in [("FAULT snapshots", fault_probs), ("NORMAL snapshots", normal_probs)]:
    print(label)
    if plist:
        means = torch.stack(plist).mean(dim=0)
        for name, m in zip(NODE_VOCAB, means):
            print(f"  {name:15s} mean risk = {m.item():.3f}")
    else:
        print("  (none)")
    print()

prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
print(f"TP={tp} FP={fp} FN={fn} TN={tn}")
print(f"Precision={prec:.3f}  Recall={rec:.3f}")
