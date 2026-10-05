# Project Requirement Document (PRD): MeshHeal AI
### Autonomous Multi-Cloud Service Mesh Orchestrator
**5th Semester Mini Project — CS**

---

## 1. Problem Statement

In large-scale microservice architectures running across multi-cloud environments (AWS, GCP, Azure), silent network degradation, packet drops, and hidden memory leaks cause cascading system failures that human SREs struggle to diagnose and isolate quickly.

**Key Challenges:**
- **Inter-Domain Complexity:** Connects Software Engineering (microservices), System Design (distributed topologies/service meshes like Istio), Cloud (multi-region VPC peering), and AI (anomaly detection & graph reasoning).
- **High Latency in Incident Response:** Traditional monitoring alerts trigger after a service fails, forcing SREs to manually trace network logs, restart pods, or alter ingress routes while users face downtime.
- **Silent Cascading Outages:** A minor latency spike in a single downstream service can saturate connection pools across dozens of upstream microservices, causing site-wide outages.

---

## 2. Scope Note (Academic Implementation vs. Production Vision)

This PRD is written in two layers, consistent with standard practice for research-oriented mini projects:

- **Production Vision** — the full system as it would exist in a real multi-cloud SRE deployment (kernel-level eBPF telemetry, live AWS/GCP/Azure VPC peering, always-on GNN inference at scale).
- **Semester Implementation** — the scoped, buildable version delivered for this project, which preserves every architectural concept and the full detection-to-remediation pipeline, but substitutes production-grade components with functionally equivalent, verifiable alternatives suited to a single-semester timeline.

The table below maps each layer explicitly so the design intent is never lost, only the implementation depth.

| Layer | Production Vision | Semester Implementation |
|---|---|---|
| Telemetry | Kernel-level eBPF probes (libbpf, kprobes on `tcp_sendmsg`/`tcp_retransmit`) | Istio/Envoy sidecar metrics scraped via Prometheus (RTT, error rate, request duration) |
| Multi-cloud topology | Real AWS/GCP/Azure clusters with VPC peering | Simulated regions via labeled K3d/Minikube namespaces (`region: aws-us-east`, etc.) |
| AI/Graph reasoning | GraphSAGE GNN trained on large-scale production failure logs | Small GraphSAGE/GCN model trained on synthetic labeled data from controlled chaos injection |
| Control plane | Kubernetes Operator with full multi-cluster federation | Kubernetes Operator via `client-go`, single-cluster scope, patching Istio VirtualService/DestinationRule |
| Remediation | Autonomous rerouting across cloud boundaries | Autonomous rerouting across simulated regions within one cluster |
| Visualization | Enterprise observability dashboard | React + Cytoscape.js live topology view, color-coded node health |

This scoping is disclosed upfront in the report and viva so every claim in the FRs below is honestly implementable and defensible.

---

## 3. System Overview & Technology Stack

| Layer | Technology (Semester Build) | Key Responsibility |
|---|---|---|
| Data Plane Telemetry | Istio/Envoy sidecars + Prometheus | Capture per-connection RTT, error rate, retransmission-equivalent signals without kernel instrumentation |
| Telemetry Aggregator | Python (or Go) service | Poll Prometheus, construct sliding-window graph snapshots |
| AI Inference Engine | Python, PyTorch Geometric, NetworkX | GraphSAGE/GCN model for cascade risk scoring |
| Control Plane Integrator | Kubernetes API (client-go), Istio CRDs | Apply dynamic VirtualService and DestinationRule updates |
| Chaos/Test Harness | `tc netem`, Chaos Mesh | Inject controlled latency/packet loss for training data and live demo |
| Visualization Interface | React.js, Cytoscape.js, Tailwind CSS | Render real-time topology, node health, and audit logs |

---

## 4. Functional Requirements (FRs)

### Telemetry & Observation (FR-1)
- **FR-1.1:** Collect per-pod/per-connection latency, error rate, and retry metrics via Istio/Envoy sidecar telemetry, scraped through Prometheus.
- **FR-1.2:** Aggregate metrics into sliding-window graph snapshots at a fixed interval (target: every 1–2 seconds; relaxed from kernel-probe-level sub-second sampling).
- **FR-1.3:** Require zero application source code modification — telemetry is captured entirely at the service mesh (sidecar) layer.

