import {
  AuditEntry,
  DataSource,
  EdgeMetric,
  ModuleHealthState,
  NodeId,
  PolicyConfig,
  RiskFrame,
  SafetyCheckResult,
  ScenarioMeta,
  SimulationState,
  Snapshot
} from './types';
import { SCENARIOS } from './scenarios';

// Histogram buckets matching Prometheus/Istio quantile buckets
const HISTOGRAM_BUCKETS = [
  5.0, 7.5, 9.8, 11.2, 12.5, 15.0, 18.0, 22.0, 25.0, 35.0, 38.5, 42.5, 46.0,
  60.0, 75.0, 97.5, 120.0, 145.0, 180.0, 210.0, 241.0, 242.5, 275.0, 320.0
];

export function quantizeToBucket(value: number): number {
  let closest = HISTOGRAM_BUCKETS[0];
  let minDiff = Math.abs(value - closest);
  for (const b of HISTOGRAM_BUCKETS) {
    const diff = Math.abs(value - b);
    if (diff < minDiff) {
      minDiff = diff;
      closest = b;
    }
  }
  return closest;
}

// Seeded PRNG (Mulberry32) for absolute reproducibility
export function createPrng(seed: number = 42) {
  let s = seed >>> 0;
  return function () {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const DEFAULT_POLICY: PolicyConfig = {
  actThreshold: 0.85,
  releaseThreshold: 0.60,
  consecutiveSnapshots: 3,
  cooldownSeconds: 120,
  gnnTimeoutMs: 500,
};

// Smooth ramp function (over duration)
function ramp(t: number, start: number, duration: number): number {
  if (t <= start) return 0;
  if (t >= start + duration) return 1;
  const p = (t - start) / duration;
  return p * p * (3 - 2 * p); // smoothstep
}

// Deterministic state computation for any (scenarioId, t)
export function computeSimulationState(
  scenarioId: string,
  t: number,
  policy: PolicyConfig = DEFAULT_POLICY,
  seed: number = 1337
): SimulationState {
  const boundedT = Math.max(0, Math.min(600, t));
  // Snap to 15s rate-window polling intervals for stepped look
  const pollStep = Math.floor(boundedT / 15) * 15;
  const prng = createPrng(seed + pollStep);

  // Baseline metrics
  // Edges:
  // 1. productpage -> details (normal ~8ms)
  // 2. productpage -> reviews (normal ~38-44ms)
  // 3. reviews -> ratings (normal ~9-11ms)
  let p_det_latency = 8.5 + (prng() * 1.5 - 0.75);
  let p_rev_latency = 42.0 + (prng() * 3.0 - 1.5);
  let r_rat_latency = 10.2 + (prng() * 1.8 - 0.9);

  let p_det_err = 0.001;
  let p_rev_err = 0.002;
  let r_rat_err = 0.001;

  let p_det_rate = 0.34 + (prng() * 0.04 - 0.02);
  let p_rev_rate = 0.42 + (prng() * 0.04 - 0.02);
  let r_rat_rate = 0.38 + (prng() * 0.04 - 0.02);

  let ratingsRisk = 0.08 + prng() * 0.03;
  let reviewsRisk = 0.11 + prng() * 0.03;
  let detailsRisk = 0.07 + prng() * 0.02;
  let productpageRisk = 0.09 + prng() * 0.02;

  let riskSource: "gnn" | "fallback_threshold" = "gnn";
  let activeReroute: SimulationState["activeReroute"] = undefined;

  let safetyCheck: SafetyCheckResult = {
    evaluatedAt: 0,
    podReadiness: true,
    circularRouteCheck: true,
    cooldownRemaining: 0,
    alternativePathFound: true,
    decision: "IDLE",
  };

  const audit: AuditEntry[] = [];

  // SCENARIO IMPLEMENTATIONS
  if (scenarioId === "A") {
    // ratings +200ms: fault at 120, removed at 420. Reroute reviews to reviews-v1 at t=180
    const faultStart = 120;
    const rerouteTime = 180;
    const faultEnd = 420;

    // Latency ramp up (90s) & decay (75s)
    let rampFactor = 0;
    if (boundedT >= faultStart && boundedT < faultEnd) {
      rampFactor = ramp(boundedT, faultStart, 90);
    } else if (boundedT >= faultEnd) {
      rampFactor = 1 - ramp(boundedT, faultEnd, 75);
    }

    const addedDelay = 200 * rampFactor;
    r_rat_latency += addedDelay;

    if (boundedT < rerouteTime) {
      // Before reroute, reviews inherits delay from ratings
      p_rev_latency += addedDelay;
      p_rev_err += 0.04 * rampFactor;
    } else {
      // After reroute applied (reviews-v1 bypasses ratings):
      // productpage->reviews recovers immediately to healthy version latency
      p_rev_latency = 41.5 + (prng() * 2.0 - 1.0);
      // traffic to ratings drops significantly
      r_rat_rate = Math.max(0.01, 0.38 * (1 - ramp(boundedT, rerouteTime, 20)));
      activeReroute = {
        fromEdge: { source: "reviews", destination: "ratings" },
        toTarget: "reviews-v1",
        appliedAt: rerouteTime,
      };
    }

    // Risk modeling (culprit vs victim)
    if (boundedT >= faultStart && boundedT < faultEnd + 75) {
      const riskRamp = rampFactor;
      ratingsRisk = Math.min(0.96, 0.08 + riskRamp * 0.86 + (prng() * 0.02 - 0.01));
      // reviews is victim (direct caller)
      reviewsRisk = boundedT < rerouteTime
        ? Math.min(0.62, 0.11 + riskRamp * 0.45)
        : Math.max(0.12, 0.55 * (1 - ramp(boundedT, rerouteTime, 30)));
      productpageRisk = Math.min(0.25, 0.09 + riskRamp * 0.14);
    }

    // Audit logs
    if (boundedT >= 120) {
      audit.push({
        id: "a-1",
        t: 120,
        type: "FAULT_INJECTED",
        node: "ratings",
        detail: "Injected artificial latency fault (+200ms) on ratings-v1 container",
      });
    }
    if (boundedT >= 150) {
      audit.push({
        id: "a-2",
        t: 150,
        type: "THRESHOLD_CROSSED",
        node: "ratings",
        detail: "Illustrative risk crossed act threshold 0.85 (ratings p95=145.0ms)",
      });
    }
    if (boundedT >= 180) {
      audit.push({
        id: "a-3",
        t: 180,
        type: "REROUTE_APPLIED",
        node: "reviews",
        detail: "Shifted 100% reviews traffic to reviews-v1 (bypasses ratings)",
      });
    }
    if (boundedT >= 420) {
      audit.push({
        id: "a-4",
        t: 420,
        type: "FAULT_INJECTED",
        node: "ratings",
        detail: "Fault injection terminated at t=420s; starting 75s telemetry rate-window drain",
      });
    }
    if (boundedT >= 495) {
      audit.push({
        id: "a-5",
        t: 495,
        type: "RECOVERED",
        node: "ratings",
        detail: "Ratings p95 latency returned to baseline (9.8ms); reviews route normalized",
      });
    }

    // Safety check state
    if (boundedT >= 180 && boundedT < 300) {
      const cooldownRemaining = Math.max(0, 180 + policy.cooldownSeconds - boundedT);
      safetyCheck = {
        evaluatedAt: 180,
        targetNode: "ratings",
        podReadiness: true,
        circularRouteCheck: true,
        cooldownRemaining,
        alternativePathFound: true,
        decision: "PASSED",
        actionTaken: "Shift reviews traffic to reviews-v1",
      };
    } else if (boundedT >= 300) {
      safetyCheck = {
        evaluatedAt: 180,
        targetNode: "ratings",
        podReadiness: true,
        circularRouteCheck: true,
        cooldownRemaining: 0,
        alternativePathFound: true,
        decision: "PASSED",
        actionTaken: "Shift reviews traffic to reviews-v1",
      };
    }
  } else if (scenarioId === "B") {
    // details +100ms: blocked (no_healthy_alternative)
    const faultStart = 120;
    const faultEnd = 420;
    let rampFactor = 0;
    if (boundedT >= faultStart && boundedT < faultEnd) {
      rampFactor = ramp(boundedT, faultStart, 90);
    } else if (boundedT >= faultEnd) {
      rampFactor = 1 - ramp(boundedT, faultEnd, 75);
    }

    p_det_latency += 100 * rampFactor;
    p_det_err += 0.05 * rampFactor;

    if (boundedT >= faultStart && boundedT < faultEnd + 75) {
      detailsRisk = Math.min(0.94, 0.07 + rampFactor * 0.85 + (prng() * 0.02 - 0.01));
      productpageRisk = Math.min(0.38, 0.09 + rampFactor * 0.28);
    }

    if (boundedT >= 120) {
      audit.push({
        id: "b-1",
        t: 120,
        type: "FAULT_INJECTED",
        node: "details",
        detail: "Injected artificial latency fault (+100ms) on details-v1",
      });
    }
    if (boundedT >= 150) {
      audit.push({
        id: "b-2",
        t: 150,
        type: "THRESHOLD_CROSSED",
        node: "details",
        detail: "Illustrative risk crossed act threshold 0.85 (details p95=85.0ms)",
      });
    }
    if (boundedT >= 180) {
      audit.push({
        id: "b-3",
        t: 180,
        type: "ACTION_BLOCKED",
        node: "details",
        detail: "Reroute action suppressed by safety policy: details has no replica path",
        reason: "no_healthy_alternative",
      });
    }
    if (boundedT >= 420) {
      audit.push({
        id: "b-4",
        t: 420,
        type: "FAULT_INJECTED",
        node: "details",
        detail: "Fault injection cleared; latency window draining",
      });
    }
    if (boundedT >= 495) {
      audit.push({
        id: "b-5",
        t: 495,
        type: "RECOVERED",
        node: "details",
        detail: "Details latency restored to baseline 8.2ms",
      });
    }

    if (boundedT >= 180) {
      safetyCheck = {
        evaluatedAt: 180,
        targetNode: "details",
        podReadiness: true,
        circularRouteCheck: true,
        cooldownRemaining: 0,
        alternativePathFound: false, // blocked!
        decision: "BLOCKED",
        blockReason: "no_healthy_alternative",
      };
    }
  } else if (scenarioId === "C") {
    // reviews +200ms: cascade. productpage affected too. Culprit ranked first; blocked.
    const faultStart = 120;
    const faultEnd = 420;
    let rampFactor = 0;
    if (boundedT >= faultStart && boundedT < faultEnd) {
      rampFactor = ramp(boundedT, faultStart, 90);
    } else if (boundedT >= faultEnd) {
      rampFactor = 1 - ramp(boundedT, faultEnd, 75);
    }

    // reviews internal delay: productpage->reviews increases, but reviews->ratings is NORMAL!
    p_rev_latency += 200 * rampFactor;
    // reviews->ratings stays normal ~10ms (shows reviews is the culprit, not ratings!)
    p_rev_err += 0.03 * rampFactor;

    if (boundedT >= faultStart && boundedT < faultEnd + 75) {
      reviewsRisk = Math.min(0.95, 0.11 + rampFactor * 0.82 + (prng() * 0.02 - 0.01));
      productpageRisk = Math.min(0.52, 0.09 + rampFactor * 0.41);
      ratingsRisk = 0.08 + prng() * 0.02; // ratings is unaffected!
    }

    if (boundedT >= 120) {
      audit.push({
        id: "c-1",
        t: 120,
        type: "FAULT_INJECTED",
        node: "reviews",
        detail: "Injected internal compute bottleneck (+200ms) on reviews service",
      });
    }
    if (boundedT >= 150) {
      audit.push({
        id: "c-2",
        t: 150,
        type: "THRESHOLD_CROSSED",
        node: "reviews",
        detail: "Illustrative risk crossed act threshold 0.85 (reviews p95=185.0ms)",
      });
    }
    if (boundedT >= 180) {
      audit.push({
        id: "c-3",
        t: 180,
        type: "ACTION_BLOCKED",
        node: "reviews",
        detail: "Remediation blocked: reviews has no available healthy alternative pathway",
        reason: "no_healthy_alternative",
      });
    }
    if (boundedT >= 420) {
      audit.push({
        id: "c-4",
        t: 420,
        type: "FAULT_INJECTED",
        node: "reviews",
        detail: "Fault injection cleared",
      });
    }
    if (boundedT >= 495) {
      audit.push({
        id: "c-5",
        t: 495,
        type: "RECOVERED",
        node: "reviews",
        detail: "Reviews p95 latency recovered to baseline 38.5ms",
      });
    }

    if (boundedT >= 180) {
      safetyCheck = {
        evaluatedAt: 180,
        targetNode: "reviews",
        podReadiness: true,
        circularRouteCheck: true,
        cooldownRemaining: 0,
        alternativePathFound: false,
        decision: "BLOCKED",
        blockReason: "no_healthy_alternative",
      };
    }
  } else if (scenarioId === "D") {
    // GNN down mid-run at t=200s. Fallback activated. Fault at t=240s.
    const gnnFailTime = 200;
    const faultStart = 240;
    const faultEnd = 480;

    if (boundedT >= gnnFailTime) {
      riskSource = "fallback_threshold";
    }

    let rampFactor = 0;
    if (boundedT >= faultStart && boundedT < faultEnd) {
      rampFactor = ramp(boundedT, faultStart, 90);
    } else if (boundedT >= faultEnd) {
      rampFactor = 1 - ramp(boundedT, faultEnd, 75);
    }

    r_rat_latency += 200 * rampFactor;
    p_rev_latency += 200 * rampFactor;

    if (boundedT < gnnFailTime) {
      ratingsRisk = 0.08 + prng() * 0.02;
      reviewsRisk = 0.11 + prng() * 0.02;
    } else {
      // In fallback mode, risk is computed via static latency threshold:
      // ratings incoming p95 / 220
      ratingsRisk = Math.min(0.92, Math.max(0.08, r_rat_latency / 220));
      reviewsRisk = Math.min(0.65, Math.max(0.11, p_rev_latency / 350));
    }

    if (boundedT >= 200) {
      audit.push({
        id: "d-1",
        t: 200,
        type: "FALLBACK_ACTIVATED",
        detail: "GNN predictor inference timeout exceeded 500ms; engaged static threshold fallback (FR-4.1)",
      });
    }
    if (boundedT >= 240) {
      audit.push({
        id: "d-2",
        t: 240,
        type: "FAULT_INJECTED",
        node: "ratings",
        detail: "Injected latency fault (+200ms) on ratings while GNN is offline",
      });
    }
    if (boundedT >= 285) {
      audit.push({
        id: "d-3",
        t: 285,
        type: "THRESHOLD_CROSSED",
        node: "ratings",
        detail: "Static rule threshold triggered by incoming p95 > 150ms",
      });
    }
    if (boundedT >= 315) {
      audit.push({
        id: "d-4",
        t: 315,
        type: "REROUTE_APPLIED",
        node: "reviews",
        detail: "Fallback rule applied: shifted reviews traffic to reviews-v1",
      });
      activeReroute = {
        fromEdge: { source: "reviews", destination: "ratings" },
        toTarget: "reviews-v1",
        appliedAt: 315,
      };
    }
    if (boundedT >= 480) {
      audit.push({
        id: "d-5",
        t: 480,
        type: "FAULT_INJECTED",
        node: "ratings",
        detail: "Fault injection cleared",
      });
    }
    if (boundedT >= 540) {
      audit.push({
        id: "d-6",
        t: 540,
        type: "RECOVERED",
        node: "ratings",
        detail: "Ratings latency returned below static threshold",
      });
    }

    if (boundedT >= 315) {
      safetyCheck = {
        evaluatedAt: 315,
        targetNode: "ratings",
        podReadiness: true,
        circularRouteCheck: true,
        cooldownRemaining: Math.max(0, 315 + policy.cooldownSeconds - boundedT),
        alternativePathFound: true,
        decision: "PASSED",
        actionTaken: "Shift reviews traffic to reviews-v1 (fallback)",
      };
    }
  } else if (scenarioId === "E") {
    // flapping near threshold (0.85): cooldown and hysteresis produce one action + several ACTION_BLOCKED (cooldown)
    const initialActionTime = 165;
    const cooldownDuration = policy.cooldownSeconds; // 120s => ends at 285s

    // Jitter around 0.85: base curve that oscillates between 0.81 and 0.89
    const oscillation = Math.sin(boundedT / 12) * 0.06;
    if (boundedT >= 120 && boundedT <= 400) {
      ratingsRisk = Math.min(0.92, Math.max(0.80, 0.85 + oscillation + (prng() * 0.02 - 0.01)));
      r_rat_latency = 180 + oscillation * 100;
      reviewsRisk = 0.50 + oscillation * 0.04;
      p_rev_latency = 190 + oscillation * 80;
    } else if (boundedT > 400) {
      const recFactor = ramp(boundedT, 400, 60);
      ratingsRisk = Math.max(0.08, 0.85 * (1 - recFactor));
      r_rat_latency = 10.2;
    }

    if (boundedT >= 120) {
      audit.push({
        id: "e-1",
        t: 120,
        type: "FAULT_INJECTED",
        node: "ratings",
        detail: "Injected oscillatory jitter disturbance near 0.85 threshold",
      });
    }
    if (boundedT >= 150) {
      audit.push({
        id: "e-2",
        t: 150,
        type: "THRESHOLD_CROSSED",
        node: "ratings",
        detail: "Initial threshold breach (risk=0.87 > 0.85) in 3 consecutive snapshots",
      });
    }
    if (boundedT >= initialActionTime) {
      audit.push({
        id: "e-3",
        t: initialActionTime,
        type: "REROUTE_APPLIED",
        node: "reviews",
        detail: "Initial remediation applied: shifted reviews to reviews-v1; 120s cooldown armed",
      });
      activeReroute = {
        fromEdge: { source: "reviews", destination: "ratings" },
        toTarget: "reviews-v1",
        appliedAt: initialActionTime,
      };
    }
    if (boundedT >= 210) {
      audit.push({
        id: "e-4",
        t: 210,
        type: "ACTION_BLOCKED",
        node: "ratings",
        detail: "Suppressed flapping: cooldown in effect (75s remaining)",
        reason: "cooldown",
      });
    }
    if (boundedT >= 255) {
      audit.push({
        id: "e-5",
        t: 255,
        type: "ACTION_BLOCKED",
        node: "ratings",
        detail: "Suppressed flapping: cooldown in effect (30s remaining)",
        reason: "cooldown",
      });
    }
    if (boundedT >= 400) {
      audit.push({
        id: "e-6",
        t: 400,
        type: "FAULT_INJECTED",
        node: "ratings",
        detail: "Disturbance generator halted; stabilizing",
      });
    }
    if (boundedT >= 460) {
      audit.push({
        id: "e-7",
        t: 460,
        type: "RECOVERED",
        node: "ratings",
        detail: "All edge latencies returned within steady-state limits",
      });
    }

    if (boundedT >= initialActionTime) {
      const cooldownRemaining = Math.max(0, initialActionTime + cooldownDuration - boundedT);
      if (cooldownRemaining > 0) {
        safetyCheck = {
          evaluatedAt: boundedT < 210 ? initialActionTime : boundedT < 255 ? 210 : 255,
          targetNode: "ratings",
          podReadiness: true,
          circularRouteCheck: true,
          cooldownRemaining,
          alternativePathFound: true,
          decision: boundedT === initialActionTime ? "PASSED" : "BLOCKED",
          blockReason: boundedT > initialActionTime ? "cooldown" : undefined,
          actionTaken: boundedT === initialActionTime ? "Shift reviews to reviews-v1" : undefined,
        };
      } else {
        safetyCheck = {
          evaluatedAt: 285,
          targetNode: "ratings",
          podReadiness: true,
          circularRouteCheck: true,
          cooldownRemaining: 0,
          alternativePathFound: true,
          decision: "IDLE",
        };
      }
    }
  }

  // Ensure risk strictly stays in [0, 1]
  const clamp01 = (v: number) => Math.max(0, Math.min(1, Number(v.toFixed(4))));

  const risk: RiskFrame = {
    t: boundedT,
    risk: {
      ratings: clamp01(ratingsRisk),
      reviews: clamp01(reviewsRisk),
      details: clamp01(detailsRisk),
      productpage: clamp01(productpageRisk),
    },
    source: riskSource,
  };

  // Module health strip state
  const isGnnDown = scenarioId === "D" && boundedT >= 200;
  const pollTimeStr = `t-${boundedT % 15}s`;
  const moduleHealth: ModuleHealthState = {
    telemetry: {
      status: "ok",
      lastUpdate: pollTimeStr,
      note: "15s poll • 1m rate window",
    },
    gnnPredictor: {
      status: isGnnDown ? "down" : "ok",
      lastUpdate: isGnnDown ? "t=200s" : "48ms avg",
      note: isGnnDown ? "Timeout >500ms; fallback active" : "500ms timeout budget",
    },
    controlPlane: {
      status: "ok",
      lastUpdate: "synced",
      note: "Simulated controller",
    },
    meshIstio: {
      status: "ok",
      lastUpdate: "v1.22",
      note: "3 active virtualservices",
    },
  };

  // Stepped histogram quantization for p95
  const snapshot: Snapshot = {
    t: boundedT,
    edges: [
      {
        source: "productpage",
        destination: "details",
        request_rate: Number(p_det_rate.toFixed(3)),
        error_rate: Number(Math.min(1, Math.max(0, p_det_err)).toFixed(4)),
        latency_p95: quantizeToBucket(p_det_latency),
      },
      {
        source: "productpage",
        destination: "reviews",
        request_rate: Number(p_rev_rate.toFixed(3)),
        error_rate: Number(Math.min(1, Math.max(0, p_rev_err)).toFixed(4)),
        latency_p95: quantizeToBucket(p_rev_latency),
      },
      {
        source: "reviews",
        destination: "ratings",
        request_rate: Number(r_rat_rate.toFixed(3)),
        error_rate: Number(Math.min(1, Math.max(0, r_rat_err)).toFixed(4)),
        latency_p95: quantizeToBucket(r_rat_latency),
      },
    ],
  };

  return {
    snapshot,
    risk,
    audit,
    safetyCheck,
    moduleHealth,
    activeReroute,
  };
}

export class SimulatedDataSource implements DataSource {
  private currentT: number = 0;
  private currentScenarioId: string = "A";
  private subscribers: Set<(data: SimulationState) => void> = new Set();
  private policy: PolicyConfig = { ...DEFAULT_POLICY };
  private seed: number = 1337;

  constructor(initialScenario: string = "A") {
    this.currentScenarioId = initialScenario;
  }

  public subscribe(cb: (data: SimulationState) => void): () => void {
    this.subscribers.add(cb);
    // Dispatch immediately
    cb(this.getCurrentState());
    return () => {
      this.subscribers.delete(cb);
    };
  }

  public seek(t: number): void {
    this.currentT = Math.max(0, Math.min(600, t));
    this.notify();
  }

  public setScenario(scenarioId: string): void {
    this.currentScenarioId = scenarioId;
    this.notify();
  }

  public getScenarioId(): string {
    return this.currentScenarioId;
  }

  public getCurrentTime(): number {
    return this.currentT;
  }

  public scenarios(): ScenarioMeta[] {
    return SCENARIOS;
  }

  public updatePolicy(config: Partial<PolicyConfig>): void {
    this.policy = { ...this.policy, ...config };
    this.notify();
  }

  public getPolicy(): PolicyConfig {
    return { ...this.policy };
  }

  public getCurrentState(): SimulationState {
    return computeSimulationState(
      this.currentScenarioId,
      this.currentT,
      this.policy,
      this.seed
    );
  }

  private notify(): void {
    const state = this.getCurrentState();
    this.subscribers.forEach((cb) => cb(state));
  }
}
