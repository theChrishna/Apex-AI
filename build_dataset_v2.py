"""
build_dataset_v2.py
====================
Unified dataset builder for all 8 fault episodes:
  - 2 legacy episodes (hardcoded from label_dataset_v2.py):
      A: ratings 200 ms  2026-10-04 09:49:02 -- 10:03:48 UTC
      B: details 100 ms  2026-10-09 07:43:57 -- 07:48:25 UTC
  - 6 new episodes from fault_log.jsonl (only completed=true)

Labeling rules (identical for all 8 episodes):
  - EXCLUDE lag:      [start, start+90s)  -- rate window still rising
  - EXCLUDE recovery: (end,   end+90s]    -- metrics still decaying
  - POSITIVE (1):     faulted node only,  start+90s <= t <= end
  - NEGATIVE (0):     all other nodes in any non-excluded snapshot

Pure-normal holdout: latest 25% of snapshots not within 120 s of any episode.
Never used for training; evaluated for FPR each fold.
"""

import json
import math
import sys
from datetime import datetime, timedelta

import torch
from torch_geometric.data import Data

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
SNAPSHOTS_PATH = "snapshots.jsonl"
FAULT_LOG_PATH = "fault_log.jsonl"
MEAN_LAT_PATH  = "latency_mean.jsonl"

LAG_DURATION     = timedelta(seconds=90)
RECOVERY_BUFFER  = timedelta(seconds=90)
LEAKAGE_BUFFER   = timedelta(seconds=120)  # used in LOEO split
HOLDOUT_FRAC     = 0.25                    # last 25% of pure-normal

NODE_VOCAB = ["details", "productpage", "ratings", "reviews"]
NODE_INDEX = {name: i for i, name in enumerate(NODE_VOCAB)}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Episode catalogue
# ─────────────────────────────────────────────────────────────────────────────

def _load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _build_episode_list():
    legacy = [
        {
            "episode_id": "A",
            "node": "ratings",
            "delay_ms": 200,
            "start": datetime.fromisoformat("2026-10-04T09:49:02+00:00"),
            "end":   datetime.fromisoformat("2026-10-04T10:03:48+00:00"),
            "source": "legacy",
        },
        {
            "episode_id": "B",
            "node": "details",
            "delay_ms": 100,
            "start": datetime.fromisoformat("2026-10-09T07:43:57+00:00"),
            "end":   datetime.fromisoformat("2026-10-09T07:48:25+00:00"),
            "source": "legacy",
        },
    ]
    new_eps = []
    try:
        for row in _load_jsonl(FAULT_LOG_PATH):
            if not row.get("completed", False):
                continue
            new_eps.append({
                "episode_id": str(row["episode"]),
                "node": row["node"],
                "delay_ms": row["delay_ms"],
                "start": datetime.fromisoformat(row["start"]),
                "end":   datetime.fromisoformat(row["end"]),
                "source": "fault_log",
            })
    except FileNotFoundError:
        print(f"WARNING: {FAULT_LOG_PATH} not found.", file=sys.stderr)

    all_eps = sorted(legacy + new_eps, key=lambda e: e["start"])
    for i, e in enumerate(all_eps):
        e["fold_index"] = i
    return all_eps


ALL_EPISODES = _build_episode_list()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Per-snapshot phase classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_snapshot(ts: datetime):
    """
    Returns (phase, episode_id, fault_node).
    phase: 'lag' | 'recovery' | 'steady' | 'normal'
    lag and recovery are both EXCLUDED from training and evaluation.
    """
    for ep in ALL_EPISODES:
        s, e, node = ep["start"], ep["end"], ep["node"]
        if s <= ts < s + LAG_DURATION:
            return "lag", ep["episode_id"], node
        if e < ts <= e + RECOVERY_BUFFER:
            return "recovery", ep["episode_id"], node
        if s + LAG_DURATION <= ts <= e:
            return "steady", ep["episode_id"], node
    return "normal", None, None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Load all raw records with phase tags
# ─────────────────────────────────────────────────────────────────────────────

