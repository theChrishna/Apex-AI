#!/usr/bin/env python3
"""MeshHeal read-only local API for the dashboard (stdlib only; never writes anything).

  LIVE   : tails shadow_run/snapshots.jsonl and the audit files; "age" values are real wall-clock ages,
           so a stopped telemetry or controller shows up as stale.
  REPLAY : plays back shadow_run/snapshots.jsonl + audit_rule.jsonl + audit_gnn.jsonl between
           2026-10-26T05:48:25Z and 2026-10-26T07:02:26Z (the shadow run) at 1x or 10x. Always labelled REPLAY.

Per-node risk shown by the dashboard is the RULE score computed from the snapshot with the control plane's own
node_stats() and RuleScorer; the audit files only hold the TOP node's risk per scorer, never per-node GNN scores.

  python Frontend_v2/api/meshheal_api.py --mode live            # then open http://127.0.0.1:8765
  python Frontend_v2/api/meshheal_api.py --mode replay --speed 10
"""
import argparse
import json
import math
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIST = HERE.parent / "dist"
sys.path.insert(0, str(ROOT / "meshheal_controlplane"))
try:
    from controlplane.scorer import RuleScorer
    from controlplane.snapshot import BadSnapshot, node_stats, parse_snapshot
except Exception as e:   # the API still serves raw data without the control plane package
    RuleScorer = None
    IMPORT_ERROR = repr(e)
else:
    IMPORT_ERROR = None

NODES = ("productpage", "details", "reviews", "ratings")
REPLAY_START = datetime(2026, 10, 26, 5, 48, 25, tzinfo=timezone.utc)
REPLAY_END = datetime(2026, 10, 26, 7, 2, 26, tzinfo=timezone.utc)
STALE_S = 45.0
SHOWN_EVENTS = ("REROUTE", "ACTION_BLOCKED", "SUPPRESSED_VICTIM", "PROBE_START", "PROBE_FAILED", "RELEASE", "SNAPSHOT_REJECTED")


