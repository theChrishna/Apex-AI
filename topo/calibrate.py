"""Compare the simulated Bookinfo with the real Bookinfo data. Prints numbers only; nothing is tuned here.

  python -m topo.calibrate            (run from the repo root; reads snapshots.jsonl and fault_log.jsonl)
"""
import collections
import os
import statistics as st
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from build_dataset_v2 import ALL_EPISODES, load_all_records  # noqa: E402
from topo.sim import bookinfo_topology, snapshot  # noqa: E402

N_SIM = 600


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def row(label, xs):
    return f"{label:<30} n={len(xs):>4}  p25/50/75/95 = {q(xs,.25):6.1f} {q(xs,.5):6.1f} {q(xs,.75):6.1f} {q(xs,.95):6.1f}   share>=50ms {sum(x>=50 for x in xs)/len(xs):5.1%}"


def main():
    recs = load_all_records()
    topo = bookinfo_topology()
    rng = np.random.default_rng(0)

    real, sim = collections.defaultdict(list), collections.defaultdict(list)
    rate_real, rate_sim = collections.defaultdict(list), collections.defaultdict(list)
    for r in recs:
        if r["phase"] == "normal":
            for e in r["edges"]:
                real[(e["source"], e["destination"])].append(e["latency_p95"]); rate_real[(e["source"], e["destination"])].append(e["request_rate"])
    for _ in range(N_SIM):
        for e in snapshot(topo, rng)["edges"]:
            sim[(e["source"], e["destination"])].append(e["latency_p95"]); rate_sim[(e["source"], e["destination"])].append(e["request_rate"])

    print("== NORMAL traffic: latency_p95 per edge (ms), real vs simulated ==")
    for k in sorted(real):
        print(f"{k[0]}->{k[1]}")
        print("   real  " + row("", real[k])[1:] + f"   rate med {st.median(rate_real[k]):.3f}/s")
        print("   sim   " + row("", sim[k])[1:] + f"   rate med {st.median(rate_sim[k]):.3f}/s")

    print("\n== FAULT episodes: median latency_p95 per edge (ms) in steady state, real vs simulated (same node, same delay) ==")
    steady = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in recs:
        if r["phase"] == "steady":
            for e in r["edges"]:
                steady[r["episode_id"]][(e["source"], e["destination"])].append(e["latency_p95"])
    print(f"{'episode':<22}{'edge':<24}{'real':>8}{'sim':>8}")
    for ep in ALL_EPISODES:
        simv = collections.defaultdict(list)
        for _ in range(40):
            for e in snapshot(topo, rng, fault=(ep["node"], ep["delay_ms"]))["edges"]:
                simv[(e["source"], e["destination"])].append(e["latency_p95"])
        for k in sorted(steady[ep["episode_id"]]):
            if k in simv:
                print(f"{ep['episode_id']+' '+ep['node']+' '+str(ep['delay_ms'])+'ms':<22}{k[0]+'->'+k[1]:<24}"
                      f"{st.median(steady[ep['episode_id']][k]):8.1f}{st.median(simv[k]):8.1f}")


if __name__ == "__main__":
    main()
