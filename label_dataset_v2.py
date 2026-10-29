"""
label_dataset_v2.py  –  Task 1
-------------------------------
Builds labeled_dataset_v2.jsonl from snapshots.jsonl with:
  - Both fault windows correctly labelled
  - Snapshots in the 75 s *after* each window excluded (recovery blur)
  - Snapshots in the first 90 s of each window labelled 1 but flagged
    with "lagged": true  (telemetry hasn't fully risen yet)
  - All other snapshots labelled normally (fault node = 1, rest = 0)

Usage:
    python label_dataset_v2.py
"""

import json
from datetime import datetime, timezone, timedelta

# ---------- Ground-truth fault windows ----------
# Each tuple: (window_start, window_end, fault_node)
FAULT_WINDOWS = [
    (
        datetime(2026, 10, 4, 9, 49, 2,  tzinfo=timezone.utc),
        datetime(2026, 10, 4, 10, 3, 48, tzinfo=timezone.utc),
        "ratings",
    ),
    (
        datetime(2026, 10, 9, 7, 43, 57, tzinfo=timezone.utc),
        datetime(2026, 10, 9, 7, 48, 25, tzinfo=timezone.utc),
        "details",
    ),
]

# How long after a window ends to discard (metrics still decaying)
RECOVERY_BUFFER = timedelta(seconds=75)
# How long into a window metrics are still rising (label 1 but flag lagged)
LAG_DURATION    = timedelta(seconds=90)


def classify_snapshot(ts: datetime):
    """
    Returns (action, fault_node, lagged) where:
      action = "exclude"  -> skip this snapshot entirely
      action = "normal"   -> label all nodes 0
      action = "fault"    -> label fault_node = 1, others = 0
                             lagged=True if within first 90 s of window
    """
    for (start, end, node) in FAULT_WINDOWS:
        # Recovery blur: exclude snapshots just after the window
        if end < ts <= end + RECOVERY_BUFFER:
            return "exclude", None, False
        # Inside fault window
        if start <= ts <= end:
            lagged = ts < start + LAG_DURATION
            return "fault", node, lagged
    return "normal", None, False


def build_labeled_dataset_v2(
    input_path="snapshots.jsonl",
    output_path="labeled_dataset_v2.jsonl",
):
    from build_graph_dataset import NODE_VOCAB  # reuse canonical node list

    counts = {"total": 0, "excluded": 0, "written": 0}
    pos_counts = {node: 0 for node in NODE_VOCAB}

    with open(input_path) as infile, open(output_path, "w") as outfile:
        for line in infile:
            record = json.loads(line)
            counts["total"] += 1

            ts = datetime.fromisoformat(record["timestamp"])
            action, fault_node, lagged = classify_snapshot(ts)

            if action == "exclude":
                counts["excluded"] += 1
                continue

            # Build node list (same logic as original label_dataset.py)
            if "nodes" in record:
                node_ids = [n["id"] for n in record["nodes"]]
            else:
                node_ids = sorted(
                    {e["source"] for e in record["edges"]}
                    | {e["destination"] for e in record["edges"]}
                )

            labels = {}
            for nid in node_ids:
                if action == "fault" and nid == fault_node:
                    labels[nid] = 1
                else:
                    labels[nid] = 0

            labeled_record = {
                "timestamp": record["timestamp"],
                "nodes": record.get(
                    "nodes",
                    [{"id": n, "region": "unknown"} for n in node_ids],
                ),
                "edges": record["edges"],
                "labels": labels,
            }
            if lagged:
                labeled_record["lagged"] = True

            outfile.write(json.dumps(labeled_record) + "\n")
            counts["written"] += 1
            for nid, lbl in labels.items():
                if lbl == 1 and nid in pos_counts:
                    pos_counts[nid] += 1

    print(f"Input snapshots   : {counts['total']}")
    print(f"Excluded (recovery): {counts['excluded']}")
    print(f"Written           : {counts['written']}")
    print("\nPositive labels per node:")
    for node in NODE_VOCAB:
        print(f"  {node:15s}  {pos_counts[node]}")


if __name__ == "__main__":
    build_labeled_dataset_v2()
