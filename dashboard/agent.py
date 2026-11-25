"""Cluster agent: pushes a cluster's new snapshots and controller decisions to the fleet API.

  python -m dashboard.agent --url http://fleet:8780 --cluster boutique --token-file /var/run/meshheal/ingest-token \\
         --snapshots /data/live_snapshots.jsonl --audit /data/audit.jsonl

It reads the files the collector and controller already write, remembers how far it got (byte offsets, kept in memory
and optionally in --state), and posts new lines in batches. A file that was rotated (smaller than the offset) is read
from the start again; the API ignores duplicates, so resending is harmless. If the API is down it keeps the offset and
retries with backoff. It only reads local files and makes outbound HTTP requests; it never touches the cluster.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BATCH = 200


class Tail:
    """New complete JSON lines of a file since the last call."""

    def __init__(self, path, offset=0):
        self.path, self.offset = path, offset

    def read(self, max_lines=BATCH):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return [], self.offset
        if size < self.offset:                 # rotated or truncated: start over
            self.offset = 0
        items, off = [], self.offset
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            for line in f:
                if not line.endswith(b"\n"):   # a half-written last line: wait for the rest
                    break
                off += len(line)
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                if len(items) >= max_lines:
                    break
        return items, off


def post(url, token, items, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(items).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


class Agent:
    def __init__(self, url, cluster, token, snapshots=None, audit=None, state_path=None, post_fn=post, log=print):
        self.base = url.rstrip("/") + f"/api/v1/ingest/{cluster}"
        self.token, self.state_path, self.post, self.log = token, state_path, post_fn, log
        offsets = self._load_state()
        self.tails = {}
        if snapshots:
            self.tails["snapshots"] = Tail(snapshots, offsets.get("snapshots", 0))
        if audit:
            self.tails["events"] = Tail(audit, offsets.get("events", 0))

    def _load_state(self):
        if self.state_path and os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
        return {}

    def _save_state(self):
        if self.state_path:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({k: t.offset for k, t in self.tails.items()}, f)
            os.replace(tmp, self.state_path)

    def once(self):
        """Push everything new. Returns {kind: pushed count}; raises on a failed push (offset unchanged)."""
        out = {}
        for kind, tail in self.tails.items():
            total = 0
            while True:
                items, new_off = tail.read()
                if not items:
                    tail.offset = new_off          # skip blank / undecodable lines too
                    break
                self.post(f"{self.base}/{kind}", self.token, items)
                tail.offset = new_off              # only advance after the API accepted the batch
                total += len(items)
            out[kind] = total
        self._save_state()
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--cluster", required=True)
    ap.add_argument("--token-file", required=True, help="file holding the ingest token (never pass the token itself as an argument)")
    ap.add_argument("--snapshots", default=None)
    ap.add_argument("--audit", default=None)
    ap.add_argument("--state", default=None, help="file to remember offsets across restarts")
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    with open(a.token_file, encoding="utf-8") as f:
        token = f.read().strip()
    agent = Agent(a.url, a.cluster, token, a.snapshots, a.audit, a.state)
    backoff = a.interval
    while True:
        try:
            n = agent.once()
            if any(n.values()):
                print(f"[{time.strftime('%H:%M:%S')}] pushed {n}", flush=True)
            backoff = a.interval
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"push failed ({e}); retrying in {backoff:.0f}s", flush=True)
            backoff = min(backoff * 2, 300.0)
        if a.once:
            return
        time.sleep(backoff)


if __name__ == "__main__":
    main()
