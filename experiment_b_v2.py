"""
experiment_b_v2.py  –  Improved Experiment B (both fault windows)
==================================================================
Improvements over experiment_b.py:
  1. Three-way chronological split per block: 70% train / 10% val / 20% test.
     Validation is carved from the TAIL of training (never from test).
  2. Three pos_weight candidates compared on validation: 1, sqrt(ratio), full
     ratio. Best chosen by validation F1.
  3. Decision threshold grid-searched on validation to maximise F1.
     Test precision/recall reported at that threshold ONLY.
  4. Average precision (area under P-R curve) computed manually – no sklearn.
  5. Training repeated with 5 random seeds; mean ± std reported.
  6. Results broken down by fault type (ratings vs details) and normal FPR.
  7. Latency-threshold baseline on the SAME train/test split.
  8. If the baseline is competitive with or beats the GNN, we say so honestly.

Models saved as models/v2b_seed<N>.pt (skipped if already exist).
"""

import sys
import os
import json
import math
import torch
import torch.nn as nn
from datetime import datetime, timezone, timedelta
from build_graph_dataset import snapshot_to_graph, NODE_VOCAB, NODE_INDEX
from model import RiskGNN

# ── Constants ────────────────────────────────────────────────────────────────
FAULT1_START = datetime(2026, 10, 4, 9, 49, 2,  tzinfo=timezone.utc)
FAULT1_END   = datetime(2026, 10, 4, 10, 3, 48, tzinfo=timezone.utc)
FAULT2_START = datetime(2026, 10, 9, 7, 43, 57, tzinfo=timezone.utc)
FAULT2_END   = datetime(2026, 10, 9, 7, 48, 25, tzinfo=timezone.utc)
RECOVERY_BUFFER = timedelta(seconds=75)
DATASET         = "labeled_dataset_v2.jsonl"
SEEDS           = [42, 7, 13, 99, 2024]
EPOCHS          = 100
IN_LAT_IDX      = 2   # feature index of log1p(in_latency)
os.makedirs("models", exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def is_recovery(ts, fault_end):
    return fault_end < ts <= fault_end + RECOVERY_BUFFER


def chrono_three_split(graphs, val_frac=0.10, test_frac=0.20):
    """
    Chronological three-way split within a single block.
    Order: [----train----|--val--|--test--]
    Validation comes from the tail of what would be 'train' in a 2-way split.
    For blocks too small to have any val examples, val is empty.
    """
    n = len(graphs)
    n_test = max(1, int(n * test_frac))
    n_val  = max(0, int(n * val_frac))
    n_train = n - n_val - n_test
    if n_train < 1:          # block is tiny – put everything in train
        return graphs, [], []
    train = graphs[:n_train]
    val   = graphs[n_train:n_train + n_val]
    test  = graphs[n_train + n_val:]
    return train, val, test


def class_counts(graphs):
    """Return (total_nodes, pos_nodes, neg_nodes) over a list of graphs."""
    total = sum(g.y.numel() for g in graphs)
    pos   = sum(int(g.y.sum().item()) for g in graphs)
    return total, pos, total - pos


def average_precision(probs_flat, labels_flat):
    """
    Manually compute area under the precision-recall curve (AP/mAP).
    probs_flat, labels_flat: plain Python lists (floats, 0/1 ints).
    Uses the 'interpolated' trapezoid area.
    """
    if sum(labels_flat) == 0:
        return 0.0
    # Sort by descending probability
    paired = sorted(zip(probs_flat, labels_flat), key=lambda x: -x[0])
    tp = 0; fp = 0
    prec_points = []   # (recall, precision) pairs
    total_pos = sum(labels_flat)
    for prob, label in paired:
        if label == 1:
            tp += 1
        else:
            fp += 1
        prec = tp / (tp + fp)
        rec  = tp / total_pos
        prec_points.append((rec, prec))
    # Trapezoid integration
    ap = 0.0
    prev_rec = 0.0
    prev_prec = 1.0
    for rec, prec in prec_points:
        ap += (rec - prev_rec) * (prec + prev_prec) / 2.0
        prev_rec = rec; prev_prec = prec
    return ap


def best_threshold(probs_flat, labels_flat, candidates=None):
    """
    Find threshold that maximises F1 on the given data.
    Candidates default to percentile grid between 1st and 99th percentile.
    """
    if candidates is None:
        sorted_p = sorted(set(probs_flat))
        # Use 50 evenly-spaced values across the probability range
        lo, hi = sorted_p[0], sorted_p[-1]
        step = (hi - lo) / 50 if hi > lo else 0.01
        candidates = [lo + i * step for i in range(51)]
    best_f1, best_t = -1.0, 0.5
    for t in candidates:
        tp = fp = fn = 0
        for p, l in zip(probs_flat, labels_flat):
            pred = 1 if p > t else 0
            if pred == 1 and l == 1: tp += 1
            elif pred == 1 and l == 0: fp += 1
            elif pred == 0 and l == 1: fn += 1
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        if f1 > best_f1:
            best_f1 = f1; best_t = t
    return best_t, best_f1


def evaluate_at_threshold(probs_flat, labels_flat, thresh):
    """Return (tp, fp, fn, tn, precision, recall, f1)."""
    tp = fp = fn = tn = 0
    for p, l in zip(probs_flat, labels_flat):
        pred = 1 if p > thresh else 0
        if pred == 1 and l == 1: tp += 1
        elif pred == 1 and l == 0: fp += 1
        elif pred == 0 and l == 1: fn += 1
        else: tn += 1
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return tp, fp, fn, tn, prec, rec, f1


def get_probs_labels(model_, graphs):
    """Run model on graphs, return flat lists of (prob, label) per node."""
    probs_all = []; labels_all = []
    model_.eval()
    with torch.no_grad():
        for g in graphs:
            p = torch.sigmoid(model_(g.x, g.edge_index))
            probs_all.extend(p.tolist())
            labels_all.extend(g.y.tolist())
    return probs_all, labels_all


# ════════════════════════════════════════════════════════════════════════════
# STEP 1 – Partition into blocks (same classification as experiment_b.py)
# ════════════════════════════════════════════════════════════════════════════

print(f"Partitioning {DATASET} into contiguous blocks ...")
blocks = {
    "normal_pre":    [],   # all normal data before Oct 4 fault
    "fault1":        [],   # Oct 4 ratings fault
    "normal_post_4": [],   # Oct 4 normal after fault window
    "normal_oct9":   [],   # Oct 9 normal
    "fault2":        [],   # Oct 9 details fault
}

# We also tag each graph with which fault it belongs to (for per-fault reporting)
fault_tag = {}    # id(graph) -> "ratings" | "details" | "normal"

with open(DATASET) as f:
    for line in f:
        record = json.loads(line)
        ts = datetime.fromisoformat(record["timestamp"])
        if is_recovery(ts, FAULT1_END) or is_recovery(ts, FAULT2_END):
            continue
        g = snapshot_to_graph(record)
        if g is None:
            continue
        if FAULT1_START <= ts <= FAULT1_END:
            blocks["fault1"].append(g); fault_tag[id(g)] = "ratings"
        elif FAULT2_START <= ts <= FAULT2_END:
            blocks["fault2"].append(g); fault_tag[id(g)] = "details"
        elif ts.date().isoformat() == "2026-10-04" and ts > FAULT1_END:
            blocks["normal_post_4"].append(g); fault_tag[id(g)] = "normal"
        elif ts.date().isoformat() == "2026-10-09":
            blocks["normal_oct9"].append(g); fault_tag[id(g)] = "normal"
        else:
            blocks["normal_pre"].append(g); fault_tag[id(g)] = "normal"

print("Block sizes:")
for name, g in blocks.items():
    print(f"  {name:20s}: {len(g):3d} graphs")

# ════════════════════════════════════════════════════════════════════════════
# STEP 2 – Three-way chronological split
# ════════════════════════════════════════════════════════════════════════════

train_graphs = []; val_graphs = []; test_graphs = []
for name, g in blocks.items():
    tr, va, te = chrono_three_split(g, val_frac=0.10, test_frac=0.20)
    train_graphs.extend(tr); val_graphs.extend(va); test_graphs.extend(te)

_, train_pos, train_neg = class_counts(train_graphs)
_, val_pos, val_neg     = class_counts(val_graphs)
_, test_pos, test_neg   = class_counts(test_graphs)

print(f"\nSplit sizes (graphs):   train={len(train_graphs)}  val={len(val_graphs)}  test={len(test_graphs)}")
print(f"Positive node-labels:  train={train_pos}  val={val_pos}  test={test_pos}")

# ════════════════════════════════════════════════════════════════════════════
# STEP 3 – Choose pos_weight on validation (1, sqrt(ratio), full ratio)
# ════════════════════════════════════════════════════════════════════════════

full_ratio = train_neg / train_pos if train_pos > 0 else 1.0
pw_candidates = {
    "pw=1":         1.0,
    "pw=sqrt":      math.sqrt(full_ratio),
    "pw=full":      full_ratio,
}
print(f"\npos_weight candidates: {', '.join(f'{k}={v:.2f}' for k,v in pw_candidates.items())}")

# Quick single-seed training to pick pos_weight
SEED_PW = 42
best_pw_name = None; best_pw_val = None; best_pw_f1 = -1.0
print("  Selecting pos_weight on validation (1 training run each) ...")

for pw_name, pw_val in pw_candidates.items():
    torch.manual_seed(SEED_PW)
    mdl = RiskGNN(num_node_features=6)
    opt = torch.optim.Adam(mdl.parameters(), lr=0.01)
    lf  = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pw_val]))
    mdl.train()
    for ep in range(EPOCHS):
        for g in train_graphs:
            opt.zero_grad()
            loss = lf(mdl(g.x, g.edge_index), g.y)
            loss.backward(); opt.step()
    vp, vl = get_probs_labels(mdl, val_graphs)
    _, vf1 = best_threshold(vp, vl)
    vap    = average_precision(vp, vl)
    print(f"    {pw_name:12s}  val F1={vf1:.3f}  val AP={vap:.3f}")
    if vf1 > best_pw_f1:
        best_pw_f1 = vf1; best_pw_name = pw_name; best_pw_val = pw_val