### Topology Graph & AI Prediction (FR-2)
- **FR-2.1:** Dynamically map service dependencies into a directed graph *G = (V, E)*, where nodes *V* represent pods (labeled with a simulated region) and edges *E* represent active request paths between services.
- **FR-2.2:** Update edge feature vectors on each aggregation interval with windowed average latency and error/packet-loss rate.
- **FR-2.3:** Run GNN inference (GraphSAGE/GCN) to assign an anomaly risk score *R ∈ [0, 1]* to every node, trained on labeled normal-vs-anomalous graph snapshots generated via controlled chaos injection.

### Autonomous Remediation & Safety (FR-3)
- **FR-3.1:** Trigger automated traffic mitigation whenever a node's predicted risk score exceeds a calibrated threshold (baseline *R > 0.85*, tuned empirically against validation data — not treated as a fixed constant).
- **FR-3.2:** Generate dynamic Istio VirtualService patches to shed traffic or shift weights away from unhealthy pods toward healthy standby pods (simulating cross-region failover).
- **FR-3.3:** Execute rule-based safety checks before applying any patch: verify target pods are in `Ready` state, prevent circular routing loops, and enforce a cooldown/hysteresis window to prevent remediation flapping if the risk score oscillates near the threshold.
- **FR-3.4 (new):** Maintain a simple audit log of every remediation action taken (timestamp, node, risk score, patch applied) to support rollback and post-hoc review.

### Fallback Behavior (FR-4, new)
- **FR-4.1:** If the GNN inference service is unavailable or has not yet accumulated sufficient graph history (cold start), fall back to a static rule-based threshold on raw latency/error-rate metrics.

---

## 5. Non-Functional Requirements (NFRs)

- **Latency SLA:** Complete the end-to-end detection-to-remediation pipeline in under 2 seconds from anomaly injection to routing change, measured within the simulated single-cluster environment.
- **System Resilience:** If the GNN inference service crashes or is cold-started with insufficient data, the control daemon falls back to rule-based thresholds (FR-4.1) without disrupting active routing.
- **Portability:** Containerize all control services to run on local Kubernetes environments (K3d/Minikube); document the (unimplemented) path to cloud-managed clusters (EKS/GKE) as future work.
- **Explainability:** Every autonomous action must be traceable via the audit log (FR-3.4) — no black-box remediation without a recorded justification (risk score + contributing metrics).

---

## 6. Module Execution Specification

```
┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐
│ Module 1: Envoy/   ├────►│ Module 2: GNN     ├────►│ Module 3: Istio   │
│ Prometheus         │     │ Predictor Daemon  │     │ Mesh Orchestrator │
│ Telemetry Engine   │     │                   │     │                   │
└───────────────────┘     └───────────────────┘     └─────────┬─────────┘
                                                                │
                                                                ▼
                                                      ┌───────────────────┐
                                                      │ Module 4: Live UI │
                                                      │ Topology Monitor  │
                                                      └───────────────────┘
```

- **Module 1 (Telemetry Engine):** Scrapes Envoy sidecar metrics via Prometheus; outputs RTT and error-rate signals per service edge.
- **Module 2 (Graph Inference):** Converts telemetry into PyTorch Geometric `Data` objects; computes per-node risk scores and structural failure propagation paths.
- **Module 3 (Kubernetes Operator):** Uses `client-go` to enforce traffic shifting and circuit breaking via Istio CRDs (`VirtualService`, `DestinationRule`).
- **Module 4 (Observability UI):** Visualizes the living topology graph with color-coded node health (Green: Normal, Orange: At Risk, Red: Degrading) and displays the remediation audit log.

---

## 7. Minimum Viable Product (MVP) Success Criteria

1. **Local Sandbox Test:** Successfully run a 4-microservice test app across 3 simulated regions on a local K3d/Minikube cluster with Istio enabled.
2. **Chaos Simulation:** Inject an artificial 200ms TCP delay (or comparable packet loss) into a deep service dependency using `tc netem` or Chaos Mesh.
3. **Automated Healing:** Demonstrate that MeshHeal AI detects the latency spike before HTTP 500 errors occur and automatically reroutes upstream traffic to a healthy standby pod in under 2 seconds.
4. **Model Validation:** Show the GNN correctly distinguishes injected-anomaly graph states from normal states on a held-out validation set (basic precision/recall reported).
5. **Traceability:** Show the audit log correctly recording the triggering risk score and the resulting remediation action for the demo scenario.

---

## 8. Explicitly Out of Scope (This Semester)

- Real multi-cloud provisioning and cross-cloud VPC peering.
- Kernel-level eBPF instrumentation.
- Production-scale training data or large-scale GNN benchmarking.
- Multi-cluster federation of the Kubernetes Operator.

These are documented as **Future Work** in the final report to preserve the full ambition of the original problem statement while keeping the delivered system honest and fully defensible.
