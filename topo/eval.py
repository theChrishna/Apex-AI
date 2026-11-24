"""Leave-one-topology-out evaluation of GNN vs MLP vs rule vs p95 baseline.

  python -m topo.eval --tag run1                       # full run (several minutes on CPU)
  python -m topo.eval --tag smoke --per-family 2 --epochs 3 --seeds 42 --size-test-min 8

Protocols (all use the SAME labelling rule as the real data: only the faulted node is positive in steady state):
  family  leave-one-family-out on simulated meshes: train on 4 families, test on the 5th (never seen at all)
  size    train on meshes with <= SMALL nodes, test on meshes with >= LARGE nodes (does it scale to bigger meshes?)
  real    train on all simulated meshes, test on the real Bookinfo episodes.
          CAUTION: the simulator was calibrated on this same Bookinfo data, so this number is optimistic.
Results are SYNTHETIC unless the protocol says real. Training is mini-batch (64 graphs), unlike train_final.py which
steps one graph at a time; hyper-parameters otherwise follow loeo_eval.py (Adam lr 0.01, hidden 16, pos_weight 1).

Metrics per fold: AP (sklearn, distinct thresholds) over all node scores; RC@1 = share of fault snapshots where the
faulted node has the top score (ties count 1/k, i.e. random tie-breaking); FPR = share of normal snapshots whose top
score exceeds 0.85, the controller's act threshold (only for scorers that output a 0..1 risk).
"""
import argparse
import csv
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import average_precision_score
from torch_geometric.loader import DataLoader

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "meshheal_controlplane"))

from controlplane.scorer import RuleScorer  # noqa: E402
from controlplane.snapshot import Snapshot, node_stats, parse_ts  # noqa: E402
from model import RiskGNN  # noqa: E402
from topo import sim  # noqa: E402
from topo.graphs import record_to_graph  # noqa: E402

SEEDS = [42, 7, 13, 99, 2024]
ACT_THRESHOLD = 0.85
IN_LAT_IDX = 2


class NodeMLP(nn.Module):
    """Per-node MLP, no graph (same shape as controls_eval.NodeMLP): the 'does message passing help?' control."""

    def __init__(self, nf, h=16):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(nf, h), nn.LeakyReLU(0.1), nn.Linear(h, h), nn.LeakyReLU(0.1), nn.Linear(h, 1))

    def forward(self, x, edge_index=None):
        return self.net(x).squeeze(-1)


MODELS = {                       # name -> (class, number of features it sees)
    "gnn": (RiskGNN, 6),
    "mlp": (NodeMLP, 6),
    "gnn_degree": (RiskGNN, 8),  # + log1p in/out degree, to test whether structure features help
}
BASELINES = ["rule", "p95"]


# ------------------------------------------------------------------------------------------------ graphs
def build_graphs(records):
    graphs = []
    rule = RuleScorer(100.0)
    for r in records:
        g = record_to_graph(r, degree=True)
        snap = Snapshot(ts=parse_ts(r["timestamp"]), nodes=r["nodes"], edges=r["edges"])
        sc = rule.score(node_stats(snap))                       # the deployed rule, rate-weighted as in the controller
        g.rule = torch.tensor([sc.get(n, 0.0) for n in g.node_ids], dtype=torch.float)
        graphs.append(g)
    return graphs


def view(graphs, nf):
    """Same graphs with only the first nf features (so one build serves the 6- and 8-feature models)."""
    out = []
    for g in graphs:
        h = g.clone()
        h.x = g.x[:, :nf]
        out.append(h)
    return out


def real_bookinfo_graphs():
    """Real Bookinfo steady + normal snapshots (lag and recovery excluded, as everywhere else in the project)."""
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        from build_dataset_v2 import load_all_records
        recs = [r for r in load_all_records() if r["phase"] in ("steady", "normal")]
    finally:
        os.chdir(cwd)
    for r in recs:
        r["topology"], r["family"] = "bookinfo-real", "real"
    return build_graphs(recs)


# ------------------------------------------------------------------------------------------------ train / score
def train(spec, graphs, seed, epochs, lr=0.01, bs=64):
    cls, nf = MODELS[spec]
    torch.manual_seed(seed)
    model = cls(nf)
    gen = torch.Generator().manual_seed(seed)
    loader = DataLoader(view(graphs, nf), batch_size=bs, shuffle=True, generator=gen)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.BCEWithLogitsLoss()
    model.train()
    for _ in range(epochs):
        for b in loader:
            opt.zero_grad()
            loss_fn(model(b.x, b.edge_index), b.y).backward()
            opt.step()
    return model


