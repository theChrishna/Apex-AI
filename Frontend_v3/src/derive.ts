import { AuditEvent, NODES, NodeId, NodeStat, State } from "./api";

/** Edge or node p95 at or above this reads as Slow. Same 50 ms as the 0.5 amber level on the service graph (rule score = ms / 100). */
export const SLOW_MS = 50;

export type Health = "Healthy" | "Slow" | "Rerouted" | "Stale" | "No data";
export interface ServiceRow { id: NodeId; health: Health; tone: string; stat?: NodeStat; note: string }

/** Rerouted comes from the audit-derived mesh state, Slow / Healthy from the latest snapshot. Never claims Healthy on old data. */
export function serviceRows(s: State | null): ServiceRow[] {
  return NODES.map((id) => {
    const stat = s?.snapshot?.nodes[id];
    const latency = stat ? [stat.in_rate > 0 ? `in ${stat.in_lat} ms` : "no incoming traffic", stat.out_lat > 0 ? `out ${stat.out_lat} ms` : "", `rule risk ${stat.risk_rule.toFixed(2)}`].filter(Boolean).join(" · ") : "no snapshot";
    const holders = (s?.streams ?? []).filter((st) => s?.mesh[st.name]?.culprits[id]);
    if (s && holders.length) {
      const bits = [holders.map((h) => h.name).join(", ")];
      if (holders.some((h) => s.mesh[h.name].culprits[id] === "PROBING")) bits.push("probing");
      if (holders.some((h) => h.dry_run)) bits.push("dry-run, nothing was changed");
      if (holders.every((h) => h.stale)) bits.push("last known, controller not running");
      return { id, health: "Rerouted", tone: "crit", stat, note: bits.join(" · ") };
    }
    if (!stat) return { id, health: "No data", tone: "", note: latency };
    if (s?.status.snapshot_stale) return { id, health: "Stale", tone: "", stat, note: `${latency} (old snapshot)` };
    if (Math.max(stat.in_lat, stat.out_lat) >= SLOW_MS) return { id, health: "Slow", tone: "warn", stat, note: latency };
    return { id, health: "Healthy", tone: "ok", stat, note: latency };
  });
}

/** Both controllers can be fresh at once (the shadow run ran them side by side). The API then names whichever scored last,
 *  which flips every cycle, so a fresh GNN stream decides what is shown. */
export function scorerInUse(s: State | null) {
  const stream = s?.streams.find((x) => x.name === "gnn" && !x.stale) ?? s?.streams.find((x) => x.name === s.status.scorer_in_use);
  const label = !s ? "…" : !stream ? "None running" : stream.name !== "gnn" ? "Rule" : stream.last_scored?.source === "fallback" ? "Fallback (rule)" : "GNN";
  return { stream, label };
}

/** Decisions the controller took: the events the Incidents stat card counts. */
export const isDecision = (e: AuditEvent) => e.event === "REROUTE" || e.event === "ACTION_BLOCKED";

export const ACTION: Record<string, string> = { SCORED: "FALLBACK SCORING" };
const OUTCOME: Record<string, [string, string]> = {
  REROUTE: ["Rerouted", "crit"], ACTION_BLOCKED: ["Blocked", "warn"], SUPPRESSED_VICTIM: ["Suppressed", "accent"], PROBE_START: ["Probing", "warn"],
  PROBE_FAILED: ["Probe failed", "crit"], RELEASE: ["Released", "ok"], SNAPSHOT_REJECTED: ["Rejected", "crit"],
};
export const outcome = (e: AuditEvent): [string, string] => OUTCOME[e.event] ?? [e.event, ""];

export const scorerLabel = (e: AuditEvent) => (e.stream === "gnn" ? (e.scorer_source === "fallback" ? "rule fallback" : "GNN") : "rule");
