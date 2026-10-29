# MeshHeal AI: Autonomous Service-Mesh Remediation Prototype

A serene, high-signal SRE operations console dashboard for **MeshHeal AI**, built with React 18, TypeScript, Tailwind CSS, Cytoscape.js, and Recharts. All telemetry in the simulation engine runs deterministically in-browser using a seeded PRNG (with optional replay of recorded episode telemetry).

---

## Design System & Atmosphere

The console features a deep violet, spacious, and breathable visual architecture designed for maximum signal clarity with zero clutter.

### Dark Theme (Default Console)
- **Page Background**: `#0F0720` to `#150A2E` with an atmospheric soft violet radial glow behind the live status headline (`rgba(139, 92, 246, 0.40)` blurred, fixed).
- **Surfaces**: Surface `#1D1438`, Surface-2 `#261B48`, Subtle overlays `rgba(255, 255, 255, 0.04)`.
- **Borders**: 1px hairline `rgba(255, 255, 255, 0.08)`.
- **Text & Accents**: Text `#F4F0FF`, Muted `#A99BC9`, Primary `#6D4AFF` (interactive pills & active states).
- **Threshold Policy Colors**:
  - Below $0.60$ = **OK** (`#34D6B0` Teal)
  - $0.60$ – $0.85$ = **WARN** (`#FFB347` Amber)
  - Above $0.85$ = **CRITICAL** (`#FF5C7C` Vermillion / Action Zone)
  - Culprit Ring: Warm orange-to-pink gradient (`#FF9A3D` to `#FF4F81`) reserved exclusively for root-cause pulsing emphasis.

### Light Theme (Print / Report Mode)
- **Background**: `#F6F3FF`
- **Surface**: `#FFFFFF` (Surface-2 `#F0EAFB`)
- **Border**: `#E4DCF7`
- **Text & Accents**: Text `#1B1038`, Muted `#5E5380`, Primary `#5B3FE0`, OK `#0E8F76`, WARN `#B86E00`, CRITICAL `#D6254F`.
- Fully WCAG AA contrast compliant for all text and background pairings.

### Typography
- **Display Headlines**: `Sofia Sans Condensed 600` (fallback `Barlow Condensed`), $48$–$56\text{px}$, tight tracking ($-0.02\text{em}$).
- **Section Titles**: $24$–$28\text{px}$.
- **Card Titles**: `Inter 600` at $18\text{px}$.
- **Body & Captions**: `Inter` at $14\text{px}$ / $12\text{px}$.
- **Numbers & Metrics**: `JetBrains Mono` with tabular numerals (`tabular-nums`), used sparingly for high-density telemetry.
- All fonts loaded locally via `@fontsource` packages for $100\%$ offline reproducibility.

### Geometry & Spacing
- 8px base spacing scale; section gaps $64$–$96\text{px}$; card padding $28$–$32\text{px}$.
- Large card radius **28px**, inner tiles **16px**, pills fully rounded.

---

## Layout: One Calm Vertical Flow

Designed at $1440\times900$, the interface delivers **ONE primary focus per screen**, eliminating competing boxes:

1. **Top Slim Strip**: Non-negotiable honesty badge (`SIMULATED DATA - control plane not yet implemented`).
2. **Clean Header**: Geometric logo mark, centered segmented view tabs (`[ Operations | Evaluation ]`), scenario selector, and theme toggle.
3. **Live Status Hero**: Eyebrow label, scenario-driven display headline (max 6 words, `aria-live="polite"`), and one-line subtitle with key facts and timestamp.
4. **Topology Stage & Detail Drawer**:
   - Centered wide card with `aws-us-east` soft container and dashed chips for `gcp-asia` & `azure-eu` ("namespace only, no workloads").
   - Edge telemetry labels hidden by default; revealed with offset pill on hover/selection to eliminate node clipping.
   - Truncated service tabs removed in favor of a full-name keyboard-accessible service list (`productpage`, `details`, `reviews`, `ratings`).
   - Clicking any node shifts the stage and slides in the **400px Detail Drawer**: single risk number (e.g. `0.88`) with $0.60$ and $0.85$ tick bar, 3 large metrics, sparkline, single-sentence diagnosis, and consistency circles ($k$ of 4). Closes with `Esc`.
5. **Module Health**: 4 compact pills in one row (`Telemetry`, `GNN Predictor`, `Control Plane`, `Service Mesh`) with status dots and hover popovers containing strictly verified facts.
6. **Safety Verification (FR-3.3)**: 4 small tiles with one-word verdicts (*Pass*, *Pass*, *Ready*, *Found*) plus verdict pill and expandable policy parameter editor.
7. **Risk Over Time**: Full-width Recharts line chart with $0.60$ Release and $0.85$ Act threshold lines, shaded fault window, and log-scale latency toggle.
8. **Remediation Audit Trail (FR-3.4)**: Full-width 5-column table (*Time*, *Event*, *Service*, *Detail*, *Reason*), clickable jump-to-time rows, and type filters.
9. **Floating Playback Dock**: Centered at bottom of viewport with Play/Pause (`Space`), speed toggle ($1\times, 2\times, 4\times$), time scrubber with fault window & event pins, and time readout. Hidden when `chrome=0`.