def ts_of(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def tail_lines(path, nbytes):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            data = f.read()
    except OSError:
        return []
    lines = data.splitlines()
    if size > nbytes:
        lines = lines[1:]   # first line may be cut
    return lines


def load_jsonl(path, tail_bytes=None):
    rows = []
    lines = tail_lines(path, tail_bytes) if tail_bytes else (Path(path).read_bytes().splitlines() if Path(path).exists() else [])
    for raw in lines:
        raw = raw.strip()
        if raw:
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError:
                pass   # partially written last line
    return rows


def newest_match(path):
    """An audit path may contain `*` (e.g. live_demo/audit_*.jsonl): use the most recently modified match."""
    if "*" not in str(path):
        return path
    hits = sorted(ROOT.glob(str(Path(path).relative_to(ROOT))), key=lambda f: f.stat().st_mtime)
    return hits[-1] if hits else path


def snapshot_view(raw):
    """One snapshot -> dashboard dict. Risk is the rule score (labelled as such in the UI)."""
    out = {"ts": raw["timestamp"], "edges": [{k: e.get(k) for k in ("source", "destination", "request_rate", "error_rate", "latency_p95")} for e in raw.get("edges", [])],
           "valid": True, "reject_reason": None, "nodes": {}}
    if RuleScorer is None:
        out.update(valid=False, reject_reason=f"controlplane import failed: {IMPORT_ERROR}")
        return out
    try:
        snap = parse_snapshot(json.loads(json.dumps(raw)), NODES)
    except BadSnapshot as e:
        out.update(valid=False, reject_reason=e.reason)
        return out
    stats = node_stats(snap)
    risk = RuleScorer(100.0).score(stats)
    for n in NODES:
        s = stats.get(n)
        if s:
            out["nodes"][n] = {"risk_rule": round(risk[n], 3), "in_lat": round(s["in_lat"], 1), "out_lat": round(s["out_lat"], 1),
                               "in_rate": round(s["in_rate"], 3), "in_err": round(s["in_err"], 4)}
    return out


def fold_mesh_state(events):
    """NORMAL / REROUTED / PROBING per culprit, folded from audit events in time order."""
    active = {}
    for e in events:
        k, c = e["event"], e.get("culprit") or e.get("node")
        if k == "REROUTE":
            active[c] = "REROUTED"
        elif k == "PROBE_START":
            active[c] = "PROBING"
        elif k == "PROBE_FAILED":
            active[c] = "REROUTED"
        elif k == "RELEASE":
            active.pop(c, None)
    if not active:
        return {"state": "NORMAL", "culprits": {}}
    state = "PROBING" if "PROBING" in active.values() else "REROUTED"
    return {"state": state, "culprits": active}


class Data:
    def __init__(self, args):
        self.args = args
        self.snap_path = ROOT / args.snapshots
        self.streams = {}
        for item in args.audit:
            name, _, p = item.partition("=")
            self.streams[name] = ROOT / p
        self.lock = threading.Lock()
        self.mode = args.mode
        self.speed = args.speed
        self.replay_anchor = time.time()       # wall-clock moment when replay position == replay_pos0
        self.replay_pos0 = REPLAY_START
        self._replay_cache = None

    # ---------------------------------------------------------------- replay
    def replay_data(self):
        if self._replay_cache is None:
            snaps = [r for r in load_jsonl(self.snap_path) if REPLAY_START <= ts_of(r["timestamp"]) <= REPLAY_END]
            audits = {}
            for name, p in self.streams.items():
                audits[name] = [dict(e, _t=ts_of(e["ts"])) for e in load_jsonl(newest_match(p)) if REPLAY_START <= ts_of(e["ts"]) <= REPLAY_END]
            self._replay_cache = (snaps, audits)
        return self._replay_cache

    def replay_pos(self):
        span = (REPLAY_END - REPLAY_START).total_seconds()
        el = ((time.time() - self.replay_anchor) * self.speed) % span
        off = (self.replay_pos0 - REPLAY_START).total_seconds()
        return REPLAY_START.fromtimestamp(REPLAY_START.timestamp() + (off + el) % span, tz=timezone.utc)

    def control(self, q):
        with self.lock:
            if "speed" in q:
                cur = self.replay_pos()
                self.speed = 10.0 if q["speed"][0] == "10" else 1.0
                self.replay_pos0, self.replay_anchor = cur, time.time()
            if "restart" in q:
                self.replay_pos0, self.replay_anchor = REPLAY_START, time.time()

    # ---------------------------------------------------------------- state
    def state(self):
        now_wall = datetime.now(timezone.utc)
        replay = self.mode == "replay"
        if replay:
            snaps, audits = self.replay_data()
            pos = self.replay_pos()
            now = pos
            shown = [r for r in snaps if ts_of(r["timestamp"]) <= pos][-90:]
            all_ev = {n: [e for e in ev if e["_t"] <= pos] for n, ev in audits.items()}
        else:
            now = now_wall
            shown = load_jsonl(self.snap_path, 160_000)[-90:]
            all_ev = {n: [dict(e, _t=ts_of(e["ts"])) for e in load_jsonl(newest_match(p), 400_000)] for n, p in self.streams.items()}

        series = [snapshot_view(r) for r in shown]
        last = series[-1] if series else None
        snap_age = (now - ts_of(last["ts"])).total_seconds() if last else None

        streams, events = [], []
        for name, evs in all_ev.items():
            scored = [e for e in evs if e["event"] == "SCORED"]
            ls = scored[-1] if scored else None
            age = (now - ls["_t"]).total_seconds() if ls else None
            streams.append({"name": name, "path": str(newest_match(self.streams[name]).relative_to(ROOT)), "last_scored": ({k: v for k, v in ls.items() if k != "_t"} if ls else None),
                            "age_s": None if age is None else round(age, 1), "stale": age is None or age > STALE_S,
                            "fallback_scored": sum(1 for e in scored if e.get("source") == "fallback"), "scored_total": len(scored),
                            "dry_run": (ls or {}).get("dry_run")})
            cur = None   # most recent SCORED in this stream: gives each event its scorer source / fallback note
            for e in evs:
                if e["event"] == "SCORED":
                    cur = e
                    if e.get("source") == "fallback":   # fallback scoring is itself an incident worth listing
                        events.append(dict({k: v for k, v in e.items() if k != "_t"}, stream=name, scorer_source="fallback", scorer_note=e.get("note"), _t=e["_t"]))
                elif e["event"] in SHOWN_EVENTS:
                    events.append(dict({k: v for k, v in e.items() if k != "_t"}, stream=name, _t=e["_t"],
                                       scorer_source=cur.get("source") if cur else None, scorer_note=(cur or {}).get("note")))
        events.sort(key=lambda e: e["_t"])
        mesh = {}
        for name, evs in all_ev.items():
            mesh[name] = fold_mesh_state(sorted((e for e in evs if e["event"] in SHOWN_EVENTS), key=lambda e: e["_t"]))
        for e in events:
            e.pop("_t")
        fresh = [s for s in streams if not s["stale"]]
        in_use = (min(fresh, key=lambda s: s["age_s"]) if fresh else None)
        used_source = in_use["last_scored"]["source"] if in_use else None
        return {
            "mode": self.mode.upper(),
            "label": "REPLAY of the 2026-10-26 shadow run (05:48:25Z-07:02:26Z), not live data" if replay else "LIVE from files in the repo",
            "now": now.isoformat(), "wall_now": now_wall.isoformat(),
            "replay": ({"speed": self.speed, "start": REPLAY_START.isoformat(), "end": REPLAY_END.isoformat(), "pos": now.isoformat()} if replay else None),
            "status": {"snapshot_age_s": None if snap_age is None else round(snap_age, 1), "snapshot_stale": snap_age is None or snap_age > STALE_S,
                       "scorer_in_use": in_use["name"] if in_use else None,
                       "scorer_source": (("GNN" if used_source == "primary" else "FALLBACK (rule)") if in_use["name"] == "gnn" else "RULE (no GNN in this stream)") if in_use else None,
                       "controller_running": bool(fresh), "note": None if fresh else "no audit stream has a SCORED event in the last 45 s: the controllers are not running"},
            "snapshot": last, "series": [{"ts": s["ts"], "risk": {n: v["risk_rule"] for n, v in s["nodes"].items()}} for s in series],
            "mesh": mesh, "streams": streams, "events": events[-300:],
            "import_error": IMPORT_ERROR,
        }

    # ---------------------------------------------------------------- evaluation tables
    def evaluation(self):
        files = {"loeo": "results_loeo.md", "controls": "results_controls.md", "shadow": "shadow_run/results_shadow.md", "policy": "results_policy.md"}
        out = {}
        for k, rel in files.items():
            p = ROOT / rel
            out[k] = {"file": rel, "tables": md_tables(p) if p.exists() else [], "missing": not p.exists()}
        return out


def md_tables(path):
    """Every markdown table with the nearest heading above it. Cell text is passed through unchanged."""
    tables, heading, cur = [], "", None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            heading, cur = line.lstrip("#").strip(), None
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cur is None:
                cur = {"heading": heading, "header": cells, "rows": []}
                tables.append(cur)
            elif all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            else:
                cur["rows"].append(cells)
        else:
            cur = None
    return tables


class Handler(BaseHTTPRequestHandler):
    data: Data = None

    def log_message(self, fmt, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/state":
                return self._json(self.data.state())
            if u.path == "/api/evaluation":
                return self._json(self.data.evaluation())
            if u.path == "/api/replay/control":
                if self.data.mode != "replay":
                    return self._json({"error": "not in replay mode"}, 400)
                self.data.control(parse_qs(u.query))
                return self._json({"ok": True, "speed": self.data.speed})
            if u.path.startswith("/api/"):
                return self._json({"error": "unknown endpoint"}, 404)
            return self._static(u.path)
        except Exception as e:   # never take the server down on one bad read
            return self._json({"error": repr(e)}, 500)

    def _static(self, path):
        if not DIST.exists():
            return self._json({"error": "no build found: run `npm run build` in Frontend_v2, or use `npm run dev`"}, 404)
        rel = path.lstrip("/") or "index.html"
        f = (DIST / rel).resolve()
        if not str(f).startswith(str(DIST.resolve())) or not f.is_file():
            f = DIST / "index.html"
        types = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff", ".json": "application/json"}
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", types.get(f.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["live", "replay"], default="live")
    ap.add_argument("--speed", type=float, choices=[1.0, 10.0], default=1.0, help="replay speed")
    ap.add_argument("--snapshots", default="shadow_run/snapshots.jsonl", help="relative to the project root")
    ap.add_argument("--audit", action="append", default=None, metavar="NAME=PATH",
                    help="audit stream, repeatable; PATH may contain * to follow the newest match (default gnn=shadow_run/audit_gnn.jsonl, rule=shadow_run/audit_rule.jsonl)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    args.audit = args.audit or ["gnn=shadow_run/audit_gnn.jsonl", "rule=shadow_run/audit_rule.jsonl"]
    Handler.data = Data(args)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"MeshHeal API ({args.mode.upper()}) on http://{args.host}:{args.port}  snapshots={args.snapshots} audit={args.audit}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
