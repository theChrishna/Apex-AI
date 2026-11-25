"""CLI.

Live, shadow (the default: reads the cluster, never writes):   python -m controlplane.run --snapshots snapshots.jsonl
Live, acting (writes VirtualServices; needs --act):            python -m controlplane.run --snapshots snapshots.jsonl --act
Replay stored data (no cluster):                               python -m controlplane.run --snapshots snapshots.jsonl --replay
--dry-run is still accepted and means the same as the default.
"""
import argparse
import json
import time
from datetime import datetime, timezone

from .audit import AuditLog
from .cluster import DryRunClient, FakeClient, KubeClient
from .config import Config
from .controller import Controller, step_from_file
from .health import Health, start_server
from .playbook import DEFAULT_PATH, Playbook
from .scorer import BaselineScorer, EdgeScorer, ResilientScorer, RuleScorer
from .snapshot import BadSnapshot, parse_snapshot


def build_scorer(name, cfg, gnn_manifest=None, gnn_kill_file=None, baseline_path=None):
    rule = RuleScorer(cfg.self_lat_full_ms)
    if name == "rule":
        return rule
    if name in ("baseline", "edge"):
        path = baseline_path or cfg.baseline_path
        if not path:
            raise SystemExit(f"--scorer {name} needs --baseline FILE (learn one with python -m controlplane.learn_baseline)")
        # the learned scorer is the primary; the hand-set rule is the fallback if it ever fails
        cls = EdgeScorer if name == "edge" else BaselineScorer
        return ResilientScorer(cls.from_file(path, full_ms=cfg.self_lat_full_ms), rule, cfg.scorer_timeout_s)
    from .gnn_adapter import GnnScorer
    return ResilientScorer(GnnScorer(gnn_manifest, kill_file=gnn_kill_file), rule, cfg.scorer_timeout_s)


def replay(path, cfg, scorer, playbook=None):
    """Offline: step through every stored snapshot with a simulated clock. Decisions only (no feedback)."""
    audit = AuditLog(None)
    box = {"now": datetime.now(timezone.utc)}
    ctrl = Controller(cfg, scorer, FakeClient(), audit, clock=lambda: box["now"], dry_run=True, playbook=playbook)
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


def resolve_dry_run(ap, a):
    """Shadow mode (no writes) unless --act was given."""
    if a.act and a.dry_run:
        ap.error("--act and --dry-run contradict each other")
    return not a.act


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", default="snapshots.jsonl")
    ap.add_argument("--config", default=None, help="YAML file of Config settings (see meshheal.example.yaml)")
    ap.add_argument("--playbook", default=None, help="YAML playbook (default playbooks/bookinfo.yaml)")
    ap.add_argument("--namespace", default=None)
    ap.add_argument("--scorer", choices=["rule", "baseline", "edge", "gnn"], default="rule")
    ap.add_argument("--baseline", default=None, help="learned baseline YAML for --scorer baseline (controlplane.learn_baseline)")
    ap.add_argument("--gnn-manifest", default="../models/gnn_final_manifest.json",
                    help="written by train_final.py (seed weights sit next to it)")
    ap.add_argument("--gnn-kill-file", default=None,
                    help="demo kill switch: while this file exists the GNN raises and the rule fallback scores")
    ap.add_argument("--act", action="store_true",
                    help="ALLOW cluster writes. Without it the controller is in shadow mode and only reads.")
    ap.add_argument("--dry-run", action="store_true", help="shadow mode (the default); kept for older commands")
    ap.add_argument("--replay", action="store_true", help="offline replay of the snapshot file")
    ap.add_argument("--audit", default=None)
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--metrics-port", type=int, default=0, help="serve /healthz and /metrics on this port (0 = off)")
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    dry_run = resolve_dry_run(ap, a)         # safe by default: writing to the cluster has to be asked for

    # explicit command-line flags win over the config file, which wins over the defaults
    cli = dict(namespace=a.namespace, audit_path=a.audit, interval_s=a.interval or None, playbook_path=a.playbook)
    cfg = Config.from_file(a.config, **cli) if a.config else Config(**{k: v for k, v in cli.items() if v is not None})
    playbook = Playbook.from_file(cfg.playbook_path or DEFAULT_PATH)
    scorer = build_scorer(a.scorer, cfg, a.gnn_manifest, a.gnn_kill_file, a.baseline)
    if a.replay:
        return replay(a.snapshots, cfg, scorer, playbook)

    client = KubeClient(cfg.namespace, cfg.app_label, cfg.version_label, cfg.state_annotation, cfg.control_configmap)
    if dry_run:
        client = DryRunClient(client)
    ctrl = Controller(cfg, scorer, client, AuditLog(cfg.audit_path, echo=cfg.audit_stdout), dry_run=dry_run, playbook=playbook)
    mode = ("SHADOW MODE: reading only, no cluster writes. Pass --act to allow writes." if dry_run
            else "ACTING: this controller WILL change VirtualServices.")
    print(f"control plane up: {mode}\n  scorer={a.scorer} ns={cfg.namespace} interval={cfg.interval_s}s "
          f"playbook={len(playbook.reroutes)} reroute(s), {sum(1 for r in playbook.reroutes.values() if not r.confirmed)} unconfirmed; "
          f"max {cfg.max_actions_per_hour} reroutes/hour, auto-release after {cfg.max_reroute_s:.0f}s", flush=True)
    health = Health(ctrl, cfg.interval_s)
    if a.metrics_port:
        server, _ = start_server(health, a.metrics_port)
        print(f"  /healthz and /metrics on port {server.server_address[1]}", flush=True)
    ctrl.reconcile()                         # pick up reroutes recorded before a restart
    while True:
        t0 = time.time()
        ok = True
        try:
            step_from_file(ctrl, a.snapshots)
        except Exception as e:   # the loop must survive anything
            ctrl._log("LOOP_ERROR", error=repr(e))
            ok = False
        health.loop_done(ok)
        time.sleep(max(0.0, cfg.interval_s - (time.time() - t0)))


if __name__ == "__main__":
    main()
