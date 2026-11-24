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

from controlplane.scorer import BaselineScorer, RuleScorer  # noqa: E402
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
BASELINES = ["rule", "p95", "baseline", "baseline_clamp"]
RISK_SCALED = ("rule", "baseline", "baseline_clamp")    # these output a 0..1 risk, so the 0.85 false-alarm rate applies


# ------------------------------------------------------------------------------------------------ graphs
def build_graphs(records, baseline_path=None):
    """Attach to each graph the deterministic baseline scores we compare the models against:
      g.rule     = RuleScorer (hand-set 100 ms scale)
      g.baseline = BaselineScorer (loaded from --baseline, if any; otherwise same as rule).
    """
    graphs = []
    rule = RuleScorer(100.0)
    baseline = BaselineScorer.from_file(baseline_path) if baseline_path else BaselineScorer()
    clamp = BaselineScorer.from_file(baseline_path, saturation="clamp") if baseline_path else BaselineScorer(saturation="clamp")
    for r in records:
        g = record_to_graph(r, degree=True)
        snap = Snapshot(ts=parse_ts(r["timestamp"]), nodes=r["nodes"], edges=r["edges"])
        st = node_stats(snap)
        sc_rule = rule.score(st)
        sc_base = baseline.score(st)
        sc_clamp = clamp.score(st)
        g.rule = torch.tensor([sc_rule.get(n, 0.0) for n in g.node_ids], dtype=torch.float)
        g.baseline = torch.tensor([sc_base.get(n, 0.0) for n in g.node_ids], dtype=torch.float)
        g.baseline_clamp = torch.tensor([sc_clamp.get(n, 0.0) for n in g.node_ids], dtype=torch.float)
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


def real_boutique_graphs(snapshots, fault_log, normal_only=None, baseline_path=None):
    """Real Online Boutique: labelled fault episodes plus (optionally) a separate fault-free collection."""
    from topo import real
    recs = real.label_records(snapshots, fault_log, "boutique-real", family="real", keep=("steady", "normal"))
    if normal_only:
        recs += real.normal_records(normal_only, "boutique-real")
    # The collector lists a service only when it has an edge in that window. A service with almost no traffic (the checkout
    # path gets ~3 requests per minute) can be absent from a snapshot even though it is up. Give every graph the same full set
    # of services, with zero features for an idle one (the original Bookinfo builder treats idle services the same way).
    universe = sorted({n["id"] for r in recs for n in r["nodes"]} - {"unknown"})
    for r in recs:
        have = {n["id"] for n in r["nodes"]}
        r["nodes"] = list(r["nodes"]) + [{"id": n, "region": "boutique"} for n in universe if n not in have]
        r["labels"] = {n: int(r["phase"] == "steady" and n == r["fault_node"]) for n in universe}
    return build_graphs(recs, baseline_path)


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
    if name == "baseline":
        return [g.baseline.numpy() for g in graphs]
    if name == "baseline_clamp":
        return [g.baseline_clamp.numpy() for g in graphs]
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


