"""Make the report/slide figures from real files only. Run from the project root with a Python that has matplotlib:

    python figures/make_figures.py

Writes figures/fig_*_{light,dark}.png (200 dpi, 13.33 x 7.5 in = 16:9 slide size). Reads, never writes, the data files.
Nothing is recomputed or rounded: the numbers are the cells of the markdown tables / the audit events as written.
"""
import json
import re
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "figures"
DPI, SIZE = 200, (13.33, 7.5)
THEMES = {
    "light": dict(bg="#ffffff", fg="#14161a", muted="#566070", grid="#dde1e7", box="#f6f7f9", edge="#9aa4b2", shade="#4f46e5"),
    "dark": dict(bg="#0c0f13", fg="#e9edf2", muted="#9ba7b6", grid="#272f3a", box="#141920", edge="#566070", shade="#8e90fa"),
}
# Okabe-Ito colour-blind-safe colours, one per service / series
NODE_COLOR = {"productpage": "#0072B2", "details": "#E69F00", "reviews": "#009E73", "ratings": "#D55E00"}
SERIES = {"p95 baseline": "#999999", "culprit rule": "#E69F00", "no-graph MLP": "#009E73", "GNN": "#0072B2"}
RUN_LO, RUN_HI = "2026-10-26T05:48:25", "2026-10-26T07:02:27"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)


def jsonl(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def md_table(path, heading_start):
    """Rows of the first markdown table under the first heading that starts with `heading_start`."""
    rows, on, started = [], False, False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            on = line.lstrip("#").strip().startswith(heading_start)
            if started:
                break
        elif on and line.startswith("|"):
            started = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                rows.append(cells)
        elif on and started:
            break
    return rows[0], rows[1:]


def style(ax, t):
    ax.set_facecolor(t["bg"])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(t["edge"])
    ax.tick_params(colors=t["muted"], labelsize=14)
    ax.yaxis.label.set_color(t["fg"]); ax.xaxis.label.set_color(t["fg"])
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig, name, theme, t, tight=True):
    fig.patch.set_facecolor(t["bg"])
    fig.savefig(OUT / f"{name}_{theme}.png", dpi=DPI, facecolor=t["bg"], bbox_inches="tight" if tight else None)
    plt.close(fig)
    print("wrote", f"figures/{name}_{theme}.png")


# ----------------------------------------------------------------------------- (a) top-node risk over the shadow run
def fig_a(theme, t):
    faults = jsonl(ROOT / "shadow_run/fault_log_shadow.jsonl")
    soak_end = ts(jsonl(ROOT / "shadow_run/schedule_log.jsonl")[1]["utc"])
    fig, axes = plt.subplots(2, 1, figsize=SIZE, sharex=True)
    for ax, scorer in zip(axes, ("rule", "gnn")):
        ev = [e for e in jsonl(ROOT / f"shadow_run/audit_{scorer}.jsonl") if RUN_LO <= e["ts"][:19] <= RUN_HI]
        scored = [e for e in ev if e["event"] == "SCORED"]
        style(ax, t)
        for f in faults:
            ax.axvspan(ts(f["start_utc"]), ts(f["end_utc"]), color=t["shade"], alpha=0.16, lw=0)
            ax.text(ts(f["start_utc"]), 1.04, f"{f['node']} {f['delay']}", color=t["fg"], fontsize=13, va="bottom", ha="left")
        for node, c in NODE_COLOR.items():
            pts = [(ts(e["ts"]), e["risk"]) for e in scored if e["top"] == node]
            if pts:
                ax.scatter(*zip(*pts), s=16, color=c, label=f"top node = {node}", zorder=3)
        ax.axhline(0.85, color=t["muted"], ls="--", lw=1.2)
        ax.text(ts(RUN_LO) , 0.865, "act threshold 0.85", color=t["muted"], fontsize=12, va="bottom")
        for f in faults:
            first = next((e for e in ev if e["event"] in ("REROUTE", "ACTION_BLOCKED", "SUPPRESSED_VICTIM") and f["start_utc"][:19] <= e["ts"][:19] <= f["end_utc"][:19]), None)
            if first:
                ax.axvline(ts(first["ts"]), color=t["fg"], lw=1.6)
                ax.annotate(first["event"].replace("ACTION_BLOCKED", "BLOCKED"), (ts(first["ts"]), 0.55), rotation=90, fontsize=12, color=t["fg"], ha="right", va="center")
        ax.set_ylim(-0.03, 1.12)
        ax.set_ylabel(f"{scorer.upper()} top-node risk", fontsize=14)
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, 1.32), ncol=4, frameon=False, fontsize=13, labelcolor=t["fg"], markerscale=2)
    axes[1].set_xlabel("time, UTC (2026-10-26); shaded = injected fault, vertical line = first REROUTE / BLOCKED event", fontsize=14)
    axes[1].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    fig.suptitle("Shadow run: highest risk per 15 s cycle, rule vs GNN (dry-run)", color=t["fg"], fontsize=20, fontweight="bold", y=1.02)
    fig.subplots_adjust(hspace=0.25)
    save(fig, "fig_a_shadow_risk", theme, t)


