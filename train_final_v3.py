"""
train_final_v3.py
=================
Same as train_final.py (same model, features, config, seeds, lag/recovery and holdout handling) but on the cleaned data
from build_dataset_v3 (noisy normal snapshots in excluded_windows_v3.json removed).

Output (new files only; refuses to overwrite; the v1 files are not touched):
  models/gnn_final_v3_seed{seed}.pt
  models/gnn_final_v3_manifest.json   (records the sha256 of excluded_windows_v3.json)
"""
import json
import os
from datetime import datetime, timezone

import torch

import build_dataset_v3 as d3
from build_dataset_v2 import ALL_EPISODES, FAULT_LOG_PATH, NODE_VOCAB, SNAPSHOTS_PATH, record_to_graph
from loeo_eval import EPOCHS, LR, NUM_FEATURES, POS_WEIGHT, SEEDS, train_gnn
from train_final import git_commit, sha256

MODEL_DIR = "models"
MANIFEST = os.path.join(MODEL_DIR, "gnn_final_v3_manifest.json")


def main():
    if os.path.exists(MANIFEST):
        raise SystemExit(f"refusing to overwrite {MANIFEST}")
    records = d3.load_all_records()
    holdout_ts = d3.build_normal_holdout_ts(records)
    train_graphs = []
    for r in records:
        if r["phase"] in ("lag", "recovery") or r["timestamp"] in holdout_ts:
            continue
        g = record_to_graph(r)
        if g is not None:
            train_graphs.append(g)
    n_pos = int(sum(g.y.sum().item() for g in train_graphs))
    print(f"train graphs={len(train_graphs)}  positive node labels={n_pos}  holdout excluded={len(holdout_ts)}  "
          f"noisy snapshots removed={len(d3.EXCLUDED)}", flush=True)

    paths = {}
    for seed in SEEDS:
        path = os.path.join(MODEL_DIR, f"gnn_final_v3_seed{seed}.pt")
        if os.path.exists(path):
            raise SystemExit(f"refusing to overwrite {path}")
        model = train_gnn(train_graphs, seed)
        torch.save(model.state_dict(), path)
        paths[str(seed)] = os.path.basename(path)
        print(f"  seed {seed} -> {path}", flush=True)

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
            "variant": "v3 (noisy normal snapshots excluded)",
            "episodes": [{"id": e["episode_id"], "node": e["node"], "delay_ms": e["delay_ms"]} for e in ALL_EPISODES],
            "train_graphs": len(train_graphs),
            "positive_node_labels": n_pos,
            "excluded": "lag, recovery, normal holdout, and the noisy normal snapshots in excluded_windows_v3.json",
            "holdout_snapshots": len(holdout_ts),
            "excluded_windows_file": "excluded_windows_v3.json",
            "excluded_windows_sha256": d3.EXCLUDED_SHA256,
            "excluded_snapshots": len(d3.EXCLUDED),
            "snapshots_sha256": sha256(SNAPSHOTS_PATH),
            "fault_log_sha256": sha256(FAULT_LOG_PATH),
        },
        "weights": paths,
    }
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"manifest -> {MANIFEST}", flush=True)


if __name__ == "__main__":
    main()
