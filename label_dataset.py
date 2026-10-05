import json
from datetime import datetime, timezone

FAULT_WINDOWS = [
    (datetime(2026, 10, 4, 9, 49, 2, tzinfo=timezone.utc),
     datetime(2026, 10, 4, 10, 3, 48, tzinfo=timezone.utc)),
]

FAULT_NODE = "ratings"

def is_in_fault_window(timestamp):
    for start, end in FAULT_WINDOWS:
        if start <= timestamp <= end:
            return True
    return False

def label_snapshot(record):
    timestamp = datetime.fromisoformat(record["timestamp"])
    anomalous_now = is_in_fault_window(timestamp)

    if "nodes" in record:
        node_ids = [node["id"] for node in record["nodes"]]
    else:
        node_ids = set()
        for edge in record["edges"]:
            node_ids.add(edge["source"])
            node_ids.add(edge["destination"])
        node_ids = sorted(node_ids)

    labels = {}
    for node_id in node_ids:
        labels[node_id] = 1 if (anomalous_now and node_id == FAULT_NODE) else 0

    return labels

def build_labeled_dataset(input_path="snapshots.jsonl", output_path="labeled_dataset.jsonl"):
    count_total = 0
    count_anomalous_nodes = 0

    with open(input_path) as infile, open(output_path, "w") as outfile:
        for line in infile:
            record = json.loads(line)
            labels = label_snapshot(record)

            labeled_record = {
                "timestamp": record["timestamp"],
                "nodes": record.get("nodes", [{"id": n, "region": "unknown"} for n in labels.keys()]),
                "edges": record["edges"],
                "labels": labels
            }

            outfile.write(json.dumps(labeled_record) + "\n")

            count_total += 1
            count_anomalous_nodes += sum(labels.values())

    print(f"Processed {count_total} snapshots.")
    print(f"Total anomalous node-labels: {count_anomalous_nodes}")

if __name__ == "__main__":
    build_labeled_dataset()