# ----------------------------------------------------------------------------- (b) detection time per fault and scorer
def fig_b(theme, t):
    hdr, rows = md_table(ROOT / "shadow_run/results_shadow.md", "Fault windows")
    i_f, i_s, i_t = hdr.index("fault"), hdr.index("scorer"), hdr.index("s after start")
    faults = list(dict.fromkeys(r[i_f] for r in rows))
    val = {(r[i_f], r[i_s]): float(r[i_t]) for r in rows}
    fig, ax = plt.subplots(figsize=SIZE)
    style(ax, t)
    w = 0.36
    for k, (sc, col) in enumerate((("rule", "#E69F00"), ("gnn", "#0072B2"))):
        xs = [i + (k - 0.5) * w for i in range(len(faults))]
        bars = ax.bar(xs, [val[(f, sc)] for f in faults], w, color=col, label=sc.upper())
        for b, f in zip(bars, faults):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.5, f"{val[(f, sc)]:g}", ha="center", color=t["fg"], fontsize=15, fontweight="bold")
    ax.set_xticks(range(len(faults)))
    ax.set_xticklabels(faults, fontsize=15, color=t["fg"])
    ax.set_ylabel("seconds after fault start to first decision event", fontsize=14)
    ax.set_ylim(0, max(val.values()) * 1.2)
    ax.legend(frameon=False, fontsize=15, labelcolor=t["fg"], loc="upper right")
    ax.set_title("Detection time per fault (first REROUTE or ACTION_BLOCKED), shadow run", color=t["fg"], fontsize=20, fontweight="bold", loc="left")
    fig.subplots_adjust(left=0.075, right=0.985, top=0.9, bottom=0.2)
    fig.text(0.075, 0.02, "Source: shadow_run/results_shadow.md. Rule and GNN decided identically in all 4 windows.\n"
             "Events fall on 15 s controller cycles; the times are consistent with the persistence rule (3 of 4 cycles) setting the timing rather than the scorer.",
             color=t["muted"], fontsize=12, va="bottom", linespacing=1.4)
    save(fig, "fig_b_detection_time", theme, t, tight=False)


# ----------------------------------------------------------------------------- (c) LOEO AP per fold
def fig_c(theme, t):
    # the AP table sits under the "### Average Precision" sub-heading of Control 3
    text = (ROOT / "results_controls.md").read_text(encoding="utf-8").splitlines()
    i = next(n for n, l in enumerate(text) if l.strip() == "### Average Precision")
    tab, started = [], False
    for l in text[i + 1:]:
        if l.startswith("|"):
            started = True
            tab.append([c.strip() for c in l.strip().strip("|").split("|")])
        elif started:
            break   # end of this table
    hdr, rows = tab[0], [r for r in tab[2:]]
    mean = next(r for r in rows if r[0].startswith("**Mean"))
    folds = [r for r in rows if not r[0].startswith("**")]
    col = {name: hdr.index(h) for name, h in (("p95 baseline", "p95-BL"), ("culprit rule", "CS(raw)"), ("no-graph MLP", "MLP"), ("GNN", "GNN"))}
    fig, ax = plt.subplots(figsize=SIZE)
    style(ax, t)
    n, w = len(SERIES), 0.2
    labels = [f"{r[1]} {r[2]}\n{r[3]}" for r in folds] + ["mean"]
    for k, (name, c) in enumerate(SERIES.items()):
        vals = [float(r[col[name]]) for r in folds] + [float(mean[col[name]])]
        ax.bar([j + (k - 1.5) * w for j in range(len(vals))], vals, w, color=c, label=name)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, fontsize=12, color=t["fg"])
    ax.set_ylim(0, 1.18); ax.set_ylabel("average precision (AP)", fontsize=14)
    ax.legend(frameon=False, fontsize=14, labelcolor=t["fg"], ncol=4, loc="upper center")
    ax.set_title("Leave-one-episode-out AP per fold: the GNN is not better than simpler scorers", color=t["fg"], fontsize=20, fontweight="bold", loc="left")
    ms = {k: mean[v] for k, v in col.items()}
    fig.text(0.01, -0.05, f"AP method: distinct-threshold (results_controls.md, Control 3); the trapezoidal method is order-dependent with tied scores, so it is not used here. "
             f"Means: baseline {ms['p95 baseline']}, culprit rule (raw ms, as deployed) {ms['culprit rule']}, MLP {ms['no-graph MLP']}, GNN {ms['GNN']}. 8 episodes, one testbed.",
             color=t["muted"], fontsize=11, wrap=True)
    save(fig, "fig_c_loeo_ap", theme, t)