def run(folds, seeds, epochs, log=print, train_models=True):
    rows = []
    for proto, name, train_g, test_g in folds:
        t0 = time.time()
        for b in BASELINES:
            m = evaluate(test_g, baseline_scores(b, test_g), risk_scale=(b in RISK_SCALED))
            rows.append(dict(protocol=proto, fold=name, model=b, seed="-", n_train=len(train_g), n_test=len(test_g), **m))
        for spec in (MODELS if train_models else ()):
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
    the rule on AP and RC@1 by more than the larger seed std of the two being compared. Returns (bool, text lines);
    (None, [...]) when neither synthetic protocol was run, so no verdict is claimed."""
    if not any(p in summary for p in ("family", "size")):
        return None, ["not evaluated: this run has no held-out synthetic protocol"]
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
          "Protocols `family` and `size` are SYNTHETIC. `real` is the real Bookinfo data, but the simulator was calibrated on it, so it is optimistic. "
          "`boutique*` is real Online Boutique data (load-generated traffic with faults WE injected) that the simulator was NOT calibrated on.", ""]
    for proto, s in summary.items():
        md += [f"## {proto}", f"Folds: {'; '.join(s['_folds'])}", "", "| model | AP | RC@1 | FPR@0.85 |", "|---|---|---|---|"]
        for model in ("gnn", "gnn_degree", "mlp", "baseline", "baseline_clamp", "rule", "p95"):
            if model in s:
                md.append(f"| {model} | {fmt(s[model]['ap'])} | {fmt(s[model]['rc1'])} | {fmt(s[model]['fpr'])} |")
        md.append("")
    md += ["## Adoption rule (agreed in advance)", "GNN is adopted only if it beats both the MLP and the rule on AP and RC@1 "
           "on the held-out synthetic protocols by more than the seed spread.", "", "```"] + lines + ["```", "",
          ("**Verdict: not evaluated in this run (no held-out synthetic protocol).**" if ok is None
           else f"**Verdict: GNN {'ADOPTED' if ok else 'NOT adopted'}.**"), ""]
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
    ap.add_argument("--boutique-snapshots", help="real Online Boutique snapshots from the fault run")
    ap.add_argument("--boutique-fault-log", help="fault log of that run")
    ap.add_argument("--boutique-normal", help="extra fault-free Boutique snapshots (for the false-alarm rate)")
    ap.add_argument("--only-boutique", action="store_true", help="run only the real-Boutique protocols (no family/size/Bookinfo folds)")
    ap.add_argument("--baseline", default=None, help="learned BaselineScorer YAML (controlplane.learn_baseline) for the real-Boutique folds")
    ap.add_argument("--baselines-only", action="store_true", help="score only the deterministic baselines (rule, p95, baseline); no model training")
    a = ap.parse_args(argv)

    t0 = time.time()
    topos, records = sim.make_corpus(a.corpus_seed, per_family=a.per_family)
    graphs = build_graphs(records)
    print(f"corpus: {len(topos)} topologies, {len(graphs)} snapshots, node counts {min(len(t.nodes) for t in topos)}-"
          f"{max(len(t.nodes) for t in topos)}  ({time.time() - t0:.0f}s)")
    folds = [] if a.only_boutique else family_folds(graphs) + size_fold(graphs, a.size_small, a.size_test_min)
    bookinfo = None
    if not a.no_real and not a.only_boutique:
        bookinfo = real_bookinfo_graphs()
        folds.append(("real", "synthetic -> real Bookinfo", graphs, bookinfo))
    if a.boutique_snapshots:
        boutique = real_boutique_graphs(a.boutique_snapshots, a.boutique_fault_log, a.boutique_normal, a.baseline)
        n_st = sum(1 for g in boutique if g.phase == "steady")
        print(f"real Boutique: {len(boutique)} snapshots ({n_st} steady, {len(boutique) - n_st} normal), "
              f"{len({g.fault_node for g in boutique if g.phase == 'steady'})} faulted services")
        folds.append(("boutique", "synthetic -> real Boutique (independent real test)", graphs, boutique))
        bookinfo = bookinfo or real_bookinfo_graphs()
        folds.append(("boutique_plus_bookinfo", "synthetic + real Bookinfo -> real Boutique", graphs + bookinfo, boutique))
    if not folds:
        ap.error("nothing to run")
    rows = run(folds, a.seeds, a.epochs, train_models=not a.baselines_only)
    summary = summarise(rows)
    ok, lines = adoption(summary)
    meta = {"baseline": a.baseline, "baselines_only": a.baselines_only, "corpus_seed": a.corpus_seed, "per_family": a.per_family, "epochs": a.epochs, "seeds": a.seeds,
            "snapshots": len(graphs), "size_small": a.size_small, "size_test_min": a.size_test_min,
            "torch": torch.__version__, "elapsed_s": round(time.time() - t0)}
    write_outputs(rows, summary, ok, lines, meta, os.path.join(ROOT, "topo", "results", a.tag))
    print("\n".join(lines))
    verdict = "not evaluated (no held-out synthetic protocol)" if ok is None else ("ADOPTED" if ok else "NOT adopted")
    print(f"GNN {verdict} under the pre-agreed rule; wrote topo/results/{a.tag}.*")


if __name__ == "__main__":
    main()
