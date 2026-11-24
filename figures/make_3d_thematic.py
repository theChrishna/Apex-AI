import os
import sys
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Polygon, FancyBboxPatch, Circle, PathPatch
from matplotlib.path import Path as MplPath
from PIL import Image, ImageFilter

os.environ["MPLCONFIGDIR"] = os.path.join(os.environ.get("TEMP", "/tmp"), "mpl_cache")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "figures"
OUT.mkdir(exist_ok=True)

# -----------------------------------------------------------------------------
# Color Palette - Futuristic 3D Cyberpunk / Neon SRE
# -----------------------------------------------------------------------------
BG_DARK = "#07090E"
GRID_COLOR = "#121A27"
CYAN = "#00F0FF"
PURPLE = "#A855F7"
NEON_BLUE = "#3B82F6"
NEON_GREEN = "#10B981"
NEON_AMBER = "#F59E0B"
NEON_RED = "#FF3366"
TEXT_WHITE = "#FFFFFF"
TEXT_MUTED = "#8E9EB5"
GLASS_BORDER = "#1E2D42"

def iso(x, y, z, origin=(800, 500), scale=1.0):
    """Project 3D (x, y, z) into 2D isometric screen space."""
    angle = np.radians(28)
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    sx = origin[0] + (x - y) * cos_a * scale
    sy = origin[1] - ((x + y) * sin_a - z) * scale
    return sx, sy

def draw_iso_box(ax, origin_xyz, size_xyz, top_color, left_color, right_color, edge_color=None, alpha=0.9, proj_origin=(800, 500), scale=1.0):
    """Draw a 3D isometric box with 3 shaded faces."""
    x, y, z = origin_xyz
    dx, dy, dz = size_xyz
    
    # Vertices of the box
    # Base: 0=(x,y,z), 1=(x+dx,y,z), 2=(x+dx,y+dy,z), 3=(x,y+dy,z)
    # Top:  4=(x,y,z+dz), 5=(x+dx,y,z+dz), 6=(x+dx,y+dy,z+dz), 7=(x,y+dy,z+dz)
    pts = [iso(x + px, y + py, z + pz, proj_origin, scale) for pz in (0, dz) for py in (0, dy) for px in (0, dx)]
    # pts: 0: (0,0,0), 1: (1,0,0), 2: (0,1,0), 3: (1,1,0), 4: (0,0,1), 5: (1,0,1), 6: (0,1,1), 7: (1,1,1)
    p000, p100, p010, p110 = pts[0], pts[1], pts[2], pts[3]
    p001, p101, p011, p111 = pts[4], pts[5], pts[6], pts[7]
    
    ec = edge_color or top_color
    # Left face: (000, 010, 011, 001) -> along y axis
    poly_left = Polygon([p000, p010, p011, p001], facecolor=left_color, edgecolor=ec, lw=0.8, alpha=alpha, zorder=int(z))
    # Right face: (000, 100, 101, 001) -> along x axis
    poly_right = Polygon([p000, p100, p101, p001], facecolor=right_color, edgecolor=ec, lw=0.8, alpha=alpha, zorder=int(z))
    # Top face: (001, 101, 111, 011)
    poly_top = Polygon([p001, p101, p111, p011], facecolor=top_color, edgecolor=ec, lw=1.0, alpha=alpha, zorder=int(z+dz)+1)
    
    ax.add_patch(poly_left)
    ax.add_patch(poly_right)
    ax.add_patch(poly_top)
    return p001, p101, p111, p011  # Return top face corners

def draw_iso_plane(ax, origin_xyz, size_xy, fill_color, border_color, alpha=0.3, proj_origin=(800, 500), scale=1.0, zorder=10):
    """Draw a translucent floating isometric glass plane."""
    x, y, z = origin_xyz
    dx, dy = size_xy
    p1 = iso(x, y, z, proj_origin, scale)
    p2 = iso(x + dx, y, z, proj_origin, scale)
    p3 = iso(x + dx, y + dy, z, proj_origin, scale)
    p4 = iso(x, y + dy, z, proj_origin, scale)
    poly = Polygon([p1, p2, p3, p4], facecolor=fill_color, edgecolor=border_color, lw=1.5, alpha=alpha, zorder=zorder)
    ax.add_patch(poly)
    return p1, p2, p3, p4