print(f"  → Chosen: {best_pw_name}  (val F1={best_pw_f1:.3f})")

# ════════════════════════════════════════════════════════════════════════════
# STEP 4 – Train with 5 seeds; pick threshold on val each time
# ════════════════════════════════════════════════════════════════════════════

print(f"\nTraining with 5 seeds (pos_weight={best_pw_val:.2f}, epochs={EPOCHS}) ...")
loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([best_pw_val]))

# Accumulators (test metrics per seed)
seed_prec = []; seed_rec = []; seed_ap = []
# Per-fault-type accumulators
# We'll collect per-seed lists of (prob, label, tag) for the test set
seed_test_results = []   # list of (probs_flat, labels_flat, tags_flat)

for seed in SEEDS:
    torch.manual_seed(seed)
    save_path = f"models/v2b_seed{seed}.pt"

    model = RiskGNN(num_node_features=6)
    opt   = torch.optim.Adam(model.parameters(), lr=0.01)

    # Train
    model.train()
    for ep in range(EPOCHS):
        for g in train_graphs:
            opt.zero_grad()
            loss = loss_fn(model(g.x, g.edge_index), g.y)
            loss.backward(); opt.step()

    # Collapse check on val
    vp, vl = get_probs_labels(model, val_graphs)
    if torch.tensor(vp).std().item() < 0.01:
        print(f"  Seed {seed}: COLLAPSE – skipping.")
        continue

    # Pick threshold on validation
    thresh, val_f1 = best_threshold(vp, vl)

    # Evaluate on test
    tp_flat = []; tl_flat = []; tt_flat = []
    model.eval()
    with torch.no_grad():
        for g in test_graphs:
            probs = torch.sigmoid(model(g.x, g.edge_index)).tolist()
            lbls  = g.y.tolist()
            tag_g = fault_tag.get(id(g), "normal")
            for node_i, (prob, lbl) in enumerate(zip(probs, lbls)):
                tp_flat.append(prob); tl_flat.append(lbl); tt_flat.append(tag_g)

    _, _, _, _, prec, rec, f1 = evaluate_at_threshold(tp_flat, tl_flat, thresh)
    ap = average_precision(tp_flat, tl_flat)
    seed_prec.append(prec); seed_rec.append(rec); seed_ap.append(ap)
    seed_test_results.append((tp_flat, tl_flat, tt_flat, thresh))

    prob_std = torch.tensor(tp_flat).std().item()
    print(f"  Seed {seed}: val_thresh={thresh:.3f} val_F1={val_f1:.3f} "
          f"| test: P={prec:.3f} R={rec:.3f} AP={ap:.3f}  (prob_std={prob_std:.3f})")

    # Save model (skip if file already exists)
    if not os.path.exists(save_path):
        torch.save(model.state_dict(), save_path)
        print(f"    Saved {save_path}")
    else:
        print(f"    (not overwriting {save_path})")