def predict(spec, model, graphs):
    _, nf = MODELS[spec]
    model.eval()
    out = []
    with torch.no_grad():
        for b in DataLoader(view(graphs, nf), batch_size=512, shuffle=False):
            p = torch.sigmoid(model(b.x, b.edge_index))
            out.extend(t.numpy() for t in torch.split(p, torch.bincount(b.batch).tolist()))
    return out


def baseline_scores(name, graphs):
    if name == "rule":
        return [g.rule.numpy() for g in graphs]
    return [g.x[:, IN_LAT_IDX].numpy() for g in graphs]       # p95: log1p(incoming latency)


# ------------------------------------------------------------------------------------------------ metrics
def evaluate(graphs, scores, risk_scale=True):
    y = np.concatenate([g.y.numpy() for g in graphs])
    s = np.concatenate(scores)
    ap = float(average_precision_score(y, s)) if y.sum() > 0 else float("nan")
    rc, fp = [], []
    for g, sc in zip(graphs, scores):
        if g.phase == "steady":
            i = g.node_ids.index(g.fault_node)
            greater = int((sc > sc[i]).sum())
            ties = int((sc == sc[i]).sum()) - 1
            rc.append(0.0 if greater else 1.0 / (1 + ties))
        elif g.phase == "normal":
            fp.append(float(sc.max() > ACT_THRESHOLD))
    return {"ap": ap, "rc1": float(np.mean(rc)) if rc else float("nan"),
            "fpr": float(np.mean(fp)) if (fp and risk_scale) else float("nan")}


# ------------------------------------------------------------------------------------------------ protocols
def family_folds(graphs):
    fams = sorted({g.family for g in graphs})
    return [("family", f"hold out {f}", [g for g in graphs if g.family != f], [g for g in graphs if g.family == f]) for f in fams]


def size_fold(graphs, small, large):
    tr = [g for g in graphs if len(g.node_ids) <= small]
    te = [g for g in graphs if len(g.node_ids) >= large]
    return [("size", f"train <= {small} nodes, test >= {large} nodes", tr, te)] if tr and te else []


def run(folds, seeds, epochs, log=print):
    rows = []
    for proto, name, train_g, test_g in folds:
        t0 = time.time()
        for b in BASELINES:
            m = evaluate(test_g, baseline_scores(b, test_g), risk_scale=(b == "rule"))
            rows.append(dict(protocol=proto, fold=name, model=b, seed="-", n_train=len(train_g), n_test=len(test_g), **m))
        for spec in MODELS:
            for seed in seeds:
                model = train(spec, train_g, seed, epochs)
                m = evaluate(test_g, predict(spec, model, test_g))
                rows.append(dict(protocol=proto, fold=name, model=spec, seed=seed, n_train=len(train_g), n_test=len(test_g), **m))
        log(f"[{proto}] {name}: train {len(train_g)} / test {len(test_g)} graphs, {time.time() - t0:.0f}s")
    return rows


# ------------------------------------------------------------------------------------------------ summary
def summarise(rows):
    """{protocol: {model: {metric: (mean over folds of seed-mean, std over seeds of fold-mean)}}} plus per-fold means."""
    out = {}
    for proto in sorted({r["protocol"] for r in rows}):
        rp = [r for r in rows if r["protocol"] == proto]
        folds = sorted({r["fold"] for r in rp})
        out[proto] = {}
        for model in sorted({r["model"] for r in rp}):
            res = {}
            for met in ("ap", "rc1", "fpr"):
                seeds = sorted({r["seed"] for r in rp if r["model"] == model}, key=str)
                per_seed = []
                for s in seeds:
                    vals = [r[met] for r in rp if r["model"] == model and r["seed"] == s]
                    per_seed.append(float(np.nanmean(vals)) if not all(np.isnan(vals)) else float("nan"))
                res[met] = (float(np.nanmean(per_seed)) if not all(np.isnan(per_seed)) else float("nan"),
                            float(np.nanstd(per_seed)) if len(per_seed) > 1 and not all(np.isnan(per_seed)) else 0.0)
            out[proto][model] = res
        out[proto]["_folds"] = folds
    return out