# ==============================================================================
# 1. 3D THEMATIC HERO BANNER (figures/banner_3d_thematic.png)
# ==============================================================================
def make_banner_3d_thematic():
    fig = plt.figure(figsize=(16, 6.0), dpi=220)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG_DARK)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 600)
    ax.axis("off")

    # Perspective Grid lines in background
    for gx in range(-500, 2100, 80):
        p_start = (gx, 0)
        p_end = (800 + (gx - 800) * 0.35, 600)
        ax.plot([p_start[0], p_end[0]], [p_start[1], p_end[1]], color="#111827", lw=0.7, alpha=0.6)
    for gy in range(0, 600, 40):
        alpha_y = 0.2 + (gy / 600) * 0.4
        ax.plot([0, 1600], [gy, gy], color="#111827", lw=0.6, alpha=alpha_y)

    # Ambient volumetric neon glows
    ax.add_patch(patches.Ellipse((300, 300), 700, 400, facecolor="#6366F1", alpha=0.15))
    ax.add_patch(patches.Ellipse((1300, 300), 800, 500, facecolor="#06B6D4", alpha=0.12))
    ax.add_patch(patches.Ellipse((800, 500), 900, 300, facecolor="#A855F7", alpha=0.18))

    # Floating 3D Isometric Cluster Representation on the Right Side (x ~ 1000..1550)
    proj_origin = (1280, 260)
    p_scale = 0.85

    # Base ground plane
    draw_iso_plane(ax, (-250, -250, -20), (500, 500), "#0A101D", "#1E2D45", alpha=0.7, proj_origin=proj_origin, scale=p_scale, zorder=2)
    # Grid lines on base plane
    for step in range(-200, 250, 100):
        p_a = iso(step, -250, -20, proj_origin, p_scale)
        p_b = iso(step, 250, -20, proj_origin, p_scale)
        ax.plot([p_a[0], p_b[0]], [p_a[1], p_b[1]], color="#1E2D45", lw=0.8, zorder=3)
        p_c = iso(-250, step, -20, proj_origin, p_scale)
        p_d = iso(250, step, -20, proj_origin, p_scale)
        ax.plot([p_c[0], p_d[0]], [p_c[1], p_d[1]], color="#1E2D45", lw=0.8, zorder=3)

    # 3D Isometric Service Pods
    # 1. Productpage Gateway (Cyan)
    draw_iso_box(ax, (-140, 40, 0), (60, 60, 80), "#083344", "#062430", "#0e4559", edge_color=CYAN, alpha=0.85, proj_origin=proj_origin, scale=p_scale)
    tp1 = iso(-110, 70, 80, proj_origin, p_scale)
    ax.text(tp1[0], tp1[1] + 12, "Gateway", color=CYAN, fontsize=9, fontweight="bold", ha="center", zorder=50)

    # 2. Details Pod (Emerald)
    draw_iso_box(ax, (-140, -140, 0), (60, 60, 50), "#064E3B", "#043327", "#065f46", edge_color=NEON_GREEN, alpha=0.85, proj_origin=proj_origin, scale=p_scale)
    tp2 = iso(-110, -110, 50, proj_origin, p_scale)
    ax.text(tp2[0], tp2[1] + 10, "details", color=NEON_GREEN, fontsize=8.5, ha="center", zorder=50)

    # 3. Reviews Pod (Caller with traffic shift)
    draw_iso_box(ax, (40, 40, 0), (70, 70, 65), "#1E1B4B", "#151336", "#272363", edge_color=PURPLE, alpha=0.85, proj_origin=proj_origin, scale=p_scale)
    tp3 = iso(75, 75, 65, proj_origin, p_scale)
    ax.text(tp3[0], tp3[1] + 12, "reviews (v1)", color=PURPLE, fontsize=9, fontweight="bold", ha="center", zorder=50)

    # 4. Ratings Pod (Isolated Culprit with crimson shield)
    draw_iso_box(ax, (50, -140, 0), (60, 60, 40), "#4C0519", "#330311", "#680824", edge_color=NEON_RED, alpha=0.85, proj_origin=proj_origin, scale=p_scale)
    tp4 = iso(80, -110, 40, proj_origin, p_scale)
    ax.text(tp4[0], tp4[1] + 10, "ratings [FAULT]", color=NEON_RED, fontsize=8.5, fontweight="bold", ha="center", zorder=50)

    # 3D Glowing Conduits / Data Beams connecting pods
    # productpage -> details (green beam)
    e1_a = iso(-110, 40, 20, proj_origin, p_scale)
    e1_b = iso(-110, -80, 20, proj_origin, p_scale)
    ax.plot([e1_a[0], e1_b[0]], [e1_a[1], e1_b[1]], color=NEON_GREEN, lw=2.5, alpha=0.8, zorder=25)

    # productpage -> reviews (cyan/purple beam)
    e2_a = iso(-80, 70, 25, proj_origin, p_scale)
    e2_b = iso(40, 70, 25, proj_origin, p_scale)
    ax.plot([e2_a[0], e2_b[0]], [e2_a[1], e2_b[1]], color=CYAN, lw=2.5, alpha=0.8, zorder=25)

    # reviews -> ratings (Bypassed dotted beam with warning marker)
    e3_a = iso(75, 40, 15, proj_origin, p_scale)
    e3_b = iso(75, -80, 15, proj_origin, p_scale)
    ax.plot([e3_a[0], e3_b[0]], [e3_a[1], e3_b[1]], color=NEON_AMBER, lw=1.5, ls="--", alpha=0.6, zorder=25)

    # 3D Floating Holographic GNN Neural Lattice above the mesh (z = 180)
    draw_iso_plane(ax, (-200, -200, 160), (400, 400), "#3B0764", "#9333EA", alpha=0.25, proj_origin=proj_origin, scale=p_scale, zorder=60)
    for gnode_xyz in [(-120, 60, 160), (-120, -120, 160), (60, 60, 160), (60, -120, 160)]:
        gp = iso(*gnode_xyz, proj_origin, p_scale)
        ax.add_patch(Circle((gp[0], gp[1]), 6, facecolor=PURPLE, edgecolor=TEXT_WHITE, lw=1.2, zorder=70))
        # Vertical drop line connecting GNN to cluster pods
        gp_base = iso(gnode_xyz[0], gnode_xyz[1], 40, proj_origin, p_scale)
        ax.plot([gp[0], gp_base[0]], [gp[1], gp_base[1]], color="#818CF8", lw=0.9, ls=":", alpha=0.5, zorder=55)

    # Holographic label above the GNN layer
    gnn_label_pt = iso(0, 0, 195, proj_origin, p_scale)
    ax.text(gnn_label_pt[0], gnn_label_pt[1], "GRAPH REASONING LAYER (GCN/SAGE)",
            color="#E9D5FF", fontsize=9, fontweight="bold", ha="center", zorder=80,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#1E1B4B", edgecolor=PURPLE, lw=0.8))

    # LEFT SIDE: Futuristic Typography & Value Proposition
    # Glowing pill badge
    pill = FancyBboxPatch((80, 500), 400, 36, boxstyle="round,pad=0,rounding_size=18",
                          facecolor="#1E1B4B", edgecolor="#6366F1", lw=1.5)
    ax.add_patch(pill)
    ax.text(280, 518, "NEXT-GEN AUTONOMOUS SERVICE MESH", color="#C7D2FE",
            fontsize=10.5, fontweight="bold", ha="center", va="center")

    # Main Project Title
    ax.text(80, 430, "Apex-AI", color=TEXT_WHITE, fontsize=42, fontweight="heavy")
    ax.text(320, 430, "(MeshHeal AI)", color="#94A3B8", fontsize=32, fontweight="normal")

    # Tagline
    ax.text(80, 375, "Autonomous Multi-Cloud Service Mesh Self-Healing",
            color=CYAN, fontsize=18, fontweight="bold")
    ax.text(80, 340, "Instant silent degradation isolation & zero-downtime dynamic Istio rerouting\nvia continuous Graph Neural Network (GNN) topological inference.",
            color=TEXT_MUTED, fontsize=12.5, linespacing=1.35)

    # 3D Thematic Floating Metric Badges
    card_metrics = [
        ("< 2.0s Self-Healing", "172ms to 23ms baseline instantly", NEON_GREEN),
        ("95.0% Root-Cause Top-1", "Isolates culprit; saves victims", PURPLE),
        ("0.4% Wrong-Action", "vs 10.1% naive alerting rules", CYAN),
        ("0 False Positives", "30-min continuous soak verification", NEON_AMBER)
    ]

    bx, by, bw, bh = 80, 190, 210, 80
    for idx, (m_val, m_desc, m_col) in enumerate(card_metrics):
        cx = bx + (idx % 2) * (bw + 25)
        cy = by - (idx // 2) * (bh + 20)
        card = FancyBboxPatch((cx, cy), bw, bh, boxstyle="round,pad=0,rounding_size=12",
                              facecolor="#0B1320", edgecolor="#1F2E45", lw=1.2)
        ax.add_patch(card)
        # Accent top bar
        ax.add_patch(FancyBboxPatch((cx + 10, cy + bh - 4), bw - 20, 3, boxstyle="round,pad=0,rounding_size=1.5",
                                    facecolor=m_col, edgecolor=m_col))
        ax.text(cx + 15, cy + bh - 24, m_val, color=m_col, fontsize=12.5, fontweight="bold")
        ax.text(cx + 15, cy + 18, m_desc, color=TEXT_MUTED, fontsize=9.5, linespacing=1.2)

    # Tech Stack Tag Pills along the bottom left
    stacks = ["Kubernetes 1.28+", "Istio 1.20+", "PyG (GCN/GraphSAGE)", "Prometheus TSDB", "React 18 + Cytoscape"]
    tx = 80
    for st in stacks:
        w_pill = len(st) * 8.5 + 24
        ax.add_patch(FancyBboxPatch((tx, 30), w_pill, 28, boxstyle="round,pad=0,rounding_size=14",
                                    facecolor="#111827", edgecolor="#374151", lw=0.8))
        ax.text(tx + w_pill / 2, 44, st, color="#9CA3AF", fontsize=9.5, ha="center", va="center")
        tx += w_pill + 12

    plt.savefig(OUT / "banner_3d_thematic.png", dpi=220, facecolor=BG_DARK)
    plt.close(fig)
    print("Generated figures/banner_3d_thematic.png")


# ==============================================================================
# 2. 3D EXPLODED ARCHITECTURE DIAGRAM (figures/architecture_3d_isometric.png)
# ==============================================================================
def make_architecture_3d_isometric():
    fig = plt.figure(figsize=(16, 9.5), dpi=220)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG_DARK)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 950)
    ax.axis("off")

    # Header
    ax.text(800, 905, "3D Exploded-View Architecture & Self-Healing Pipeline",
            color=TEXT_WHITE, fontsize=24, fontweight="bold", ha="center")
    ax.text(800, 875, "Multi-tier cross-plane orchestration from kernel mesh telemetry to autonomous Istio dynamic steering",
            color=TEXT_MUTED, fontsize=13, ha="center")

    proj_origin = (680, 120)
    p_scale = 1.05

    # 4 Exploded Floating Glass Planes:
    # Layer 1: Substrate Mesh (z = 40)
    # Layer 2: Telemetry TSDB (z = 240)
    # Layer 3: Graph Neural Intelligence (z = 440)
    # Layer 4: Autonomous Control & Routing (z = 640)

    layers = [
        (40, "LAYER 1: SERVICE MESH CLOUD SUBSTRATE",
         "K3d Cluster • aws-us-east • Istio/Envoy Sidecars • Bookinfo Pods (v1/v2/v3)", "#064E3B", NEON_GREEN),
        (240, "LAYER 2: OBSERVABILITY & GRAPH TSDB AGGREGATION",
         "Prometheus TSDB Scrapes • Sliding-Window Graph Snapshots • Source RTT • Age < 45s Validation", "#083344", CYAN),
        (440, "LAYER 3: TOPOLOGICAL GRAPH NEURAL REASONING",
         "PyTorch Geometric • 5-Seed Ensemble GCN/GraphSAGE • Upstream Victim Suppression Filter", "#3B0764", PURPLE),
        (640, "LAYER 4: CLOSED-LOOP AUTONOMOUS ACTUATION",
         "VirtualService Dynamic JSON Patch • 100% v1 Traffic Shift • 70/15/15 Canary Probe & Hysteresis", "#450A0A", NEON_RED)
    ]

    for z_level, title, subtitle, fill_c, edge_c in layers:
        # Draw translucent isometric plane
        draw_iso_plane(ax, (-280, -280, z_level), (560, 560), fill_c, edge_c, alpha=0.35, proj_origin=proj_origin, scale=p_scale, zorder=z_level)
        
        # Grid lines inside each plane for high-tech holographic look
        for g_i in range(-200, 250, 100):
            p1 = iso(g_i, -280, z_level, proj_origin, p_scale)
            p2 = iso(g_i, 280, z_level, proj_origin, p_scale)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=edge_c, lw=0.6, alpha=0.3, zorder=z_level + 1)
            p3 = iso(-280, g_i, z_level, proj_origin, p_scale)
            p4 = iso(280, g_i, z_level, proj_origin, p_scale)
            ax.plot([p3[0], p4[0]], [p3[1], p4[1]], color=edge_c, lw=0.6, alpha=0.3, zorder=z_level + 1)

        # 3D Blocks / Components on this level
        if z_level == 40:
            # Microservices on mesh
            draw_iso_box(ax, (-180, 50, z_level), (70, 70, 45), "#064E3B", "#03281E", "#076049", edge_color=NEON_GREEN, proj_origin=proj_origin, scale=p_scale)
            draw_iso_box(ax, (-180, -150, z_level), (70, 70, 45), "#064E3B", "#03281E", "#076049", edge_color=NEON_GREEN, proj_origin=proj_origin, scale=p_scale)
            draw_iso_box(ax, (50, 50, z_level), (80, 80, 45), "#1E1B4B", "#100E2B", "#2B2668", edge_color=PURPLE, proj_origin=proj_origin, scale=p_scale)
            draw_iso_box(ax, (60, -150, z_level), (70, 70, 45), "#4C0519", "#29020D", "#6C0824", edge_color=NEON_RED, proj_origin=proj_origin, scale=p_scale)
        elif z_level == 240:
            # Snapshots & TSDB cache
            draw_iso_box(ax, (-100, -100, z_level), (200, 200, 35), "#083344", "#041B24", "#0D4961", edge_color=CYAN, proj_origin=proj_origin, scale=p_scale)
        elif z_level == 440:
            # GNN Weights & Inference blocks
            draw_iso_box(ax, (-140, -140, z_level), (120, 120, 40), "#3B0764", "#1F0335", "#510A8A", edge_color=PURPLE, proj_origin=proj_origin, scale=p_scale)
            draw_iso_box(ax, (30, 20, z_level), (110, 110, 40), "#451A03", "#230C01", "#682705", edge_color=NEON_AMBER, proj_origin=proj_origin, scale=p_scale)
        elif z_level == 640:
            # Dynamic Patch Controller & Canary
            draw_iso_box(ax, (-120, -120, z_level), (240, 240, 45), "#1E1B4B", "#100E2B", "#2E2A73", edge_color=CYAN, proj_origin=proj_origin, scale=p_scale)

        # Right-side explanatory banner card for each level
        corner_pt = iso(280, 0, z_level, proj_origin, p_scale)
        c_x = 1120
        c_y = corner_pt[1] - 30

        # Dotted leader line from isometric plane to right callout card
        ax.plot([corner_pt[0], c_x - 10], [corner_pt[1], c_y + 35], color=edge_c, lw=1.2, ls="--", alpha=0.7)
        ax.add_patch(Circle((corner_pt[0], corner_pt[1]), 5, facecolor=edge_c, edgecolor=TEXT_WHITE, lw=1.0))

        # Callout Card
        card = FancyBboxPatch((c_x, c_y), 440, 72, boxstyle="round,pad=0,rounding_size=10",
                              facecolor="#0B1220", edgecolor=edge_c, lw=1.2)
        ax.add_patch(card)
        ax.text(c_x + 18, c_y + 46, title, color=edge_c, fontsize=11, fontweight="bold")
        ax.text(c_x + 18, c_y + 20, subtitle, color=TEXT_MUTED, fontsize=9.5)

    # Vertical Glowing Data Conduits (Beams traveling vertically between planes)
    conduit_positions = [(-110, 60), (-110, -110), (60, 60), (60, -110)]
    conduit_colors = [CYAN, NEON_GREEN, PURPLE, NEON_RED]
    for (cx, cy), ccol in zip(conduit_positions, conduit_colors):
        p_bot = iso(cx, cy, 40, proj_origin, p_scale)
        p_top = iso(cx, cy, 685, proj_origin, p_scale)
        ax.plot([p_bot[0], p_top[0]], [p_bot[1], p_top[1]], color=ccol, lw=2.2, alpha=0.75, zorder=500)
        # Pulse dots traveling up
        for z_pulse in [150, 350, 550]:
            p_pulse = iso(cx, cy, z_pulse, proj_origin, p_scale)
            ax.add_patch(Circle((p_pulse[0], p_pulse[1]), 4.5, facecolor=ccol, edgecolor=TEXT_WHITE, lw=1.0, zorder=510))

    plt.savefig(OUT / "architecture_3d_isometric.png", dpi=220, facecolor=BG_DARK)
    plt.close(fig)
    print("Generated figures/architecture_3d_isometric.png")


