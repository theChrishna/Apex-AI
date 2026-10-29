import json
import torch
from datetime import datetime, timezone, timedelta
from build_graph_dataset import snapshot_to_graph, NODE_VOCAB
from model import RiskGNN

FAULT_START = datetime(2026, 10, 9, 7, 43, 57, tzinfo=timezone.utc)
FAULT_END = datetime(2026, 10, 9, 7, 48, 25, tzinfo=timezone.utc)
FAULT_NODE = "details"
SESSION_START = datetime(2026, 10, 9, 0, 0, 0, tzinfo=timezone.utc)
RECOVERY_BUFFER = timedelta(seconds=75)
THRESHOLD = 0.5

model = RiskGNN(num_node_features=6)
model.load_state_dict(torch.load("risk_gnn.pt"))
model.eval()

fault_probs = []
normal_probs = []
tp = fp = fn = tn = 0

with open("snapshots.jsonl") as f:
    for line in f:
        record = json.loads(line)
        ts = datetime.fromisoformat(record["timestamp"])

        if ts < SESSION_START:
            continue
        if FAULT_END < ts <= FAULT_END + RECOVERY_BUFFER:
            continue

        in_fault = FAULT_START <= ts <= FAULT_END
        record["labels"] = {
            n: (1 if (in_fault and n == FAULT_NODE) else 0) for n in NODE_VOCAB
        }

        graph = snapshot_to_graph(record)
        if graph is None:
            continue

        with torch.no_grad():
            probs = torch.sigmoid(model(graph.x, graph.edge_index))

        (fault_probs if in_fault else normal_probs).append(probs)

        for p, true in zip(probs, graph.y):
            pred = 1 if p.item() > THRESHOLD else 0
            if pred == 1 and true == 1:
                tp += 1
            elif pred == 1 and true == 0:
                fp += 1
            elif pred == 0 and true == 1:
                fn += 1
            else:
                tn += 1

def mean_by_node(prob_list):
    if not prob_list:
        return None
    stacked = torch.stack(prob_list)
    return stacked.mean(dim=0)

print(f"Snapshots during fault: {len(fault_probs)}, normal: {len(normal_probs)}\n")

for label, plist in [("DURING details fault", fault_probs), ("NORMAL periods", normal_probs)]:
    means = mean_by_node(plist)
    print(label)
    if means is None:
        print("  (no snapshots)")
        continue
    for name, m in zip(NODE_VOCAB, means):
        print(f"  {name:12s} mean risk = {m.item():.3f}")
    print()

precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
print(f"TP={tp} FP={fp} FN={fn} TN={tn}")
print(f"Precision: {precision:.3f}  Recall: {recall:.3f}")