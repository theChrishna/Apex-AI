"""Fleet API: authenticated, any mesh, any number of clusters. Stdlib only (http.server + sqlite3).

  python -m dashboard.server --db fleet.db --tokens tokens.json --port 8780 \\
         [--baseline boutique=topo/boutique_baseline_v2.yaml] [--static Frontend_v3/dist]

Endpoints (all JSON):
  GET  /api/v1/health                               no auth
  GET  /api/v1/clusters                             read token
  GET  /api/v1/clusters/<c>/state?minutes=30        read token: latest graph, per-service risk, risk history, decisions
  GET  /api/v1/clusters/<c>/events?limit=200        read token
  POST /api/v1/ingest/<c>/snapshots                 ingest token of cluster <c>: JSON array of snapshots
  POST /api/v1/ingest/<c>/events                    ingest token of cluster <c>: JSON array of audit events
Tokens are sent as "Authorization: Bearer <token>". Pushed snapshots are validated with the controller's own parser;
invalid ones are rejected and counted, never stored. Per-service risk is computed here with the cluster's learned
baseline when one is configured (edge scorer if the file has edges), else with the hand-set rule, and is labelled with
the scorer that produced it. This server never writes to any cluster.
"""
import argparse
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "meshheal_controlplane"))

from controlplane.scorer import BaselineScorer, EdgeScorer, RuleScorer, as_result  # noqa: E402
from controlplane.snapshot import BadSnapshot, node_stats, parse_snapshot  # noqa: E402

from .store import Store, _ts  # noqa: E402
from .tokens import CLUSTER_RE, Tokens  # noqa: E402

MAX_BODY = 2 * 1024 * 1024
MAX_ITEMS = 500
STALE_S = 60.0
DECISIONS = ("REROUTE", "PROBE_START", "PROBE_FAILED", "RELEASE", "ACTION_BLOCKED", "ACTION_FAILED", "SUPPRESSED_VICTIM",
             "RECONCILED", "RECONCILE_ORPHAN", "RECONCILE_FAILED", "SNAPSHOT_REJECTED", "LOOP_ERROR", "PAUSE_CHECK_FAILED")
PATH_RE = re.compile(r"^/api/v1/(clusters|ingest)/([^/]+)/(state|events|snapshots)$")


class HttpError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def fold_mesh(events):
    """NORMAL / REROUTED / PROBING per culprit from decisions in time order."""
    active = {}
    for e in events:
        k, c = e.get("event"), e.get("culprit") or e.get("node")
        if k == "REROUTE":
            active[c] = "REROUTED"
        elif k == "PROBE_START":
            active[c] = "PROBING"
        elif k == "PROBE_FAILED":
            active[c] = "REROUTED"
        elif k == "RELEASE":
            active.pop(c, None)
    state = "NORMAL" if not active else ("PROBING" if "PROBING" in active.values() else "REROUTED")
    return {"state": state, "culprits": active}


