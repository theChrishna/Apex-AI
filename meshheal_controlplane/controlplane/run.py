"""CLI.

Live (shadow first!):   python -m controlplane.run --snapshots snapshots.jsonl --dry-run
Live (acting):          python -m controlplane.run --snapshots snapshots.jsonl
Replay stored data:     python -m controlplane.run --snapshots snapshots.jsonl --replay
"""
import argparse
import json
import time
from datetime import datetime, timezone

from .audit import AuditLog
from .cluster import DryRunClient, FakeClient, KubeClient
from .config import Config
from .controller import Controller, step_from_file
from .scorer import ResilientScorer, RuleScorer
from .snapshot import BadSnapshot, parse_snapshot


def build_scorer(name, cfg):
    rule = RuleScorer(cfg.self_lat_full_ms)
    if name == "rule":
        return rule
    from .gnn_adapter import GnnScorer   # raises NotImplementedError until wired
    return ResilientScorer(GnnScorer([]), rule, cfg.scorer_timeout_s)


def replay(path, cfg, scorer):
    """Offline: step through every stored snapshot with a simulated clock. Decisions only (no feedback)."""
    audit = AuditLog(None)
    box = {"now": datetime.now(timezone.utc)}
    ctrl = Controller(cfg, scorer, FakeClient(), audit, clock=lambda: box["now"], dry_run=True)
    n = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                snap = parse_snapshot(json.loads(line), cfg.expected_nodes)
            except (BadSnapshot, json.JSONDecodeError):
                continue
            box["now"] = snap.ts
            ctrl.step(snap)
            n += 1
    for e in audit.events:
        if e["event"] not in ("SCORED",):
            print(json.dumps(e))
    print(f"replayed {n} snapshots")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", default="snapshots.jsonl")
    ap.add_argument("--namespace", default="aws-us-east")
    ap.add_argument("--scorer", choices=["rule", "gnn"], default="rule")
    ap.add_argument("--dry-run", action="store_true", help="read real cluster state, never write")
    ap.add_argument("--replay", action="store_true", help="offline replay of the snapshot file")
    ap.add_argument("--audit", default="audit_log.jsonl")
    ap.add_argument("--interval", type=float, default=None)
    a = ap.parse_args()

    cfg = Config(namespace=a.namespace, audit_path=a.audit)
    if a.interval:
        cfg.interval_s = a.interval
    scorer = build_scorer(a.scorer, cfg)
    if a.replay:
        return replay(a.snapshots, cfg, scorer)

    client = KubeClient(cfg.namespace)
    if a.dry_run:
        client = DryRunClient(client)
    ctrl = Controller(cfg, scorer, client, AuditLog(cfg.audit_path), dry_run=a.dry_run)
    print(f"control plane up: scorer={a.scorer} dry_run={a.dry_run} ns={cfg.namespace} interval={cfg.interval_s}s")
    while True:
        t0 = time.time()
        try:
            step_from_file(ctrl, a.snapshots)
        except Exception as e:   # the loop must survive anything
            ctrl._log("LOOP_ERROR", error=repr(e))
        time.sleep(max(0.0, cfg.interval_s - (time.time() - t0)))


if __name__ == "__main__":
    main()