# ════════════════════════════════════════════════════════════════════════════
# STEP 5 – Aggregate statistics across seeds
# ════════════════════════════════════════════════════════════════════════════

def mean_std(lst):
    if not lst: return 0.0, 0.0
    m = sum(lst) / len(lst)
    v = sum((x - m) ** 2 for x in lst) / max(len(lst) - 1, 1)
    return m, math.sqrt(v)

m_prec, s_prec = mean_std(seed_prec)
m_rec,  s_rec  = mean_std(seed_rec)
m_ap,   s_ap   = mean_std(seed_ap)

print(f"\n{'='*60}")
print(f"GNN AGGREGATE (n={len(seed_prec)} seeds)")
print(f"{'='*60}")
print(f"  Precision : {m_prec:.3f} ± {s_prec:.3f}")
print(f"  Recall    : {m_rec:.3f} ± {s_rec:.3f}")
print(f"  Avg Prec  : {m_ap:.3f} ± {s_ap:.3f}")

# ════════════════════════════════════════════════════════════════════════════
# STEP 6 – Per-fault-type breakdown (use last seed's results for illustration)
# ════════════════════════════════════════════════════════════════════════════

if seed_test_results:
    # Accumulate per-fault-type across all seeds
    fault_data = {"ratings": ([], []), "details": ([], []), "normal": ([], [])}
    for tp_flat, tl_flat, tt_flat, thresh in seed_test_results:
        for prob, lbl, tag in zip(tp_flat, tl_flat, tt_flat):
            fault_data[tag][0].append(prob)
            fault_data[tag][1].append(lbl)

    # Average threshold across seeds
    avg_thresh = sum(r[3] for r in seed_test_results) / len(seed_test_results)

    print(f"\nGNN per-fault breakdown (averaged threshold={avg_thresh:.3f}):")
    for fault_name in ["ratings", "details", "normal"]:
        fp2, fl2 = fault_data[fault_name]
        if not fp2:
            print(f"  {fault_name:10s}: (no data)")
            continue
        tp_, fp_, fn_, tn_, prec_, rec_, f1_ = evaluate_at_threshold(fp2, fl2, avg_thresh)
        total_nodes_ = len(fp2)
        flagged_     = tp_ + fp_
        if fault_name == "normal":
            fpr_ = flagged_ / total_nodes_ if total_nodes_ > 0 else 0.0
            print(f"  {fault_name:10s}: {flagged_}/{total_nodes_} node-reads flagged  "
                  f"(FPR={fpr_:.3f})")
        else:
            ap_ = average_precision(fp2, fl2)
            print(f"  {fault_name:10s}: P={prec_:.3f}  R={rec_:.3f}  AP={ap_:.3f}  "
                  f"(TP={tp_} FP={fp_} FN={fn_})")

