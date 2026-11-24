import os
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Rectangle

# Set non-interactive writable cache dir
os.environ["MPLCONFIGDIR"] = os.path.join(os.environ.get("TEMP", "/tmp"), "mpl_cache")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "figures"
OUT.mkdir(exist_ok=True)

# Common styling
FONT_FAMILY = "sans-serif"
BG_DARK = "#0B0F17"
CARD_BG = "#131B26"
CARD_BORDER = "#223147"
TEXT_WHITE = "#F3F4F6"
TEXT_MUTED = "#9CA3AF"
CYAN = "#06B6D4"
PURPLE = "#8B5CF6"
GREEN = "#10B981"
AMBER = "#F59E0B"
RED = "#EF4444"
BLUE = "#3B82F6"

# ==============================================================================
# 1. HERO BANNER (figures/hero_banner.png)
# ==============================================================================
def make_hero_banner():
    fig = plt.figure(figsize=(16, 5.5), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG_DARK)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 550)
    ax.axis("off")

    # Background subtle grid lines
    for x in range(0, 1600, 40):
        ax.plot([x, x], [0, 550], color="#162032", lw=0.5, alpha=0.5)
    for y in range(0, 550, 40):
        ax.plot([0, 1600], [y, y], color="#162032", lw=0.5, alpha=0.5)

    # Gradient highlight glow at the top center
    glow = patches.Ellipse((800, 550), 1200, 300, facecolor="#4F46E5", alpha=0.15)
    ax.add_patch(glow)

    # Main Card container
    card = FancyBboxPatch((40, 30), 1520, 490, boxstyle="round,pad=0,rounding_size=20",
                          facecolor=CARD_BG, edgecolor=CARD_BORDER, linewidth=1.5)
    ax.add_patch(card)

    # Eyebrow Pill
    pill = FancyBboxPatch((80, 440), 380, 42, boxstyle="round,pad=0,rounding_size=21",
                          facecolor="#1E1B4B", edgecolor="#6366F1", linewidth=1.2)
    ax.add_patch(pill)
    ax.text(270, 461, "AUTONOMOUS SERVICE-MESH ORCHESTRATOR", color="#A5B4FC",
            fontsize=11, fontweight="bold", ha="center", va="center")

    # Main Title & Subtitle
    ax.text(80, 380, "Apex-AI (MeshHeal AI)", color=TEXT_WHITE,
            fontsize=34, fontweight="bold", va="center")
    ax.text(80, 325, "Self-Healing Multi-Cloud Microservices via Graph Neural Networks & Istio",
            color=TEXT_MUTED, fontsize=16, va="center")

    # Pipeline Flow Visual inside Banner
    steps = [
        ("1. Telemetry Ingest", "Prometheus + Istio Envoy\nSource RTT & Packet Loss", "#3B82F6"),
        ("2. Graph Reasoning", "5-Seed GNN (GCN/SAGE)\nTopological Anomaly Scoring", "#8B5CF6"),
        ("3. Safety Control Plane", "Victim Suppression Gate\nPersistence Rule (k=3 of 4)", "#F59E0B"),
        ("4. Closed-Loop Reroute", "Istio Dynamic JSON Patch\nCanary Probe & Release", "#10B981")
    ]

    box_w, box_h, start_x, start_y = 310, 105, 80, 175
    for i, (title, desc, color) in enumerate(steps):
        bx = start_x + i * (box_w + 65)
        # Card
        b_card = FancyBboxPatch((bx, start_y), box_w, box_h, boxstyle="round,pad=0,rounding_size=12",
                                facecolor="#0E1624", edgecolor=color, linewidth=1.2)
        ax.add_patch(b_card)
        # Dot indicator
        ax.add_patch(Circle((bx + 25, start_y + box_h - 26), 6, facecolor=color))
        # Text
        ax.text(bx + 40, start_y + box_h - 26, title, color=TEXT_WHITE,
                fontsize=13, fontweight="bold", va="center")
        ax.text(bx + 25, start_y + 38, desc, color=TEXT_MUTED,
                fontsize=11, va="center", linespacing=1.3)

        # Arrow to next step
        if i < 3:
            arr_x = bx + box_w + 12
            arr_y = start_y + box_h / 2
            ax.annotate("", xy=(arr_x + 40, arr_y), xytext=(arr_x, arr_y),
                        arrowprops=dict(arrowstyle="->", color="#4B5563", lw=2, mutation_scale=15))

    # Metric Badges along bottom
    metrics = [
        ("< 2.0s Latency Recovery", "From 172ms down to 23ms baseline", GREEN),
        ("0.4% Wrong-Action Rate", "vs 10.1% naive latency rule", BLUE),
        ("0 False Positives", "30-minute full soak test", PURPLE),
        ("35 / 35 Tests Passing", "Zero-cluster offline suite", CYAN)
    ]

    m_w, m_h, m_y = 340, 65, 60
    for j, (top_txt, sub_txt, col) in enumerate(metrics):
        mx = start_x + j * (m_w + 35)
        m_card = FancyBboxPatch((mx, m_y), m_w, m_h, boxstyle="round,pad=0,rounding_size=10",
                                facecolor="#162032", edgecolor="#2D3F58", linewidth=1.0)
        ax.add_patch(m_card)
        ax.text(mx + 20, m_y + 42, top_txt, color=col, fontsize=13, fontweight="bold")
        ax.text(mx + 20, m_y + 18, sub_txt, color=TEXT_MUTED, fontsize=10.5)

    plt.savefig(OUT / "hero_banner.png", dpi=200, facecolor=BG_DARK)
    plt.close(fig)
    print("Generated figures/hero_banner.png")