# ----------------------------------------------------------------------------- (d) pipeline diagram
def fig_d(theme, t):
    fig, ax = plt.subplots(figsize=SIZE)
    ax.set_xlim(-1, 101); ax.set_ylim(-3, 58); ax.axis("off")

    def box(x, y, w, h, title, sub="", color=None, tsize=14.5):
        """Title and sub text are top-aligned inside the box with fixed padding, whatever the number of lines."""
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.2", fc=t["box"], ec=color or t["edge"], lw=2.4))
        tl = title.count("\n") + 1
        ax.text(x + w / 2, y + h - 1.4, title, ha="center", va="top", color=t["fg"], fontsize=tsize, fontweight="bold", linespacing=1.15)
        if sub:
            top = y + h - 1.4 - tl * (tsize / 14.5) * 2.3 - 0.5
            ax.text(x + w / 2, top, sub, ha="center", va="top", color=t["muted"], fontsize=10.5, linespacing=1.35)

    def arrow(a, b, rad=0.0, color=None):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=20, lw=2.2, color=color or t["fg"], connectionstyle=f"arc3,rad={rad}"))

    W, G = 17.2, 3.5
    xs = [i * (W + G) for i in range(5)]
    ax.text(0, 56.5, "MeshHeal AI control plane, one loop every 15 s", color=t["fg"], fontsize=21, fontweight="bold", va="top")
    Y, H = 37.5, 13
    names = [("Istio telemetry", "Prometheus per-edge\nrate, errors, p95", None), ("Snapshots", "snapshots.jsonl\none JSON per 15 s", None),
             ("Scorer", "GNN, 500 ms budget;\nelse rule fallback", "#0072B2"), ("Persistence", "top node risk > 0.85\nin 3 of last 4 and now", None),
             ("Safety checks", "playbook, pod ready,\nno dependency,\nhealthy alternative,\ncooldown", None)]
    for x, (n, sub, c) in zip(xs, names):
        box(x, Y, W, H, n, sub, c)
    for i in range(4):
        arrow((xs[i] + W + 0.6, Y + H / 2), (xs[i + 1] - 0.6, Y + H / 2))
    Y2 = 20.5
    box(xs[4], Y2, W, H, "Patch\nVirtualService", "reviews to v1, or log\nACTION_BLOCKED", "#D55E00", tsize=13)
    box(xs[3], Y2, W, H, "Audit log", "audit_log.jsonl,\none line per decision", None)
    arrow((xs[4] + W / 2, Y - 0.5), (xs[4] + W / 2, Y2 + H + 0.5))
    arrow((xs[4] - 0.6, Y2 + H / 2), (xs[3] + W + 0.6, Y2 + H / 2))
    ax.text(0, Y2 + H, "Fallback: a scorer timeout, error or kill file\n"
            "makes the rule score that cycle; the audit\n"
            "line then says source = fallback.\n"
            "Input checks: snapshots older than 45 s, or\n"
            "with NaN or missing nodes, are rejected and\n"
            "logged as SNAPSHOT_REJECTED.", color=t["muted"], fontsize=11.5, va="top", linespacing=1.35)
    # probe / release loop
    ax.add_patch(FancyBboxPatch((0, -2.2), 100, 21.0, boxstyle="round,pad=0.3,rounding_size=1.2", fc="none", ec=t["edge"], lw=1.6, ls="--"))
    ax.text(1.5, 17.1, "After a reroute: probe and release", color=t["fg"], fontsize=15, fontweight="bold", va="center")
    Ys, Hs = 6.4, 7.6
    steps = [("REROUTED", "all traffic to v1", None), ("cooldown", "120 s", None), ("PROBING", "90 s at 70/15/15", None),
             ("risk < 0.60 and", ">= 0.05 req/s?", None), ("RELEASE", "back to 34/33/33", "#009E73")]
    for x, (n, sub, c) in zip(xs, steps):
        box(x, Ys, W, Hs, n, sub, c, tsize=12.5)
    for i in range(4):
        arrow((xs[i] + W + 0.6, Ys + Hs / 2), (xs[i + 1] - 0.6, Ys + Hs / 2))
    ax.text(xs[3] + W + G / 2, Ys + Hs + 0.9, "yes", color="#009E73", fontsize=13, ha="center", fontweight="bold")
    arrow((xs[3] + W / 2, Ys - 0.6), (xs[0] + W / 2, Ys - 0.6), rad=-0.1, color="#D55E00")
    ax.text((xs[0] + xs[3] + W) / 2, -1.2, "no: PROBE_FAILED, back to REROUTED", color="#D55E00", fontsize=12.5, ha="center", fontweight="bold", va="bottom")
    save(fig, "fig_d_pipeline", theme, t)


if __name__ == "__main__":
    import matplotlib.dates
    for theme, t in THEMES.items():
        fig_a(theme, t); fig_b(theme, t); fig_c(theme, t); fig_d(theme, t)
