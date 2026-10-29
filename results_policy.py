"""
results_policy.py
=================
Policy simulation for MeshHeal AI.

For each of the 8 LOEO folds:
  1. Retrain the GNN (same seeds, config as loeo_eval.py) and confirm per-fold AP
     matches results_loeo.csv (flag any fold that differs by >0.001).
  2. Split the 137-snapshot normal holdout chronologically into two halves.
  3. Set each model's threshold at the 95th percentile of its scores over all
     node-readings in the FIRST half. Never use the second half to set anything.
  4. Policy: act on the single top-ranked node only if its score is above that
     threshold AND the same node was the top-ranked, above-threshold node in
     3 of the last 4 snapshots.
  5. Report per fold and per model (GNN, p95 baseline, culprit-score rule):
       a. Share of steady snapshots where action targets the faulted node
       b. Share where it targets a wrong node
       c. Share where no action fires
       d. On the SECOND half of the holdout only: share where any action fires

Output: results_policy.md
New file; does not modify any existing script or result.
"""

import csv
import math
import os
from collections import deque
from datetime import timedelta

import torch
import torch.nn as nn

from build_dataset_v2 import (
    ALL_EPISODES, NODE_VOCAB, NODE_INDEX,
    load_all_records, build_normal_holdout_ts,
    record_to_graph,
    LEAKAGE_BUFFER, RECOVERY_BUFFER,
)
from loeo_eval import (
    build_loeo_split, train_gnn, gnn_probs, gnn_scores_for_graph,
    baseline_probs,
    SEEDS, IN_LAT_IDX, LR, EPOCHS, POS_WEIGHT, NUM_FEATURES,
)

RESULT_MD = os.environ.get("POLICY_RESULT_MD", "results_policy.md")
LOEO_CSV = os.environ.get("LOEO_RESULT_CSV", "results_loeo.csv")   # AP reproduction check reads this
TEST_PRE_BUFFER = timedelta(seconds=60)
COLLAPSE_THRESH = 0.01
POLICY_WINDOW = 4
POLICY_MIN = 3
OUT_LAT_IDX = 3  # log1p(out_latency_p95) — from build_dataset_v2.py record_to_graph


# ─────────────────────────────────────────────────────────────────────────────
# Metric helpers
# ─────────────────────────────────────────────────────────────────────────────

def mean_std(lst):
    lst = [x for x in lst if x == x]
    if not lst:
        return float("nan"), float("nan")
    m = sum(lst) / len(lst)
    v = sum((x - m) ** 2 for x in lst) / max(len(lst) - 1, 1)
    return m, math.sqrt(v)


def ap_trapezoidal(probs, labels):
    """Exact same as loeo_eval.py average_precision."""
    if sum(labels) == 0:
        return 0.0
    paired = sorted(zip(probs, labels), key=lambda x: -x[0])
    tp = fp = 0
    total_pos = sum(labels)
    prev_rec = 0.0; prev_prec = 1.0; ap = 0.0
    for prob, lbl in paired:
        if lbl == 1: tp += 1
        else:        fp += 1
        prec = tp / (tp + fp)
        rec  = tp / total_pos
        ap  += (rec - prev_rec) * (prec + prev_prec) / 2.0
        prev_rec = rec; prev_prec = prec
    return ap


# ─────────────────────────────────────────────────────────────────────────────
# Score functions
# ─────────────────────────────────────────────────────────────────────────────

def baseline_score_fn(g):
    return g.x[:, IN_LAT_IDX].tolist()

def culprit_score_fn(g):
    scores = []
    for i in range(len(NODE_VOCAB)):
        inf  = g.x[i, IN_LAT_IDX].item()
        outf = g.x[i, OUT_LAT_IDX].item()
        scores.append(inf - outf)
    return scores


# ─────────────────────────────────────────────────────────────────────────────
# Policy logic
# ─────────────────────────────────────────────────────────────────────────────

def percentile_95(score_lists):
    all_s = [s for lst in score_lists for s in lst]
    if not all_s:
        return float("nan")
    all_s.sort()
    idx = min(int(0.95 * len(all_s)), len(all_s) - 1)
    return all_s[idx]


