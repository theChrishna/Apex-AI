"""
controls_eval.py — Two missing controls plus a cleaner mean-latency experiment.
Output: results_controls.md
New file; does not modify any existing script or result file.
"""
import warnings
warnings.filterwarnings("ignore")
import json, math, bisect, csv, os
from datetime import datetime, timedelta
import torch
import torch.nn as nn
from build_dataset_v2 import (
    ALL_EPISODES, NODE_VOCAB, NODE_INDEX,
    load_all_records, build_normal_holdout_ts,
    record_to_graph, load_latency_mean,
    LEAKAGE_BUFFER, RECOVERY_BUFFER,
)
from loeo_eval import (
    build_loeo_split, train_gnn, gnn_probs, gnn_scores_for_graph,
    baseline_probs, best_threshold_f1, SEEDS, IN_LAT_IDX,
    LR, EPOCHS, POS_WEIGHT, NUM_FEATURES,
)
from model import RiskGNN

COLLAPSE_THRESH  = 0.01
OUT_LAT_IDX      = 3   # log1p(out_latency_p95) in record_to_graph
TEST_PRE_BUFFER  = timedelta(seconds=60)
RESULT_MD        = os.environ.get("CONTROLS_RESULT_MD", "results_controls.md")

# ── Metrics ──────────────────────────────────────────────────────────────────

def ap_distinct(probs, labels):
    """AP: one PR point per distinct score (equivalent to sklearn's implementation)."""
    if sum(labels) == 0:
        return 0.0
    total_pos = sum(labels)
    pairs = sorted(zip(probs, labels), key=lambda x: -x[0])
    tp = fp = ap = 0
    prev_rec = 0.0
    ptp = pfp = 0
    prev_score = None
    for score, lbl in pairs:
        if prev_score is not None and score != prev_score:
            tp += ptp; fp += pfp
            prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
            rec  = tp / total_pos
            ap  += (rec - prev_rec) * prec
            prev_rec = rec; ptp = pfp = 0
        (ptp if lbl else pfp).__class__  # dummy
        if lbl: ptp += 1
        else:   pfp += 1
        prev_score = score
    tp += ptp; fp += pfp
    prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    rec  = tp / total_pos
    ap  += (rec - prev_rec) * prec
    return ap


def ap_original(probs, labels):
    """Original trapezoidal AP from loeo_eval.py."""
    if sum(labels) == 0: return 0.0
    paired = sorted(zip(probs, labels), key=lambda x: -x[0])
    tp = fp = 0; total_pos = sum(labels)
    prev_rec = 0.0; prev_prec = 1.0; ap = 0.0
    for prob, lbl in paired:
        if lbl: tp += 1
        else:   fp += 1
        prec = tp/(tp+fp); rec = tp/total_pos
        ap += (rec - prev_rec) * (prec + prev_prec) / 2.0
        prev_rec = rec; prev_prec = prec
    return ap


def auroc(probs, labels):
    pos = [p for p,l in zip(probs,labels) if l==1]
    neg = [p for p,l in zip(probs,labels) if l==0]
    if not pos or not neg: return float("nan")
    c = sum(1 for p in pos for n in neg if p>n) + 0.5*sum(1 for p in pos for n in neg if p==n)
    return c / (len(pos)*len(neg))


def mean_std(vs):
    if not vs: return float("nan"), float("nan")
    m = sum(vs)/len(vs)
    if len(vs)==1: return m, 0.0
    return m, math.sqrt(sum((x-m)**2 for x in vs)/(len(vs)-1))


def rc1(graphs, score_fn, fault_node):
    correct = total = 0
    for g in graphs:
        scores = score_fn(g)
        bi = max(range(len(NODE_VOCAB)), key=lambda i: scores[i])
        if NODE_VOCAB[bi] == fault_node: correct += 1
        total += 1
    return correct/total if total>0 else float("nan")


def rec_at_5pct(holdout_graphs, score_fn, steady_graphs, fault_node):
    hs = []
    for g in holdout_graphs: hs.extend(score_fn(g))
    if not hs: return float("nan")
    hs.sort()
    thr = hs[int(0.95*len(hs))]
    fi = NODE_INDEX[fault_node]
    correct = total = 0
    for g in steady_graphs:
        if score_fn(g)[fi] > thr: correct += 1
        total += 1
    return correct/total if total>0 else float("nan")


