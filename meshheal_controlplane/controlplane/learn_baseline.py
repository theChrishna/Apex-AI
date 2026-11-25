"""Learn a per-service normal baseline (median + MAD of incoming / outgoing latency) from fault-free snapshots.

  python -m controlplane.learn_baseline --snapshots path.jsonl --out baseline.yaml

Fault-free means the file was collected while no fault was injected. If you have a mixed file with a fault log,
pass --fault-log and only the normal windows are used (same labelling rules as the Bookinfo evaluation: lag 90 s
excluded, recovery 90 s excluded, nothing near an episode window either).

The output is a small YAML file the controller loads with --baseline. Services not in the file fall back to the
hand-set `self_lat_full_ms` scale, so a learned baseline is additive: it can cover only part of the mesh.
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime

from .snapshot import Snapshot, node_stats, parse_ts

PROTECTED = {"snapshots.jsonl", "fault_log.jsonl", "labeled_dataset.jsonl", "labeled_dataset_v2.jsonl"}


def quantile(values, q):
    """Linear-interpolation quantile (same as numpy's default), without needing numpy."""
    v = sorted(values)
    if len(v) == 1:
        return float(v[0])
    pos = q * (len(v) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return float(v[lo] + (v[hi] - v[lo]) * (pos - lo))


def envelope(values, q=0.99):
    """Median and a high quantile of normal values: the normal range the scorer tolerates."""
    return {"median": float(statistics.median(values)), "high": quantile(values, q)}


def median_and_mad(values):
    """Robust location + scale (MAD = median absolute deviation). MAD is less sensitive to a few outliers
    than the standard deviation, which matters because Istio's p95 is bucketed and a single slow request
    jumps a snapshot to the next bucket."""
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    return float(med), float(mad)


def collect_normal_stats(records):
    """{service: {"in_lat": [...], "out_lat": [...], "in_rate": [...]}} from the given records (phase=normal)."""
    bag = {}
    for r in records:
        if r.get("phase") not in ("normal", None):
            continue
        try:
            snap = Snapshot(ts=parse_ts(r["timestamp"]), nodes=r.get("nodes", []), edges=r["edges"])
        except Exception:
            continue
        for n, s in node_stats(snap).items():
            d = bag.setdefault(n, {"in_lat": [], "out_lat": [], "in_rate": []})
            if s["in_rate"] > 0:                                  # idle services say nothing about normal latency
                d["in_lat"].append(s["in_lat"])
                d["in_rate"].append(s["in_rate"])
            if s["out_rate"] > 0:
                d["out_lat"].append(s["out_lat"])
    return bag


def build_baseline(bag, min_samples=20, q=0.99):
    """{service: {"in_lat": [median, mad], ...}}. Services with too few samples are skipped (noted)."""
    out, notes = {}, []
    for svc, d in sorted(bag.items()):
        row = {}
        for kind in ("in_lat", "out_lat"):
            vals = d[kind]
            if len(vals) < min_samples:
                continue
            row[kind] = envelope(vals, q)
        if "in_lat" not in row:
            notes.append(f"{svc}: only {len(d['in_lat'])} normal in_lat samples (< {min_samples}); skipped")
            continue
        if d["in_rate"]:
            med_rate, _ = median_and_mad(d["in_rate"])
            row["in_rate_median"] = med_rate
        row["samples"] = len(d["in_lat"])
        out[svc] = row
    return out, notes


def collect_normal_edges(records, min_rate=1 / 60):
    """{"src>dst": {"lat": [...], "err": [...]}} from normal records: latency p95 and error fraction of every edge that
    carried at least min_rate req/s in that snapshot (an idle edge's p95 says nothing)."""
    from .scorer import EdgeScorer
    bag = {}
    for r in records:
        if r.get("phase") not in ("normal", None):
            continue
        for e in r.get("edges", []):
            if e.get("destination") == "unknown" or EdgeScorer.rate(e) < min_rate:
                continue
            lat = e.get("latency_p95")
            if not isinstance(lat, (int, float)) or lat != lat:
                continue
            d = bag.setdefault(EdgeScorer.key(e["source"], e["destination"]), {"lat": [], "err": []})
            d["lat"].append(float(lat))
            d["err"].append(EdgeScorer.error_fraction(e))
    return bag


def build_edges(bag, min_samples=20, q=0.99):
    out, notes = {}, []
    for k, d in sorted(bag.items()):
        if len(d["lat"]) < min_samples:
            notes.append(f"edge {k}: only {len(d['lat'])} normal samples (< {min_samples}); left to the hand-set scale")
            continue
        out[k] = {"lat": envelope(d["lat"], q), "err": envelope(d["err"], q), "samples": len(d["lat"])}
    return out, notes


def _load_records(path):
    with open(path, encoding="utf-8") as f:
        return [{**json.loads(line), "phase": "normal"} for line in f if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshots", required=True, help="snapshots JSONL to learn from")
    ap.add_argument("--fault-log", default=None, help="if set, only non-fault windows are used (topo/real.py rules)")
    ap.add_argument("--out", required=True, help="YAML file to write")
    ap.add_argument("--quantile", type=float, default=0.99, help="high quantile of normal latency that counts as still normal")
    ap.add_argument("--floor-ms", type=float, default=10.0, help="smallest normal spread (high - median) in ms")
    ap.add_argument("--min-rate", type=float, default=0.05, help="req/s a service must receive before its score may rise")
    ap.add_argument("--min-samples", type=int, default=20, help="minimum normal in_lat samples per service")
    a = ap.parse_args(argv)

    if os.path.exists(a.out):
        ap.error(f"{a.out} exists; choose another --out")
    if os.path.basename(a.out) in PROTECTED:
        ap.error(f"{a.out} is an uploaded data file name: choose another --out")

    if a.fault_log:
        try:
            sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
            from topo import real
        except ImportError:
            ap.error("--fault-log needs the repository's topo/ package (run it from a repo checkout, not the container)")
        records = real.label_records(a.snapshots, a.fault_log, "learned", keep=("normal",))
    else:
        records = _load_records(a.snapshots)

    bag = collect_normal_stats(records)
    base, notes = build_baseline(bag, min_samples=a.min_samples, q=a.quantile)
    edges, edge_notes = build_edges(collect_normal_edges(records), min_samples=a.min_samples, q=a.quantile)
    notes += edge_notes
    if not base:
        print(f"no baselines learned: {len(records)} records, bag keys {list(bag)}; notes:", file=sys.stderr)
        for n in notes:
            print(f"  {n}", file=sys.stderr)
        sys.exit(1)

    import yaml
    header = (f"# Learned by controlplane.learn_baseline on {datetime.utcnow().isoformat()}Z\n"
              f"# Source: {a.snapshots} (fault log: {a.fault_log or 'none'})  records={len(records)}  services={len(base)}\n"
              f"# services: median and q{a.quantile} (ms) of a service's rate-weighted incoming / outgoing latency (--scorer baseline)\n"
              f"# edges:    median and q{a.quantile} of each edge's latency p95 (ms) and error fraction (--scorer edge)\n"
              "# All from NORMAL traffic. A service or edge not listed falls back to the hand-set scale.\n")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump({"method": f"envelope-q{a.quantile}", "floor_ms": a.floor_ms, "min_rate": a.min_rate,
                        "err_floor": 0.05, "edge_min_rate": round(1 / 60, 6),
                        "services": base, "edges": edges}, f, sort_keys=False)
    print(f"wrote {a.out}: {len(base)} service(s) and {len(edges)} edge(s) with baselines, "
          f"from {sum(len(d['in_lat']) for d in bag.values())} samples", file=sys.stderr)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