def load_all_records(snapshots_path=SNAPSHOTS_PATH):
    """
    Returns list of dicts including lag/recovery (marked for exclusion in split).
    Each dict has: timestamp, phase, episode_id, fault_node, labels, edges, nodes.
    """
    records = []
    with open(snapshots_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            ts  = datetime.fromisoformat(raw["timestamp"])
            phase, ep_id, fault_node = classify_snapshot(ts)

            if "nodes" in raw:
                node_ids = [n["id"] for n in raw["nodes"]]
            else:
                node_ids = sorted(
                    {e["source"] for e in raw["edges"]}
                    | {e["destination"] for e in raw["edges"]}
                )

            labels = {}
            for nid in node_ids:
                if phase == "steady" and nid == fault_node:
                    labels[nid] = 1
                else:
                    labels[nid] = 0

            records.append({
                "timestamp":  raw["timestamp"],
                "phase":      phase,
                "episode_id": ep_id,
                "fault_node": fault_node,
                "labels":     labels,
                "edges":      raw["edges"],
                "nodes":      raw.get("nodes", [{"id": n} for n in node_ids]),
            })
    return records


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pure-normal holdout
# ─────────────────────────────────────────────────────────────────────────────

def build_normal_holdout_ts(records, frac=HOLDOUT_FRAC):
    """
    Return a frozenset of timestamp strings: latest `frac` of pure-normal
    snapshots not within LEAKAGE_BUFFER of any episode window.
    """
    def near_any(ts):
        for ep in ALL_EPISODES:
            if (ep["start"] - LEAKAGE_BUFFER) <= ts <= (ep["end"] + LEAKAGE_BUFFER):
                return True
        return False

    normal_ts = sorted(
        r["timestamp"] for r in records
        if r["phase"] == "normal"
        and not near_any(datetime.fromisoformat(r["timestamp"]))
    )
    cutoff_idx = int(len(normal_ts) * (1 - frac))
    return frozenset(normal_ts[cutoff_idx:])


# ─────────────────────────────────────────────────────────────────────────────
# 5. Per-episode count printout
# ─────────────────────────────────────────────────────────────────────────────

def print_episode_counts(records, holdout_ts=None):
    from collections import defaultdict
    counts = defaultdict(lambda: {"lag": 0, "steady": 0, "recovery": 0})
    for r in records:
        if r["episode_id"] is not None:
            counts[r["episode_id"]][r["phase"]] += 1

    normal_total   = sum(1 for r in records if r["phase"] == "normal")
    holdout_count  = sum(1 for r in records if holdout_ts and r["timestamp"] in holdout_ts)

    print("=" * 75)
    print("PER-EPISODE SNAPSHOT COUNTS")
    print(f"  {'ID':>3}  {'Node':10} {'Delay':>7}  {'Lag':>4} {'Steady':>6} {'Recovery':>9}  {'Source'}")
    print("-" * 75)
    warnings = []
    for ep in ALL_EPISODES:
        eid = ep["episode_id"]
        c = counts[eid]
        lag_n, steady_n, rec_n = c["lag"], c["steady"], c["recovery"]
        flag = ""
        if ep["source"] == "fault_log":
            if not (5 <= lag_n <= 7):
                flag += f"  !! lag={lag_n} (expected 5-6)"
                warnings.append(f"Ep {eid}: lag={lag_n} out of expected 5-6")
            if not (13 <= steady_n <= 15):
                flag += f"  !! steady={steady_n} (expected 13-14)"
                warnings.append(f"Ep {eid}: steady={steady_n} out of expected 13-14")
        print(f"  {eid:>3}  {ep['node']:10} {ep['delay_ms']:>4}ms  "
              f"{lag_n:>4} {steady_n:>6} {rec_n:>9}  {ep['source']}{flag}")
    print("-" * 75)
    print(f"  Normal snapshots (not in any window): {normal_total}")
    if holdout_ts is not None:
        print(f"  Normal holdout (latest {int(HOLDOUT_FRAC*100)}%):            {holdout_count}")
    print("=" * 75)
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  {w}")
    else:
        print("All new episodes match expected lag/steady counts (5-6 lag, 13-14 steady).")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Convert record -> PyG graph
# ─────────────────────────────────────────────────────────────────────────────

def record_to_graph(record, scale=True, extra_mean_lat=None):
    """
    6-feature (or 7-feature if extra_mean_lat provided) PyG Data object.
    Features: [in_rate, in_err, in_lat, out_rate, out_err, out_lat(, in_mean_lat)]
    Returns None if any canonical node is absent.
    """
    node_ids_present = {n["id"] for n in record["nodes"]}
    if not node_ids_present.issuperset(NODE_VOCAB):
        return None

    in_vals  = {n: [] for n in NODE_VOCAB}
    out_vals = {n: [] for n in NODE_VOCAB}
    edge_index = [[], []]

    for edge in record["edges"]:
        src, dst = edge["source"], edge["destination"]
        if src not in NODE_INDEX or dst not in NODE_INDEX:
            continue
        edge_index[0].append(NODE_INDEX[src])
        edge_index[1].append(NODE_INDEX[dst])
        out_vals[src].append((edge["request_rate"], edge["error_rate"], edge["latency_p95"]))
        in_vals[dst].append((edge["request_rate"], edge["error_rate"], edge["latency_p95"]))

    def avg(vals):
        if not vals:
            return (0.0, 0.0, 0.0)
        n = len(vals)
        return tuple(sum(v[i] for v in vals) / n for i in range(3))

    def sc(v):
        return math.log1p(v) if scale else v

    node_features = []
    for node in NODE_VOCAB:
        in_rate, in_err, in_lat = avg(in_vals[node])
        out_rate, out_err, out_lat = avg(out_vals[node])
        feats = [sc(in_rate), in_err, sc(in_lat), sc(out_rate), out_err, sc(out_lat)]
        if extra_mean_lat is not None:
            ml = extra_mean_lat.get(node, 0.0)
            feats.append(sc(ml))
        node_features.append(feats)

    y = [record["labels"].get(node, 0) for node in NODE_VOCAB]

    g = Data(
        x=torch.tensor(node_features, dtype=torch.float),
        edge_index=torch.tensor(edge_index, dtype=torch.long),
        y=torch.tensor(y, dtype=torch.float),
    )
    g.timestamp  = record["timestamp"]
    g.phase      = record["phase"]
    g.episode_id = record["episode_id"]
    g.fault_node = record["fault_node"]
    return g


# ─────────────────────────────────────────────────────────────────────────────
# 7. Load latency_mean indexed by timestamp
# ─────────────────────────────────────────────────────────────────────────────

def load_latency_mean(mean_path=MEAN_LAT_PATH):
    """
    Returns dict: timestamp_str -> {node_name: avg_mean_latency}.
    Uses destination node to assign incoming mean latency.
    """
    index = {}
    try:
        with open(mean_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                ts = row["timestamp"]
                node_lat = {}
                for edge in row.get("edges", []):
                    dst = edge.get("destination")
                    val = edge.get("latency_mean")
                    if dst in NODE_INDEX and val is not None:
                        node_lat.setdefault(dst, []).append(val)
                index[ts] = {n: sum(v)/len(v) for n, v in node_lat.items()}
    except FileNotFoundError:
        pass
    return index


# ─────────────────────────────────────────────────────────────────────────────
# 8. CLI self-check
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Loaded {len(ALL_EPISODES)} episodes:\n")
    for ep in ALL_EPISODES:
        print(f"  fold={ep['fold_index']}  id={ep['episode_id']}  "
              f"node={ep['node']:10}  delay={ep['delay_ms']:3d}ms  src={ep['source']}")
    print()
    recs = load_all_records()
    holdout_ts = build_normal_holdout_ts(recs)
    print(f"Total raw snapshots: {len(recs)}")
    print(f"Normal holdout size: {len(holdout_ts)} timestamps\n")
    print_episode_counts(recs, holdout_ts)
