"""The fresh test: scorers frozen BEFORE this data existed, evaluated on a new Online Boutique run with four fault types.

  python -m topo.fresh_test --tag phase4_fresh_run3 --snapshots topo/live_boutique_20261125c.jsonl \\
         --fault-log topo/boutique_fault_log_run3.jsonl [--mlp]

Data split (all from the one continuous collector file):
  learn   fault-free snapshots before the run, first `--learn-share` of them: the learned baselines come from here only
  normal  the rest of the fault-free snapshots before the run, plus any after it (false alarms are measured here only)
  faults  every episode in the fault log; steady snapshots are positive for the faulted service only (Bookinfo rules)
Per-snapshot metrics (AP, root cause ranked first, false alarms at 0.85) and what the controller would do under its
persistence rule (caught, delay, wrong service alarmed first, false-alarm onsets per hour), each per fault type.
"""
import argparse
import collections
import json
import os
import sys
import tempfile
from datetime import timedelta

import numpy as np
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "meshheal_controlplane"))

from controlplane import learn_baseline as lb  # noqa: E402
from topo import eval as ev  # noqa: E402
from topo import persistence as P  # noqa: E402
from topo import real  # noqa: E402

SCORERS = ("rule", "baseline", "edge")


def split(snapshots_path, fault_log, learn_share, margin_s=300, until=None, exclude=()):
    eps = real.load_episodes(fault_log)
    if not eps:
        raise SystemExit("no completed episodes in the fault log")
    run_start = min(e["start"] for e in eps) - timedelta(seconds=margin_s)
    run_end = max(e["end"] for e in eps) + timedelta(seconds=margin_s)
    before, after, during = [], [], []
    for r in real.load_jsonl(snapshots_path):
        t = P._ts(r)
        if until is not None and t > until:
            continue                                   # e.g. a later test that degrades services on purpose
        if any(a <= t <= b for a, b in exclude):
            continue                                   # e.g. an unlogged partial episode or a cluster outage
        (before if t < run_start else after if t > run_end else during).append(r)
    k = int(len(before) * learn_share)
    learn, normal = before[:k], before[k:] + after
    recs = []
    for r in during:
        ph, ep, node = real.classify(P._ts(r), eps)
        if ph in ("steady", "lag", "recovery", "normal"):
            recs.append({**r, "phase": ph, "episode_id": ep, "fault_node": node})
    recs += [{**r, "phase": "normal", "episode_id": None, "fault_node": None} for r in normal]
    return learn, recs, eps


def per_snapshot(recs, scored, eps):
    """AP / RC@1 / FPR per scorer and fault type, on steady + normal snapshots."""
    etype = {e["id"]: e.get("type", "delay") for e in eps}
    by_ts = {P._ts(r): r for r in recs}
    out = {}
    for name, seq in scored.items():
        rows = {}
        for ftype in sorted(set(etype.values())) + ["all"]:
            ys, ss, rc, fp = [], [], [], []
            for t, sc in seq:
                r = by_ts[t]
                if r["phase"] == "steady" and (ftype == "all" or etype.get(r["episode_id"]) == ftype):
                    names = sorted(sc)
                    v = np.array([sc[n] for n in names])
                    y = np.array([1.0 if n == r["fault_node"] else 0.0 for n in names])
                    ys.append(y)
                    ss.append(v)
                    i = names.index(r["fault_node"]) if r["fault_node"] in names else None
                    if i is not None:
                        greater, ties = int((v > v[i]).sum()), int((v == v[i]).sum()) - 1
                        rc.append(0.0 if greater else 1.0 / (1 + ties))
                elif r["phase"] == "normal" and ftype == "all":
                    fp.append(float(max(sc.values()) > 0.85))
            from sklearn.metrics import average_precision_score
            y, s = (np.concatenate(ys), np.concatenate(ss)) if ys else (np.array([]), np.array([]))
            rows[ftype] = {"ap": float(average_precision_score(y, s)) if y.sum() else None,
                           "rc1": float(np.mean(rc)) if rc else None, "n_steady": len(ys),
                           **({"fpr": float(np.mean(fp)) if fp else None, "n_normal": len(fp)} if ftype == "all" else {})}
        out[name] = rows
    return out


