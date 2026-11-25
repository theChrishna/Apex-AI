"""Tokens for the fleet API. Only SHA-256 hashes are stored; a token is printed once when created.

  python -m dashboard.tokens --file tokens.json add-read [--label alice]
  python -m dashboard.tokens --file tokens.json add-ingest <cluster>
  python -m dashboard.tokens --file tokens.json list
  python -m dashboard.tokens --file tokens.json revoke <label-or-cluster>

Two scopes:
  read    may read every cluster (the dashboard)
  ingest  may only push data for ONE cluster name (an agent); it cannot read anything
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sys

CLUSTER_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


def digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Tokens:
    def __init__(self, data=None):
        self.data = data or {"read": {}, "ingest": {}}           # read: {label: hash}; ingest: {cluster: hash}

    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls({"read": dict(d.get("read") or {}), "ingest": dict(d.get("ingest") or {})})

    def save(self, path):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(tmp, path)

    # ---- checks (constant time per comparison) ---------------------------------------------------
    def can_read(self, token):
        if not token:
            return False
        h = digest(token)
        return any(hmac.compare_digest(h, v) for v in self.data["read"].values())

    def ingest_cluster(self, token):
        """The cluster this ingest token may push for, or None."""
        if not token:
            return None
        h = digest(token)
        hit = None
        for cluster, v in self.data["ingest"].items():
            if hmac.compare_digest(h, v):
                hit = cluster
        return hit

    # ---- management ------------------------------------------------------------------------------
    def add_read(self, label):
        tok = "mhr_" + secrets.token_urlsafe(32)
        self.data["read"][label] = digest(tok)
        return tok

    def add_ingest(self, cluster):
        if not CLUSTER_RE.match(cluster):
            raise ValueError(f"invalid cluster name {cluster!r}: lowercase letters, digits and '-' only")
        tok = "mhi_" + secrets.token_urlsafe(32)
        self.data["ingest"][cluster] = digest(tok)
        return tok

    def revoke(self, name):
        return bool(self.data["read"].pop(name, None) or self.data["ingest"].pop(name, None))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default="tokens.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("add-read")
    r.add_argument("--label", default=None)
    i = sub.add_parser("add-ingest")
    i.add_argument("cluster")
    sub.add_parser("list")
    v = sub.add_parser("revoke")
    v.add_argument("name")
    a = ap.parse_args(argv)
    t = Tokens.load(a.file)
    if a.cmd == "add-read":
        label = a.label or f"read-{len(t.data['read']) + 1}"
        tok = t.add_read(label)
        t.save(a.file)
        print(tok)
        print(f"read token '{label}' saved (hash only) to {a.file}; this is the only time it is shown", file=sys.stderr)
    elif a.cmd == "add-ingest":
        tok = t.add_ingest(a.cluster)
        t.save(a.file)
        print(tok)
        print(f"ingest token for cluster '{a.cluster}' saved (hash only) to {a.file}; shown only now", file=sys.stderr)
    elif a.cmd == "list":
        print("read:", ", ".join(sorted(t.data["read"])) or "-")
        print("ingest:", ", ".join(sorted(t.data["ingest"])) or "-")
    else:
        print("revoked" if t.revoke(a.name) else "not found")
        t.save(a.file)


if __name__ == "__main__":
    main()
