"""
run_faults.py - runs a schedule of fault-injection episodes and records ground truth.

Before running, start these in other terminals (same as for earlier data collection):
    - kubectl port-forward for productpage (9080) and prometheus (9090)
    - python traffic_gen.py
    - python telemetry.py

Usage:
    python run_faults.py --dry-run   # prints the plan only, touches nothing
    python run_faults.py             # real run (about 55 minutes)

What it writes:
    fault_log.jsonl     one line per episode: node, delay, exact start/end (UTC).
                        This is the ground truth used for labeling later.
    latency_mean.jsonl  mean latency per edge every 15s (an extra feature that is
                        not affected by Prometheus histogram buckets).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

NAMESPACE = "aws-us-east"
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
FAULT_LOG = "fault_log.jsonl"
MEAN_LOG = "latency_mean.jsonl"
POLL_SECONDS = 15

# (node, injected delay in ms). Each node appears twice with two different delays,
# and no two episodes in a row hit the same node. productpage is left out because
# our traffic enters through port-forward, so no caller sidecar exists to delay it.
SCHEDULE = [
    ("reviews", 100),
    ("details", 50),
    ("ratings", 100),
    ("reviews", 200),
    ("details", 200),
    ("ratings", 50),
]

# Mean latency per edge = total time / number of requests (both from Istio's histogram).
# Same labels as the p95 query in telemetry.py (reporter="source").
MEAN_QUERY = (
    'sum(rate(istio_request_duration_milliseconds_sum'
    '{reporter="source", source_workload_namespace="%s"}[1m])) by (source_app, destination_app)'
    ' / '
    'sum(rate(istio_request_duration_milliseconds_count'
    '{reporter="source", source_workload_namespace="%s"}[1m])) by (source_app, destination_app)'
) % (NAMESPACE, NAMESPACE)


def now_iso():
    """Current UTC time in the same format telemetry.py uses for snapshots."""
    return datetime.now(timezone.utc).isoformat()


def clock():
    """Short local time for progress messages."""
    return datetime.now().strftime("%H:%M:%S")


def fault_yaml(node, delay_ms):
    """Istio VirtualService that delays 100% of requests to `node`."""
    return f"""apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: {node}
spec:
  hosts:
  - {node}
  http:
  - fault:
      delay:
        percentage:
          value: 100.0
        fixedDelay: {delay_ms}ms
    route:
    - destination:
        host: {node}
