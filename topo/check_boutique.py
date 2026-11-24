"""Quality checks for real fault-episode data (read-only). For each episode:
  * culprit edges (edges INTO the faulted service): is the steady-state p95 clearly above the normal baseline?
  * victim edges (edges into services that call the culprit, directly or not): informational, they may rise
  * unrelated edges: must NOT rise, otherwise the slowdown is not isolated to the fault (e.g. an overloaded app)
Thresholds: a fault is "visible" if some culprit edge rises by >= 0.5 x the injected delay; an unrelated edge is
"affected" if it rises by >= 0.5 x the injected delay too. Edges with fewer than MIN_N steady samples are ignored.

  python -m topo.check_boutique --snapshots topo/boutique_snapshots_clean.jsonl --fault-log topo/boutique_fault_log.jsonl
"""
import argparse
import collections
import os
import statistics as st
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from topo import real  # noqa: E402

MIN_N = 5


def ancestors(edges, node):
    """Services that call `node`, directly or through others."""
    callers = collections.defaultdict(set)
    for s, d in edges:
        callers[d].add(s)
    seen, todo = set(), [node]
    while todo:
        for c in callers[todo.pop()]:
            if c not in seen:
                seen.add(c)
                todo.append(c)
    return seen


def episode_windows(episodes):
    from datetime import timedelta
    return {ep["id"]: (ep["start"] + real.LAG, ep["end"]) for ep in episodes}


def check(snapshots, fault_log, topology="boutique"):
    episodes = real.load_episodes(fault_log)
    recs = real.label_records(snapshots, fault_log, topology, keep=("steady", "normal"))
    normal = collections.defaultdict(list)
    steady = collections.defaultdict(lambda: collections.defaultdict(list))
    all_edges = set()
    for r in recs:
        for e in r["edges"]:
            if e["destination"] == "unknown":
                continue
            k = (e["source"], e["destination"])
            all_edges.add(k)
            (normal[k].append(e["latency_p95"]) if r["phase"] == "normal" else steady[r["episode_id"]][k].append(e["latency_p95"]))
    out = []
    for ep in episodes:
        node, delay = ep["node"], ep["delay_ms"]
        anc = ancestors(all_edges, node)
        rows = {"culprit": [], "victim": [], "unrelated": []}
        for k, v in steady[ep["id"]].items():
            if len(v) < MIN_N or len(normal[k]) < MIN_N:
                continue
            d = st.median(v) - st.median(normal[k])
            kind = "culprit" if k[1] == node else ("victim" if k[1] in anc else "unrelated")
            rows[kind].append((k, st.median(normal[k]), st.median(v), d, len(v)))
        n_steady = sum(1 for r in recs if r["episode_id"] == ep["id"])
        vis = max((x[3] for x in rows["culprit"]), default=float("nan"))
        worst_unrel = max((x[3] for x in rows["unrelated"]), default=0.0)
        out.append({"episode": ep["id"], "node": node, "delay_ms": delay, "n_steady": n_steady, "rows": rows,
                    "visible": vis >= 0.5 * delay, "culprit_rise": vis,
                    "isolated": worst_unrel < 0.5 * delay, "worst_unrelated_rise": worst_unrel})
    return out, collections.Counter(r["phase"] for r in recs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--fault-log", required=True)
    ap.add_argument("--verbose", action="store_true", help="list every edge")
    a = ap.parse_args(argv)
    res, phases = check(a.snapshots, a.fault_log)
    print(f"labelled records kept: {dict(phases)}  (lag and recovery excluded)\n")
    print(f"{'ep':>2} {'culprit':<22}{'delay':>6}{'steady n':>9}{'culprit rise':>13}{'visible':>9}{'worst unrelated rise':>22}{'isolated':>10}")
    for r in res:
        print(f"{r['episode']:>2} {r['node']:<22}{r['delay_ms']:>5}ms{r['n_steady']:>9}{r['culprit_rise']:>11.1f}ms{'YES' if r['visible'] else 'NO':>9}"
              f"{r['worst_unrelated_rise']:>20.1f}ms{'YES' if r['isolated'] else 'NO':>10}")
        if a.verbose:
            for kind in ("culprit", "victim", "unrelated"):
                for (k, nm, sm, d, n) in sorted(r["rows"][kind], key=lambda x: -x[3]):
                    print(f"      {kind:<9}{k[0]+' -> '+k[1]:<46}normal {nm:7.1f}  steady {sm:7.1f}  rise {d:+8.1f}  n={n}")
    ok = all(r["visible"] and r["isolated"] for r in res)
    print(f"\n{sum(r['visible'] for r in res)}/{len(res)} faults visible on a culprit edge; "
          f"{sum(r['isolated'] for r in res)}/{len(res)} isolated (no unrelated edge rose by >= half the delay).")
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED: read the rows above before using this data")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