def by_type(persist, eps):
    etype = {e["id"]: e.get("type", "delay") for e in eps}
    out = {}
    for name, r in persist.items():
        groups = collections.defaultdict(list)
        for row in r["rows"]:
            groups[etype.get(row["episode"], "delay")].append(row)
        out[name] = {t: {"episodes": len(rows), "caught": sum(x["caught"] for x in rows),
                         "wrong_first": sum(x["wrong_first"] for x in rows),
                         "median_delay_s": float(np.median([x["delay_s"] for x in rows if x["caught"]])) if any(x["caught"] for x in rows) else None}
                     for t, rows in sorted(groups.items())}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--fault-log", required=True)
    ap.add_argument("--learn-share", type=float, default=0.6)
    ap.add_argument("--until", default=None, help="ignore snapshots after this ISO time (UTC)")
    ap.add_argument("--exclude", nargs=2, action="append", default=[], metavar=("FROM", "TO"),
                    help="drop snapshots in this ISO time window (UTC); repeatable")
    ap.add_argument("--mlp", action="store_true", help="also score the MLP trained on simulated data (5 seeds; CPU heavy)")
    a = ap.parse_args(argv)
    out_md = os.path.join(ROOT, "topo", "results", a.tag + ".md")
    if os.path.exists(out_md):
        raise SystemExit(f"refusing to overwrite {out_md}")

    until = P._ts({"timestamp": a.until}) if a.until else None
    exclude = [(P._ts({"timestamp": x}), P._ts({"timestamp": y})) for x, y in a.exclude]
    learn, recs, eps = split(a.snapshots, a.fault_log, a.learn_share, until=until, exclude=exclude)
    base, _ = lb.build_baseline(lb.collect_normal_stats([{**r, "phase": "normal"} for r in learn]))
    edges, _ = lb.build_edges(lb.collect_normal_edges([{**r, "phase": "normal"} for r in learn]))
    mlps = P.train_mlps(ev.SEEDS, 40) if a.mlp else []
    with tempfile.TemporaryDirectory() as t:
        path = os.path.join(t, "fresh_baseline.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"floor_ms": 10.0, "min_rate": 0.05, "services": base, "edges": edges}, f)
        recs, scored = P.score_all(recs, path, mlps)
    episodes = [{"id": e["id"], "node": e["node"], "delay_ms": e["delay_ms"], "start": e["start"], "end": e["end"]} for e in eps]
    persist = P.evaluate(recs, episodes, scored)
    snap_m = per_snapshot(recs, scored, eps)
    types = by_type(persist, eps)

    n_normal = sum(1 for r in recs if r["phase"] == "normal")
    lines = ["# Fresh test: Online Boutique, four fault types (generated by topo/fresh_test.py)", "",
             f"Scorer designs were frozen before this run. Learned baselines come ONLY from the first {a.learn_share:.0%} of the "
             f"fault-free snapshots before the run ({len(learn)} snapshots); false alarms are measured on the other {n_normal} "
             f"fault-free snapshots. {len(eps)} episodes: " + ", ".join(f"{k} {v}" for k, v in collections.Counter(e.get('type', 'delay') for e in eps).items()) + ".", "",
             "## What the controller would do (persistence rule: 3 of 4 checks above 0.85)", "",
             "| scorer | fault type | caught | wrong service first | median detection delay |", "|---|---|---|---|---|"]
    for name, t in types.items():
        for ftype, r in t.items():
            d = f"{r['median_delay_s']:.0f} s" if r["median_delay_s"] is not None else "n/a"
            lines.append(f"| {name} | {ftype} | {r['caught']}/{r['episodes']} | {r['wrong_first']} | {d} |")
    lines += ["", "| scorer | normal hours | false-alarm onsets | per hour |", "|---|---|---|---|"]
    for name, r in persist.items():
        lines.append(f"| {name} | {r['normal_hours']} | {r['normal_alarm_onsets']} | {r['false_alarms_per_hour']} |")
    lines += ["", "## Per snapshot (steady fault snapshots and fault-free snapshots)", "",
              "| scorer | fault type | AP | root cause ranked first | steady snapshots |", "|---|---|---|---|---|"]
    for name, rows in snap_m.items():
        for ftype, m in rows.items():
            ap_ = "n/a" if m["ap"] is None else f"{m['ap']:.3f}"
            rc_ = "n/a" if m["rc1"] is None else f"{m['rc1']:.3f}"
            lines.append(f"| {name} | {ftype} | {ap_} | {rc_} | {m['n_steady']} |")
    lines += ["", "| scorer | false alarms per snapshot | fault-free snapshots |", "|---|---|---|"]
    for name, rows in snap_m.items():
        m = rows["all"]
        fpr = "n/a" if m.get("fpr") is None else f"{m['fpr']:.3f}"
        lines.append(f"| {name} | {fpr} | {m.get('n_normal')} |")
    lines += ["", "<details><summary>per episode</summary>", "", "| scorer | episode | type | service | caught | after s | first alarm |", "|---|---|---|---|---|---|---|"]
    etype = {e["id"]: e.get("type", "delay") for e in eps}
    for name, r in persist.items():
        for row in r["rows"]:
            lines.append(f"| {name} | {row['episode']} | {etype.get(row['episode'])} | {row['node']} | {'yes' if row['caught'] else 'no'} | "
                         f"{row['delay_s'] if row['delay_s'] is not None else '-'} | {row['first_alarm'] or '-'} |")
    lines += ["", "</details>", ""]
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(out_md[:-3] + ".json", "w", encoding="utf-8") as f:
        json.dump({"persistence": persist, "by_type": types, "per_snapshot": snap_m,
                   "learn_snapshots": len(learn), "normal_snapshots": n_normal}, f, indent=1, default=str)
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main()