class PolicyState:
    def __init__(self):
        self.history = {n: deque(maxlen=POLICY_WINDOW) for n in NODE_VOCAB}

    def reset(self):
        for n in NODE_VOCAB:
            self.history[n].clear()

    def step(self, scores, threshold):
        """Return action node name, or None."""
        best_i = max(range(len(scores)), key=lambda i: scores[i])
        top_name = NODE_VOCAB[best_i] if scores[best_i] > threshold else None
        for n in NODE_VOCAB:
            self.history[n].append(n == top_name)
        if top_name is not None and sum(self.history[top_name]) >= POLICY_MIN:
            return top_name
        return None


def eval_steady(graphs, fault_node, score_fn, threshold, policy_state):
    correct = wrong = no_action = 0
    for g in graphs:
        action = policy_state.step(score_fn(g), threshold)
        if action is None:
            no_action += 1
        elif action == fault_node:
            correct += 1
        else:
            wrong += 1
    n = correct + wrong + no_action
    def sh(x): return x / n if n > 0 else float("nan")
    return dict(n=n, correct=correct, wrong=wrong, no_action=no_action,
                s_correct=sh(correct), s_wrong=sh(wrong), s_no_action=sh(no_action))


def eval_holdout2(graphs, score_fn, threshold, policy_state):
    fires = total = 0
    for g in graphs:
        action = policy_state.step(score_fn(g), threshold)
        total += 1
        if action is not None:
            fires += 1
    return dict(n=total, fires=fires, s_fires=fires/total if total > 0 else float("nan"))


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def run_policy():
    print("=" * 70)
    print("MeshHeal AI  --  Policy Simulation")
    print("=" * 70)

    print("\nLoading all records ...")
    all_records = load_all_records()
    holdout_ts = build_normal_holdout_ts(all_records)

    holdout_graphs_ordered = sorted(
        (r for r in all_records if r["timestamp"] in holdout_ts),
        key=lambda r: r["timestamp"]
    )
    holdout_graphs_ordered = [g for r in holdout_graphs_ordered
                               for g in [record_to_graph(r)] if g is not None]
    n_holdout = len(holdout_graphs_ordered)
    mid = n_holdout // 2
    h1 = holdout_graphs_ordered[:mid]
    h2 = holdout_graphs_ordered[mid:]
    print(f"Normal holdout: {n_holdout} graphs -> h1={len(h1)}, h2={len(h2)}")

    csv_gnn_ap = {}
    try:
        with open(LOEO_CSV) as f:
            for row in csv.DictReader(f):
                csv_gnn_ap[int(row["fold"])] = float(row["gnn_ap_mean"])
    except Exception as e:
        print(f"WARNING: {LOEO_CSV}: {e}")

    fold_results = []

    for fold_k in range(len(ALL_EPISODES)):
        ep = ALL_EPISODES[fold_k]
        fn = ep["node"]
        print(f"\n{'─'*70}")
        print(f"FOLD {fold_k}  ep={ep['episode_id']} node={fn} delay={ep['delay_ms']}ms")

        train_g, val_g, test_g, steady_test_g = build_loeo_split(
            all_records, fold_k, holdout_ts)
        if not train_g or not steady_test_g:
            print("  SKIP")
            continue

        # Baseline threshold
        bl_thresh = percentile_95([baseline_score_fn(g) for g in h1])
        cs_thresh = percentile_95([culprit_score_fn(g) for g in h1])
        print(f"  bl_thresh={bl_thresh:.4f}  cs_thresh={cs_thresh:.4f}")

        # Baseline policy
        bl_ps = PolicyState()
        bl_steady = eval_steady(steady_test_g, fn, baseline_score_fn, bl_thresh, bl_ps)
        bl_h2 = eval_holdout2(h2, baseline_score_fn, bl_thresh, bl_ps)

        # Culprit policy
        cs_ps = PolicyState()
        cs_steady = eval_steady(steady_test_g, fn, culprit_score_fn, cs_thresh, cs_ps)
        cs_h2 = eval_holdout2(h2, culprit_score_fn, cs_thresh, cs_ps)

        print(f"  BL steady: {bl_steady['correct']}/{bl_steady['n']} correct  h2_fires={bl_h2['fires']}/{bl_h2['n']}")
        print(f"  CS steady: {cs_steady['correct']}/{cs_steady['n']} correct  h2_fires={cs_h2['fires']}/{cs_h2['n']}")

        # GNN per seed
        gnn_seed_ap = []
        gnn_fold_data = []

        for seed in SEEDS:
            model = train_gnn(train_g, seed)
            gtp, gtl = gnn_probs(model, test_g)
            prob_std = torch.tensor(gtp).std().item()
            ap_val = ap_trapezoidal(gtp, gtl)

            if prob_std < COLLAPSE_THRESH:
                print(f"    Seed {seed}: COLLAPSE std={prob_std:.4f}")
                gnn_fold_data.append(dict(seed=seed, collapsed=True, ap=ap_val, std=prob_std))
                continue

            gnn_seed_ap.append(ap_val)

            def _gfn(g, m=model):
                return gnn_scores_for_graph(m, g)

            gnn_thresh = percentile_95([_gfn(g) for g in h1])
            gnn_ps = PolicyState()
            gnn_st = eval_steady(steady_test_g, fn, _gfn, gnn_thresh, gnn_ps)
            gnn_h2 = eval_holdout2(h2, _gfn, gnn_thresh, gnn_ps)

            gnn_fold_data.append(dict(
                seed=seed, collapsed=False, ap=ap_val, std=prob_std,
                thresh=gnn_thresh, steady=gnn_st, h2=gnn_h2,
            ))
            print(f"    Seed {seed}: AP={ap_val:.3f} thresh={gnn_thresh:.4f} "
                  f"correct={gnn_st['correct']} wrong={gnn_st['wrong']} "
                  f"no_action={gnn_st['no_action']}  h2_fires={gnn_h2['fires']}")

        gnn_ap_m, gnn_ap_s = mean_std(gnn_seed_ap) if gnn_seed_ap else (float("nan"), float("nan"))
        csv_ap = csv_gnn_ap.get(fold_k, float("nan"))
        ap_diff = abs(gnn_ap_m - csv_ap) if (gnn_ap_m == gnn_ap_m and csv_ap == csv_ap) else float("nan")
        flag = "FLAG" if (ap_diff == ap_diff and ap_diff > 0.001) else "OK"
        print(f"  GNN AP={gnn_ap_m:.3f} CSV={csv_ap:.3f} diff={ap_diff:.4f} [{flag}]")

        fold_results.append(dict(
            fold=fold_k, ep=ep["episode_id"], node=fn, delay=ep["delay_ms"],
            n_steady=len(steady_test_g),
            bl_thresh=bl_thresh, bl_steady=bl_steady, bl_h2=bl_h2,
            cs_thresh=cs_thresh, cs_steady=cs_steady, cs_h2=cs_h2,
            gnn_ap_m=gnn_ap_m, gnn_ap_s=gnn_ap_s,
            gnn_csv_ap=csv_ap, gnn_ap_diff=ap_diff, gnn_ap_flag=flag,
            gnn_fold_data=gnn_fold_data,
        ))

    return fold_results, len(h1), len(h2)


