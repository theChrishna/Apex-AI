import json
import torch
from datetime import datetime, timezone, timedelta
from build_graph_dataset import snapshot_to_graph, NODE_VOCAB
from model import RiskGNN

FAULT_START = datetime(2026, 10, 9, 7, 43, 57, tzinfo=timezone.utc)
FAULT_END = datetime(2026, 10, 9, 7, 48, 25, tzinfo=timezone.utc)

model = RiskGNN(num_node_features=6)
model.load_state_dict(torch.load("risk_gnn.pt"))
model.eval()

shown = 0
with open("snapshots.jsonl") as f:
    for line in f:
        record = json.loads(line)
        ts = datetime.fromisoformat(record["timestamp"])
        if not (FAULT_START + timedelta(seconds=90) <= ts <= FAULT_END):
            continue
        record["labels"] = {n: 0 for n in NODE_VOCAB}
        graph = snapshot_to_graph(record)
        if graph is None:
            continue
        with torch.no_grad():
            logits = model(graph.x, graph.edge_index)
        print(record["timestamp"])
        for name, feats, logit in zip(NODE_VOCAB, graph.x, logits):
            print(f"  {name:12s} in_lat={feats[2]:7.1f} out_lat={feats[5]:7.1f} logit={logit.item():8.2f}")
        shown += 1
        if shown == 3:
            break