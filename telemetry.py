import requests
import math
import json
import time
from datetime import datetime, timezone
import subprocess

PROMETHEUS_URL = "http://localhost:9090"

def get_nodes(namespace="aws-us-east"):
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", namespace, "-l", "app",
         "-o", "jsonpath={.items[*].metadata.labels.app}"],
        capture_output=True, text=True
    )
    app_names = sorted(set(result.stdout.split()))
    return [{"id": name, "region": namespace} for name in app_names]

def is_snapshot_valid(edge):
    for field in ["request_rate", "error_rate", "latency_p95"]:
        value = edge[field]
        if value is None or math.isnan(value):
            return False
    return True

def save_snapshot(nodes, edges, filepath="snapshots.jsonl"):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nodes": nodes,
        "edges": edges
    }
    with open(filepath, "a") as f:
        f.write(json.dumps(record) + "\n")

def query_prometheus(promql_query):
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": promql_query}
    )
    return response.json()

def parse_edge_metric(prom_response):
    edges = []
    for series in prom_response["data"]["result"]:
        source = series["metric"].get("source_app", "unknown")
        destination = series["metric"].get("destination_app", "unknown")
        value = float(series["value"][1])
        edges.append({"source": source, "destination": destination, "value": value})
    return edges

def get_request_rate():
    query = 'sum(rate(istio_requests_total{reporter="destination", source_workload_namespace="aws-us-east"}[1m])) by (source_app, destination_app)'
    return parse_edge_metric(query_prometheus(query))

def get_error_rate():
    query = 'sum(rate(istio_requests_total{reporter="destination", source_workload_namespace="aws-us-east", response_code=~"5.*"}[1m])) by (source_app, destination_app)'
    return parse_edge_metric(query_prometheus(query))

def get_latency_p95():
    query = 'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket{reporter="source", source_workload_namespace="aws-us-east"}[1m])) by (le, source_app, destination_app))'
    return parse_edge_metric(query_prometheus(query))

def build_graph_snapshot():
    request_rates = get_request_rate()
    error_rates = get_error_rate()
    latencies = get_latency_p95()

    snapshot = {}

    def add_metric(edge_list, field_name):
        for edge in edge_list:
            key = (edge["source"], edge["destination"])
            if key not in snapshot:
                snapshot[key] = {"source": edge["source"], "destination": edge["destination"]}
            snapshot[key][field_name] = edge["value"]

    add_metric(request_rates, "request_rate")
    add_metric(error_rates, "error_rate")
    add_metric(latencies, "latency_p95")

    edges = list(snapshot.values())
    for edge in edges:
        edge.setdefault("request_rate", 0.0)
        edge.setdefault("error_rate", 0.0)
        edge.setdefault("latency_p95", 0.0)

    nodes = get_nodes()

    return {"nodes": nodes, "edges": edges}

if __name__ == "__main__":
    POLL_INTERVAL_SECONDS = 15

    print(f"Starting telemetry loop, polling every {POLL_INTERVAL_SECONDS}s. Press Ctrl+C to stop.")

    try:
        while True:
            graph = build_graph_snapshot()
            valid_edges = [e for e in graph["edges"] if is_snapshot_valid(e)]
            skipped = len(graph["edges"]) - len(valid_edges)

            if valid_edges:
                save_snapshot(graph["nodes"], valid_edges)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved {len(graph['nodes'])} nodes, {len(valid_edges)} edges ({skipped} skipped)")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No valid edges this cycle, nothing saved")

            time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopped by user.")