# ════════════════════════════════════════════════════════════════════════════
# STEP 7 – Latency-threshold baseline on the SAME train/test split
# ════════════════════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print("LATENCY-THRESHOLD BASELINE (same train/test split as GNN)")
print(f"{'='*60}")

# Build (in_lat, label, tag) from training set
train_lats = []
for g in train_graphs:
    tag_g = fault_tag.get(id(g), "normal")
    for i in range(g.x.shape[0]):
        train_lats.append((g.x[i, IN_LAT_IDX].item(), int(g.y[i].item()), tag_g))

# Choose threshold on training data only (maximise F1)
bl_thresh, bl_train_f1 = best_threshold(
    [x[0] for x in train_lats],
    [x[1] for x in train_lats],
)
print(f"  Chosen threshold (log1p in_lat) = {bl_thresh:.4f}  (train F1={bl_train_f1:.3f})")

# Evaluate on test set
test_lat_probs  = []   # use latency AS a "probability" for AP calculation
test_lat_labels = []
test_lat_tags   = []

for g in test_graphs:
    tag_g = fault_tag.get(id(g), "normal")
    for i in range(g.x.shape[0]):
        lat = g.x[i, IN_LAT_IDX].item()
        lbl = int(g.y[i].item())
        test_lat_probs.append(lat); test_lat_labels.append(lbl); test_lat_tags.append(tag_g)

