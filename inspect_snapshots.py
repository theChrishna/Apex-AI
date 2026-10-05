import json

with open("snapshots.jsonl") as f:
    for line in f:
        record = json.loads(line)
        for edge in record["edges"]:
            if edge["source"] == "reviews" and edge["destination"] == "ratings":
                print(record["timestamp"], "->", edge["latency_p95"])