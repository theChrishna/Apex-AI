import { useCallback, useEffect, useRef, useState } from "react";

export type NodeId = "productpage" | "details" | "reviews" | "ratings";
export const NODES: NodeId[] = ["productpage", "details", "reviews", "ratings"];

export interface NodeStat { risk_rule: number; in_lat: number; out_lat: number; in_rate: number; in_err: number }
export interface Edge { source: NodeId; destination: NodeId; request_rate: number; error_rate: number; latency_p95: number }
export interface SnapshotView { ts: string; edges: Edge[]; valid: boolean; reject_reason: string | null; nodes: Partial<Record<NodeId, NodeStat>> }
export interface AuditEvent {
  ts: string; event: string; stream: string; node?: string; culprit?: string; risk?: number; reason?: string; why?: string;
  virtual_service?: string; weights?: Record<string, number>; dry_run?: boolean; scorer_source?: string | null; scorer_note?: string | null;
  top?: string; source?: string; note?: string; age_s?: number;
}
export interface Stream {
  name: string; path: string; age_s: number | null; stale: boolean; fallback_scored: number; scored_total: number; dry_run?: boolean;
  last_scored: { ts: string; top: string; risk: number; source: string; note?: string } | null;
}
export interface MeshState { state: "NORMAL" | "REROUTED" | "PROBING"; culprits: Record<string, string> }
export interface State {
  mode: "LIVE" | "REPLAY"; label: string; now: string; wall_now: string;
  replay: { speed: number; start: string; end: string; pos: string } | null;
  status: { snapshot_age_s: number | null; snapshot_stale: boolean; scorer_in_use: string | null; scorer_source: string | null; controller_running: boolean; note: string | null };
  snapshot: SnapshotView | null; series: { ts: string; risk: Partial<Record<NodeId, number>> }[];
  mesh: Record<string, MeshState>; streams: Stream[]; events: AuditEvent[]; import_error: string | null;
}
export interface MdTable { heading: string; header: string[]; rows: string[][] }
export type Evaluation = Record<string, { file: string; tables: MdTable[]; missing: boolean }>;

/** Poll a JSON endpoint. `error` is set when the API cannot be reached; the last good data stays on screen. */
export function usePoll<T>(path: string, everyMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const load = useCallback(async () => {
    try {
      const r = await fetch(path, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      if (alive.current) { setData(j); setError(null); }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    load();
    const id = everyMs > 0 ? window.setInterval(load, everyMs) : 0;
    return () => { alive.current = false; if (id) window.clearInterval(id); };
  }, [load, everyMs]);
  return { data, error, reload: load };
}

export const fmtTime = (iso: string) => iso.slice(11, 19);
export const fmtAge = (s: number | null) => (s === null ? "no data" : s < 120 ? `${s.toFixed(0)} s` : s < 7200 ? `${(s / 60).toFixed(0)} min` : `${(s / 3600).toFixed(1)} h`);
