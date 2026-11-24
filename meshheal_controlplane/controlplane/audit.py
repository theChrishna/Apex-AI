"""FR-3.4 audit log: one JSON object per decision, append-only. Rotates at max_bytes so a long-running service cannot fill its disk."""
import collections
import json
import os


class AuditLog:
    def __init__(self, path=None, max_bytes=50 * 1024 * 1024, echo=False):
        self.path, self.events, self.max_bytes, self.echo = path, [], max_bytes, echo   # echo: also print each event (container logs)
        self.counts = collections.Counter()          # event name -> how many (exposed on /metrics)

    def write(self, ts, event, **fields):
        rec = {"ts": ts.isoformat(), "event": event, **fields}
        self.events.append(rec)
        self.counts[event] += 1
        if self.echo:
            print(json.dumps(rec), flush=True)
        if self.path:
            try:
                if self.max_bytes and os.path.getsize(self.path) > self.max_bytes:
                    os.replace(self.path, self.path + ".1")          # keep one previous file
            except OSError:
                pass                                                  # no file yet
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        return rec