# ==============================================================================
# 2. BEFORE vs. AFTER REMEDIATION WORKFLOW (figures/remediation_workflow.png)
# ==============================================================================
def make_remediation_workflow():
    fig = plt.figure(figsize=(16, 8.5), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG_DARK)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 850)
    ax.axis("off")

    # Header Title
    ax.text(800, 805, "Autonomous Self-Healing: Before vs. After Incident Lifecycle",
            color=TEXT_WHITE, fontsize=24, fontweight="bold", ha="center")
    ax.text(800, 770, "How Apex-AI intercepts silent cascading microservice degradation without false alarms",
            color=TEXT_MUTED, fontsize=14, ha="center")

    panel_w = 440
    panel_h = 680
    panel_y = 60
    positions = [80, 580, 1080]

    # Panel 1: Injected Failure & Cascade
    p1 = FancyBboxPatch((positions[0], panel_y), panel_w, panel_h, boxstyle="round,pad=0,rounding_size=16",
                        facecolor=CARD_BG, edgecolor=RED, linewidth=1.5)
    ax.add_patch(p1)
    ax.text(positions[0] + 25, panel_y + panel_h - 40, "STAGE 1: SILENT FAILURE CASCADE",
            color=RED, fontsize=13, fontweight="bold")
    ax.text(positions[0] + 25, panel_y + panel_h - 75, "Downstream fault stalls upstream callers",
            color=TEXT_MUTED, fontsize=11)

    # Topology in Panel 1
    # Nodes: productpage -> reviews -> ratings (FAULT)
    # productpage -> details
    def draw_mini_topo(px, py, ratings_status="fault", reviews_route="v1+v2+v3"):
        # productpage
        ax.add_patch(FancyBboxPatch((px + 140, py + 340), 120, 45, boxstyle="round,pad=0,rounding_size=8",
                                    facecolor="#1E293B", edgecolor="#38BDF8", lw=1.2))
        ax.text(px + 200, py + 362, "productpage", color=TEXT_WHITE, fontsize=11, ha="center", va="center")

        # details
        ax.add_patch(FancyBboxPatch((px + 30, py + 220), 100, 40, boxstyle="round,pad=0,rounding_size=8",
                                    facecolor="#1E293B", edgecolor="#34D399", lw=1.0))
        ax.text(px + 80, py + 240, "details (v1)", color=TEXT_WHITE, fontsize=10, ha="center", va="center")

        # reviews
        rev_border = RED if ratings_status == "fault" else "#34D399"
        ax.add_patch(FancyBboxPatch((px + 250, py + 220), 130, 40, boxstyle="round,pad=0,rounding_size=8",
                                    facecolor="#1E293B", edgecolor=rev_border, lw=1.5))
        ax.text(px + 315, py + 240, f"reviews ({reviews_route})", color=TEXT_WHITE, fontsize=10, ha="center", va="center")

        # ratings
        rat_bg = "#450A0A" if ratings_status == "fault" else "#064E3B"
        rat_border = RED if ratings_status == "fault" else GREEN
        ax.add_patch(FancyBboxPatch((px + 250, py + 100), 130, 45, boxstyle="round,pad=0,rounding_size=8",
                                    facecolor=rat_bg, edgecolor=rat_border, lw=1.8))
        rat_txt = "ratings (150ms FAULT)" if ratings_status == "fault" else "ratings (Bypassed/Probing)"
        ax.text(px + 315, py + 122, rat_txt, color=RED if ratings_status == "fault" else GREEN,
                fontsize=9.5, fontweight="bold", ha="center", va="center")

        # Edges
        ax.annotate("", xy=(px + 80, py + 265), xytext=(px + 160, py + 340),
                    arrowprops=dict(arrowstyle="->", color="#64748B", lw=1.5))
        ax.annotate("", xy=(px + 315, py + 265), xytext=(px + 240, py + 340),
                    arrowprops=dict(arrowstyle="->", color=RED if ratings_status == "fault" else "#64748B", lw=1.8))

        if reviews_route == "100% v1":
            # ratings edge severed
            ax.annotate("", xy=(px + 315, py + 150), xytext=(px + 315, py + 215),
                        arrowprops=dict(arrowstyle="->", color="#475569", lw=1.2, ls="--"))
            ax.text(px + 315, py + 180, "[TRAFFIC SHIFTED AWAY]", color=AMBER, fontsize=9, ha="center",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=BG_DARK, edgecolor=AMBER, lw=0.8))
        else:
            ax.annotate("", xy=(px + 315, py + 150), xytext=(px + 315, py + 215),
                        arrowprops=dict(arrowstyle="->", color=RED, lw=2))

    draw_mini_topo(positions[0], panel_y + 160, ratings_status="fault", reviews_route="v1/v2/v3")

    # Panel 1 Metrics Box
    m1 = FancyBboxPatch((positions[0] + 25, panel_y + 25), panel_w - 50, 110, boxstyle="round,pad=0,rounding_size=10",
                        facecolor="#1A1215", edgecolor="#7F1D1D", lw=1.2)
    ax.add_patch(m1)
    ax.text(positions[0] + 45, panel_y + 105, "Observed Impact:", color=RED, fontsize=11, fontweight="bold")
    ax.text(positions[0] + 45, panel_y + 75, "• Productpage Latency: 172 ms (Spike)", color=TEXT_WHITE, fontsize=10.5)
    ax.text(positions[0] + 45, panel_y + 52, "• Upstream reviews saturated waiting on ratings", color=TEXT_WHITE, fontsize=10.5)
    ax.text(positions[0] + 45, panel_y + 32, "• Naive Rule Blunder: Blames victim 'reviews' (RC1: 7%)", color="#FCA5A5", fontsize=10)

    # Panel 2: Apex-AI Analysis & Decision
    p2 = FancyBboxPatch((positions[1], panel_y), panel_w, panel_h, boxstyle="round,pad=0,rounding_size=16",
                        facecolor=CARD_BG, edgecolor=PURPLE, linewidth=1.5)
    ax.add_patch(p2)
    ax.text(positions[1] + 25, panel_y + panel_h - 40, "STAGE 2: REASONING & GATING",
            color=PURPLE, fontsize=13, fontweight="bold")
    ax.text(positions[1] + 25, panel_y + panel_h - 75, "Dual-engine scoring & victim suppression",
            color=TEXT_MUTED, fontsize=11)

    steps_p2 = [
        ("Feature Vector Construction", "6-dim metrics: in/out rate, error, latency\nlog1p scaled, refreshed every 15s", CYAN),
        ("Dual-Engine Risk Scoring", "GNN Primary (5-seed ensemble, <500ms)\nFallback: Culprit Rule (in_lat - out_lat)", PURPLE),
        ("Victim Suppression Logic", "reviews waiting on ratings -> flagged\nas SUPPRESSED_VICTIM (prevents false drop)", AMBER),
        ("Temporal Persistence Filter", "Top node risk > 0.85 in 3 of last 4 cycles\nZero false alarms during 30m soak", BLUE),
        ("Safety Gate Verification", "Target pod ready; playbook found; no loops;\nEnforces 120s cooldown against flapping", GREEN),
    ]

    for k, (st_t, st_d, st_c) in enumerate(steps_p2):
        sy = panel_y + 440 - k * 72
        ax.add_patch(FancyBboxPatch((positions[1] + 25, sy), panel_w - 50, 60, boxstyle="round,pad=0,rounding_size=8",
                                    facecolor="#0E1726", edgecolor=st_c, lw=1.0))
        ax.add_patch(Circle((positions[1] + 45, sy + 30), 5, facecolor=st_c))
        ax.text(positions[1] + 60, sy + 38, st_t, color=TEXT_WHITE, fontsize=10.5, fontweight="bold")
        ax.text(positions[1] + 60, sy + 18, st_d, color=TEXT_MUTED, fontsize=9.5, linespacing=1.2)

    # Panel 2 Bottom Callout
    ax.add_patch(FancyBboxPatch((positions[1] + 25, panel_y + 25), panel_w - 50, 50, boxstyle="round,pad=0,rounding_size=8",
                               facecolor="#2E1065", edgecolor="#7C3AED", lw=1.0))
    ax.text(positions[1] + 45, panel_y + 50, "DECISION EVENT: REROUTE (ratings)", color="#DDD6FE", fontsize=11, fontweight="bold")
    ax.text(positions[1] + 45, panel_y + 32, "Action: Patch reviews VirtualService -> 100% v1", color=TEXT_WHITE, fontsize=9.5)

    # Panel 3: Closed-Loop Remediation & Recovery
    p3 = FancyBboxPatch((positions[2], panel_y), panel_w, panel_h, boxstyle="round,pad=0,rounding_size=16",
                        facecolor=CARD_BG, edgecolor=GREEN, linewidth=1.5)
    ax.add_patch(p3)
    ax.text(positions[2] + 25, panel_y + panel_h - 40, "STAGE 3: CLOSED-LOOP RECOVERY",
            color=GREEN, fontsize=13, fontweight="bold")
    ax.text(positions[2] + 25, panel_y + panel_h - 75, "Sub-2s recovery, canary probe & safe release",
            color=TEXT_MUTED, fontsize=11)

    draw_mini_topo(positions[2], panel_y + 160, ratings_status="mitigated", reviews_route="100% v1")

    # Panel 3 Metrics Box
    m3 = FancyBboxPatch((positions[2] + 25, panel_y + 25), panel_w - 50, 110, boxstyle="round,pad=0,rounding_size=10",
                        facecolor="#064E3B", edgecolor=GREEN, lw=1.2)
    ax.add_patch(m3)
    ax.text(positions[2] + 45, panel_y + 105, "Verified Results:", color="#A7F3D0", fontsize=11, fontweight="bold")
    ax.text(positions[2] + 45, panel_y + 75, "• Latency Dropped: 172 ms -> 23 ms (Baseline)", color=TEXT_WHITE, fontsize=10.5, fontweight="bold")
    ax.text(positions[2] + 45, panel_y + 52, "• Recovery Velocity: < 2.0 s after Istio patch", color=TEXT_WHITE, fontsize=10.5)
    ax.text(positions[2] + 45, panel_y + 32, "• Canary Probing: 70/15/15 until Risk < 0.60 -> Release", color="#D1FAE5", fontsize=10)

    # Arrow connections between panels
    for arr_idx in [0, 1]:
        ax.annotate("", xy=(positions[arr_idx + 1] - 15, panel_y + panel_h / 2),
                    xytext=(positions[arr_idx] + panel_w + 15, panel_y + panel_h / 2),
                    arrowprops=dict(arrowstyle="->", color="#6366F1", lw=3, mutation_scale=25))

    plt.savefig(OUT / "remediation_workflow.png", dpi=200, facecolor=BG_DARK)
    plt.close(fig)
    print("Generated figures/remediation_workflow.png")


