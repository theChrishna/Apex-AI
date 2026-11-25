"""Label real snapshots from a fault log, with exactly the rules used for Bookinfo (build_dataset_v2.py):

  lag       [start, start+90s)   excluded (rate window still rising)
  steady    [start+90s, end]     only the faulted node is positive (label 1), every other node 0
  recovery  (end, end+90s]       excluded (metrics still decaying)
  normal    everything else      all nodes 0

Snapshots near an episode (within `leak_buffer` of any window) but not inside lag/steady/recovery are dropped from
`normal` when `strict_normal=True`, so a slow tail after an episode is not counted as healthy traffic.
Input: a snapshots JSONL (collect.py format) and a fault log JSONL ({"episode","node","delay_ms","start","end","completed"}).
"""
import json
from datetime import datetime, timedelta

LAG = timedelta(seconds=90)
RECOVERY = timedelta(seconds=90)
LEAK = timedelta(seconds=120)


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_episodes(fault_log):
    eps = []
    for row in load_jsonl(fault_log):
        if row.get("completed", False):
            eps.append({"id": str(row["episode"]), "node": row["node"], "delay_ms": row.get("delay_ms", 0),
                        "type": row.get("type", "delay"), "param": row.get("param", row.get("delay_ms")),
                        "start": _ts(row["start"]), "end": _ts(row["end"])})
    return sorted(eps, key=lambda e: e["start"])


def classify(ts, episodes, lag=LAG, recovery=RECOVERY, leak=LEAK, strict_normal=True):
    """(phase, episode_id, fault_node) for a timestamp."""
    for ep in episodes:
        s, e = ep["start"], ep["end"]
        if s <= ts < s + lag:
            return "lag", ep["id"], ep["node"]
        if s + lag <= ts <= e:
            return "steady", ep["id"], ep["node"]
        if e < ts <= e + recovery:
            return "recovery", ep["id"], ep["node"]
    if strict_normal and any(ep["start"] - leak <= ts <= ep["end"] + recovery + leak for ep in episodes):
        return "near", None, None
    return "normal", None, None


def label_records(snapshots_path, fault_log_path, topology, family="real", keep=("steady", "normal"), **kw):
    """Snapshots as labelled records (phases not in `keep` are dropped)."""
    episodes = load_episodes(fault_log_path)
    out = []
    for raw in load_jsonl(snapshots_path):
        phase, ep_id, node = classify(_ts(raw["timestamp"]), episodes, **kw)
        if phase not in keep:
            continue
        ids = [n["id"] for n in raw["nodes"]]
        out.append({**raw, "phase": phase, "episode_id": ep_id, "fault_node": node, "topology": topology,
                    "family": family, "labels": {n: int(phase == "steady" and n == node) for n in ids}})
    return out


def normal_records(snapshots_path, topology, family="real", skip_first=2):
    """Records from a fault-free collection: every snapshot is phase "normal" with all labels 0.
    The first `skip_first` snapshots are dropped (the Prometheus rate window is still warming up)."""
    out = []
    for raw in load_jsonl(snapshots_path)[skip_first:]:
        ids = [n["id"] for n in raw["nodes"]]
        out.append({**raw, "phase": "normal", "episode_id": None, "fault_node": None, "topology": topology,
                    "family": family, "labels": {n: 0 for n in ids}})
    return out