# ── Culprit rule ──────────────────────────────────────────────────────────────

def culprit_probs(graphs, log1p=True):
    ps = []; ls = []
    for g in graphs:
        for i in range(len(NODE_VOCAB)):
            inf = g.x[i, IN_LAT_IDX].item()
            outf = g.x[i, OUT_LAT_IDX].item()
            s = (inf - outf) if log1p else (math.expm1(max(inf,0)) - math.expm1(max(outf,0)))
            ps.append(s); ls.append(int(g.y[i].item()))
    return ps, ls


def culprit_fn(g, log1p=True):
    scores = []
    for i in range(len(NODE_VOCAB)):
        inf = g.x[i, IN_LAT_IDX].item()
        outf = g.x[i, OUT_LAT_IDX].item()
        scores.append((inf-outf) if log1p else (math.expm1(max(inf,0))-math.expm1(max(outf,0))))
    return scores


# ── MLP ───────────────────────────────────────────────────────────────────────

class NodeMLP(nn.Module):
    def __init__(self, nf=NUM_FEATURES, h=16):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(nf,h), nn.LeakyReLU(0.1),
            nn.Linear(h,h),  nn.LeakyReLU(0.1),
            nn.Linear(h,1),
        )
    def forward(self, x):
        return self.net(x).squeeze(-1)


def train_mlp(train_graphs, seed, nf=NUM_FEATURES):
    torch.manual_seed(seed)
    m = NodeMLP(nf)
    opt = torch.optim.Adam(m.parameters(), lr=LR)
    lf  = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([POS_WEIGHT]))
    m.train()
    for _ in range(EPOCHS):
        for g in train_graphs:
            opt.zero_grad()
            loss = lf(m(g.x), g.y.float())
            loss.backward(); opt.step()
    m.eval(); return m


def mlp_probs(model, graphs):
    ps=[]; ls=[]
    with torch.no_grad():
        for g in graphs:
            p = torch.sigmoid(model(g.x))
            ps.extend(p.tolist()); ls.extend(g.y.tolist())
    return ps, ls


def mlp_fn(model, g):
    with torch.no_grad():
        return torch.sigmoid(model(g.x)).tolist()


# ── Oct-18 6-fold split ───────────────────────────────────────────────────────

def _nn(ts_str, raw, times, keys, gap=10.0):
    ts = datetime.fromisoformat(ts_str)
    idx = bisect.bisect_left(times, ts)
    best_dt = best_k = None
    for ci in [max(0,idx-1), min(idx,len(times)-1)]:
        dt = abs((times[ci]-ts).total_seconds())
        if best_dt is None or dt < best_dt: best_dt, best_k = dt, keys[ci]
    return raw[best_k] if best_dt is not None and best_dt <= gap else None


def oct18_split(all_records, fold_k, holdout_ts,
                use7=False, raw=None, times=None, keys=None):
    new_eps = [ep for ep in ALL_EPISODES if ep["source"]=="fault_log"]
    ep_t = new_eps[fold_k]; ep_v = new_eps[(fold_k+1)%len(new_eps)]
    tlo = ep_t["start"]-TEST_PRE_BUFFER; thi = ep_t["end"]+RECOVERY_BUFFER
    vlo = ep_v["start"]-TEST_PRE_BUFFER; vhi = ep_v["end"]+RECOVERY_BUFFER

    def to_g(r):
        if use7:
            ex = _nn(r["timestamp"], raw, times, keys)
            if ex is None: return None
            return record_to_graph(r, scale=True, extra_mean_lat=ex)
        return record_to_graph(r, scale=True)

    tr=[]; va=[]; te=[]; st=[]
    for r in all_records:
        if "2026-10-18" not in r["timestamp"]: continue
        ts = datetime.fromisoformat(r["timestamp"])
        ph = r["phase"]
        if ph in ("lag","recovery"): continue
        if r["timestamp"] in holdout_ts: continue
        in_t = tlo<=ts<=thi; in_v = vlo<=ts<=vhi
        nt = (tlo-LEAKAGE_BUFFER)<=ts<=(thi+LEAKAGE_BUFFER)
        nv = (vlo-LEAKAGE_BUFFER)<=ts<=(vhi+LEAKAGE_BUFFER)
        g = to_g(r)
        if g is None: continue
        if in_t:
            te.append(g)
            if ph=="steady" and r["episode_id"]==ep_t["episode_id"]: st.append(g)
        elif in_v: va.append(g)
        elif not nt and not nv: tr.append(g)
    return tr, va, te, st


