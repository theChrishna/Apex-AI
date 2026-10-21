export type NodeId = "productpage" | "details" | "reviews" | "ratings";
export type Region = "aws-us-east" | "gcp-asia" | "azure-eu";

export interface EdgeMetric {
  source: NodeId;
  destination: NodeId;
  request_rate: number; // req/s, about 0.2-0.5
  error_rate: number;   // 0.0 - 1.0
  latency_p95: number;  // ms
}

export interface Snapshot {
  t: number; // seconds from scenario start (0-600)
  edges: EdgeMetric[];
}

export interface RiskFrame {
  t: number;
  risk: Record<NodeId, number>;
  source: "gnn" | "fallback_threshold";
}

export type AuditType =
  | "FAULT_INJECTED"
  | "THRESHOLD_CROSSED"
  | "REROUTE_APPLIED"
  | "ACTION_BLOCKED"
  | "FALLBACK_ACTIVATED"
  | "RECOVERED";

export type BlockReason =
  | "cooldown"
  | "circular_route"
  | "target_not_ready"
  | "no_healthy_alternative";

export interface AuditEntry {
  id?: string;
  t: number;
  type: AuditType;
  node?: NodeId;
  detail: string;
  reason?: BlockReason;
}

export interface ScenarioMeta {
  id: string;
  name: string;
  description: string;
  duration: number; // 600s
  faultWindow?: {
    start: number;
    end: number;
    node: NodeId;
    description: string;
  };
  isReplay?: boolean;
}

export interface PolicyConfig {
  actThreshold: number; // default 0.85
  releaseThreshold: number; // default 0.60
  consecutiveSnapshots: number; // default 3 (out of last 4)
  cooldownSeconds: number; // default 120
  gnnTimeoutMs: number; // default 500
}

export interface SafetyCheckResult {
  evaluatedAt: number;
  targetNode?: NodeId;
  podReadiness: boolean;
  circularRouteCheck: boolean;
  cooldownRemaining: number;
  alternativePathFound: boolean;
  decision: "PASSED" | "BLOCKED" | "IDLE";
  blockReason?: BlockReason;
  actionTaken?: string;
}

export type ModuleStatus = "ok" | "degraded" | "down";

export interface ModuleHealthState {
  telemetry: { status: ModuleStatus; lastUpdate: string; note: string };
  gnnPredictor: { status: ModuleStatus; lastUpdate: string; note: string };
  controlPlane: { status: ModuleStatus; lastUpdate: string; note: string };
  meshIstio: { status: ModuleStatus; lastUpdate: string; note: string };
}

export interface SimulationState {
  snapshot: Snapshot;
  risk: RiskFrame;
  audit: AuditEntry[];
  safetyCheck: SafetyCheckResult;
  moduleHealth: ModuleHealthState;
  activeReroute?: {
    fromEdge: { source: NodeId; destination: NodeId };
    toTarget: string; // "reviews-v1"
    appliedAt: number;
  };
}

export interface DataSource {
  subscribe(cb: (data: SimulationState) => void): () => void;
  seek(t: number): void;
  scenarios(): ScenarioMeta[];
  setScenario(scenarioId: string): void;
  getCurrentState(): SimulationState;
  updatePolicy?(config: Partial<PolicyConfig>): void;
}