# ==============================================================================
# 3. 3D CLOSED-LOOP SELF-HEALING TOPOLOGY CONDUIT (figures/closed_loop_3d.png)
# ==============================================================================
def make_closed_loop_3d():
    fig = plt.figure(figsize=(16, 8.5), dpi=220)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(BG_DARK)
    ax.set_xlim(0, 1600)
    ax.set_ylim(0, 850)
    ax.axis("off")

    ax.text(800, 805, "3D Isometric Self-Healing Dynamic Conduit",
            color=TEXT_WHITE, fontsize=24, fontweight="bold", ha="center")
    ax.text(800, 770, "How Apex-AI detours traffic around the degraded 'ratings' microservice to achieve sub-2s latency recovery",
            color=TEXT_MUTED, fontsize=13, ha="center")

    proj_origin = (800, 360)
    p_scale = 1.25

    # Ground platform (aws-us-east namespace)
    draw_iso_plane(ax, (-320, -320, -10), (640, 640), "#0B1322", "#1E2E48", alpha=0.8, proj_origin=proj_origin, scale=p_scale, zorder=1)

    # Simulated Region Labels on Base
    lbl_pt = iso(-280, 240, -10, proj_origin, p_scale)
    ax.text(lbl_pt[0], lbl_pt[1], "REGION: aws-us-east (Kubernetes Namespace)", color="#64748B", fontsize=10, fontweight="bold")

    # 1. Productpage Pod (x=-200, y=0)
    draw_iso_box(ax, (-230, -35, 0), (70, 70, 75), "#083344", "#04202B", "#0E475E", edge_color=CYAN, proj_origin=proj_origin, scale=p_scale)
    p_prod = iso(-195, 0, 75, proj_origin, p_scale)
    ax.text(p_prod[0], p_prod[1] + 16, "productpage", color=TEXT_WHITE, fontsize=12, fontweight="bold", ha="center", zorder=30)
    ax.text(p_prod[0], p_prod[1] + 2, "Ingress RTT: 23ms", color=NEON_GREEN, fontsize=9.5, ha="center", zorder=30)

    # 2. Details Pod (x=0, y=180)
    draw_iso_box(ax, (-35, 145, 0), (70, 70, 55), "#064E3B", "#032C21", "#08664D", edge_color=NEON_GREEN, proj_origin=proj_origin, scale=p_scale)
    p_det = iso(0, 180, 55, proj_origin, p_scale)
    ax.text(p_det[0], p_det[1] + 14, "details (v1)", color=TEXT_WHITE, fontsize=11, fontweight="bold", ha="center", zorder=30)
    ax.text(p_det[0], p_det[1] + 2, "Healthy • 0.01s", color=NEON_GREEN, fontsize=9, ha="center", zorder=30)

    # 3. Reviews Pod (x=0, y=-180) -> Multi-version container
    draw_iso_box(ax, (-50, -230, 0), (100, 100, 70), "#1E1B4B", "#12102E", "#2B2669", edge_color=PURPLE, proj_origin=proj_origin, scale=p_scale)
    p_rev = iso(0, -180, 70, proj_origin, p_scale)
    ax.text(p_rev[0], p_rev[1] + 16, "reviews", color=TEXT_WHITE, fontsize=12, fontweight="bold", ha="center", zorder=30)
    ax.text(p_rev[0], p_rev[1] + 2, "DYNAMIC SHIFT: 100% v1", color=CYAN, fontsize=9.5, fontweight="bold", ha="center", zorder=30)

    # 4. Ratings Pod (x=200, y=-180) -> Degraded Node
    draw_iso_box(ax, (165, -215, 0), (70, 70, 45), "#4C0519", "#29020D", "#6C0824", edge_color=NEON_RED, proj_origin=proj_origin, scale=p_scale)
    p_rat = iso(200, -180, 45, proj_origin, p_scale)
    ax.text(p_rat[0], p_rat[1] + 16, "ratings", color=NEON_RED, fontsize=12, fontweight="bold", ha="center", zorder=30)
    ax.text(p_rat[0], p_rat[1] + 2, "CULPRIT (+150ms Delay)", color=NEON_AMBER, fontsize=9, fontweight="bold", ha="center", zorder=30)

    # 3D Pulsing Anomaly Halo around Ratings Pod
    halo_pts = [iso(200 + 75 * np.cos(t), -180 + 75 * np.sin(t), 0, proj_origin, p_scale) for t in np.linspace(0, 2*np.pi, 24)]
    ax.add_patch(Polygon(halo_pts, facecolor="#FF3366", edgecolor="#FF3366", lw=2, alpha=0.25, zorder=10))

    # Glowing 3D Curved Conduits
    # Productpage -> Details
    e_det1 = iso(-195, 35, 30, proj_origin, p_scale)
    e_det2 = iso(-35, 180, 30, proj_origin, p_scale)
    ax.annotate("", xy=e_det2, xytext=e_det1,
                arrowprops=dict(arrowstyle="->", color=NEON_GREEN, lw=3, mutation_scale=20))

    # Productpage -> Reviews
    e_rev1 = iso(-195, -35, 30, proj_origin, p_scale)
    e_rev2 = iso(-50, -180, 30, proj_origin, p_scale)
    ax.annotate("", xy=e_rev2, xytext=e_rev1,
                arrowprops=dict(arrowstyle="->", color=CYAN, lw=3.5, mutation_scale=20))

    # The Detour: Reviews internal routing loop (v1 does NOT call ratings)
    # Severed / Bypassed link to Ratings
    e_rat1 = iso(50, -180, 20, proj_origin, p_scale)
    e_rat2 = iso(165, -180, 20, proj_origin, p_scale)
    ax.plot([e_rat1[0], e_rat2[0]], [e_rat1[1], e_rat2[1]], color="#64748B", lw=2, ls=":", zorder=15)
    p_cross = ((e_rat1[0] + e_rat2[0]) / 2, (e_rat1[1] + e_rat2[1]) / 2)
    ax.text(p_cross[0], p_cross[1], "✖ BYPASSED", color=NEON_RED, fontsize=9.5, fontweight="bold", ha="center", va="center",
            bbox=dict(boxstyle="round,pad=0.2", facecolor=BG_DARK, edgecolor=NEON_RED, lw=0.8), zorder=40)

    # 3D Canary Probe Concurrency Arc (70/15/15)
    probe_top = iso(100, -260, 90, proj_origin, p_scale)
    ax.annotate("70% v1 / 15% v2 / 15% v3 (Canary Probe)", xy=iso(200, -180, 50, proj_origin, p_scale),
                xytext=probe_top,
                arrowprops=dict(arrowstyle="->", color=NEON_AMBER, lw=1.8, connectionstyle="arc3,rad=-0.3"),
                color=NEON_AMBER, fontsize=10, fontweight="bold", zorder=50)

    # Summary Callout Boxes Left and Right
    # Left Callout: Detection & Victim Suppression
    box_l = FancyBboxPatch((60, 100), 360, 160, boxstyle="round,pad=0,rounding_size=12",
                           facecolor="#0B1322", edgecolor=PURPLE, lw=1.5)
    ax.add_patch(box_l)
    ax.text(80, 230, "INTELLIGENT VICTIM SUPPRESSION", color=PURPLE, fontsize=12, fontweight="bold")
    ax.text(80, 205, "• Upstream reviews caller stalls waiting on ratings", color=TEXT_WHITE, fontsize=10)
    ax.text(80, 185, "• Naive monitors blame reviews (False Root Cause)", color=NEON_RED, fontsize=10)
    ax.text(80, 165, "• Apex-AI extracts (in_lat - out_lat) feature vector", color=CYAN, fontsize=10)
    ax.text(80, 145, "• reviews classified as SUPPRESSED_VICTIM", color=NEON_GREEN, fontsize=10, fontweight="bold")
    ax.text(80, 120, "• Zero misdirected failovers (RC1: 95.0%)", color=TEXT_MUTED, fontsize=9.5)

    # Right Callout: Sub-2s Recovery
    box_r = FancyBboxPatch((1180, 100), 360, 160, boxstyle="round,pad=0,rounding_size=12",
                           facecolor="#0B1322", edgecolor=NEON_GREEN, lw=1.5)
    ax.add_patch(box_r)
    ax.text(1200, 230, "INSTANT LATENCY NORMALIZATION", color=NEON_GREEN, fontsize=12, fontweight="bold")
    ax.text(1200, 205, "• Istio VirtualService JSON patch executed", color=TEXT_WHITE, fontsize=10)
    ax.text(1200, 185, "• reviews route shifted 100% to subset v1", color=CYAN, fontsize=10)
    ax.text(1200, 165, "• Median latency falls: 172ms -> 23ms", color=NEON_GREEN, fontsize=10, fontweight="bold")
    ax.text(1200, 145, "• Recovery Velocity: < 2.0s post-patch", color=TEXT_WHITE, fontsize=10)
    ax.text(1200, 120, "• Automatic Canary Probe & Hysteresis Release", color=NEON_AMBER, fontsize=9.5)

    plt.savefig(OUT / "closed_loop_3d.png", dpi=220, facecolor=BG_DARK)
    plt.close(fig)
    print("Generated figures/closed_loop_3d.png")

if __name__ == "__main__":
    make_banner_3d_thematic()
    make_architecture_3d_isometric()
    make_closed_loop_3d()
