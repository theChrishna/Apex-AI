"""
train_final.py
==============
Train the FINAL GNN used by the control plane (controlplane/gnn_adapter.py).

Same model, features and config as loeo_eval.py (no retuning): RiskGNN 2x GCNConv hidden=16,
pos_weight=1, Adam lr=0.01, 100 epochs, seeds [42, 7, 13, 99, 2024].

Training data: every snapshot from all 8 episodes plus normal data, minus lag and recovery phases
(as in LOEO), minus the 137-snapshot normal holdout (kept clean for a normal-only check).
There is NO held-out episode: evaluation of the pipeline is the LOEO result, not this model.

Output (new files; nothing existing is overwritten):
  models/gnn_final_seed{seed}.pt      state_dict per seed
  models/gnn_final_manifest.json      seeds, config, feature spec, data hashes, counts
"""

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

import torch

from build_dataset_v2 import (
    ALL_EPISODES, NODE_VOCAB, FAULT_LOG_PATH, SNAPSHOTS_PATH,
    load_all_records, build_normal_holdout_ts, record_to_graph,
)
from loeo_eval import SEEDS, EPOCHS, LR, POS_WEIGHT, NUM_FEATURES, train_gnn

MODEL_DIR = "models"
MANIFEST = os.path.join(MODEL_DIR, "gnn_final_manifest.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def main():
    if os.path.exists(MANIFEST):
        raise SystemExit(f"refusing to overwrite {MANIFEST}")
    records = load_all_records()
    holdout_ts = build_normal_holdout_ts(records)

    train_graphs = []
    for r in records:
        if r["phase"] in ("lag", "recovery") or r["timestamp"] in holdout_ts:
            continue
        g = record_to_graph(r)
        if g is not None:
            train_graphs.append(g)
    n_pos = int(sum(g.y.sum().item() for g in train_graphs))
    print(f"train graphs={len(train_graphs)}  positive node labels={n_pos}  holdout excluded={len(holdout_ts)}")

    paths = {}
    for seed in SEEDS:
        path = os.path.join(MODEL_DIR, f"gnn_final_seed{seed}.pt")
        if os.path.exists(path):
            raise SystemExit(f"refusing to overwrite {path}")
        model = train_gnn(train_graphs, seed)
        torch.save(model.state_dict(), path)
        paths[str(seed)] = os.path.basename(path)
        print(f"  seed {seed} -> {path}")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "model": {"class": "model.RiskGNN", "num_node_features": NUM_FEATURES, "hidden_dim": 16},
        "train_config": {"epochs": EPOCHS, "lr": LR, "pos_weight": POS_WEIGHT, "seeds": SEEDS},
        "features": {
            "builder": "build_dataset_v2.record_to_graph(scale=True)",
            "order": ["in_rate", "in_err", "in_lat", "out_rate", "out_err", "out_lat"],
            "scaling": "log1p on rates and latencies; error rates unscaled",
            "node_vocab": NODE_VOCAB,
        },
        "inference": "mean of sigmoid(logits) over seeds",
        "data": {
            "episodes": [{"id": e["episode_id"], "node": e["node"], "delay_ms": e["delay_ms"]} for e in ALL_EPISODES],
            "train_graphs": len(train_graphs),
            "positive_node_labels": n_pos,
            "excluded": "lag, recovery, normal holdout",
            "holdout_snapshots": len(holdout_ts),
            "snapshots_sha256": sha256(SNAPSHOTS_PATH),
            "fault_log_sha256": sha256(FAULT_LOG_PATH),
        },
        "weights": paths,
    }
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"manifest -> {MANIFEST}")


if __name__ == "__main__":
    main()