# Normalise latencies to [0,1] for AP (monotone transform, doesn't change ranking)
lat_max = max(test_lat_probs) if test_lat_probs else 1.0
lat_min = min(test_lat_probs)
lat_range = lat_max - lat_min if lat_max > lat_min else 1.0
test_lat_probs_norm = [(v - lat_min) / lat_range for v in test_lat_probs]

bl_tp, bl_fp, bl_fn, bl_tn, bl_prec, bl_rec, bl_f1 = evaluate_at_threshold(
    test_lat_probs, test_lat_labels, bl_thresh
)
bl_ap = average_precision(test_lat_probs_norm, test_lat_labels)

print(f"\n  Overall: TP={bl_tp} FP={bl_fp} FN={bl_fn} TN={bl_tn}")
print(f"           Precision={bl_prec:.3f}  Recall={bl_rec:.3f}  AP={bl_ap:.3f}")

# Per-fault breakdown for baseline
print(f"\n  Per-fault breakdown (threshold={bl_thresh:.4f}):")
for fault_name in ["ratings", "details", "normal"]:
    fp2 = [p for p, l, t in zip(test_lat_probs, test_lat_labels, test_lat_tags) if t == fault_name]
    fl2 = [l for p, l, t in zip(test_lat_probs, test_lat_labels, test_lat_tags) if t == fault_name]
    if not fp2:
        print(f"    {fault_name:10s}: (no data)")
        continue
    tp_, fp_, fn_, tn_, prec_, rec_, f1_ = evaluate_at_threshold(fp2, fl2, bl_thresh)
    total_ = len(fp2); flagged_ = tp_ + fp_
    if fault_name == "normal":
        fpr_ = flagged_ / total_ if total_ > 0 else 0.0
        print(f"    {fault_name:10s}: {flagged_}/{total_} node-reads flagged  (FPR={fpr_:.3f})")
    else:
        fp2_n = [(v - lat_min) / lat_range for v in fp2]
        ap_ = average_precision(fp2_n, fl2)
        print(f"    {fault_name:10s}: P={prec_:.3f}  R={rec_:.3f}  AP={ap_:.3f}  "
              f"(TP={tp_} FP={fp_} FN={fn_})")

# ════════════════════════════════════════════════════════════════════════════
# STEP 8 – Summary table
# ════════════════════════════════════════════════════════════════════════════

print(f"\n{'='*70}")
print("SUMMARY TABLE  (Experiment B v2  –  same train/val/test split)")
print(f"{'='*70}")
print(f"  {'Method':<28} {'Precision':>9} {'Recall':>8} {'Avg Prec':>9}")
print(f"  {'-'*28} {'-'*9} {'-'*8} {'-'*9}")

# GNN overall (mean across seeds)
gnn_label = f"GNN (n={len(seed_prec)} seeds, thresh=val-F1)"
print(f"  {gnn_label:<28} {m_prec:.3f}±{s_prec:.3f}  {m_rec:.3f}±{s_rec:.3f}  {m_ap:.3f}±{s_ap:.3f}")

# Baseline
bl_label = "Latency threshold (baseline)"
print(f"  {bl_label:<28} {bl_prec:>9.3f}  {bl_rec:>8.3f}  {bl_ap:>9.3f}")

print(f"  {'-'*70}")

# Honest comparison
if len(seed_prec) > 0:
    if bl_prec >= m_prec and bl_rec >= m_rec:
        verdict = ("HONEST NOTE: The rule-based latency threshold matches or beats "
                   "the GNN on both precision AND recall on this test set.")
    elif bl_ap >= m_ap:
        verdict = ("HONEST NOTE: The baseline's average precision matches or beats "
                   "the GNN's AP, meaning the GNN's ranking is not clearly superior.")
    else:
        verdict = ("The GNN outperforms the simple threshold on this test set, "
                   "but the dataset is small — treat results with caution.")
    print(f"\n  {verdict}")

print(f"\nModels saved: models/v2b_seed{{42,7,13,99,2024}}.pt")
