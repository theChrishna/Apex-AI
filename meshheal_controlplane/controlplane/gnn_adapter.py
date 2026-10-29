"""Adapter that makes the trained GNN look like a Scorer.

Features come from the training code itself (build_dataset_v2.record_to_graph), not a copy, so the
6 features [in_rate, in_err, in_lat, out_rate, out_err, out_lat], their log1p scaling and the
NODE_VOCAB node order are identical to training. The FINAL model (train_final.py) is one RiskGNN per
seed; scores are the mean of sigmoid(logits) over seeds.

record_to_graph needs the raw edges (plain mean per node, includes out_err), which node_stats() does
not carry, so this scorer asks for the snapshot (needs_snapshot = True).
"""
import json
import os
import sys


class GnnScorer:
    name = "gnn"
    needs_snapshot = True

    def __init__(self, manifest_path, repo_root=None, kill_file=None):
        self.kill_file = kill_file   # demo kill switch: while this file exists, score() raises
        manifest_path = os.path.abspath(manifest_path)
        self.repo_root = os.path.abspath(repo_root or os.path.join(os.path.dirname(manifest_path), ".."))
        with open(manifest_path) as f:
            self.manifest = json.load(f)
        self._import_training_code()

        import torch
        self._torch = torch
        m = self.manifest["model"]
        weights_dir = os.path.dirname(manifest_path)
        self.models = []
        for seed in self.manifest["train_config"]["seeds"]:
            net = self._RiskGNN(m["num_node_features"], hidden_dim=m["hidden_dim"])
            state = torch.load(os.path.join(weights_dir, self.manifest["weights"][str(seed)]),
                               map_location="cpu", weights_only=True)
            net.load_state_dict(state)
            net.eval()
            self.models.append(net)
        if list(self.manifest["features"]["node_vocab"]) != list(self.node_vocab):
            raise ValueError("NODE_VOCAB in manifest differs from build_dataset_v2.NODE_VOCAB")
        # warm-up: the first torch forward pass is slow; keep it out of the 500 ms scoring budget
        with torch.no_grad():
            x = torch.zeros(len(self.node_vocab), m["num_node_features"])
            for net in self.models:
                net(x, torch.zeros(2, 0, dtype=torch.long))

    def _import_training_code(self):
        # build_dataset_v2 reads fault_log.jsonl by relative path at import time: import from the repo root.
        if self.repo_root not in sys.path:
            sys.path.insert(0, self.repo_root)
        cwd = os.getcwd()
        try:
            os.chdir(self.repo_root)
            from build_dataset_v2 import NODE_VOCAB, record_to_graph
            from model import RiskGNN
        finally:
            os.chdir(cwd)
        self.node_vocab, self._record_to_graph, self._RiskGNN = NODE_VOCAB, record_to_graph, RiskGNN

    def graph(self, snap):
        record = {"timestamp": snap.ts.isoformat(), "phase": None, "episode_id": None, "fault_node": None,
                  "labels": {}, "nodes": snap.nodes, "edges": snap.edges}
        g = self._record_to_graph(record)
        if g is None:
            raise ValueError("snapshot is missing a NODE_VOCAB node")
        return g

    def per_seed(self, snap):
        """List (one per seed) of {node: prob}."""
        g = self.graph(snap)
        with self._torch.no_grad():
            return [dict(zip(self.node_vocab, self._torch.sigmoid(net(g.x, g.edge_index)).tolist()))
                    for net in self.models]

    def score(self, stats, snap=None):
        if self.kill_file and os.path.exists(self.kill_file):
            raise RuntimeError(f"GNN disabled by kill file {self.kill_file}")
        if snap is None:
            raise ValueError("GnnScorer needs the snapshot")
        runs = self.per_seed(snap)
        return {n: sum(r[n] for r in runs) / len(runs) for n in self.node_vocab}