"""


def kubectl(args, stdin_text=None):
    """Run a kubectl command and return the finished process."""
    return subprocess.run(["kubectl"] + args, input=stdin_text,
                          capture_output=True, text=True)


def apply_fault(node, delay_ms):
    result = kubectl(["apply", "-n", NAMESPACE, "-f", "-"], fault_yaml(node, delay_ms))
    if result.returncode != 0:
        raise RuntimeError("kubectl apply failed: " + result.stderr)


def remove_fault(node):
    result = kubectl(["delete", "virtualservice", node, "-n", NAMESPACE, "--ignore-not-found"])
    if result.returncode != 0:
        print(f"!! WARNING: could not delete VirtualService '{node}': {result.stderr}")
        print(f"!! Remove it by hand: kubectl delete virtualservice {node} -n {NAMESPACE}")


def query_prometheus(query):
    response = requests.get(PROMETHEUS_URL + "/api/v1/query",
                            params={"query": query}, timeout=10)
    response.raise_for_status()
    return response.json()["data"]["result"]


def valid_edges(results):
    """Turn a Prometheus result into edge dicts, skipping NaN values."""
    edges = []
    for item in results:
        value = float(item["value"][1])
        if math.isnan(value):
            continue
        edges.append({
            "source": item["metric"]["source_app"],
            "destination": item["metric"]["destination_app"],
            "latency_mean": value,
        })
    return edges


def log_mean_latency():
    """Append the current mean latency of every edge to latency_mean.jsonl."""
    try:
        edges = valid_edges(query_prometheus(MEAN_QUERY))
    except (requests.exceptions.RequestException, KeyError, ValueError) as error:
        print(f"  (mean latency query failed this cycle: {error})")
        return
    with open(MEAN_LOG, "a") as f:
        f.write(json.dumps({"timestamp": now_iso(), "edges": edges}) + "\n")


def wait_and_log(minutes, label):
    """Wait `minutes`, logging mean latency every POLL_SECONDS."""
    print(f"[{clock()}] {label} ({minutes} min)")
    end = time.time() + minutes * 60
    while time.time() < end:
        log_mean_latency()
        time.sleep(max(0, min(POLL_SECONDS, end - time.time())))


def preflight():
    """Stop early if the setup would give bad data."""
    result = kubectl(["get", "virtualservice", "-n", NAMESPACE, "-o", "name"])
    if result.returncode != 0:
        sys.exit("kubectl failed (is the cluster up?): " + result.stderr)
    existing = {line.split("/")[-1] for line in result.stdout.split()}
    leftovers = sorted({node for node, _ in SCHEDULE} & existing)
    if leftovers:
        sys.exit("A fault rule is already active for: " + ", ".join(leftovers) +
                 f"\nDelete it first, e.g.: kubectl delete virtualservice {leftovers[0]} -n {NAMESPACE}")

    try:
        edges = valid_edges(query_prometheus(MEAN_QUERY))
    except requests.exceptions.RequestException as error:
        sys.exit(f"Cannot reach Prometheus at {PROMETHEUS_URL}. Is the port-forward running? ({error})")
    if not edges:
        sys.exit("Prometheus has no recent latency data. Is traffic_gen.py running?")
    print(f"Preflight OK: no leftover fault rules, {len(edges)} edges have live latency data.")


def run_episode(number, total, node, delay_ms, fault_minutes, recovery_minutes):
    print(f"\n=== Episode {number}/{total}: {node} +{delay_ms}ms ===")
    try:
        apply_fault(node, delay_ms)
    except RuntimeError:
        remove_fault(node)   # make sure nothing half-applied stays behind
        raise
    start = now_iso()
    completed = False
    try:
        wait_and_log(fault_minutes, f"FAULT ACTIVE on {node}")
        completed = True
    finally:
        # Runs even on Ctrl+C or a crash, so a fault rule is never left behind.
        remove_fault(node)
        end = now_iso()
        record = {"episode": number, "node": node, "delay_ms": delay_ms,
                  "start": start, "end": end, "completed": completed}
        with open(FAULT_LOG, "a") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[{clock()}] Fault removed, episode logged (completed={completed})")
    wait_and_log(recovery_minutes, "recovery, no fault")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--baseline-minutes", type=float, default=3)
    parser.add_argument("--fault-minutes", type=float, default=5)
    parser.add_argument("--recovery-minutes", type=float, default=3)
    args = parser.parse_args()

    total_minutes = args.baseline_minutes + len(SCHEDULE) * (args.fault_minutes + args.recovery_minutes)
    print(f"Plan: {args.baseline_minutes:g} min baseline, then {len(SCHEDULE)} episodes of "
          f"{args.fault_minutes:g} min fault + {args.recovery_minutes:g} min recovery "
          f"(about {total_minutes:.0f} min total)")
    for i, (node, delay_ms) in enumerate(SCHEDULE, 1):
        print(f"  {i}. {node:8s} +{delay_ms}ms")

    if args.dry_run:
        print("\nDry run only. YAML for episode 1 would be:\n")
        print(fault_yaml(*SCHEDULE[0]))
        return

    preflight()
    try:
        wait_and_log(args.baseline_minutes, "baseline, no fault")
        for i, (node, delay_ms) in enumerate(SCHEDULE, 1):
            run_episode(i, len(SCHEDULE), node, delay_ms,
                        args.fault_minutes, args.recovery_minutes)
        print(f"\n[{clock()}] All episodes done. Ground truth is in {FAULT_LOG}.")
        print("Let telemetry.py run for another minute, then stop it with Ctrl+C.")
    except KeyboardInterrupt:
        print("\nInterrupted. Any active fault rule was removed; check fault_log.jsonl for the last episode.")


if __name__ == "__main__":
    main()
