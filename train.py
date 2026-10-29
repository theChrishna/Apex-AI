"""
train.py  –  Tasks 3 & 4
--------------------------
Trains the RiskGNN and saves to models/<name>.pt.

Changes vs original:
  - Task 3: random seeds, LeakyReLU (in model.py), pos_weight computed
             from training data, collapse check at the end.
  - Task 4: --name argument, refuses to overwrite an existing file.

Usage:
    python train.py --name ratings_only
    python train.py --name v2_both  --dataset labeled_dataset_v2.jsonl
"""

import sys
import os
import argparse
import torch
import torch.nn as nn
from build_graph_dataset import load_all_graphs, train_test_split_stratified_chronological
from model import RiskGNN

# ── CLI ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Train RiskGNN")
parser.add_argument(
    "--name", required=True,
    help="Model name; saved to models/<name>.pt (will NOT overwrite an existing file)"
)
parser.add_argument(
    "--dataset", default="labeled_dataset_v2.jsonl",
    help="Path to labeled JSONL dataset (default: labeled_dataset_v2.jsonl)"
)
parser.add_argument(
    "--epochs", type=int, default=100,
    help="Number of training epochs (default: 100)"
)
args = parser.parse_args()

# ── Task 4: never overwrite ───────────────────────────────────────────────────
os.makedirs("models", exist_ok=True)
save_path = os.path.join("models", f"{args.name}.pt")
if os.path.exists(save_path):
    print(f"ERROR: {save_path} already exists. Choose a different --name.")
    sys.exit(1)

# ── Task 3: fix random seeds for reproducibility ──────────────────────────────
SEED = 42
torch.manual_seed(SEED)

# ── Load data ────────────────────────────────────────────────────────────────
print(f"Loading graphs from {args.dataset} ...")
graphs = load_all_graphs(path=args.dataset)
train_graphs, test_graphs = train_test_split_stratified_chronological(graphs)
print(f"Train: {len(train_graphs)} graphs | Test: {len(test_graphs)} graphs")

# ── Task 3: compute pos_weight from training set (not hardcoded) ──────────────
total_nodes = sum(g.y.numel() for g in train_graphs)
pos_nodes   = sum(int(g.y.sum().item()) for g in train_graphs)
neg_nodes   = total_nodes - pos_nodes
if pos_nodes == 0:
    print("WARNING: no positive labels in training set; pos_weight defaults to 1")
    pw = 1.0
else:
    pw = neg_nodes / pos_nodes          # weight for the minority class
print(f"  pos_nodes={pos_nodes}  neg_nodes={neg_nodes}  pos_weight={pw:.1f}")

pos_weight = torch.tensor([pw])
loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

# ── Model & optimiser ─────────────────────────────────────────────────────────
model = RiskGNN(num_node_features=train_graphs[0].x.shape[1])
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

# ── Training loop ─────────────────────────────────────────────────────────────
EPOCHS = args.epochs
for epoch in range(EPOCHS):
    model.train()
    total_loss = 0.0
    for graph in train_graphs:
        optimizer.zero_grad()
        output = model(graph.x, graph.edge_index)
        loss = loss_fn(output, graph.y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    avg_loss = total_loss / len(train_graphs)
    if epoch % 10 == 0 or epoch == EPOCHS - 1:
        print(f"Epoch {epoch:3d} | Train loss: {avg_loss:.4f}")

# ── Task 3: collapse check ────────────────────────────────────────────────────
# If the model gives the same probability to every node in the test set
# it has learned nothing useful. Fail loudly so we don't save garbage.
model.eval()
all_probs = []
with torch.no_grad():
    for graph in test_graphs:
        probs = torch.sigmoid(model(graph.x, graph.edge_index))
        all_probs.extend(probs.tolist())

prob_std = torch.tensor(all_probs).std().item()
print(f"\nTest-set probability std: {prob_std:.4f}")
COLLAPSE_THRESHOLD = 0.01   # std below this is considered collapse
if prob_std < COLLAPSE_THRESHOLD:
    print(f"COLLAPSE DETECTED: std={prob_std:.4f} < {COLLAPSE_THRESHOLD}")
    print("Model has collapsed to a near-constant output. NOT saving.")
    sys.exit(2)

# ── Save ──────────────────────────────────────────────────────────────────────
torch.save(model.state_dict(), save_path)
print(f"\nModel saved to {save_path}")