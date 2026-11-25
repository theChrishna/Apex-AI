import { useCallback, useEffect, useRef, useState } from "react";

/** Types of the fleet API (dashboard/server.py). Any mesh: service names are plain strings. */
export interface FleetCluster { name: string; last_push: string | null; last_snapshot: string | null; snapshots: number; events: number; snapshot_age_s: number | null; stale: boolean; scorer: string }
export interface FleetNode { id: string; risk: number; in_lat: number; out_lat: number; in_rate: number }
export interface FleetEdge { source: string; destination: string; request_rate: number; latency_p95: number; error_rate: number; src_request_rate?: number; src_error_rate?: number }
export interface Subset { rate: number; err: number; p95: number | null }
export interface FleetEvent { ts: string; event: string; node?: string; culprit?: string; risk?: number; reason?: string; why?: string; weights?: Record<string, number>; dry_run?: boolean; virtual_service?: string; error?: string }
export interface FleetState {
  cluster: string; now: string; scorer: string;
  graph: { ts: string; age_s: number; stale: boolean; nodes: FleetNode[]; edges: FleetEdge[]; subsets: Record<string, Record<string, Subset>> | null } | null;
  series: { ts: string; risk: Record<string, number> }[];
  controller: { last_scored: FleetEvent & { top?: string; source?: string } | null; age_s: number | null; running: boolean; shadow: boolean | null };
  mesh: { state: "NORMAL" | "REROUTED" | "PROBING"; culprits: Record<string, string> };
  decisions: FleetEvent[];
}

const KEY = "meshheal-fleet-token";
export const getToken = () => { try { return sessionStorage.getItem(KEY) ?? ""; } catch { return ""; } };
export const setToken = (t: string) => { try { t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY); } catch { /* private mode */ } };

/** Poll an authenticated fleet endpoint. `status` 401/403 means the token is missing or wrong. */
export function useFleet<T>(path: string | null, token: string, everyMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path || !token) return;
    try {
      const r = await fetch(path, { cache: "no-store", headers: { Authorization: `Bearer ${token}` } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw Object.assign(new Error(j.error ?? `HTTP ${r.status}`), { status: r.status });
      if (alive.current) { setData(j as T); setError(null); }
    } catch (e) {
      const status = (e as { status?: number }).status ?? 0;
      if (alive.current) setError({ status, message: e instanceof Error ? e.message : String(e) });
    }
  }, [path, token]);
  useEffect(() => {
    alive.current = true;
    setData(null);
    load();
    const id = everyMs > 0 ? window.setInterval(load, everyMs) : 0;
    return () => { alive.current = false; if (id) window.clearInterval(id); };
  }, [load, everyMs]);
  return { data, error, reload: load };
}

/** Columns by call depth (longest path from an entry service), rows ordered to keep callers next to callees. */
export function layout(nodes: string[], edges: { source: string; destination: string }[]) {
  const ids = new Set(nodes);
  const es = edges.filter((e) => ids.has(e.source) && ids.has(e.destination) && e.source !== e.destination);
  const level: Record<string, number> = Object.fromEntries(nodes.map((n) => [n, 0]));
  for (let i = 0; i < nodes.length; i++) {           // longest path; stops after N rounds even if there is a cycle
    let changed = false;
    for (const e of es) if (level[e.destination] < level[e.source] + 1 && level[e.source] + 1 < nodes.length) { level[e.destination] = level[e.source] + 1; changed = true; }
    if (!changed) break;
  }
  const cols: string[][] = [];
  for (const n of [...nodes].sort()) (cols[level[n]] ??= []).push(n);
  const row: Record<string, number> = {};
  cols.forEach((col, c) => {
    if (c > 0) {
      const bary = (n: string) => { const p = es.filter((e) => e.destination === n).map((e) => row[e.source] ?? 0); return p.length ? p.reduce((a, b) => a + b, 0) / p.length : 0; };
      col.sort((a, b) => bary(a) - bary(b) || a.localeCompare(b));
    }
    col.forEach((n, i) => { row[n] = i; });
  });
  return { level, row, columns: cols.length, rows: Math.max(1, ...cols.map((c) => c.length)) };
}

export const riskTone = (r: number) => (r >= 0.85 ? "crit" : r >= 0.6 ? "warn" : "ok");
export const errShare = (e: FleetEdge) => (e.src_request_rate ? (e.src_error_rate ?? 0) / e.src_request_rate : e.request_rate ? e.error_rate / e.request_rate : 0);