---

## Non-Negotiable Honesty Table: Simulated vs. Real

| Component / Feature | Status | Details & Honesty Disclaimers |
| :--- | :--- | :--- |
| **Control Plane Actions** | **Simulated** | Synthetic virtual reroute actions (`reviews` -> `reviews-v1`). Actual Kubernetes Istio Envoy VirtualService mutations are not yet connected to a live cluster. |
| **Simulation Risk Scores** | **Simulated** | Labelled explicitly in UI as *"illustrative risk (not model output)"*. Emulates GNN score dynamics to demo threshold checks and hysteresis. |
| **Simulated Telemetry** | **Simulated** | Seeded PRNG generates stepped Prometheus/Istio quantile buckets (values like 97.5ms, 241ms, 242.5ms) with realistic 15s poll lag (90s ramp up, 75s decay). |
| **Evaluation Benchmark** | **REAL** | **100% Real Empirical Data** from Leave-One-Episode-Out cross-validation across 8 folds, 5 random seeds, comparing GNN against rule baseline. |
| **Multi-Region Workloads** | **Simulated Labels** | `aws-us-east` hosts all 4 active workloads; `gcp-asia` and `azure-eu` are shown honestly as empty namespaces with no deployed workloads. |
| **Replay Mode (Scenario F)** | **Hybrid** | Replays real recorded edge metrics from `public/replay/snapshots.jsonl` and `fault_log.jsonl`; risk assessment and remediation safety checks are simulated on top. |

---

## Reproducible Report Figures

Every view and scenario state can be frozen and exported with pixel precision using URL parameters:

```
http://localhost:5173/?scenario={A|B|C|D|E|F}&t={seconds}&view={overview|evaluation}&theme={dark|light}&chrome={0|1}
```

Setting `chrome=0` freezes playback at time `t`, hides the floating playback dock, and prepares a clean $1440\times900$ stage for screenshots and 2x PNG figure exports.

### Figure Reproduction URLs

| # | Figure Description | Dark Theme URL | Light Theme URL |
| :-: | :--- | :--- | :--- |
| **1** | **Normal Steady State** ($A, t=60\text{s}$) | [A @ 60s (Dark)](http://localhost:5173/?scenario=A&t=60&view=overview&theme=dark&chrome=0) | [A @ 60s (Light)](http://localhost:5173/?scenario=A&t=60&view=overview&theme=light&chrome=0) |
| **2** | **Fault Detected** ($A, t=240\text{s}$) | [A @ 240s (Dark)](http://localhost:5173/?scenario=A&t=240&view=overview&theme=dark&chrome=0) | [A @ 240s (Light)](http://localhost:5173/?scenario=A&t=240&view=overview&theme=light&chrome=0) |
| **3** | **Reroute Applied** ($A, t=330\text{s}$) | [A @ 330s (Dark)](http://localhost:5173/?scenario=A&t=330&view=overview&theme=dark&chrome=0) | [A @ 330s (Light)](http://localhost:5173/?scenario=A&t=330&view=overview&theme=dark&chrome=0) |
| **4** | **Blocked Action (Safety Guardrail)** ($B, t=300\text{s}$) | [B @ 300s (Dark)](http://localhost:5173/?scenario=B&t=300&view=overview&theme=dark&chrome=0) | [B @ 300s (Light)](http://localhost:5173/?scenario=B&t=300&view=overview&theme=dark&chrome=0) |
| **5** | **GNN Down & Fallback Activated** ($D, t=260\text{s}$) | [D @ 260s (Dark)](http://localhost:5173/?scenario=D&t=260&view=overview&theme=dark&chrome=0) | [D @ 260s (Light)](http://localhost:5173/?scenario=D&t=260&view=overview&theme=dark&chrome=0) |
| **6** | **Flapping Suppression & Cooldown** ($E, t=350\text{s}$) | [E @ 350s (Dark)](http://localhost:5173/?scenario=E&t=350&view=overview&theme=dark&chrome=0) | [E @ 350s (Light)](http://localhost:5173/?scenario=E&t=350&view=overview&theme=dark&chrome=0) |
| **7** | **Evaluation Benchmark (8 Folds)** | [Eval (Dark)](http://localhost:5173/?view=evaluation&theme=dark&chrome=0) | [Eval (Light)](http://localhost:5173/?view=evaluation&theme=light&chrome=0) |

To export any component at **2x scale** with the burned-in honesty badge and scenario caption, click the **"Export PNG"** button on the corresponding card.

---

## Quick Start Commands

```bash
# Install dependencies
npm install

# Run local development server
npm run dev

# Run unit tests (determinism, bounds [0,1], time-ordering)
npm test

# Build production bundle
npm run build
```
