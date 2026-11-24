"""Generic telemetry collector: writes the same snapshot format as ../telemetry.py, for any namespace.

  python -m controlplane.collect --namespace my-ns --prometheus-url http://localhost:9090 --out snapshots_my-ns.jsonl

Writes only to --out (append). It never touches the cluster. Refuses to write to the uploaded data file.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone

from .discovery import discover_edges, nodes_from_edges, prom_query_fn, valid_edge

PROTECTED = {"snapshots.jsonl", "fault_log.jsonl"}


def build_snapshot(query, ns, window="1m", now=None):
    """One snapshot dict, or None when no edge has finite metrics yet (idle mesh / Prometheus warming up)."""
    edges = discover_edges(query, ns, window)
    ok = [e for e in edges if valid_edge(e)]
    if not ok:
        return None
    return {"timestamp": (now or datetime.now(timezone.utc)).isoformat(),
            "nodes": nodes_from_edges(ok, ns), "edges": ok, "skipped_edges": len(edges) - len(ok)}


def append_snapshot(path, snap):
    snap = {k: v for k, v in snap.items() if k != "skipped_edges"}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--prometheus-url", default="http://localhost:9090")
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--once", action="store_true", help="collect one snapshot and exit")
    a = ap.parse_args(argv)
    if os.path.basename(a.out) in PROTECTED:
        ap.error(f"{a.out} is an uploaded data file: choose another --out")
    query = prom_query_fn(a.prometheus_url)
    while True:
        try:
            snap = build_snapshot(query, a.namespace)
            if snap:
                append_snapshot(a.out, snap)
                print(f"[{datetime.now():%H:%M:%S}] saved {len(snap['nodes'])} nodes, {len(snap['edges'])} edges "
                      f"({snap['skipped_edges']} skipped)", flush=True)
            else:
                print(f"[{datetime.now():%H:%M:%S}] no valid edges yet", flush=True)
        except Exception as e:                      # Prometheus down etc.: keep the loop alive
            print(f"collect error: {e!r}", flush=True)
        if a.once:
            return
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