class Fleet:
    def __init__(self, store, tokens, baselines=None, clock=None):
        self.store, self.tokens = store, tokens
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.scorers = {}
        for cluster, path in (baselines or {}).items():
            try:
                self.scorers[cluster] = ("edge", EdgeScorer.from_file(path))
            except ValueError:
                self.scorers[cluster] = ("baseline", BaselineScorer.from_file(path))

    # ---- auth ------------------------------------------------------------------------------------
    def require_read(self, token):
        if not token:
            raise HttpError(401, "missing bearer token")
        if not self.tokens.can_read(token):
            raise HttpError(403, "this token may not read")

    def require_ingest(self, token, cluster):
        if not token:
            raise HttpError(401, "missing bearer token")
        allowed = self.tokens.ingest_cluster(token)
        if allowed != cluster:
            raise HttpError(403, "this token may not push data for this cluster")

    # ---- ingest ----------------------------------------------------------------------------------
    def ingest(self, cluster, kind, items):
        if not isinstance(items, list):
            raise HttpError(400, "body must be a JSON array")
        if len(items) > MAX_ITEMS:
            raise HttpError(413, f"at most {MAX_ITEMS} items per request")
        good, bad = [], 0
        for it in items:
            try:
                if kind == "snapshots":
                    parse_snapshot(json.loads(json.dumps(it)))        # the controller's own validation
                    _ts(it["timestamp"])
                else:
                    if not isinstance(it, dict) or not isinstance(it.get("event"), str):
                        raise ValueError("event without a name")
                    _ts(it["ts"])
                good.append(it)
            except (BadSnapshot, KeyError, ValueError, TypeError):
                bad += 1
        now = self.clock()
        added = self.store.add_snapshots(cluster, good, now) if kind == "snapshots" else self.store.add_events(cluster, good, now)
        return {"accepted": len(good), "new": added, "rejected": bad}

    # ---- reads -----------------------------------------------------------------------------------
    def clusters(self):
        now = self.clock()
        out = []
        for c in self.store.clusters():
            age = (now - _ts(c["last_snapshot"])).total_seconds() if c["last_snapshot"] else None
            out.append({**c, "snapshot_age_s": None if age is None else round(age, 1),
                        "stale": age is None or age > STALE_S, "scorer": self.scorers.get(c["name"], ("rule",))[0]})
        return out

    def _risk(self, cluster, raw):
        name, scorer = self.scorers.get(cluster, ("rule", RuleScorer(100.0)))
        snap = parse_snapshot(json.loads(json.dumps(raw)))
        stats = node_stats(snap)
        scores = as_result(scorer, stats, snap).scores
        return name, snap, stats, scores

    def state(self, cluster, minutes=30):
        if not CLUSTER_RE.match(cluster):
            raise HttpError(400, "invalid cluster name")
        now = self.clock()
        since = (now - timedelta(minutes=max(1, min(int(minutes), 24 * 60)))).isoformat()
        snaps = self.store.snapshots(cluster, since=since, limit=480)
        if not snaps and not self.store.snapshots(cluster, limit=1):
            raise HttpError(404, "no data for this cluster")
        series, latest = [], None
        scorer_name = self.scorers.get(cluster, ("rule",))[0]
        for raw in snaps:
            try:
                scorer_name, snap, stats, scores = self._risk(cluster, raw)
            except BadSnapshot:
                continue
            series.append({"ts": raw["timestamp"], "risk": {n: round(v, 3) for n, v in scores.items()}})
            latest = (raw, stats, scores)
        evs = self.store.events(cluster, since=since, limit=2000)
        scored = [e for e in evs if e.get("event") == "SCORED"]
        last_scored = scored[-1] if scored else None
        ctrl_age = (now - _ts(last_scored["ts"])).total_seconds() if last_scored else None
        decisions = [e for e in evs if e.get("event") in DECISIONS]
        graph = None
        if latest:
            raw, stats, scores = latest
            age = (now - _ts(raw["timestamp"])).total_seconds()
            graph = {"ts": raw["timestamp"], "age_s": round(age, 1), "stale": age > STALE_S,
                     "nodes": [{"id": n, "risk": round(scores.get(n, 0.0), 3), "in_lat": round(s["in_lat"], 1),
                                "out_lat": round(s["out_lat"], 1), "in_rate": round(s["in_rate"], 3)}
                               for n, s in sorted(stats.items())],
                     "edges": [{k: e.get(k) for k in ("source", "destination", "request_rate", "latency_p95", "error_rate",
                                                      "src_request_rate", "src_error_rate")} for e in raw["edges"]],
                     "subsets": raw.get("subsets")}
        return {"cluster": cluster, "now": now.isoformat(), "scorer": scorer_name, "graph": graph, "series": series,
                "controller": {"last_scored": last_scored, "age_s": None if ctrl_age is None else round(ctrl_age, 1),
                               "running": ctrl_age is not None and ctrl_age <= STALE_S,
                               "shadow": (last_scored or {}).get("dry_run")},
                "mesh": fold_mesh(self.store.events(cluster, limit=5000, kinds=("REROUTE", "PROBE_START", "PROBE_FAILED", "RELEASE"))),
                "decisions": decisions[-200:]}

    def events(self, cluster, limit=200):
        if not CLUSTER_RE.match(cluster):
            raise HttpError(400, "invalid cluster name")
        return self.store.events(cluster, limit=max(1, min(int(limit), 2000)))


