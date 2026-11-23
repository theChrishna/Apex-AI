import { Check, CircleAlert, CircleHelp, FileText, Globe, MessageSquare, Play, Route, Star, Timer } from "lucide-react";
import { NODES, NodeId, State, fmtTime } from "../api";
import { SLOW_MS, serviceRows } from "../derive";
import { SERIES } from "./charts";
import { PanelTitle } from "./common";

// Layered left to right: productpage calls details and reviews; reviews (v2/v3) calls ratings.
const W = 230, H = 104;
const POS: Record<NodeId, { x: number; y: number }> = {
  productpage: { x: 40, y: 140 }, details: { x: 390, y: 40 }, reviews: { x: 390, y: 240 }, ratings: { x: 740, y: 240 },
};
const ICON = { productpage: Globe, details: FileText, reviews: MessageSquare, ratings: Star };
export const ACTION_RISK = 0.85;

const tone = (s: string) => (s === "NORMAL" ? "ok" : s === "REROUTED" ? "crit" : "warn");
const TONE_COLOR: Record<string, { fg: string; bg: string }> = {
  ok: { fg: "var(--ok)", bg: "var(--ok-soft)" }, warn: { fg: "var(--warn)", bg: "var(--warn-soft)" },
  crit: { fg: "var(--crit)", bg: "var(--crit-soft)" }, "": { fg: "var(--muted)", bg: "var(--surface-2)" },
};

/** Right-angle connector with rounded corners: out of the source, a vertical run halfway across the gap, into the target. */
function elbow(x1: number, y1: number, x2: number, y2: number, r = 18) {
  const mx = (x1 + x2) / 2;
  if (Math.abs(y1 - y2) < 1) return `M${x1} ${y1}H${x2}`;
  const d = y2 > y1 ? 1 : -1;
  return `M${x1} ${y1}H${mx - r}Q${mx} ${y1} ${mx} ${y1 + d * r}V${y2 - d * r}Q${mx} ${y2} ${mx + r} ${y2}H${x2}`;
}

