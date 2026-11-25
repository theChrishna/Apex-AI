"""What the controller would actually DO with a scorer: replay real snapshot streams in time order through the
controller's own persistence rule (top node above 0.85 in 3 of the last 4 checks, current check included) and count

  * on normal traffic: alarm onsets per hour (each would be a reroute, or an ACTION_BLOCKED if there is no playbook)
  * on fault episodes: whether the culprit is caught, how long after the fault started, and whether some other service
    was alarmed first (a wrong action)

Per-snapshot false-alarm rates (REPORT_PHASE4) overstate what an operator sees, because the rule needs persistence;
this measures the operator's view.

  python -m topo.persistence --tag phase4_persistence
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "meshheal_controlplane"))

from controlplane import learn_baseline as lb  # noqa: E402
from controlplane.audit import AuditLog  # noqa: E402
from controlplane.cluster import FakeClient  # noqa: E402
from controlplane.config import Config  # noqa: E402
from controlplane.controller import Controller  # noqa: E402
from topo import eval as ev  # noqa: E402
from topo import real, sim  # noqa: E402

GAP_S = 60.0                      # a gap longer than this between snapshots starts a fresh history (as a restart would)


def _ts(r):
    return datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))


def fresh_controller():
    return Controller(Config(), None, FakeClient(), AuditLog(None))


def alarms(stream_scores):
    """[(ts, node or None)] for a time-ordered list of (ts, {node: score}); history resets on gaps."""
    out, ctrl, prev = [], fresh_controller(), None
    for ts, sc in stream_scores:
        if prev is not None and (ts - prev).total_seconds() > GAP_S:
            ctrl = fresh_controller()
        out.append((ts, ctrl._persistent_top(sc) if sc else None))
        prev = ts
    return out


def onsets(alarm_seq):
    """Alarm onsets: cycles where a node is alarmed and the previous cycle did not alarm that same node."""
    n, last = 0, None
    for _, node in alarm_seq:
        if node is not None and node != last:
            n += 1
        last = node
    return n


def hours(seq):
    if len(seq) < 2:
        return 0.0
    total = 0.0
    for (a, _), (b, _) in zip(seq, seq[1:]):
        dt = (b - a).total_seconds()
        total += dt if dt <= GAP_S else 15.0
    return total / 3600.0


# ------------------------------------------------------------------------------------------------ data
def boutique(baseline_learn):
    """(records in time order with phase, episodes, baseline yaml path, universe)."""
    eps = real.load_episodes(os.path.join(ROOT, "topo", "boutique_fault_log.jsonl"))
    recs = []
    for r in real.load_jsonl(os.path.join(ROOT, "topo", "boutique_snapshots_clean.jsonl")):
        ph, ep, node = real.classify(_ts(r), eps)
        recs.append({**r, "phase": ph, "episode_id": ep, "fault_node": node})
    for r in real.load_jsonl(os.path.join(ROOT, "topo", "boutique_normal_test.jsonl")):
        recs.append({**r, "phase": "normal", "episode_id": None, "fault_node": None})
    episodes = [{"id": e["id"], "node": e["node"], "delay_ms": e["delay_ms"], "start": e["start"], "end": e["end"]} for e in eps]
    return recs, episodes, os.path.join(ROOT, "topo", "boutique_baseline_v2.yaml")


def bookinfo(exclude_v3, tmpdir):
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        import build_dataset_v2 as b2
        recs = b2.load_all_records()
        holdout = b2.build_normal_holdout_ts(recs)
    finally:
        os.chdir(cwd)
    excluded = set()
    if exclude_v3:
        wins = [(datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"]))
                for w in json.load(open(os.path.join(ROOT, "excluded_windows_v3.json"), encoding="utf-8"))["windows"]]
        excluded = {r["timestamp"] for r in recs if any(s <= _ts(r) <= e for s, e in wins)}
    learn = [r for r in recs if r["phase"] == "normal" and r["timestamp"] not in holdout and r["timestamp"] not in excluded]
    base, _ = lb.build_baseline(lb.collect_normal_stats(learn))
    edges, _ = lb.build_edges(lb.collect_normal_edges(learn))
    # one file per variant: both variants are built before either is scored, so a shared name would let the second
    # silently overwrite the first (this happened in the first run of this script)
    path = os.path.join(tmpdir, f"bookinfo_baseline_{'v3clean' if exclude_v3 else 'all'}.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"floor_ms": 10.0, "min_rate": 0.05, "services": base, "edges": edges}, f)
    # normal traffic = holdout only (never seen by the baseline); fault episodes = every phase around each episode
    test = []
    for r in recs:
        if r["timestamp"] in excluded:
            continue
        if r["phase"] == "normal" and r["timestamp"] not in holdout:
            continue
        test.append({**r, "episode_id": r.get("episode_id")})
    episodes = [{"id": e["episode_id"], "node": e["node"], "delay_ms": e["delay_ms"], "start": e["start"], "end": e["end"]}
                for e in b2.ALL_EPISODES]
    return test, episodes, path


# ------------------------------------------------------------------------------------------------ scoring
def score_all(recs, baseline_path, mlp_models):
    """{scorer: [(ts, {node: score})]} in time order. Every record gets the full service universe."""
    recs = sorted(recs, key=_ts)
    universe = sorted({n["id"] for r in recs for n in r["nodes"]} - {"unknown"})
    for r in recs:
        have = {n["id"] for n in r["nodes"]}
        r["nodes"] = list(r["nodes"]) + [{"id": n} for n in universe if n not in have]
        r["labels"] = {n: 0 for n in universe}
        r.setdefault("topology", "real")
        r.setdefault("family", "real")
    graphs = ev.build_graphs(recs, baseline_path)
    out = {}
    for name in ("rule", "baseline", "edge"):
        arrs = ev.baseline_scores(name, graphs)
        out[name] = [(_ts(r), dict(zip(g.node_ids, a.tolist()))) for r, g, a in zip(recs, graphs, arrs)]
    if mlp_models:
        preds = [ev.predict("mlp", m, graphs) for m in mlp_models]
        avg = [np.mean([p[i] for p in preds], axis=0) for i in range(len(graphs))]
        out["mlp (5 seeds avg)"] = [(_ts(r), dict(zip(g.node_ids, a.tolist()))) for r, g, a in zip(recs, graphs, avg)]
    return recs, out


def evaluate(recs, episodes, scored):
    phase = {_ts(r): r["phase"] for r in recs}
    res = {}
    for name, seq in scored.items():
        # normal traffic: contiguous runs of normal snapshots, fresh history at each run (alarms() resets on gaps)
        normal_seq = [(t, s) for t, s in seq if phase[t] == "normal"]
        al = alarms(normal_seq)
        h = hours(al)
        n_on = onsets(al)
        # fault episodes: from 60 s before the start to 90 s after the end, fresh history
        rows = []
        for ep in episodes:
            lo, hi = ep["start"] - timedelta(seconds=60), ep["end"] + timedelta(seconds=90)
            window = [(t, s) for t, s in seq if lo <= t <= hi]
            if not window:
                continue
            al_ep = [(t, n) for t, n in alarms(window) if t >= ep["start"]]
            first_any = next(((t, n) for t, n in al_ep if n), None)
            first_ok = next((t for t, n in al_ep if n == ep["node"]), None)
            rows.append({"episode": ep["id"], "node": ep["node"], "delay_ms": ep["delay_ms"],
                         "caught": first_ok is not None,
                         "delay_s": round((first_ok - ep["start"]).total_seconds(), 1) if first_ok else None,
                         "first_alarm": first_any[1] if first_any else None,
                         "wrong_first": bool(first_any and first_any[1] != ep["node"])})
        caught = [r for r in rows if r["caught"]]
        res[name] = {"normal_hours": round(h, 2), "normal_alarm_onsets": n_on,
                     "false_alarms_per_hour": round(n_on / h, 2) if h else None,
                     "episodes": len(rows), "caught": len(caught),
                     "wrong_first": sum(r["wrong_first"] for r in rows),
                     "median_delay_s": float(np.median([r["delay_s"] for r in caught])) if caught else None,
                     "rows": rows}
    return res


def train_mlps(seeds, epochs):
    _, records = sim.make_corpus(0, per_family=8)
    graphs = ev.build_graphs(records)
    return [ev.train("mlp", graphs, s, epochs) for s in seeds]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--no-mlp", action="store_true")
    ap.add_argument("--epochs", type=int, default=40)
    a = ap.parse_args(argv)
    out_md = os.path.join(ROOT, "topo", "results", a.tag + ".md")
    if os.path.exists(out_md):
        raise SystemExit(f"refusing to overwrite {out_md}")
    mlps = [] if a.no_mlp else train_mlps(ev.SEEDS, a.epochs)
    report = {}
    with tempfile.TemporaryDirectory() as t:
        for label, (recs, eps, bpath) in {
                "Online Boutique (real; baseline design was iterated on it)": boutique(None),
                "Bookinfo, REPORT_V3 noisy windows excluded": bookinfo(True, t),
                "Bookinfo, all holdout normals (includes window B1)": bookinfo(False, t)}.items():
            recs, scored = score_all(recs, bpath, mlps)
            report[label] = evaluate(recs, eps, scored)

    lines = ["# What the controller would do: persistence-rule replay (generated by topo/persistence.py)", "",
             "Real snapshot streams replayed in time order through the controller's own `_persistent_top` (risk > 0.85 in 3 of the "
             "last 4 checks, current check included). Normal traffic = Boutique's held-out fault-free half plus the normals of the "
             "fault run; Bookinfo's holdout (never used to learn a baseline). A false alarm is an alarm ONSET on normal traffic: "
             "each one would be a reroute (or ACTION_BLOCKED where no playbook exists). The MLP is trained on simulated data only.", ""]
    for label, res in report.items():
        lines += [f"## {label}", "", "| scorer | normal hours | false alarms | per hour | faults caught | wrong service first | median detection delay |",
                  "|---|---|---|---|---|---|---|"]
        for name, r in res.items():
            d = f"{r['median_delay_s']:.0f} s" if r["median_delay_s"] is not None else "n/a"
            lines.append(f"| {name} | {r['normal_hours']} | {r['normal_alarm_onsets']} | {r['false_alarms_per_hour']} | "
                         f"{r['caught']}/{r['episodes']} | {r['wrong_first']} | {d} |")
        lines += ["", "<details><summary>per episode</summary>", "", "| scorer | episode | culprit | delay | caught | after s | first alarm |", "|---|---|---|---|---|---|---|"]
        for name, r in res.items():
            for e in r["rows"]:
                lines.append(f"| {name} | {e['episode']} | {e['node']} | {e['delay_ms']} ms | {'yes' if e['caught'] else 'no'} | "
                             f"{e['delay_s'] if e['delay_s'] is not None else '-'} | {e['first_alarm'] or '-'} |")
        lines += ["", "</details>", ""]
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(out_md[:-3] + ".json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    for label, res in report.items():
        print(f"\n{label}")
        for name, r in res.items():
            print(f"  {name:<20} false alarms {r['normal_alarm_onsets']} in {r['normal_hours']} h ({r['false_alarms_per_hour']}/h) | "
                  f"caught {r['caught']}/{r['episodes']} | wrong first {r['wrong_first']} | median delay {r['median_delay_s']}")


if __name__ == "__main__":
    main()