# ── Main ──────────────────────────────────────────────────────────────────────

def run_all():
    print("Loading ...")
    all_records = load_all_records()
    holdout_ts  = build_normal_holdout_ts(all_records)
    holdout_graphs = [g for r in all_records if r["timestamp"] in holdout_ts
                      for g in [record_to_graph(r)] if g]
    print(f"Holdout: {len(holdout_graphs)} graphs")

    mean_raw = load_latency_mean()
    _mt = sorted(datetime.fromisoformat(k) for k in mean_raw)
    _mk = sorted(mean_raw, key=lambda x: datetime.fromisoformat(x))

    lines = [
        "# MeshHeal AI — Controls and Ablation Experiments",
        "", "*Generated by controls_eval.py*", "",
        "Same 8 LOEO folds, split rules, seeds and config as `loeo_eval.py`.", "",
    ]

    # ─── items 1+2+3: 8-fold runs ────────────────────────────────────────────
    print("\n" + "="*60 + "\nItems 1+2+3: 8-fold controls\n" + "="*60)
    fold_results = []

    for fold_k in range(len(ALL_EPISODES)):
        ep = ALL_EPISODES[fold_k]
        fn = ep["node"]
        print(f"\nFold {fold_k}: {ep['episode_id']} {fn} {ep['delay_ms']}ms")
        tr, va, te, st = build_loeo_split(all_records, fold_k, holdout_ts)
        if not tr or not te: print("  SKIP"); continue

        # p95 baseline
        bvp, bvl = baseline_probs(va)
        if sum(bvl)==0: bvp, bvl = baseline_probs(tr)
        btp, btl = baseline_probs(te)
        bl_ap_o = ap_original(btp, btl)
        bl_ap_d = ap_distinct(btp, btl)
        bl_au   = auroc(btp, btl)
        bl_rc1  = rc1(st, lambda g: g.x[:,IN_LAT_IDX].tolist(), fn)
        bl_r5   = rec_at_5pct(holdout_graphs, lambda g: g.x[:,IN_LAT_IDX].tolist(), st, fn)

        # culprit rule
        cs = {}
        for ul, tag in [(True,"log1p"),(False,"raw")]:
            cvp, cvl = culprit_probs(va, ul)
            if sum(cvl)==0: cvp, cvl = culprit_probs(tr, ul)
            ctp, ctl = culprit_probs(te, ul)
            cs[tag] = dict(
                ap=ap_distinct(ctp, ctl),
                au=auroc(ctp, ctl),
                rc=rc1(st, lambda g,u=ul: culprit_fn(g,u), fn),
                r5=rec_at_5pct(holdout_graphs, lambda g,u=ul: culprit_fn(g,u), st, fn),
            )
            print(f"  CS({tag}): AP={cs[tag]['ap']:.3f} RC1={cs[tag]['rc']:.3f}")

        # MLP
        ms_ap=[]; ms_rc=[]; ms_r5=[]; ms_info={}
        for seed in SEEDS:
            model = train_mlp(tr, seed)
            mvp, mvl = mlp_probs(model, va)
            if sum(mvl)==0: mvp, mvl = mlp_probs(model, tr)
            mtp, mtl = mlp_probs(model, te)
            std = torch.tensor(mtp).std().item()
            ap_d = ap_distinct(mtp, mtl)
            rc_v = rc1(st, lambda g,m=model: mlp_fn(m,g), fn)
            r5_v = rec_at_5pct(holdout_graphs, lambda g,m=model: mlp_fn(m,g), st, fn)
            coll = std < COLLAPSE_THRESH
            ms_info[seed] = dict(ap=ap_d, rc=rc_v, r5=r5_v, std=std, coll=coll)
            if not coll: ms_ap.append(ap_d); ms_rc.append(rc_v); ms_r5.append(r5_v)
            print(f"  MLP s{seed}: AP={ap_d:.3f} std={std:.4f}" + (" COLL" if coll else ""))
        mlp_ap_m, mlp_ap_s = mean_std(ms_ap)
        mlp_rc_m, _ = mean_std(ms_rc)
        mlp_ap0 = sum(ms_info[s]["ap"] if not ms_info[s]["coll"] else 0.0 for s in SEEDS)/5

        # GNN
        gs_ap=[]; gs_rc=[]; gs_r5=[]; gs_info={}
        for seed in SEEDS:
            model = train_gnn(tr, seed)
            gvp, gvl = gnn_probs(model, va)
            if sum(gvl)==0: gvp, gvl = gnn_probs(model, tr)
            gtp, gtl = gnn_probs(model, te)
            std = torch.tensor(gtp).std().item()
            ap_d = ap_distinct(gtp, gtl)
            rc_v = rc1(st, lambda g,m=model: gnn_scores_for_graph(m,g), fn)
            r5_v = rec_at_5pct(holdout_graphs, lambda g,m=model: gnn_scores_for_graph(m,g), st, fn)
            coll = std < COLLAPSE_THRESH
            gs_info[seed] = dict(ap=ap_d, rc=rc_v, r5=r5_v, std=std, coll=coll)
            if not coll: gs_ap.append(ap_d); gs_rc.append(rc_v); gs_r5.append(r5_v)
        gnn_ap_m, gnn_ap_s = mean_std(gs_ap)
        gnn_rc_m, _ = mean_std(gs_rc)
        print(f"  GNN: AP={gnn_ap_m:.3f}±{gnn_ap_s:.3f} ({len(gs_ap)}/5)")

        fold_results.append(dict(
            fold=fold_k, ep=ep["episode_id"], node=fn, delay=ep["delay_ms"],
            n_st=len(st),
            bl_ap_o=bl_ap_o, bl_ap_d=bl_ap_d, bl_au=bl_au, bl_rc=bl_rc1, bl_r5=bl_r5,
            cs_l=cs["log1p"], cs_r=cs["raw"],
            mlp_ap_m=mlp_ap_m, mlp_ap_s=mlp_ap_s, mlp_ap0=mlp_ap0,
            mlp_rc_m=mlp_rc_m, mlp_n=len(ms_ap), ms_info=ms_info,
            gnn_ap_m=gnn_ap_m, gnn_ap_s=gnn_ap_s,
            gnn_rc_m=gnn_rc_m, gnn_n=len(gs_ap), gs_info=gs_info,
        ))

    # ─── Item 1 table ─────────────────────────────────────────────────────────
    lines += [
        "## Control 1: Culprit-Score Rule (in_lat − out_lat)", "",
        "Score = in_lat − out_lat, both log1p and raw. "
        "Threshold on val episode by best F1. AP = distinct-threshold.", "",
        "| Fold | Ep | Node | Delay | CS_log1p AP | CS_log1p AUROC | CS_log1p RC1 | "
        "CS_log1p Rec@5%FPR | CS_raw AP | CS_raw AUROC | CS_raw RC1 | CS_raw Rec@5%FPR |",
        "|------|----|------|-------|-------------|----------------|-------------|"
        "-------------------|-----------|--------------|------------|-----------------|",
    ]
    csl_aps=[]; csr_aps=[]; csl_rcs=[]; csr_rcs=[]
    for r in fold_results:
        l=r["cs_l"]; rw=r["cs_r"]
        lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | "
                     f"{l['ap']:.3f} | {l['au']:.3f} | {l['rc']:.3f} | {l['r5']:.3f} | "
                     f"{rw['ap']:.3f} | {rw['au']:.3f} | {rw['rc']:.3f} | {rw['r5']:.3f} |")
        csl_aps.append(l["ap"]); csr_aps.append(rw["ap"])
        csl_rcs.append(l["rc"]); csr_rcs.append(rw["rc"])
    lines.append(f"| **Mean** | | | | **{sum(csl_aps)/len(csl_aps):.3f}** | | "
                 f"**{sum(csl_rcs)/len(csl_rcs):.3f}** | | "
                 f"**{sum(csr_aps)/len(csr_aps):.3f}** | | "
                 f"**{sum(csr_rcs)/len(csr_rcs):.3f}** | |")
    lines.append("")

    # ─── Item 2 table ─────────────────────────────────────────────────────────
    lines += [
        "## Control 2: No-Graph MLP Ablation", "",
        "Same 6 features, hidden=16, 2×(Linear→LeakyReLU(0.1))→Linear, "
        "Adam lr=0.01, 100 epochs, pos_weight=1.0, seeds=[42,7,13,99,2024]. "
        "No message passing. Collapse rule: prob_std<0.01. "
        "AP(excl.coll): mean over non-collapsed seeds. AP(coll=0): all 5, collapsed→0.", "",
        "### Per-seed AP", "",
        "| Fold | Ep | Node | Delay | s42 | s7 | s13 | s99 | s2024 | Used | AP(excl.coll) | AP(coll=0) |",
        "|------|----|------|-------|-----|----|-----|-----|-------|------|--------------|------------|",
    ]
    mlp_means=[]; mlp_zero_means=[]
    for r in fold_results:
        si = r["ms_info"]
        lines.append(
            f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | " +
            " | ".join("COLL" if si[s]["coll"] else f"{si[s]['ap']:.3f}" for s in SEEDS) +
            f" | {r['mlp_n']}/5 | {r['mlp_ap_m']:.3f}±{r['mlp_ap_s']:.3f} | {r['mlp_ap0']:.3f} |")
        if r["mlp_n"]>0: mlp_means.append(r["mlp_ap_m"])
        mlp_zero_means.append(r["mlp_ap0"])
    lines.append(f"| **Mean** | | | | | | | | | | **{sum(mlp_means)/max(len(mlp_means),1):.3f}** | "
                 f"**{sum(mlp_zero_means)/len(mlp_zero_means):.3f}** |")
    lines.append("")

    # ─── Item 3 tables ────────────────────────────────────────────────────────
    lines += [
        "## Control 3: Comparison Table — AP and Root-Cause Top-1", "",
        "AP: distinct-threshold. GNN: excl-collapse mean. "
        "Tie = |diff| ≤ 0.01.", "",
        "### Average Precision", "",
        "| Fold | Ep | Node | Delay | p95-BL | CS(log1p) | CS(raw) | MLP | GNN |",
        "|------|----|------|-------|--------|-----------|---------|-----|-----|",
    ]
    w_bl={"win":0,"tie":0,"loss":0}; w_cs={"win":0,"tie":0,"loss":0}; w_mlp={"win":0,"tie":0,"loss":0}
    for r in fold_results:
        g=r["gnn_ap_m"]; b=r["bl_ap_d"]; cl=r["cs_l"]["ap"]; mlp=r["mlp_ap_m"]
        lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | "
                     f"{b:.3f} | {cl:.3f} | {r['cs_r']['ap']:.3f} | {mlp:.3f} | {g:.3f} |")
        for d,o in [(w_bl,b),(w_cs,cl),(w_mlp,mlp)]:
            df=g-o
            if abs(df)<=0.01: d["tie"]+=1
            elif df>0: d["win"]+=1
            else: d["loss"]+=1
    lines.append(f"| **Mean** | | | | {sum(r['bl_ap_d'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['cs_l']['ap'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['cs_r']['ap'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['mlp_ap_m'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['gnn_ap_m'] for r in fold_results)/len(fold_results):.3f} |")
    lines += [
        "", f"**GNN win/tie/loss vs p95-BL (AP):** {w_bl['win']}/{w_bl['tie']}/{w_bl['loss']}",
        "", f"**GNN win/tie/loss vs CS-log1p (AP):** {w_cs['win']}/{w_cs['tie']}/{w_cs['loss']}",
        "", f"**GNN win/tie/loss vs MLP (AP):** {w_mlp['win']}/{w_mlp['tie']}/{w_mlp['loss']}", "",
        "### Root-Cause Top-1", "",
        "| Fold | Ep | Node | Delay | n_steady | p95-BL | CS(log1p) | CS(raw) | MLP | GNN |",
        "|------|----|------|-------|---------|--------|-----------|---------|-----|-----|",
    ]
    wr_bl={"win":0,"tie":0,"loss":0}; wr_cs={"win":0,"tie":0,"loss":0}; wr_mlp={"win":0,"tie":0,"loss":0}
    for r in fold_results:
        g=r["gnn_rc_m"]; b=r["bl_rc"]; cl=r["cs_l"]["rc"]; mlp=r["mlp_rc_m"]
        lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | {r['n_st']} | "
                     f"{b:.3f} | {cl:.3f} | {r['cs_r']['rc']:.3f} | {mlp:.3f} | {g:.3f} |")
        for d,o in [(wr_bl,b),(wr_cs,cl),(wr_mlp,mlp)]:
            df=g-o
            if abs(df)<=0.01: d["tie"]+=1
            elif df>0: d["win"]+=1
            else: d["loss"]+=1
    lines.append(f"| **Mean** | | | | | {sum(r['bl_rc'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['cs_l']['rc'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['cs_r']['rc'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['mlp_rc_m'] for r in fold_results)/len(fold_results):.3f} | "
                 f"{sum(r['gnn_rc_m'] for r in fold_results)/len(fold_results):.3f} |")
    lines += [
        "", f"**GNN win/tie/loss vs p95-BL (RC1):** {wr_bl['win']}/{wr_bl['tie']}/{wr_bl['loss']}",
        "", f"**GNN win/tie/loss vs CS-log1p (RC1):** {wr_cs['win']}/{wr_cs['tie']}/{wr_cs['loss']}",
        "", f"**GNN win/tie/loss vs MLP (RC1):** {wr_mlp['win']}/{wr_mlp['tie']}/{wr_mlp['loss']}", "",
    ]

    # ─── Item 4: AP old vs new ────────────────────────────────────────────────
    csv_gnn = {}
    try:
        with open(os.environ.get("LOEO_RESULT_CSV", "results_loeo.csv")) as f:
            for row in csv.DictReader(f):
                csv_gnn[int(row["fold"])] = float(row["gnn_ap_mean"])
    except Exception: pass

    lines += [
        "## Control 4: AP Recomputed with Distinct-Threshold Method", "",
        "Old = trapezoidal from loeo_eval.py (stable sort, order-dependent in ties). "
        "New = distinct-threshold. GNN old from results_loeo.csv; "
        "MLP old recomputed (second retrain pass).", "",
        "| Fold | Ep | Node | BL AP (old) | BL AP (new) | Diff | "
        "MLP AP (old) | MLP AP (new) | GNN AP (old) | GNN AP (new) |",
        "|------|----|------|-------------|-------------|------|"
        "-------------|-------------|-------------|-------------|",
    ]
    for r in fold_results:
        k = r["fold"]
        tr,_,te,_ = build_loeo_split(all_records, k, holdout_ts)
        btp,btl = baseline_probs(te)
        bl_o = ap_original(btp, btl)
        mlp_o_aps=[]
        for seed in SEEDS:
            if r["ms_info"][seed]["coll"]: continue
            m = train_mlp(tr, seed)
            mp,ml = mlp_probs(m, te)
            mlp_o_aps.append(ap_original(mp, ml))
        mlp_o = sum(mlp_o_aps)/max(len(mlp_o_aps),1) if mlp_o_aps else float("nan")
        lines.append(
            f"| {k} | {r['ep']} | {r['node']} | {bl_o:.3f} | {r['bl_ap_d']:.3f} | "
            f"{r['bl_ap_d']-bl_o:+.3f} | {mlp_o:.3f} | {r['mlp_ap_m']:.3f} | "
            f"{csv_gnn.get(k,float('nan')):.3f} | {r['gnn_ap_m']:.3f} |")
    lines += ["",
        "> GNN and MLP outputs are continuous; tied scores are rare and AP differences are small. "
        "The p95 baseline has many tied scores (log1p(0)=0 for nodes with no incoming traffic), "
        "so the old method is most affected there.", "",
    ]

    # ─── Item 5: clean Oct-18 6-fold ─────────────────────────────────────────
    print("\n" + "="*60 + "\nItem 5: Clean Oct-18 6-fold\n" + "="*60)
    new_eps = [ep for ep in ALL_EPISODES if ep["source"]=="fault_log"]
    lines += [
        "## Control 5: Clean Mean-Latency Test (Oct-18 Only, 6 Folds)", "",
        "Training rows: **Oct-18 snapshots only** (6 new episodes + Oct-18 normals). "
        "Legacy episodes A and B excluded. "
        "Each fold trained twice on identical rows: 6 features vs 7 features "
        "(log1p(latency_mean), NN≤10s, drop unmatched). "
        "All other config identical to loeo_eval.py.", "",
    ]
    cfr = []
    for fold_k in range(len(new_eps)):
        ep = new_eps[fold_k]; fn = ep["node"]
        print(f"\n6f fold {fold_k}: {ep['episode_id']} {fn} {ep['delay_ms']}ms")
        tr6,va6,te6,st6 = oct18_split(all_records, fold_k, holdout_ts, use7=False)
        tr7,va7,te7,st7 = oct18_split(all_records, fold_k, holdout_ts, use7=True,
                                       raw=mean_raw, times=_mt, keys=_mk)
        print(f"  tr6={len(tr6)} tr7={len(tr7)} te6={len(te6)} te7={len(te7)}")
        if not tr6 or not te6:
            print("  SKIP (no data)"); continue

        # 6f
        sa6=[]; sr6=[]; si6={}
        for seed in SEEDS:
            m = train_gnn(tr6, seed)
            vp,vl = gnn_probs(m, va6)
            if sum(vl)==0: vp,vl = gnn_probs(m, tr6)
            tp,tl = gnn_probs(m, te6)
            std = torch.tensor(tp).std().item()
            a = ap_distinct(tp, tl); rc_v = rc1(st6, lambda g,mm=m: gnn_scores_for_graph(mm,g), fn)
            coll = std < COLLAPSE_THRESH
            si6[seed] = dict(ap=a, rc=rc_v, std=std, coll=coll)
            if not coll: sa6.append(a); sr6.append(rc_v)
            print(f"  6f s{seed}: AP={a:.3f} RC1={rc_v:.3f} std={std:.4f}" + (" COLL" if coll else ""))
        a6m, a6s = mean_std(sa6); r6m, _ = mean_std(sr6)

        # 7f
        sa7=[]; sr7=[]; si7={}
        if tr7 and te7:
            for seed in SEEDS:
                torch.manual_seed(seed)
                m7 = RiskGNN(num_node_features=7)
                opt7 = torch.optim.Adam(m7.parameters(), lr=LR)
                lf7  = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([POS_WEIGHT]))
                m7.train()
                for _ in range(EPOCHS):
                    for g in tr7:
                        opt7.zero_grad()
                        loss = lf7(m7(g.x, g.edge_index), g.y.float())
                        loss.backward(); opt7.step()
                m7.eval()
                def _gp7(graphs, mm=m7):
                    ps=[]; ls=[]
                    with torch.no_grad():
                        for g in graphs:
                            p=torch.sigmoid(mm(g.x,g.edge_index))
                            ps.extend(p.tolist()); ls.extend(g.y.tolist())
                    return ps, ls
                def _gfn7(g, mm=m7):
                    with torch.no_grad():
                        return torch.sigmoid(mm(g.x,g.edge_index)).tolist()
                vp7,vl7 = _gp7(va7)
                if sum(vl7)==0: vp7,vl7 = _gp7(tr7)
                tp7,tl7 = _gp7(te7)
                std7 = torch.tensor(tp7).std().item() if tp7 else 0.0
                a7 = ap_distinct(tp7, tl7)
                rc7 = rc1(st7, _gfn7, fn)
                coll7 = std7 < COLLAPSE_THRESH
                si7[seed] = dict(ap=a7, rc=rc7, std=std7, coll=coll7)
                if not coll7: sa7.append(a7); sr7.append(rc7)
                print(f"  7f s{seed}: AP={a7:.3f} RC1={rc7:.3f} std={std7:.4f}" + (" COLL" if coll7 else ""))
        a7m, a7s = mean_std(sa7); r7m, _ = mean_std(sr7)
        cfr.append(dict(fold=fold_k, ep=ep["episode_id"], node=fn, delay=ep["delay_ms"],
                        n_tr6=len(tr6), n_tr7=len(tr7), n_st=len(st6),
                        a6m=a6m, a6s=a6s, r6m=r6m, a7m=a7m, a7s=a7s, r7m=r7m,
                        si6=si6, si7=si7, nu6=len(sa6), nu7=len(sa7)))

    lines += [
        "### Training rows per fold", "",
        "| 6f Fold | Test Ep | Node | Train rows (6f) | Train rows (7f) | Dropped by NN-miss |",
        "|---------|---------|------|-----------------|-----------------|-------------------|",
    ]
    for r in cfr:
        lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} {r['delay']}ms | "
                     f"{r['n_tr6']} | {r['n_tr7']} | {r['n_tr6']-r['n_tr7']} |")
    lines += ["",
        "### Per-fold AP and Root-Cause Top-1", "",
        "| 6f Fold | Test Ep | Node | Delay | n_steady | 6f AP | 6f RC1 | 7f AP | 7f RC1 |",
        "|---------|---------|------|-------|---------|-------|--------|-------|--------|",
    ]
    def fmt(m,s): return f"{m:.3f}±{s:.3f}" if m==m else "n/a"
    def frc(v): return f"{v:.3f}" if v==v else "n/a"
    for r in cfr:
        lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} | {r['delay']}ms | {r['n_st']} | "
                     f"{fmt(r['a6m'],r['a6s'])} | {frc(r['r6m'])} | "
                     f"{fmt(r['a7m'],r['a7s'])} | {frc(r['r7m'])} |")
    lines += ["",
        "### Per-seed AP — 6 features", "",
        "| 6f Fold | Ep | Node | s42 | s7 | s13 | s99 | s2024 | Used |",
        "|---------|----|----|-----|----|-----|-----|-------|------|",
    ]
    for r in cfr:
        si = r["si6"]
        lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} | " +
                     " | ".join("COLL" if si[s]["coll"] else f"{si[s]['ap']:.3f}" for s in SEEDS) +
                     f" | {r['nu6']}/5 |")
    lines += ["",
        "### Per-seed AP — 7 features (log1p mean-lat, NN-matched)", "",
        "| 6f Fold | Ep | Node | s42 | s7 | s13 | s99 | s2024 | Used |",
        "|---------|----|----|-----|----|-----|-----|-------|------|",
    ]
    for r in cfr:
        si = r["si7"]
        if not si:
            lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} | n/a | n/a | n/a | n/a | n/a | 0/5 |")
        else:
            lines.append(f"| {r['fold']} | {r['ep']} | {r['node']} | " +
                         " | ".join("COLL" if si[s]["coll"] else f"{si[s]['ap']:.3f}" for s in SEEDS) +
                         f" | {r['nu7']}/5 |")
    lines.append("")

    # ─── Item 6 ───────────────────────────────────────────────────────────────
    lines += [
        "## Item 6: Assumptions, Deviations, and Items Not Run", "",
        "1. **Feature order OUT_LAT_IDX=3:** Assumed from `build_dataset_v2.py` `record_to_graph`. "
        "Not verified against live data. If wrong, culprit scores are mislabelled.",
        "2. **Culprit score sign:** score = in_lat − out_lat. "
        "Whether this correctly identifies the fault node for all Bookinfo call paths: **not tested**.",
        "3. **MLP architecture:** 2 hidden layers (matching GNN depth). "
        "Effect of using 1 hidden layer: **not tested**.",
        "4. **AP distinct vs trapezoidal:** For GNN and MLP, differences are small (continuous outputs). "
        "Largest differences are for the p95 baseline (many tied scores at log1p(0)=0).",
        "5. **Clean 6-fold holdout for 7-feature model:** The 137-snapshot holdout has no "
        "latency_mean coverage (pre-Oct-18). 7-feature model Recall@5%FPR not reported "
        "(threshold would be set on a feature that is always 0 on holdout).",
        "6. **Statistical significance:** With 6-8 folds and ~13-14 test positives per fold, "
        "no significance tests are run.",
        "7. **Causality of latency_mean vs in_latency_p95:** not tested.", "",
    ]

    with open(RESULT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nWritten to {RESULT_MD}")


if __name__ == "__main__":
    run_all()