/** Reroute state per controller, then the service graph drawn as a node canvas. */
export default function MeshGraph({ state }: { state: State | null }) {
  const snap = state?.snapshot;
  const edges = snap?.edges ?? [];
  const rows = Object.fromEntries(serviceRows(state).map((r) => [r.id, r]));
  const entries = new Set(edges.filter((e) => !edges.some((o) => o.destination === e.source)).map((e) => e.source));

  const status = (n: NodeId) => {
    const r = rows[n], risk = snap?.nodes[n]?.risk_rule;
    if (r.health === "Rerouted") return { label: "Rerouted", tone: "crit", Icon: Route, border: "var(--crit)" };
    if (r.health === "Stale" || r.health === "No data") return { label: r.health, tone: "", Icon: CircleHelp, border: "var(--axis)" };
    if (risk !== undefined && risk >= ACTION_RISK) return { label: `Risk ${risk.toFixed(2)}`, tone: "crit", Icon: CircleAlert, border: "var(--crit)" };
    if (r.health === "Slow") return { label: "Slow", tone: "warn", Icon: Timer, border: "var(--warn)" };
    return { label: "Healthy", tone: "ok", Icon: Check, border: "var(--accent)" };
  };
  const edgeColor = (e: { request_rate: number; latency_p95: number }) =>
    e.request_rate <= 0 ? "var(--axis)" : e.latency_p95 >= SLOW_MS ? "var(--warn)" : "var(--accent)";

  return (
    <section className="card mesh-card" aria-labelledby="mesh">
      <PanelTitle id="mesh">Service graph</PanelTitle>
      {snap && !snap.valid && <div className="banner problem" role="alert">Latest snapshot rejected by the validator: {snap.reject_reason}</div>}
      <div className="ctl-state" aria-label="Reroute state per scorer">
        {state?.streams.map((st) => {
          const m = state.mesh[st.name];
          return (
            <div key={st.name}>
              <b>{st.name.toUpperCase()} controller</b>
              <span className={`pill ${tone(m.state)}`}>{m.state}</span>
              {st.stale && <span className="pill">not running (last audit {st.age_s === null ? "never" : "stale"})</span>}
              {st.last_scored && <span className="pill">top {st.last_scored.top} {st.last_scored.risk.toFixed(3)} · {st.name === "gnn" ? (st.last_scored.source === "fallback" ? "rule fallback" : "GNN") : "rule"}</span>}
            </div>
          );
        })}
      </div>
      <figure className="mesh-wrap mesh-canvas">
        <svg viewBox="0 0 1010 372" role="img" aria-label="Service graph: productpage calls details and reviews; reviews calls ratings. Each card shows the service's status and rule risk.">
          {edges.map((e) => {
            const a = POS[e.source], b = POS[e.destination];
            if (!a || !b) return null;
            const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2, my = (y1 + y2) / 2, c = edgeColor(e);
            return (
              <g key={e.source + e.destination}>
                <path d={elbow(x1, y1, x2, y2)} fill="none" stroke={c} strokeWidth="1.8" />
                <path d={`M${x2 - 9} ${y2 - 6}L${x2} ${y2}L${x2 - 9} ${y2 + 6}`} fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                <rect className="edge-chip" x={mx - 52} y={my - 19} width="104" height="38" rx="11" />
                <text x={mx} y={my - 2} textAnchor="middle" className="edge-main">{e.latency_p95.toFixed(1)} ms p95</text>
                <text x={mx} y={my + 13} textAnchor="middle" className="edge-sub">{e.request_rate.toFixed(2)} req/s</text>
              </g>
            );
          })}
          {NODES.map((n) => {
            const { x, y } = POS[n], ns = snap?.nodes[n], st = status(n), Icon = ICON[n], t = TONE_COLOR[st.tone];
            const chipW = 30 + st.label.length * 6.6;
            const detail = ns ? [ns.in_rate > 0 ? `in ${ns.in_lat} ms` : "no traffic in", ns.out_lat > 0 ? `out ${ns.out_lat} ms` : ""].filter(Boolean).join(" · ") : "no snapshot";
            return (
              <g key={n}>
                {entries.has(n) && (
                  <g>
                    <rect x={x} y={y - 30} width="92" height="46" rx="12" style={{ fill: "var(--accent)" }} />
                    <Play x={x + 11} y={y - 21} size={13} style={{ color: "var(--accent-text)" }} aria-hidden="true" />
                    <text x={x + 31} y={y - 10} className="node-tab">Entry</text>
                  </g>
                )}
                <rect className="node-card" x={x} y={y} width={W} height={H} rx="20" style={{ stroke: st.border }} />
                <rect x={x + 16} y={y + 16} width="34" height="34" rx="10" style={{ fill: `color-mix(in srgb, ${SERIES[n].color} 15%, var(--surface))` }} />
                <Icon x={x + 25} y={y + 25} size={16} style={{ color: SERIES[n].color }} aria-hidden="true" />
                <text x={x + 62} y={y + 39} className="node-title">{n}</text>
                <text x={x + 16} y={y + 74} className="node-sub">{ns ? `rule risk ${ns.risk_rule.toFixed(2)}` : "no data"}</text>
                <text x={x + 16} y={y + 92} className="node-sub">{detail}</text>
                <g>
                  <rect x={x + W - 12 - chipW} y={y - 30} width={chipW} height="24" rx="8" style={{ fill: t.bg }} />
                  {st.tone === "crit" && state?.status.controller_running && <circle className="pulse-ring" cx={x + W - 12 - chipW + 14.5} cy={y - 17.5} r="7" style={{ fill: t.fg }} aria-hidden="true" />}
                  <st.Icon x={x + W - 12 - chipW + 8} y={y - 24} size={13} style={{ color: t.fg }} aria-hidden="true" />
                  <text x={x + W - 12 - chipW + 27} y={y - 14} className="node-badge" style={{ fill: t.fg }}>{st.label}</text>
                </g>
              </g>
            );
          })}
          {NODES.map((n) => {
            const out = edges.filter((e) => e.source === n);
            if (!out.length) return null;
            const { x, y } = POS[n];
            return <circle key={n} className="edge-dot" cx={x + W} cy={y + H / 2} r="5.5" style={{ fill: out.some((e) => e.request_rate > 0) ? "var(--accent)" : "var(--axis)" }} />;
          })}
        </svg>
      </figure>
      <div className="legend" aria-label="Legend">
        <span><i className="sw" style={{ background: "var(--accent)" }} />traffic flowing</span>
        <span><i className="sw" style={{ background: "var(--warn)" }} />p95 {SLOW_MS} ms or more</span>
        <span><i className="sw" style={{ background: "var(--axis)" }} />no traffic in the snapshot</span>
        <span>Card outline: red at rule risk {ACTION_RISK} or more (the action threshold) or when rerouted, amber when slow</span>
      </div>
      <p className="note">Risk on each card is the <b>rule score</b> <code>(in_lat − out_lat)/100 ms</code> computed from the latest snapshot with the control plane's own functions. The audit files hold only the top node's risk for each scorer, so per-node GNN risk is not available here. <b>Entry</b> marks the service with no incoming edge. Edge latency is a histogram p95, bucketed (e.g. 97.5, 241 ms). Snapshot {snap ? fmtTime(snap.ts) + "Z" : "n/a"}.</p>
    </section>
  );
}
