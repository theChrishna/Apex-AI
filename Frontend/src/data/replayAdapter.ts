import { AuditEntry, EdgeMetric, NodeId, RiskFrame, SafetyCheckResult, SimulationState, Snapshot } from './types';
import { quantizeToBucket } from './simulatedDataSource';

export interface ReplayFaultLogEntry {
  episode: string;
  node: NodeId;
  delay_ms: number;
  start: number;
  end: number;
}

export interface ReplaySnapshotLine {
  timestamp: string;
  t?: number;
  episode?: string;
  nodes: NodeId[];
  edges: {
    source: NodeId;
    destination: NodeId;
    request_rate: number;
    error_rate: number;
    latency_p95: number;
  }[];
}

export interface ReplayEpisodeMeta {
  episode: string;
  fault: ReplayFaultLogEntry;
  snapshots: { t: number; edges: EdgeMetric[] }[];
  duration: number;
}

export class ReplayAdapter {
  private static cachedEpisodes: Map<string, ReplayEpisodeMeta> | null = null;
  private static checkAttempted = false;

  public static async loadEpisodes(): Promise<Map<string, ReplayEpisodeMeta> | null> {
    if (this.checkAttempted && this.cachedEpisodes !== null) {
      return this.cachedEpisodes;
    }

    try {
      const [faultResp, snapResp] = await Promise.all([
        fetch('/replay/fault_log.jsonl'),
        fetch('/replay/snapshots.jsonl')
      ]);

      if (!faultResp.ok || !snapResp.ok) {
        this.checkAttempted = true;
        this.cachedEpisodes = null;
        return null;
      }

      const faultText = await faultResp.text();
      const snapText = await snapResp.text();

      if (!faultText.trim() || !snapText.trim()) {
        this.checkAttempted = true;
        this.cachedEpisodes = null;
        return null;
      }

      // Parse fault log
      const faultLogs: ReplayFaultLogEntry[] = faultText
        .split('\n')
        .map(l => l.trim())
        .filter(Boolean)
        .map(line => JSON.parse(line));

      // Parse snapshots
      const rawSnapshots: ReplaySnapshotLine[] = snapText
        .split('\n')
        .map(l => l.trim())
        .filter(Boolean)
        .map(line => JSON.parse(line));

      const episodeMap = new Map<string, ReplayEpisodeMeta>();

      for (const fault of faultLogs) {
        const epSnapshots = rawSnapshots
          .filter(s => !s.episode || s.episode === fault.episode)
          .map((s, idx) => ({
            t: typeof s.t === 'number' ? s.t : idx * 15,
            edges: s.edges.map(e => ({
              source: e.source,
              destination: e.destination,
              request_rate: e.request_rate,
              error_rate: e.error_rate,
              latency_p95: quantizeToBucket(e.latency_p95),
            }))
          }));

        episodeMap.set(fault.episode, {
          episode: fault.episode,
          fault,
          snapshots: epSnapshots,
          duration: 600,
        });
      }

      this.checkAttempted = true;
      this.cachedEpisodes = episodeMap.size > 0 ? episodeMap : null;
      return this.cachedEpisodes;
    } catch {
      this.checkAttempted = true;
      this.cachedEpisodes = null;
      return null;
    }
  }

  public static computeReplayState(
    episodeMeta: ReplayEpisodeMeta,
    t: number
  ): SimulationState {
    const boundedT = Math.max(0, Math.min(episodeMeta.duration, t));
    
    // Find closest snapshot
    let currentSnap = episodeMeta.snapshots[0];
    for (const snap of episodeMeta.snapshots) {
      if (snap.t <= boundedT) {
        currentSnap = snap;
      } else {
        break;
      }
    }

    const fault = episodeMeta.fault;
    const isFaultActive = boundedT >= fault.start && boundedT <= fault.end;

    // Simulate risk & remediation on top of real recorded edge metrics
    let ratingsRisk = 0.08;
    let reviewsRisk = 0.11;
    let detailsRisk = 0.07;
    let productpageRisk = 0.09;

    const audit: AuditEntry[] = [];
    let safetyCheck: SafetyCheckResult = {
      evaluatedAt: 0,
      podReadiness: true,
      circularRouteCheck: true,
      cooldownRemaining: 0,
      alternativePathFound: fault.node === "ratings",
      decision: "IDLE",
    };

    if (fault.node === "ratings") {
      if (isFaultActive) {
        ratingsRisk = 0.92;
        reviewsRisk = boundedT < 180 ? 0.54 : 0.15;
      }
      if (boundedT >= fault.start) {
        audit.push({
          id: `rep-1`,
          t: fault.start,
          type: "FAULT_INJECTED",
          node: "ratings",
          detail: `[Recorded Telemetry] Delay +${fault.delay_ms}ms observed at ${fault.node}`,
        });
      }
      if (boundedT >= fault.start + 30) {
        audit.push({
          id: `rep-2`,
          t: fault.start + 30,
          type: "THRESHOLD_CROSSED",
          node: "ratings",
          detail: `Simulated risk model crossed 0.85 threshold`,
        });
      }
      if (boundedT >= 180) {
        audit.push({
          id: `rep-3`,
          t: 180,
          type: "REROUTE_APPLIED",
          node: "reviews",
          detail: `Simulated mitigation: shifted reviews traffic to reviews-v1`,
        });
        safetyCheck = {
          evaluatedAt: 180,
          targetNode: "ratings",
          podReadiness: true,
          circularRouteCheck: true,
          cooldownRemaining: Math.max(0, 180 + 120 - boundedT),
          alternativePathFound: true,
          decision: "PASSED",
          actionTaken: "Shift reviews to reviews-v1",
        };
      }
      if (boundedT >= fault.end) {
        audit.push({
          id: `rep-4`,
          t: fault.end,
          type: "FAULT_INJECTED",
          node: "ratings",
          detail: `Recorded fault window ended`,
        });
      }
      if (boundedT >= fault.end + 75) {
        audit.push({
          id: `rep-5`,
          t: fault.end + 75,
          type: "RECOVERED",
          node: "ratings",
          detail: `Telemetry normalized to baseline`,
        });
      }
    }

    const snapshot: Snapshot = {
      t: boundedT,
      edges: currentSnap ? currentSnap.edges : [
        { source: "productpage", destination: "details", request_rate: 0.35, error_rate: 0.001, latency_p95: 8.5 },
        { source: "productpage", destination: "reviews", request_rate: 0.42, error_rate: 0.002, latency_p95: 42.0 },
        { source: "reviews", destination: "ratings", request_rate: 0.38, error_rate: 0.001, latency_p95: 10.2 },
      ]
    };

    const risk: RiskFrame = {
      t: boundedT,
      risk: {
        ratings: ratingsRisk,
        reviews: reviewsRisk,
        details: detailsRisk,
        productpage: productpageRisk,
      },
      source: "gnn",
    };

    return {
      snapshot,
      risk,
      audit,
      safetyCheck,
      moduleHealth: {
        telemetry: { status: "ok", lastUpdate: "replay stream", note: `Episode: ${fault.episode}` },
        gnnPredictor: { status: "ok", lastUpdate: "active", note: "Simulated on replay" },
        controlPlane: { status: "ok", lastUpdate: "active", note: "Simulated controller" },
        meshIstio: { status: "ok", lastUpdate: "v1.22", note: "Recorded trace replay" },
      },
      activeReroute: boundedT >= 180 && fault.node === "ratings" ? {
        fromEdge: { source: "reviews", destination: "ratings" },
        toTarget: "reviews-v1",
        appliedAt: 180,
      } : undefined
    };
  }
}
