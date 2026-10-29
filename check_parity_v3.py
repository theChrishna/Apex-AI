"""Live-path parity check for a final GNN manifest (default: the v3 one). Read-only; writes nothing.

For every stored snapshot the control plane accepts, compare GnnScorer.score() (the live path: parse_snapshot ->
node_stats -> adapter -> record_to_graph) with an independent offline computation (raw record -> record_to_graph ->
each seed's net loaded here -> mean of sigmoid). Reports the max absolute difference.

    python check_parity_v3.py [models/gnn_final_v3_manifest.json]   # from the project root
"""
import json
import os
import sys

import torch

sys.path.insert(0, os.path.join(os.getcwd(), "meshheal_controlplane"))
from build_dataset_v2 import NODE_VOCAB, record_to_graph          # noqa: E402
from model import RiskGNN                                         # noqa: E402
from controlplane.gnn_adapter import GnnScorer                    # noqa: E402
from controlplane.snapshot import BadSnapshot, node_stats, parse_snapshot   # noqa: E402

NODES = ("productpage", "details", "reviews", "ratings")
manifest = sys.argv[1] if len(sys.argv) > 1 else "models/gnn_final_v3_manifest.json"
man = json.load(open(manifest))
gnn = GnnScorer(manifest, os.getcwd())
nets = []
for seed in man["train_config"]["seeds"]:
    net = RiskGNN(man["model"]["num_node_features"], hidden_dim=man["model"]["hidden_dim"])
    net.load_state_dict(torch.load(os.path.join(os.path.dirname(manifest), man["weights"][str(seed)]), weights_only=True))
    net.eval(); nets.append(net)

worst, n, rejected, argmax = 0.0, 0, 0, ("", "")
for line in open("snapshots.jsonl"):
    if not line.strip():
        continue
    raw = json.loads(line)
    try:
        snap = parse_snapshot(json.loads(line), NODES)
    except BadSnapshot:
        rejected += 1
        continue
    live = gnn.score(node_stats(snap), snap)
    g = record_to_graph({**raw, "labels": {}, "phase": None, "episode_id": None, "fault_node": None})
    with torch.no_grad():
        per = [torch.sigmoid(net(g.x, g.edge_index)).tolist() for net in nets]
    ref = {nd: sum(p[i] for p in per) / len(per) for i, nd in enumerate(NODE_VOCAB)}
    d = max(abs(live[nd] - ref[nd]) for nd in NODES)
    if d > worst:
        worst, argmax = d, (raw["timestamp"], max(NODES, key=lambda nd: abs(live[nd] - ref[nd])))
    n += 1
print(f"manifest={manifest}\nsnapshots compared={n} rejected_by_validator={rejected} max_abs_diff={worst:.3e} at {argmax}")
print("PASS (< 1e-6)" if worst < 1e-6 else "FAIL")
