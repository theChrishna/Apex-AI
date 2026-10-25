"""Snapshot reading + validation (FR-2.4: reject stale / NaN / incomplete input)."""
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone


class BadSnapshot(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Snapshot:
    ts: datetime
    nodes: list
    edges: list


def parse_ts(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_snapshot(obj, expected_nodes=()):
    try:
        ts = parse_ts(obj["timestamp"])
        nodes, edges = obj["nodes"], obj["edges"]
    except (KeyError, ValueError, TypeError) as e:
        raise BadSnapshot(f"malformed: {e}")
    ids = {n["id"] for n in nodes}
    missing = [n for n in expected_nodes if n not in ids]
    if missing:
        raise BadSnapshot(f"missing_nodes:{','.join(missing)}")
    for e in edges:
        for k in ("request_rate", "error_rate", "latency_p95"):
            v = e.get(k)
            if v is None or not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
                # NaN latency on an idle edge is normal (no samples); anything else is bad input.
                if k == "latency_p95" and (e.get("request_rate") or 0) == 0:
                    e[k] = 0.0
                    continue
                raise BadSnapshot(f"non_finite:{e.get('source')}->{e.get('destination')}:{k}")
    return Snapshot(ts=ts, nodes=nodes, edges=edges)


def read_last_snapshot(path, expected_nodes=()):
    """Return the newest snapshot in a JSONL file (tail read; the file can be large)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = f.read().splitlines()
    except OSError as e:
        raise BadSnapshot(f"unreadable:{e}")
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            return parse_snapshot(json.loads(raw), expected_nodes)
        except json.JSONDecodeError:
            continue  # partially written last line: fall back to the previous one
    raise BadSnapshot("empty")


def node_stats(snap):
    """Per-node rate-weighted incoming/outgoing latency (ms), rates and error rates."""
    stats = {n["id"]: dict(in_rate=0.0, in_lat=0.0, in_err=0.0, out_rate=0.0, out_lat=0.0)
             for n in snap.nodes}
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # in: r, r*lat, r*err | out: r, r*lat, r*err
    for e in snap.edges:
        s, d, r = e["source"], e["destination"], e["request_rate"]
        if d in stats:
            a = acc[d]; a[0] += r; a[1] += r * e["latency_p95"]; a[2] += r * e["error_rate"]
        if s in stats:
            a = acc[s]; a[3] += r; a[4] += r * e["latency_p95"]; a[5] += r * e["error_rate"]
    for n, a in acc.items():
        st = stats[n]
        st["in_rate"], st["out_rate"] = a[0], a[3]
        st["in_lat"] = a[1] / a[0] if a[0] > 0 else 0.0
        st["in_err"] = a[2] / a[0] if a[0] > 0 else 0.0
        st["out_lat"] = a[4] / a[3] if a[3] > 0 else 0.0
    return stats