def adoption(summary):
    """The pre-agreed rule: the GNN is adopted only if, on the held-out SYNTHETIC protocols, it beats BOTH the MLP and
    the rule on AP and RC@1 by more than the larger seed std of the two being compared. Returns (bool, text lines)."""
    lines, ok = [], True
    for proto in ("family", "size"):
        if proto not in summary:
            continue
        s = summary[proto]
        for met in ("ap", "rc1"):
            g_mean, g_std = s["gnn"][met]
            for other in ("mlp", "rule"):
                o_mean, o_std = s[other][met]
                margin = max(g_std, o_std)
                win = (g_mean - o_mean) > margin
                ok &= win
                lines.append(f"{proto:<7}{met:<4} gnn {g_mean:.3f} vs {other:<4} {o_mean:.3f}: diff {g_mean - o_mean:+.3f}, "
                             f"needs > {margin:.3f}  -> {'beats' if win else 'does NOT beat'}")
    return ok, lines


def write_outputs(rows, summary, ok, lines, meta, out_prefix):
    os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
    for ext in (".csv", ".md", ".json"):
        if os.path.exists(out_prefix + ext):
            raise SystemExit(f"refusing to overwrite {out_prefix + ext}; choose another --tag")
    with open(out_prefix + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(out_prefix + ".json", "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "adopt_gnn": ok, "rows": rows}, f, indent=1)
    fmt = lambda t: f"{t[0]:.3f} ± {t[1]:.3f}" if not np.isnan(t[0]) else "n/a"   # noqa: E731
    md = ["# Phase 3 evaluation (generated by topo/eval.py)", "",
          f"Meta: `{json.dumps(meta)}`", "",
          "Mean over folds; ± is the std over seeds of the fold-mean (0 for the deterministic rule and p95 baselines).",
          "Protocols `family` and `size` are SYNTHETIC. `real` is the real Bookinfo data, but the simulator was calibrated on it, so it is optimistic.", ""]
    for proto, s in summary.items():
        md += [f"## {proto}", f"Folds: {'; '.join(s['_folds'])}", "", "| model | AP | RC@1 | FPR@0.85 |", "|---|---|---|---|"]
        for model in ("gnn", "gnn_degree", "mlp", "rule", "p95"):
            if model in s:
                md.append(f"| {model} | {fmt(s[model]['ap'])} | {fmt(s[model]['rc1'])} | {fmt(s[model]['fpr'])} |")
        md.append("")
    md += ["## Adoption rule (agreed in advance)", "GNN is adopted only if it beats both the MLP and the rule on AP and RC@1 "
           "on the held-out synthetic protocols by more than the seed spread.", "", "```"] + lines + ["```", "",
          f"**Verdict: GNN {'ADOPTED' if ok else 'NOT adopted'}.**", ""]
    with open(out_prefix + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="output name: topo/results/<tag>.{csv,md,json} (never overwritten)")
    ap.add_argument("--corpus-seed", type=int, default=0)
    ap.add_argument("--per-family", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    ap.add_argument("--size-small", type=int, default=9)
    ap.add_argument("--size-test-min", type=int, default=16)
    ap.add_argument("--no-real", action="store_true")
    a = ap.parse_args(argv)

    t0 = time.time()
    topos, records = sim.make_corpus(a.corpus_seed, per_family=a.per_family)
    graphs = build_graphs(records)
    print(f"corpus: {len(topos)} topologies, {len(graphs)} snapshots, node counts {min(len(t.nodes) for t in topos)}-"
          f"{max(len(t.nodes) for t in topos)}  ({time.time() - t0:.0f}s)")
    folds = family_folds(graphs) + size_fold(graphs, a.size_small, a.size_test_min)
    if not a.no_real:
        real = real_bookinfo_graphs()
        folds.append(("real", "synthetic -> real Bookinfo", graphs, real))
    rows = run(folds, a.seeds, a.epochs)
    summary = summarise(rows)
    ok, lines = adoption(summary)
    meta = {"corpus_seed": a.corpus_seed, "per_family": a.per_family, "epochs": a.epochs, "seeds": a.seeds,
            "snapshots": len(graphs), "size_small": a.size_small, "size_test_min": a.size_test_min,
            "torch": torch.__version__, "elapsed_s": round(time.time() - t0)}
    write_outputs(rows, summary, ok, lines, meta, os.path.join(ROOT, "topo", "results", a.tag))
    print("\n".join(lines))
    print(f"GNN {'ADOPTED' if ok else 'NOT adopted'} under the pre-agreed rule; wrote topo/results/{a.tag}.*")


if __name__ == "__main__":
    main()
