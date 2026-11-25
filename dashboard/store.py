"""SQLite storage for pushed snapshots and controller events, per cluster. One file, WAL mode, safe for one writer
process with several threads (a lock serialises writes)."""
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, cluster TEXT NOT NULL, ts TEXT NOT NULL, body TEXT NOT NULL,
                                      UNIQUE (cluster, ts));
CREATE INDEX IF NOT EXISTS snapshots_cluster_ts ON snapshots (cluster, ts);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, cluster TEXT NOT NULL, ts TEXT NOT NULL, event TEXT NOT NULL,
                                   body TEXT NOT NULL, UNIQUE (cluster, ts, event, body));
CREATE INDEX IF NOT EXISTS events_cluster_ts ON events (cluster, ts);
CREATE TABLE IF NOT EXISTS clusters (name TEXT PRIMARY KEY, last_push TEXT);
"""


def _ts(s):
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def canonical_ts(s):
    """ISO UTC with microseconds, so text order is time order in SQL."""
    return _ts(s).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


class Store:
    def __init__(self, path, retention_days=14):
        self.path, self.retention = path, timedelta(days=retention_days)
        self._lock = threading.Lock()
        self._local = threading.local()
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            self._local.conn = c
        return c

    # ---- writes ----------------------------------------------------------------------------------
    def add_snapshots(self, cluster, snaps, now=None):
        """Insert snapshots (duplicates by timestamp are ignored, so an agent may resend). Returns how many were new."""
        rows = [(cluster, canonical_ts(s["timestamp"]), json.dumps(s, separators=(",", ":"))) for s in snaps]
        with self._lock, self._conn() as c:
            before = c.total_changes
            c.executemany("INSERT OR IGNORE INTO snapshots (cluster, ts, body) VALUES (?, ?, ?)", rows)
            n = c.total_changes - before
            self._touch(c, cluster, now)
        return n

    def add_events(self, cluster, events, now=None):
        rows = [(cluster, canonical_ts(e["ts"]), str(e["event"]), json.dumps(e, separators=(",", ":"), sort_keys=True)) for e in events]
        with self._lock, self._conn() as c:
            before = c.total_changes
            c.executemany("INSERT OR IGNORE INTO events (cluster, ts, event, body) VALUES (?, ?, ?, ?)", rows)
            n = c.total_changes - before
            self._touch(c, cluster, now)
        return n

    def _touch(self, c, cluster, now):
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        c.execute("INSERT INTO clusters (name, last_push) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET last_push = excluded.last_push",
                  (cluster, stamp))

    def prune(self, now=None):
        """Drop data older than the retention period. Returns (snapshots, events) removed."""
        cut = canonical_ts(((now or datetime.now(timezone.utc)) - self.retention).isoformat())
        with self._lock, self._conn() as c:
            a = c.execute("DELETE FROM snapshots WHERE ts < ?", (cut,)).rowcount
            b = c.execute("DELETE FROM events WHERE ts < ?", (cut,)).rowcount
        return a, b

    # ---- reads -----------------------------------------------------------------------------------
    def clusters(self):
        c = self._conn()
        out = []
        for name, last_push in c.execute("SELECT name, last_push FROM clusters ORDER BY name"):
            row = c.execute("SELECT ts FROM snapshots WHERE cluster = ? ORDER BY ts DESC LIMIT 1", (name,)).fetchone()
            n_snap = c.execute("SELECT COUNT(*) FROM snapshots WHERE cluster = ?", (name,)).fetchone()[0]
            n_ev = c.execute("SELECT COUNT(*) FROM events WHERE cluster = ?", (name,)).fetchone()[0]
            out.append({"name": name, "last_push": last_push, "last_snapshot": row[0] if row else None,
                        "snapshots": n_snap, "events": n_ev})
        return out

    def snapshots(self, cluster, since=None, limit=240):
        q, args = "SELECT body FROM snapshots WHERE cluster = ?", [cluster]
        if since:
            q += " AND ts >= ?"
            args.append(canonical_ts(since))
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit))
        return [json.loads(b) for (b,) in reversed(self._conn().execute(q, args).fetchall())]

    def events(self, cluster, since=None, limit=500, kinds=None):
        q, args = "SELECT body FROM events WHERE cluster = ?", [cluster]
        if since:
            q += " AND ts >= ?"
            args.append(canonical_ts(since))
        if kinds:
            q += f" AND event IN ({','.join('?' * len(kinds))})"
            args += list(kinds)
        q += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(int(limit))
        return [json.loads(b) for (b,) in reversed(self._conn().execute(q, args).fetchall())]