def make_handler(fleet, static_dir=None):
    static = Path(static_dir).resolve() if static_dir else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "MeshHealFleet/0.7"

        def log_message(self, fmt, *a):          # keep tokens and bodies out of logs; only method, path and status
            pass

        def _token(self):
            h = self.headers.get("Authorization", "")
            return h[7:].strip() if h.startswith("Bearer ") else None

        def _send(self, code, obj):
            body = json.dumps(obj, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self, method):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/v1/health" and method == "GET":
                return 200, {"ok": True}
            if u.path == "/api/v1/clusters" and method == "GET":
                fleet.require_read(self._token())
                return 200, fleet.clusters()
            m = PATH_RE.match(u.path)
            if not m:
                raise HttpError(404, "not found")
            area, cluster, what = m.groups()
            if not CLUSTER_RE.match(cluster):
                raise HttpError(400, "invalid cluster name")
            if area == "clusters" and method == "GET" and what in ("state", "events"):
                fleet.require_read(self._token())
                if what == "state":
                    return 200, fleet.state(cluster, int(q.get("minutes", ["30"])[0]))
                return 200, fleet.events(cluster, int(q.get("limit", ["200"])[0]))
            if area == "ingest" and method == "POST" and what in ("snapshots", "events"):
                fleet.require_ingest(self._token(), cluster)
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise HttpError(413, "body too large")
                try:
                    items = json.loads(self.rfile.read(n) or b"null")
                except json.JSONDecodeError:
                    raise HttpError(400, "body is not JSON")
                return 200, fleet.ingest(cluster, what, items)
            raise HttpError(405, "method not allowed")

        def _handle(self, method):
            try:
                code, obj = self._route(method)
            except HttpError as e:
                code, obj = e.code, {"error": e.msg}
            except ValueError:
                code, obj = 400, {"error": "bad parameter"}
            except Exception:                       # never leak internals
                code, obj = 500, {"error": "internal error"}
            self._send(code, obj)

        def do_POST(self):
            self._handle("POST")

        def do_GET(self):
            if not self.path.startswith("/api/") and static:
                return self._static()
            self._handle("GET")

        def _static(self):
            rel = urlparse(self.path).path.lstrip("/") or "index.html"
            f = (static / rel).resolve()
            if static not in f.parents and f != static or not f.is_file():
                f = static / "index.html"                # single-page app: unknown paths get the app
            ctype = {".js": "application/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8",
                     ".svg": "image/svg+xml", ".woff2": "font/woff2", ".json": "application/json"}.get(f.suffix, "application/octet-stream")
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(fleet, port, host="127.0.0.1", static_dir=None):
    srv = ThreadingHTTPServer((host, port), make_handler(fleet, static_dir))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="fleet.db")
    ap.add_argument("--tokens", default="tokens.json")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--host", default="127.0.0.1", help="bind address; put TLS in front before exposing it beyond localhost")
    ap.add_argument("--baseline", action="append", default=[], metavar="CLUSTER=FILE")
    ap.add_argument("--static", default=None, help="serve the built dashboard from this directory")
    ap.add_argument("--retention-days", type=int, default=14)
    a = ap.parse_args(argv)
    if not os.path.exists(a.tokens):
        ap.error(f"{a.tokens} not found: create tokens first (python -m dashboard.tokens --file {a.tokens} add-read)")
    baselines = {}
    for item in a.baseline:
        c, _, p = item.partition("=")
        if not CLUSTER_RE.match(c) or not p:
            ap.error(f"--baseline expects CLUSTER=FILE, got {item!r}")
        baselines[c] = p
    store = Store(a.db, a.retention_days)
    store.prune()
    fleet = Fleet(store, Tokens.load(a.tokens), baselines)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(fleet, a.static))
    print(f"MeshHeal fleet API on http://{a.host}:{a.port}  db={a.db}  clusters with a learned baseline: {sorted(baselines) or 'none'}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
