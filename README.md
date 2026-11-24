# Apex-AI (MeshHeal AI)
### Autonomous Multi-Cloud Service Mesh Orchestrator & Self-Healing Control Plane

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyTorch Geometric](https://img.shields.io/badge/PyTorch-Geometric%202.4-EE4C2C.svg)](https://pytorch-geometric.readthedocs.io/)
[![Istio](https://img.shields.io/badge/service__mesh-Istio%201.20+-466BB0.svg)](https://istio.io/)
[![Kubernetes](https://img.shields.io/badge/orchestration-Kubernetes%201.28+-326CE5.svg)](https://kubernetes.io/)
[![React 18](https://img.shields.io/badge/frontend-React%2018%20%2B%20TypeScript-61DAFB.svg)](https://react.dev/)
[![Tests](https://img.shields.io/badge/tests-35%20passed-success.svg)](meshheal_controlplane/tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Apex-AI (MeshHeal AI)** is an autonomous service-mesh control plane designed to detect silent microservice degradation, resolve cascading dependency failures early, and execute zero-downtime traffic rerouting in cloud-native topologies. Built on top of **Istio**, **Prometheus**, and **Graph Neural Networks (GCN / GraphSAGE)**, it delivers closed-loop anomaly detection, culprit isolation, safety-gated traffic shifting, canary probing, and automated release.

---

## Table of Contents

1. [System Overview & Architecture](#-system-overview--architecture)
2. [Key Capabilities](#-key-capabilities)
3. [Control Plane & Safety Loop](#-control-plane--safety-loop)
4. [Empirical Evaluation & Benchmarks](#-empirical-evaluation--benchmarks)
   - [Leave-One-Episode-Out (LOEO) Cross-Validation](#leave-one-episode-out-loeo-cross-validation)
   - [Shadow Run & Soak Analysis](#shadow-run--soak-analysis)
   - [Detection-to-Remediation Timings](#detection-to-remediation-timings)
   - [Live Closed-Loop Demonstrations (Scenarios A & B)](#live-closed-loop-demonstrations-scenarios-a--b)
5. [SRE Operations Console (Frontend v2)](#-sre-operations-console-frontend-v2)
6. [Repository Structure](#-repository-structure)
7. [Getting Started & Runbook](#-getting-started--runbook)
   - [Prerequisites](#prerequisites)
   - [Cluster Deployment & Telemetry](#cluster-deployment--telemetry)
   - [Running the Control Plane](#running-the-control-plane)
   - [Running the SRE Dashboard](#running-the-sre-dashboard)
   - [Running the Test Suite](#running-the-test-suite)
8. [Scientific Candor & Viva Defense Highlights](#-scientific-candor--viva-defense-highlights)
9. [Team & Contributions](#-team--contributions)

---

## 🏛 System Overview & Architecture

Modern cloud-native architectures suffer from **silent cascading failures**: downstream latency degradation or memory pressure in a minor microservice (e.g., `ratings`) saturates connection pools in upstream callers (e.g., `reviews`), causing widespread outages. Conventional monitoring alerts trigger too late and fail to distinguish root-cause culprits from innocent victim services.

**Apex-AI** bridges the gap between deep graph telemetry and automated Kubernetes infrastructure control:

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="figures/fig_d_pipeline_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="figures/fig_d_pipeline_light.png">
    <img alt="MeshHeal Control Plane Pipeline and Probe/Release Loop" src="figures/fig_d_pipeline_dark.png" width="100%">
  </picture>
  <em>Figure 1: Control plane decision pipeline, safety verification gates, and canary probe-and-release lifecycle.</em>
</p>

### End-to-End Architectural Pipeline

```
 [ Istio / Envoy Sidecars ]
            │ (Source-reporter Latency, Error Rates, Request Throughput)
            ▼
   [ Prometheus TSDB ]
            │ (Scraped every 1–2s; sliding-window bucketed p95)
            ▼
 [ Telemetry Aggregator ]  ──► [ snapshots.jsonl ] (Validated: Age < 45s, No NaNs)
            │
            ▼
┌────────────────────────────────────────────────────────┐
│               MeshHeal AI Control Plane                │
│                                                        │
│  ┌──────────────────────┐    ┌──────────────────────┐  │
│  │   Primary Scorer     │    │   Fallback Scorer    │  │
│  │ 5-Seed GNN (GCN/SAGE)│ ──►│   Culprit Rule       │  │
│  │ (500ms SLA Budget)   │    │ (in_lat - out_lat)   │  │
│  └──────────┬───────────┘    └──────────┬───────────┘  │
│             └─────────────┬─────────────┘              │
│                           ▼                            │
│           [ Temporal Persistence Filter ]              │
│               (Risk > 0.85 in 3 of last 4)             │
│                           ▼                            │
│           [ Safety Verification Gates ]                │
│         (Playbook, Pod Ready, No Victim Loops)         │
│                           ▼                            │
│         [ Istio VirtualService JSON Patch ]            │
│         (reviews: 100% v1 traffic shift)               │
│                           ▼                            │
│         [ Active Canary Probe & Release ]              │
│         (70/15/15 canary probe share; Risk < 0.60)     │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
          [ Dynamic Kubernetes API / Istio Mesh ]
```

---

## ⚡ Key Capabilities

- **Zero-Code Mesh Observability**: Telemetry is extracted exclusively at the sidecar level (`reporter="source"`, capturing upstream-applied delays) without adding a single line of instrumentation code to application services.
- **Topological Anomaly Reasoning (GNN)**: Models dependencies as a dynamic directed graph $G = (V, E)$, embedding 6-dimensional feature vectors per node:
  $$\mathbf{x}_v = \left[\log(1 + r_{\text{in}}),\, \log(1 + e_{\text{in}}),\, \log(1 + l_{\text{in}}),\, \log(1 + r_{\text{out}}),\, \log(1 + e_{\text{out}}),\, \log(1 + l_{\text{out}})\right]$$
- **Victim Suppression & Culprit Isolation**: Upstream nodes experiencing elevated latency purely because they are awaiting downstream responses are identified and classified as `SUPPRESSED_VICTIM`, preventing destructive failovers of healthy services.
- **Resilient Dual-Engine Scoring**: GNN scorer executes with an asynchronous 500 ms SLA budget; automatic failover to the deterministic `RuleScorer` ensures uninterrupted cluster protection during GPU starvation or engine faults.
- **Fail-Safe Hysteresis & Canary Re-engagement**: Automated remediation shifts traffic away from the degraded subset, enforces a 120 s cooldown, deploys a 70/15/15 traffic probe (`probe_share: 30%` = ~0.08 req/s evidence minimum), and releases back to baseline (34/33/33) only when risk drops below $0.60$ with active verification.
- **Immutable Audit Trail**: Every scoring pass, blocked attempt, patch execution, probe step, and release event is persisted to `audit_log.jsonl` with full cryptographic traceability.

---

## 🛡 Control Plane & Safety Loop

The control plane (`meshheal_controlplane/controlplane/`) runs an iterative 15-second reconciliation loop engineered around strict SRE safety invariants:

| Phase | Invariant / Rule | Action on Violation |
|---|---|---|
| **1. Ingestion Validation** | Snapshot age $< 45\text{ s}$, complete node vocabulary (`NODE_VOCAB`), no `NaN` | Rejects stale data; retains prior state |
| **2. Scoring & Failover** | GNN inference timeout budget $\le 500\text{ ms}$; kill-file trigger (`gnn.off`) | Falls back to Culprit Rule (`in_lat - out_lat`) |
| **3. Temporal Persistence** | Top-node anomaly score $> 0.85$ in at least 3 of the last 4 cycles ($k=3, N=4$) | Suppresses transient spikes and network jitter |
| **4. Safety Gates** | Remediation playbook entry exists; alternate target pods are `Ready`; caller has no circular dependency | Halts patch; logs `ACTION_BLOCKED` |
| **5. Cooldown & Hysteresis**| 120 s mandatory stabilization window following any traffic patch | Blocks flapping and rapid oscillations |
| **6. Canary Probe & Release**| Active canary probe ($70/15/15$) after cooldown; release requires $\text{Risk} < 0.60$ and $\ge 0.05\text{ req/s}$ | Holds mitigation until real traffic confirms health |

---

## 📊 Empirical Evaluation & Benchmarks

The framework was evaluated across 8 controlled chaos injection episodes on an Istio-enabled microservices topology, comparing the GNN model against a raw p95 latency baseline, a deterministic culprit rule, and a non-graph Multi-Layer Perceptron (MLP) ablation.

### Leave-One-Episode-Out (LOEO) Cross-Validation

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="figures/fig_c_loeo_ap_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="figures/fig_c_loeo_ap_light.png">
    <img alt="Leave-One-Episode-Out Average Precision" src="figures/fig_c_loeo_ap_dark.png" width="100%">
  </picture>
  <em>Figure 2: Distinct-threshold Average Precision (AP) per LOEO fold across detection approaches.</em>
</p>

| Model / Baseline | Distinct-Threshold AP | Trapezoidal AP | Root-Cause Top-1 (RC1) | Policy Wrong-Action Rate |
|---|---|---|---|---|
| **Raw p95 Latency Baseline** | 0.930 | 0.898 | 0.070 | 10.1% |
| **Culprit Rule ($\text{in} - \text{out}$)** | 0.928 | 0.928 | 0.950 | 0.4% |
| **Apex-AI GNN (5-Seed Avg)** | **0.928** | **0.923** | **0.950** | **0.4%** |
| **No-Graph MLP Ablation** | **0.983** | 0.981 | **1.000** | 0.2% |

> **Scientific Insight:** The naive latency baseline yields high AP but fails catastrophically at root-cause identification ($\text{RC1} = 0.070$) because it repeatedly penalizes the upstream victim `reviews`. Crucially, an honest ablation shows the no-graph MLP outperforms the GCN on 4-node topologies ($\text{AP } 0.983$ vs $0.928$), demonstrating that on small diameter graphs, localized feature subtraction dominates graph message passing. The core scientific contribution of Apex-AI is the **closed-loop deployment, safety gating, and autonomous actuation pipeline**.

---

### Shadow Run & Soak Analysis

During a continuous 30-minute shadow run incorporating multiple injected delay profiles (75 ms and 150 ms faults on `ratings`, `details`, and `reviews`):

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="figures/fig_a_shadow_risk_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="figures/fig_a_shadow_risk_dark.png">
    <img alt="Top-node risk tracking across the shadow run" src="figures/fig_a_shadow_risk_dark.png" width="100%">
  </picture>
  <em>Figure 3: Top-node risk trajectories across the shadow run under GNN and Culprit Rule scoring engines.</em>
</p>

- **Decision Accuracy**: 4 out of 4 fault scenarios correctly classified (`REROUTE` for ratings; `ACTION_BLOCKED` for details/reviews due to single-version topologies).
- **False Positive Rate**: **0 false events** triggered across the entire 30-minute soak period.
- **Scorer Concordance**: Identical operational decisions reached between the GNN primary scorer and Rule fallback.

---

### Detection-to-Remediation Timings

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="figures/fig_b_detection_time_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="figures/fig_b_detection_time_light.png">
    <img alt="Detection time per fault and scorer" src="figures/fig_b_detection_time_dark.png" width="100%">
  </picture>
  <em>Figure 4: Seconds elapsed from fault injection to automated controller decision event.</em>
</p>

- Detection time consistently sits between **60 s and 80 s** across all fault types and scorers.
- Timing is strictly dictated by the **temporal persistence policy** (requiring 3 of 4 consecutive 15-second cycles above threshold) rather than inference latency, effectively trading sub-second reaction for zero false alarms.

---

### Live Closed-Loop Demonstrations (Scenarios A & B)

Live verification on a real k3d cluster with injected 150 ms ratings faults demonstrated immediate closed-loop recovery:

| Metric | Scenario A (GNN Primary) | Scenario B (Rule Fallback via Kill-File) |
|---|---|---|
| **Scoring Engine** | 5-Seed Ensemble GNN | Deterministic Culprit Rule |
| **Time to Reroute** | 78.2 s | 63.7 s |
| **Faulted Latency (Median)** | **172 ms** | **182 ms** |
| **Post-Remediation Latency (Median)** | **23 ms** (baseline) | **24 ms** (baseline) |
| **Latency Recovery Velocity** | $< 2.0\text{ s}$ post-patch | $< 2.0\text{ s}$ post-patch |
| **Probe Initiation** | 120 s cooldown | 120 s cooldown |
| **Automated Release** | 174.0 s post fault removal | 174.9 s post fault removal |

---

## 🖥 SRE Operations Console (Frontend v2)

The project includes an operations dashboard engineered with React 18, TypeScript, Tailwind CSS, Cytoscape.js, and Recharts, offering real-time situational awareness and evaluation introspection:

- **Live Dynamic Topology**: Directed graph rendering active traffic rates, p95 latencies, and real-time health borders with root-cause highlighting.
- **Deep Inspection Drawer**: Granular telemetry breakdown for individual microservices, sparkline history, and persistence consistency gauges ($k$ of $N$).
- **Audit Event Stream**: Clickable event ledger linked to time-scrubbed historical state.
- **Dual Visual Modes**: Atmospheric violet dark theme (`#0F0720`) for operational command centers and WCAG AA print-ready light theme.

---

## 📂 Repository Structure

```text
Apex-AI/
├── CLAUDE.md                       # Project technical context & ground rules
├── MeshHeal_AI_PRD.md              # Formal Product Requirements Document
├── demo_up.sh                      # Cluster bootstrap and environment bring-up
│
├── meshheal_controlplane/          # Production-grade Python Control Plane
│   ├── controlplane/
│   │   ├── cluster.py              # Kubernetes & Istio VirtualService JSON patch client
│   │   ├── config.py               # Timeouts, thresholds, probe parameters
│   │   ├── controller.py           # Core reconciliation loop & safety checks
│   │   ├── gnn_adapter.py          # PyTorch Geometric GNN inference wrapper
│   │   ├── scorer.py               # BaseScorer, RuleScorer, ResilientScorer
│   │   └── run.py                  # CLI entrypoint (--replay, --dry-run, live)
│   └── tests/                      # 35 unit & integration tests
│
├── figures/                        # High-resolution benchmark figures (200 dpi)
│   ├── fig_a_shadow_risk_{dark,light}.png
│   ├── fig_b_detection_time_{dark,light}.png
│   ├── fig_c_loeo_ap_{dark,light}.png
│   ├── fig_d_pipeline_{dark,light}.png
│   └── make_figures.py             # Reproducible figure generation script
│
├── models/                         # GNN architecture & training manifests
│   ├── gnn_final_manifest.json     # 5-seed model configuration
│   └── gnn_final_v3_manifest.json
│
├── live_demo/                      # Closed-loop live test harness
│   ├── run_live.py                 # Automated execution script for Scenarios A & B
│   ├── test_patch.py               # Pre-flight Kubernetes patch verification
│   └── result_{A,B}_*.json         # Recorded live trial evidence
│
├── shadow_run/                     # Soak testing harness & recorded telemetry
│   ├── run_schedule.py             # Multi-fault injection schedule
│   └── compare.py                  # Audit log diffing & detection metrics
│
├── Frontend_v2/                    # SRE Observability Dashboard
│   ├── src/                        # React 18, TypeScript, Cytoscape.js
│   ├── api/meshheal_api.py         # FastAPI live/replay streaming service
│   └── package.json
│
└── docs/                           # Engineering notes & defense preparation
    ├── COMMIT_SPLIT.md             # Multi-contributor commit audit
    ├── DEMO_SCRIPT.md              # 8-minute defense & live run script
    ├── REPORT_UPDATE_NOTES.md      # Detailed metrics & v3 ablation analysis
    └── VIVA_QA.md                  # Comprehensive defense Q&A reference
```

---

## 🚀 Getting Started & Runbook

### Prerequisites

- **Docker Desktop** (Kubernetes enabled or k3d installed)
- **Python 3.10+** (with virtual environment `.venv`)
- **kubectl** & **istioctl**
- **Node.js 18+** & **npm**

### Cluster Deployment & Telemetry

```bash
# 1. Start local k3d cluster and load Istio demo profile
k3d cluster create meshheal --agents 2
istioctl install --set profile=demo -y

# 2. Deploy Bookinfo with Istio injection enabled
kubectl create namespace aws-us-east
kubectl label namespace aws-us-east istio-injection=enabled
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.20/samples/bookinfo/platform/kube/bookinfo.yaml -n aws-us-east
kubectl apply -f destinationrule-reviews.yaml -n aws-us-east
kubectl apply -f reviews-normal.yaml -n aws-us-east

# 3. Spin up port-forwards, traffic generator, and telemetry harvester
./demo_up.sh
```

### Running the Control Plane

```bash
# Activate virtual environment
source .venv/bin/activate

# Execute deterministic replay over recorded episode telemetry
python -m controlplane.run --snapshots snapshots.jsonl --replay

# Run in live shadow mode (dry run: scores and logs without modifying cluster)
python -m controlplane.run --snapshots snapshots.jsonl --dry-run

# Run live active control with GNN scoring engine
python -m controlplane.run --snapshots snapshots.jsonl --scorer gnn
```

### Running the SRE Dashboard

```bash
# 1. Start the API streaming daemon (pointing to live demo audit log)
python Frontend_v2/api/meshheal_api.py --mode live --audit "gnn=live_demo/audit_*.jsonl"

# 2. Start Vite development server
cd Frontend_v2
npm install
npm run dev
# Dashboard available at http://localhost:8765
```

### Running the Test Suite

```bash
cd meshheal_controlplane
pytest -v
# 35 passed in under 2 seconds
```

---

## 🎯 Scientific Candor & Viva Defense Highlights

When evaluating Apex-AI for research and defense:

1. **Topology Scale & Graph Inductive Bias**: On a 4-node topology, message-passing neural networks do not statistically outperform a simple multi-layer perceptron with feature subtraction ($\text{MLP AP } 0.983$ vs $\text{GNN AP } 0.928$). The GNN's value proposition emerges in complex, multi-hop mesh graphs where non-local topological correlations cannot be captured by pairwise heuristics.
2. **Detection Velocity vs. Stability**: The 60–80 s remediation response time is an intentional design parameter imposed by the $k=3$ of $N=4$ temporal persistence filter. This eliminates high-frequency routing flapping caused by transient Prometheus metric jitter.
3. **Canary Validation**: The 70/15/15 canary probe guarantees that degraded paths receive sufficient active traffic ($\ge 0.05\text{ req/s}$) to provide statistical confidence before normal routing weights (34/33/33) are restored.
4. **Single-Cluster Regional Emulation**: For the academic scope, multi-cloud regions (`aws-us-east`, `gcp-asia`, `azure-eu`) are simulated via Kubernetes namespaces; cloud-agnostic cross-VPC routing represents the natural production extension.

---

## 👥 Team & Contributions

This project was built as a 5th-Semester Computer Science Systems & AI Engineering Mini-Project:

- **Chrishna Sharma ([@theChrishna](https://github.com/theChrishna))**: Data pipeline, GNN training architectures, synthetic chaos injection, and LOEO evaluation.
- **Varun Solanki ([@watashiwa01](https://github.com/watashiwa01))**: Control plane engineering, Kubernetes/Istio integration, dual-engine resilient scoring, and live closed-loop test harness.
- **Sneha Kumari ([@snehakumari200519](https://github.com/snehakumari200519))**: SRE Operations Console (Frontend v2), Cytoscape topology rendering, figure generation, and empirical reporting.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
