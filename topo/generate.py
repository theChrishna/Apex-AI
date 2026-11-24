"""Generate labelled SIMULATED snapshots on demand (no cluster needed).

  python -m topo.generate --out topo/data/sim_seed1.jsonl --seed 1 --per-family 2
  python -m topo.generate --out topo/data/chain12.jsonl --seed 5 --families chain --per-family 1 --min-nodes 12 --max-nodes 12

Output: one JSON snapshot per line, in the same format as the real snapshots (timestamp, nodes, edges with request_rate /
error_rate / latency_p95) plus the labels: phase ("normal" | "steady"), fault_node, episode_id, labels {node: 0/1},
topology, family. A second file, <out>.topologies.json, holds the topology definitions (services, call probabilities, rates).
The same --seed always gives the same files. Every record is SYNTHETIC: say so wherever the data is used (see topo/sim.py
for what the simulator does and does not model). Never overwrites an existing file or the uploaded data files.
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from topo import sim  # noqa: E402

PROTECTED = {"snapshots.jsonl", "fault_log.jsonl", "labeled_dataset.jsonl", "labeled_dataset_v2.jsonl"}


def topology_dict(t):
    return {"name": t.name, "family": t.family, "nodes": t.nodes, "root_rate_per_s": t.root_rate,
            "edges": [[u, v, p] for (u, v), p in t.edges.items()],
            "mean_service_ms": t.mu_ms, "slow_request_probability": t.spike_p}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="new .jsonl file to create")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--families", nargs="+", default=sim.FAMILIES, choices=sim.FAMILIES)
    ap.add_argument("--per-family", type=int, default=2, help="topologies per family")
    ap.add_argument("--min-nodes", type=int, default=4)
    ap.add_argument("--max-nodes", type=int, default=25)
    ap.add_argument("--normal", type=int, default=60, help="normal snapshots per topology")
    ap.add_argument("--episodes", type=int, default=6, help="fault episodes per topology")
    ap.add_argument("--steady", type=int, default=14, help="steady-state snapshots per episode (real episodes: 13-14)")
    a = ap.parse_args(argv)

    if os.path.basename(a.out) in PROTECTED:
        ap.error(f"{a.out} is an uploaded data file: choose another --out")
    meta = a.out + ".topologies.json"
    for p in (a.out, meta):
        if os.path.exists(p):
            ap.error(f"{p} already exists; choose another --out")
    if a.min_nodes < 3 or a.max_nodes < a.min_nodes:
        ap.error("need 3 <= --min-nodes <= --max-nodes")

    topos, records = sim.make_corpus(a.seed, per_family=a.per_family, families=a.families,
                                     size_range=(a.min_nodes, a.max_nodes), n_normal=a.normal,
                                     n_episodes=a.episodes, steady_per_episode=a.steady)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"synthetic": True, "seed": a.seed, "topologies": [topology_dict(t) for t in topos]}, f, indent=1)
    phases = {p: sum(1 for r in records if r["phase"] == p) for p in ("normal", "steady")}
    print(f"wrote {len(records)} SYNTHETIC snapshots ({phases}) for {len(topos)} topologies to {a.out}")
    print(f"topology definitions: {meta}")


if __name__ == "__main__":
    main()
