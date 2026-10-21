# MeshHeal AI: Autonomous Service-Mesh Remediation Prototype

A frontend-only SRE operations console dashboard for **MeshHeal AI**, designed for academic evaluation, project reports, and interactive demonstrations. All telemetry in the simulation engine is generated deterministically in-browser using a seeded PRNG (with optional replay of recorded episode telemetry from Istio Envoy access logs).

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

## Tech Stack

- **Framework**: Vite + React 18 + TypeScript
- **Styling**: Tailwind CSS with custom CSS variables for high-contrast SRE Console (Dark) and WCAG AA Print (Light)
- **Topology**: Cytoscape.js with compound region nodes, color-blind safe risk ramps, animated dashed edge flows, and multi-cue status symbols
- **Charts**: Recharts (Risk score trajectories, log-scale p95 edge latency, grouped bar charts with standard deviation error bars)
- **State**: Zustand with continuous time scrubbing, playback speed control, and URL query parameter synchronization
- **Typography**: `@fontsource/inter` (UI) and `@fontsource/jetbrains-mono` (numbers/metrics) for full offline reproducibility
- **Export**: `html-to-image` for high-resolution 2x PNG figures with burned-in non-negotiable honesty badges

---

## Quick Start

### 1. Install Dependencies
```bash
npm install
```

### 2. Run Local Development Server
```bash
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

### 3. Run Test Suite
```bash
npm test
```
Runs the 3 deterministic scenario engine unit tests with Vitest:
1. Scenario engine determinism for fixed seeds
2. Risk score bound verification (`0 <= risk <= 1`)
3. Audit log time-ordering verification (`t_i >= t_{i-1}`)

### 4. Build Production Bundle
```bash
npm run build
```

---

## Reproducible Report Figures

Every view and scenario state can be frozen and exported with pixel precision using URL parameters:

```
?scenario={A|B|C|D|E|F}&t={seconds}&view={overview|evaluation}&theme={dark|light}&chrome={0|1}
```
Setting `chrome=0` freezes playback at time `t`, hides UI player controls, and prepares a clean 1440x900 layout ready for report figures.

### Report Figure URLs

| # | Figure Description | Dark Console Theme URL | Light Print Theme URL |
| :-: | :--- | :--- | :--- |
| **1** | **Normal Steady State** (A, t=60s) | [A @ 60s (Dark)](http://localhost:5173/?scenario=A&t=60&view=overview&theme=dark&chrome=0) | [A @ 60s (Light)](http://localhost:5173/?scenario=A&t=60&view=overview&theme=light&chrome=0) |
| **2** | **Fault Detected** (A, t=240s) | [A @ 240s (Dark)](http://localhost:5173/?scenario=A&t=240&view=overview&theme=dark&chrome=0) | [A @ 240s (Light)](http://localhost:5173/?scenario=A&t=240&view=overview&theme=light&chrome=0) |
| **3** | **Reroute Applied** (A, t=330s) | [A @ 330s (Dark)](http://localhost:5173/?scenario=A&t=330&view=overview&theme=dark&chrome=0) | [A @ 330s (Light)](http://localhost:5173/?scenario=A&t=330&view=overview&theme=light&chrome=0) |
| **4** | **Blocked Action (Safety Guardrail)** (B, t=300s) | [B @ 300s (Dark)](http://localhost:5173/?scenario=B&t=300&view=overview&theme=dark&chrome=0) | [B @ 300s (Light)](http://localhost:5173/?scenario=B&t=300&view=overview&theme=light&chrome=0) |
| **5** | **GNN Down & Fallback Activated** (D, t=260s) | [D @ 260s (Dark)](http://localhost:5173/?scenario=D&t=260&view=overview&theme=dark&chrome=0) | [D @ 260s (Light)](http://localhost:5173/?scenario=D&t=260&view=overview&theme=light&chrome=0) |
| **6** | **Flapping Suppression & Cooldown** (E, t=350s) | [E @ 350s (Dark)](http://localhost:5173/?scenario=E&t=350&view=overview&theme=dark&chrome=0) | [E @ 350s (Light)](http://localhost:5173/?scenario=E&t=350&view=overview&theme=light&chrome=0) |
| **7** | **Evaluation Benchmark (8 Folds)** | [Eval (Dark)](http://localhost:5173/?view=evaluation&theme=dark&chrome=0) | [Eval (Light)](http://localhost:5173/?view=evaluation&theme=light&chrome=0) |

### How to Take Each Figure
1. Open the desired URL above in a browser window sized at 1440x900.
2. Click the **"Export PNG"** or **"Export Report Figure (PNG)"** button on the relevant card (Topology, Risk Timeline, Audit Log, or Evaluation Tab).
3. The image is downloaded at **2x scale** with the persistent honesty badge burned into the top banner alongside the scenario title and timestamp caption.

---

## Implemented Scenarios

- **Scenario A**: `"ratings +200ms: reroute applied"`
  Fault injected at $t=120\text{s}$. Latency ramps up over 90s. Ratings risk breaches $0.85$ threshold in 3 of 4 snapshots. Safety checks pass and shift reviews traffic to `reviews-v1` at $t=180\text{s}$. Fault cleared at $t=420\text{s}$; recovered at $t=495\text{s}$.
- **Scenario B**: `"details +100ms: blocked"`
  Details latency increases. Safety checks evaluate pod readiness, circular route, cooldown, and alternative paths. Action is safely `BLOCKED` with reason `no_healthy_alternative`.
- **Scenario C**: `"reviews +200ms: cascade"`
  Reviews internal bottleneck causes productpage delay to rise while reviews-to-ratings stays baseline. Culprit analysis correctly tags reviews as root-cause ($0.94$) and productpage as victim ($0.52$). Blocked due to `no_healthy_alternative`.
- **Scenario D**: `"GNN down mid-run"`
  GNN predictor times out at $t=200\text{s}$ ($>500\text{ms}$). Full-width amber banner triggers and GNN chip turns red. Fallback rule takes over static thresholds (FR-4.1).
- **Scenario E**: `"flapping near threshold"`
  Risk oscillates around $0.85$. Initial action is permitted, arming a 120s cooldown. Subsequent threshold crosses are safely suppressed as `ACTION_BLOCKED` (`cooldown`), preventing control loop thrashing.
- **Scenario F**: `"Replay recorded episode"`
  Loads real telemetry lines from `public/replay/snapshots.jsonl` and `fault_log.jsonl`, rendering recorded edge metrics with simulated autonomous diagnosis on top.

---

## Accessibility & Design Compliance

- **No Color-Only Cues**: Nodes and health chips pair color ramps (Teal / Amber / Vermillion) with numeric values and icons (`● OK`, `▲ WARN`, `✖ CRIT`, `⚡ CULPRIT`).
- **Tabular Figures**: All metrics and numbers use `JetBrains Mono` with `tabular-nums` alignment to prevent layout shifts.
- **Motion Reduction**: `prefers-reduced-motion` media query disables edge animations; pausing simulation halts all micro-animations.
- **Keyboard Navigation**: Timeline scrubber, scenario selector, and audit table rows are fully focusable and keyboard navigable (`Space` to toggle playback, `Left/Right` arrow keys to scrub time).