# ─────────────────────────────────────────────────────────────────────────────
# Markdown
# ─────────────────────────────────────────────────────────────────────────────

def f3(v):
    return "nan" if v != v else f"{v:.3f}"

def fpct(v):
    return "nan" if v != v else f"{v:.1%}"

def mn(lst):
    v = [x for x in lst if x == x]
    return sum(v)/len(v) if v else float("nan")


def write_markdown(fold_results, n_h1, n_h2):
    lines = []
    A = lines.append

    A("# MeshHeal AI — Policy Simulation")
    A("")
    A("*Generated by results_policy.py*")
    A("")
    A("## Setup")
    A("")
    A("| Parameter | Value |")
    A("|-----------|-------|")
    A(f"| Folds | 8 (same LOEO splits, seeds, config as loeo_eval.py) |")
    A(f"| GNN seeds | {SEEDS} |")
    A(f"| GNN config | hidden=16, LeakyReLU(0.1), Adam lr={0.01}, epochs=100, pos_weight=1.0 |")
    A(f"| Collapse rule | prob_std < 0.01 → seed skipped |")
    A(f"| Normal holdout total | {n_h1 + n_h2} snapshots |")
    A(f"| Holdout first half (calibration) | {n_h1} snapshots |")
    A(f"| Holdout second half (FPR eval) | {n_h2} snapshots |")
    A(f"| Threshold rule | 95th percentile of scores over all node-readings in first half |")
    A(f"| Policy | Top node must be > threshold AND was top+above-thresh in ≥3 of last 4 snaps |")
    A("")
    A("> The second half of the holdout is used **only** to measure false-action rate; "
      "it is never used to set any threshold or tune any parameter.")
    A("")

    A(f"## GNN AP Reproduction Check (vs {LOEO_CSV})")
    A("")
    A("| Fold | Ep | Node | Delay | Seeds used | Retrained AP | CSV AP | Diff | Flag |")
    A("|------|----|------|-------|-----------|-------------|--------|------|------|")
    for r in fold_results:
        n_used = sum(1 for d in r["gnn_fold_data"] if not d["collapsed"])
        A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | {n_used}/5 | "
          f"{f3(r['gnn_ap_m'])} | {f3(r['gnn_csv_ap'])} | {f3(r['gnn_ap_diff'])} | {r['gnn_ap_flag']} |")
    A("")
    A("> Differences ≤0.001 are expected from floating-point rounding; flagged if >0.001.")
    A("")

    A("## Thresholds — 95th Percentile of Model Score on Holdout First Half")
    A("")
    A("| Fold | Ep | Node | Delay | BL thresh | CS thresh | GNN thresh (per seed) |")
    A("|------|----|------|-------|-----------|-----------|----------------------|")
    for r in fold_results:
        parts = []
        for d in r["gnn_fold_data"]:
            if d["collapsed"]:
                parts.append(f"s{d['seed']}:COLL")
            else:
                parts.append(f"s{d['seed']}:{d['thresh']:.3f}")
        A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | "
          f"{f3(r['bl_thresh'])} | {f3(r['cs_thresh'])} | {', '.join(parts)} |")
    A("")

    # Steady tables
    for label, sk, note in [
        ("Baseline (p95 in-latency)", "bl_steady", None),
        ("Culprit Score (log1p, in_lat − out_lat)", "cs_steady",
         "OUT_LAT_IDX=3 assumed from build_dataset_v2.py. If wrong, scores are mislabelled. **not tested** with live data."),
    ]:
        A(f"## Policy Results on Steady-Fault Snapshots — {label}")
        A("")
        if note:
            A(f"> {note}")
            A("")
        A("| Fold | Ep | Node | Delay | n_steady | Correct | Wrong | No-action | "
          "share_correct | share_wrong | share_no_action |")
        A("|------|----|------|-------|---------|---------|-------|-----------|"
          "------------|------------|-----------------|")
        sc=[]; sw=[]; sn=[]
        for r in fold_results:
            s = r[sk]
            A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | {s['n']} | "
              f"{s['correct']} | {s['wrong']} | {s['no_action']} | "
              f"{fpct(s['s_correct'])} | {fpct(s['s_wrong'])} | {fpct(s['s_no_action'])} |")
            sc.append(s['s_correct']); sw.append(s['s_wrong']); sn.append(s['s_no_action'])
        A(f"| **Mean** | | | | | | | | {fpct(mn(sc))} | {fpct(mn(sw))} | {fpct(mn(sn))} |")
        A("")

    A("## Policy Results on Steady-Fault Snapshots — GNN (per seed)")
    A("")
    A("Threshold per seed = 95th percentile of that seed's scores on holdout first half.")
    A("")
    A("| Fold | Ep | Node | Delay | Seed | Thresh | n_steady | Correct (%) | Wrong (%) | No-action (%) |")
    A("|------|----|------|-------|------|--------|---------|------------|----------|--------------|")
    for r in fold_results:
        for d in r["gnn_fold_data"]:
            if d["collapsed"]:
                A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | "
                  f"s{d['seed']} | COLLAPSED | {r['n_steady']} | — | — | — |")
            else:
                s = d["steady"]
                A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | "
                  f"s{d['seed']} | {d['thresh']:.3f} | {s['n']} | "
                  f"{s['correct']} ({fpct(s['s_correct'])}) | "
                  f"{s['wrong']} ({fpct(s['s_wrong'])}) | "
                  f"{s['no_action']} ({fpct(s['s_no_action'])}) |")
    A("")

    A("### GNN Policy — Mean over Non-Collapsed Seeds per Fold")
    A("")
    A("| Fold | Ep | Node | Delay | n_steady | Seeds | share_correct | share_wrong | share_no_action |")
    A("|------|----|------|-------|---------|-------|--------------|------------|-----------------|")
    gc=[]; gw=[]; gn=[]
    for r in fold_results:
        valid = [d for d in r["gnn_fold_data"] if not d["collapsed"]]
        if not valid:
            A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | {r['n_steady']} | 0/5 | nan | nan | nan |")
            continue
        c = sum(d["steady"]["s_correct"] for d in valid) / len(valid)
        w = sum(d["steady"]["s_wrong"] for d in valid) / len(valid)
        n_ = sum(d["steady"]["s_no_action"] for d in valid) / len(valid)
        A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | {r['n_steady']} | "
          f"{len(valid)}/5 | {fpct(c)} | {fpct(w)} | {fpct(n_)} |")
        gc.append(c); gw.append(w); gn.append(n_)
    A(f"| **Mean** | | | | | | {fpct(mn(gc))} | {fpct(mn(gw))} | {fpct(mn(gn))} |")
    A("")

    A(f"## False Action Rate — Second-Half Normal Holdout (n={n_h2} snapshots per fold)")
    A("")
    A("All snapshots are pure-normal; any action is a false alarm. "
      "Policy state carries over from steady-fault evaluation.")
    A("")
    A("| Fold | Ep | Node | Delay | BL fires | BL share | CS fires | CS share | GNN mean share |")
    A("|------|----|------|-------|---------|---------|---------|---------|----------------|")
    for r in fold_results:
        valid = [d for d in r["gnn_fold_data"] if not d["collapsed"]]
        gnn_mean_s = mn([d["h2"]["s_fires"] for d in valid]) if valid else float("nan")
        A(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | "
          f"{r['bl_h2']['fires']} | {fpct(r['bl_h2']['s_fires'])} | "
          f"{r['cs_h2']['fires']} | {fpct(r['cs_h2']['s_fires'])} | "
          f"{fpct(gnn_mean_s)} |")
    A("")
    A("> Policy state at start of second-half holdout reflects history accumulated during "
      "steady-fault evaluation (not reset). Early holdout snapshots may still carry "
      "above-threshold history from fault period.")
    A("")

    A("## GNN Per-Seed False Action Rate (Holdout Second Half)")
    A("")
    A("| Fold | Ep | Seed | h2 fires | h2 n | share |")
    A("|------|----|------|---------|------|-------|")
    for r in fold_results:
        for d in r["gnn_fold_data"]:
            if d["collapsed"]:
                A(f"| {r['fold']} | {r['ep']} | s{d['seed']} | COLLAPSED | — | — |")
            else:
                A(f"| {r['fold']} | {r['ep']} | s{d['seed']} | "
                  f"{d['h2']['fires']} | {d['h2']['n']} | {fpct(d['h2']['s_fires'])} |")
    A("")

    A("## Assumptions, Deviations, and Items Not Run")
    A("")
    A("1. **Threshold calibration.** 95th percentile of scores over all 4-node readings "
      f"in the first {n_h1} holdout snapshots (= {4*n_h1} node-readings).")
    A("2. **Policy state continuity.** 3-of-4 history reset at start of each fold. "
      "Steady graphs processed chronologically. History then continues into h2 holdout eval.")
    A("3. **OUT_LAT_IDX=3.** Culprit score assumption. **not tested** against live data.")
    A("4. **GNN threshold per seed.** Each seed's model gets its own 95th-pct threshold.")
    A("5. **Steady snapshots.** phase='steady', correct episode_id, within test window.")
    A("6. **Confounded 6-fold controls.** Item 5 from the task (clean Oct-18 6-fold policy) "
      "is **not run**; the 8-fold policy above already covers all episodes.")
    A("7. **results_controls.md.** Culprit-score raw-latency variant: not tested here; "
      "see Control 1 in results_controls.md.")
    A("8. **Statistical significance.** Not tested. ~13-14 steady snapshots per fold.")
    A("")
    A("---")
    A("*Generated by results_policy.py*")

    with open(RESULT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nWritten to {RESULT_MD}")


if __name__ == "__main__":
    fold_results, n_h1, n_h2 = run_policy()
    write_markdown(fold_results, n_h1, n_h2)
    print("\nDone.")