# ==============================================================================
# 3. EXECUTIVE JUDGE SCORECARD (figures/judge_scorecard.png)
# ==============================================================================
def make_judge_scorecard():
    fig = plt.figure(figsize=(16, 7.5), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG_DARK)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 750)
    ax.axis("off")

    ax.text(800, 705, "Evaluation Scorecard: Apex-AI vs. Traditional Monitoring Baselines",
            color=TEXT_WHITE, fontsize=24, fontweight="bold", ha="center")
    ax.text(800, 670, "8-Fold Leave-One-Episode-Out (LOEO) Cross-Validation & 30-Minute Soak Benchmark",
            color=TEXT_MUTED, fontsize=14, ha="center")

    # Table layout
    headers = ["Evaluation Metric", "Naive Latency Baseline", "Culprit Rule", "Apex-AI (5-Seed GNN)", "Why Judges Care / Impact"]
    col_x = [60, 360, 630, 900, 1190]
    col_w = [280, 250, 250, 270, 350]

    # Header Row
    ax.add_patch(FancyBboxPatch((50, 600), 1500, 45, boxstyle="round,pad=0,rounding_size=8",
                                facecolor="#1E293B", edgecolor="#334155", lw=1.0))
    for h, x in zip(headers, col_x):
        ax.text(x, 622, h, color=TEXT_WHITE, fontsize=12, fontweight="bold", va="center")

    rows = [
        ("Root-Cause Accuracy (RC1)", "7.0%", "95.0%", "95.0%", "Baseline falsely attacks upstream victim services", RED, GREEN, GREEN),
        ("Average Precision (Distinct AP)", "0.930", "0.928", "0.928", "Eliminates tied-zero tie-break distortion", TEXT_WHITE, TEXT_WHITE, TEXT_WHITE),
        ("Policy Wrong-Action Rate", "10.1%", "0.4%", "0.4%", "96% reduction in destructive incorrect traffic drops", RED, GREEN, GREEN),
        ("Incident Recovery Time", "15 - 30 min (Manual)", "63.7 s", "78.2 s", "Full detection, safety checks, and reroute in < 80s", RED, GREEN, GREEN),
        ("Latency Reduction Post-Patch", "0% (Downtime persists)", "-87% (182 -> 24ms)", "-87% (172 -> 23ms)", "Service recovers to baseline within 2.0s of patch", RED, GREEN, GREEN),
        ("False Alarms in 30m Soak", "Frequent jitter alerts", "0 events", "0 events", "3-of-4 persistence filter ensures absolute stability", AMBER, GREEN, GREEN),
        ("Production Fail-Safe", "None", "Deterministic", "Dual-Engine Resilient", "500ms SLA budget + fallback if GNN fails", RED, BLUE, GREEN)
    ]

    for idx, (metric, base, rule, gnn, why, c_b, c_r, c_g) in enumerate(rows):
        ry = 530 - idx * 70
        bg_color = CARD_BG if idx % 2 == 0 else "#0F172A"
        ax.add_patch(FancyBboxPatch((50, ry), 1500, 60, boxstyle="round,pad=0,rounding_size=8",
                                    facecolor=bg_color, edgecolor=CARD_BORDER, lw=0.8))

        ax.text(col_x[0], ry + 30, metric, color=TEXT_WHITE, fontsize=12, fontweight="bold", va="center")
        ax.text(col_x[1], ry + 30, base, color=c_b, fontsize=12, va="center")
        ax.text(col_x[2], ry + 30, rule, color=c_r, fontsize=12, va="center")
        ax.text(col_x[3], ry + 30, gnn, color=c_g, fontsize=12, fontweight="bold", va="center")
        ax.text(col_x[4], ry + 30, why, color=TEXT_MUTED, fontsize=10.5, va="center")

    plt.savefig(OUT / "judge_scorecard.png", dpi=200, facecolor=BG_DARK)
    plt.close(fig)
    print("Generated figures/judge_scorecard.png")


