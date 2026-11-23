import { useState } from "react";
import { useMesh } from "../App";
import { AuditEvent, fmtTime } from "../api";
import { ModeBanner } from "../components/common";
import { ACTION, scorerLabel } from "../derive";

const KINDS = ["REROUTE", "ACTION_BLOCKED", "SUPPRESSED_VICTIM", "PROBE_START", "PROBE_FAILED", "RELEASE", "SNAPSHOT_REJECTED", "SCORED"] as const;
const TONE: Record<string, string> = { REROUTE: "crit", ACTION_BLOCKED: "warn", SUPPRESSED_VICTIM: "accent", PROBE_START: "warn", PROBE_FAILED: "crit", RELEASE: "ok", SNAPSHOT_REJECTED: "crit", SCORED: "warn" };

function describe(e: AuditEvent): string {
  const bits: string[] = [];
  const who = e.event === "SUPPRESSED_VICTIM" ? `${e.node} (victim of ${e.culprit})` : e.culprit ?? e.node;
  if (who) bits.push(`blamed: ${who}`);
  if (e.risk !== undefined) bits.push(`risk ${e.risk}`);
  if (e.reason) bits.push(`reason: ${e.reason}`);
  if (e.why) bits.push(`why: ${e.why}`);
  if (e.weights) bits.push(`${e.virtual_service} weights ${Object.entries(e.weights).map(([k, v]) => `${k}=${v}`).join(" ")}`);
  return bits.join(" · ");
}

export default function Incidents() {
  const { state, error } = useMesh();
  const [stream, setStream] = useState("all");
  const [kinds, setKinds] = useState<Set<string>>(new Set(KINDS));
  const events = (state?.events ?? []).filter((e) => (stream === "all" || e.stream === stream) && kinds.has(e.event)).slice().reverse();
  const toggle = (k: string) => setKinds((p) => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; });
  return (
    <div className="page">
      <div className="page-head">
        <h1>Audit timeline</h1>
        <p>One line per decision, newest first, read from the controllers' audit files. “Dry-run” means the controller logged the write but never changed the cluster. Each row carries the scorer's source (primary = GNN where the GNN is the scorer, fallback = rule) at that moment.</p>
      </div>
      <ModeBanner s={state} error={error} />
      <div className="section panel">
        <div className="row" role="group" aria-label="Filter by controller">
          {["all", ...(state?.streams.map((s) => s.name) ?? [])].map((s) => <button key={s} className="btn small" aria-pressed={stream === s} onClick={() => setStream(s)}>{s === "all" ? "All controllers" : s.toUpperCase()}</button>)}
        </div>
        <div className="row" role="group" aria-label="Filter by event type">
          {KINDS.map((k) => <button key={k} className="btn small" aria-pressed={kinds.has(k)} onClick={() => toggle(k)}>{ACTION[k] ?? k}</button>)}
        </div>
        <p className="src">{events.length} events shown{state && state.events.length >= 300 ? " (the API returns the latest 300)" : ""}. Streams: {state?.streams.map((s) => `${s.name} = ${s.path}, ${s.scored_total} SCORED, ${s.fallback_scored} via fallback`).join("; ")}</p>
        {events.length === 0 && <div><h3>No events</h3><p className="note">Nothing matches the filters, or the audit files have no non-SCORED events yet.</p></div>}
        <ol className="timeline">
          {events.map((e, i) => (
            <li key={e.stream + e.ts + e.event + i} className={TONE[e.event] ?? ""}>
              <time dateTime={e.ts}>{e.ts.slice(5, 10)}<br />{fmtTime(e.ts)}Z</time>
              <div>
                <div className="row" style={{ gap: 8 }}>
                  <span className={`pill ${TONE[e.event] ?? ""}`}>{ACTION[e.event] ?? e.event}</span>
                  <span className="pill">{e.stream.toUpperCase()}</span>
                  {e.dry_run && <span className="pill">dry-run</span>}
                  {e.scorer_source && <span className={`pill ${e.scorer_source === "fallback" ? "warn" : ""}`}>scoring: {scorerLabel(e)}</span>}
                </div>
                <div className="meta">{e.event === "SNAPSHOT_REJECTED" ? `reason: ${e.reason ?? "n/a"}${e.age_s ? ` · age ${e.age_s} s` : ""}` : describe(e) || "(no detail)"}</div>
                {e.scorer_note && <div className="meta">fallback note: {e.scorer_note}</div>}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
