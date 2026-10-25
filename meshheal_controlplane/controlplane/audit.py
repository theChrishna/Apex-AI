"""FR-3.4 audit log: one JSON object per decision, append-only."""
import json


class AuditLog:
    def __init__(self, path=None):
        self.path, self.events = path, []

    def write(self, ts, event, **fields):
        rec = {"ts": ts.isoformat(), "event": event, **fields}
        self.events.append(rec)
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        return rec