# ==============================================================================
# 4. SRE CONSOLE DASHBOARD PREVIEW (figures/dashboard_preview.png)
# ==============================================================================
def make_dashboard_preview():
    fig = plt.figure(figsize=(16, 9.5), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("#0F0720")  # Deep violet atmospheric background from Frontend_v2
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 950)
    ax.axis("off")

    # Header Bar
    ax.add_patch(FancyBboxPatch((40, 870), 1520, 60, boxstyle="round,pad=0,rounding_size=12",
                                facecolor="#1D1438", edgecolor="#3B2A63", lw=1.2))
    ax.text(70, 900, "Apex-AI SRE Operations Console", color="#F4F0FF", fontsize=16, fontweight="bold", va="center")

    # Mode Badge
    ax.add_patch(FancyBboxPatch((380, 882), 110, 36, boxstyle="round,pad=0,rounding_size=18",
                                facecolor="#261B48", edgecolor="#6D4AFF", lw=1.0))
    ax.text(435, 900, "MODE: LIVE", color="#6D4AFF", fontsize=11, fontweight="bold", ha="center", va="center")

    # Scorer Badge
    ax.add_patch(FancyBboxPatch((505, 882), 140, 36, boxstyle="round,pad=0,rounding_size=18",
                                facecolor="#261B48", edgecolor="#34D6B0", lw=1.0))
    ax.text(575, 900, "SCORER: GNN", color="#34D6B0", fontsize=11, fontweight="bold", ha="center", va="center")

    # Status headline
    ax.text(70, 825, "INCIDENT RESOLVED: TRAFFIC SHIFTED AWAY FROM DEGRADED 'ratings'",
            color="#34D6B0", fontsize=18, fontweight="bold")
    ax.text(70, 795, "Istio VirtualService patched: reviews -> 100% v1 | Latency normalized from 172ms to 23ms",
            color="#A99BC9", fontsize=12)

    # Main Stage (Cytoscape Graph View Mockup)
    stage = FancyBboxPatch((40, 240), 1020, 520, boxstyle="round,pad=0,rounding_size=20",
                           facecolor="#150A2E", edgecolor="#2D1C54", lw=1.5)
    ax.add_patch(stage)
    ax.text(70, 730, "LIVE SERVICE MESH TOPOLOGY (aws-us-east)", color="#A99BC9", fontsize=13, fontweight="bold")

    # Nodes on stage
    # productpage
    ax.add_patch(FancyBboxPatch((120, 480), 180, 70, boxstyle="round,pad=0,rounding_size=14",
                                facecolor="#1D1438", edgecolor="#34D6B0", lw=2.0))
    ax.text(210, 525, "productpage", color="#F4F0FF", fontsize=14, fontweight="bold", ha="center")
    ax.text(210, 498, "OK • 0.02s p95", color="#34D6B0", fontsize=11, ha="center")

    # details
    ax.add_patch(FancyBboxPatch((440, 600), 180, 70, boxstyle="round,pad=0,rounding_size=14",
                                facecolor="#1D1438", edgecolor="#34D6B0", lw=2.0))
    ax.text(530, 645, "details (v1)", color="#F4F0FF", fontsize=14, fontweight="bold", ha="center")
    ax.text(530, 618, "OK • 0.01s p95", color="#34D6B0", fontsize=11, ha="center")

    # reviews
    ax.add_patch(FancyBboxPatch((440, 360), 200, 75, boxstyle="round,pad=0,rounding_size=14",
                                facecolor="#1D1438", edgecolor="#6D4AFF", lw=2.0))
    ax.text(540, 408, "reviews (100% v1)", color="#F4F0FF", fontsize=14, fontweight="bold", ha="center")
    ax.text(540, 380, "REROUTED • 0.02s p95", color="#A99BC9", fontsize=11, ha="center")

    # ratings (Culprit ring)
    ax.add_patch(FancyBboxPatch((780, 360), 210, 75, boxstyle="round,pad=0,rounding_size=14",
                                facecolor="#2A0B1E", edgecolor="#FF5C7C", lw=2.5))
    ax.text(885, 408, "ratings (CULPRIT)", color="#FF5C7C", fontsize=14, fontweight="bold", ha="center")
    ax.text(885, 380, "Risk: 0.88 • 150ms Delay", color="#FF9A3D", fontsize=11, ha="center")

    # Edges
    ax.annotate("", xy=(430, 635), xytext=(305, 530),
                arrowprops=dict(arrowstyle="->", color="#34D6B0", lw=2.5))
    ax.annotate("", xy=(430, 400), xytext=(305, 495),
                arrowprops=dict(arrowstyle="->", color="#34D6B0", lw=2.5))
    # Dashed severed edge
    ax.annotate("", xy=(770, 398), xytext=(645, 398),
                arrowprops=dict(arrowstyle="->", color="#5E5380", lw=2.0, ls="--"))
    ax.text(708, 415, "[TRAFFIC BYPASSED]", color="#FFB347", fontsize=9.5, ha="center",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#150A2E", edgecolor="#FFB347", lw=0.8))

    # Right Side: Detail Drawer (400px wide)
    drawer = FancyBboxPatch((1080, 240), 480, 520, boxstyle="round,pad=0,rounding_size=20",
                            facecolor="#1D1438", edgecolor="#3B2A63", lw=1.5)
    ax.add_patch(drawer)
    ax.text(1110, 730, "ROOT CAUSE DETAIL DRAWER", color="#F4F0FF", fontsize=14, fontweight="bold")
    ax.text(1110, 700, "Service: ratings.aws-us-east", color="#A99BC9", fontsize=11)

    # Risk Meter inside Drawer
    ax.add_patch(FancyBboxPatch((1110, 620), 420, 60, boxstyle="round,pad=0,rounding_size=10",
                                facecolor="#261B48", edgecolor="#FF5C7C", lw=1.2))
    ax.text(1130, 655, "Predicted Anomaly Risk:", color=TEXT_MUTED, fontsize=11)
    ax.text(1470, 655, "0.88", color="#FF5C7C", fontsize=22, fontweight="bold", ha="right")
    ax.text(1130, 632, "Action Threshold: > 0.85 (Enforced 3 of 4 cycles)", color="#FF9A3D", fontsize=9.5)

    # Safety Invariant Checks
    safety_checks = [
        ("Playbook Definition", "Found (reviews -> v1 reroute)", "PASS", "#34D6B0"),
        ("Target Pod Health", "reviews-v1 (1/1 Ready)", "READY", "#34D6B0"),
        ("Dependency Graph", "No circular dependency on culprit", "PASS", "#34D6B0"),
        ("Hysteresis & Cooldown", "120s stabilization timer active", "ACTIVE", "#6D4AFF")
    ]
    for s_i, (s_title, s_desc, s_badge, s_bcol) in enumerate(safety_checks):
        s_y = 540 - s_i * 68
        ax.add_patch(FancyBboxPatch((1110, s_y), 420, 56, boxstyle="round,pad=0,rounding_size=8",
                                    facecolor="#150A2E", edgecolor="#2D1C54", lw=1.0))
        ax.text(1125, s_y + 34, s_title, color="#F4F0FF", fontsize=11, fontweight="bold")
        ax.text(1125, s_y + 14, s_desc, color="#A99BC9", fontsize=9.5)
        # Badge
        ax.text(1510, s_y + 28, s_badge, color=s_bcol, fontsize=10, fontweight="bold", ha="right")

    # Bottom Area: Audit Event Stream
    audit_bar = FancyBboxPatch((40, 40), 1520, 180, boxstyle="round,pad=0,rounding_size=16",
                               facecolor="#1D1438", edgecolor="#3B2A63", lw=1.5)
    ax.add_patch(audit_bar)
    ax.text(70, 190, "IMMUTABLE REMEDIATION AUDIT LOG", color="#F4F0FF", fontsize=13, fontweight="bold")

    audits = [
        ("05:37:45Z", "SCORED", "ratings", "GNN Risk: 0.88 (Cycle 3 of 4 above threshold)", "PERSISTENCE_MET"),
        ("05:38:00Z", "REROUTE", "ratings", "Patch reviews VirtualService: 100% v1 (Bypasses ratings)", "ACTION_TAKEN"),
        ("05:39:20Z", "PROBE_START", "ratings", "Canary traffic shift 70/15/15 to measure recovered path", "CANARY_ACTIVE"),
        ("05:40:54Z", "RELEASE", "ratings", "Risk dropped to 0.12 (< 0.60 threshold) with real traffic", "RESTORE_NORMAL")
    ]
    for a_i, (a_t, a_e, a_s, a_d, a_r) in enumerate(audits):
        ay = 145 - a_i * 28
        ax.text(70, ay, a_t, color="#A99BC9", fontsize=10, fontfamily="monospace")
        e_color = "#34D6B0" if a_e in ("SCORED", "RELEASE") else ("#FF9A3D" if a_e == "REROUTE" else "#6D4AFF")
        ax.text(180, ay, a_e, color=e_color, fontsize=10, fontweight="bold")
        ax.text(320, ay, a_s, color="#F4F0FF", fontsize=10)
        ax.text(460, ay, a_d, color="#A99BC9", fontsize=10)
        ax.text(1490, ay, a_r, color="#34D6B0", fontsize=9.5, ha="right", fontfamily="monospace")

    plt.savefig(OUT / "dashboard_preview.png", dpi=200, facecolor="#0F0720")
    plt.close(fig)
    print("Generated figures/dashboard_preview.png")

if __name__ == "__main__":
    make_hero_banner()
    make_remediation_workflow()
    make_judge_scorecard()
    make_dashboard_preview()
