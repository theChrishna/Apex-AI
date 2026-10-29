import { useMesh } from "../App";
import { NODES, NodeId, fmtTime } from "../api";
import { ModeBanner, riskColor, riskSoft } from "../components/common";

// fixed layout: productpage calls details and reviews; reviews (v2/v3) calls ratings
const POS: Record<NodeId, { x: number; y: number }> = {
  productpage: { x: 110, y: 150 }, details: { x: 400, y: 60 }, reviews: { x: 400, y: 240 }, ratings: { x: 690, y: 240 },
};
const R = 46;

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return <svg width="100%" height="34" aria-hidden="true" />;
  const w = 220, h = 34;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - Math.min(1, v) * (h - 4)}`).join(" ");
  return <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="34" preserveAspectRatio="none" aria-hidden="true"><polyline points={pts} fill="none" stroke={color} strokeWidth="2" /></svg>;
}

const tone = (s: string) => (s === "NORMAL" ? "ok" : s === "REROUTED" ? "crit" : "warn");

export default function LiveMesh() {
  const { state, error } = useMesh();
  const snap = state?.snapshot;
  const edges = snap?.edges ?? [];
  return (
    <>
      <div className="page-head">
        <span className="eyebrow">Live mesh</span>
        <h1 style={{ fontSize: "clamp(2rem,4.5vw,3rem)" }}>Services and their health</h1>
        <p>Node colour is the <b>rule score</b> <code>(in_lat − out_lat)/100 ms</code> computed from the latest snapshot with the control plane's own functions. The audit files hold only the top node's risk for each scorer, so per-node GNN risk is not available here.</p>
      </div>
      <div className="section" style={{ marginTop: 0 }}>
        <ModeBanner s={state} error={error} />
        {snap && !snap.valid && <div className="banner problem" role="alert">Latest snapshot rejected by the validator: {snap.reject_reason}</div>}
        <div className="row" aria-label="Reroute state per scorer">
          {state?.streams.map((st) => {
            const m = state.mesh[st.name];
            return (
              <span key={st.name} className="row" style={{ gap: 8 }}>
                <b>{st.name.toUpperCase()} controller</b>
                <span className={`pill ${tone(m.state)}`}>{m.state}</span>
                {st.stale && <span className="pill">not running (last audit {st.age_s === null ? "never" : "stale"})</span>}
                {st.last_scored && <span className="pill">top {st.last_scored.top} {st.last_scored.risk.toFixed(3)} · {st.name === "gnn" ? (st.last_scored.source === "fallback" ? "rule fallback" : "GNN") : "rule"}</span>}
              </span>
            );
          })}
        </div>
        <figure className="mesh-wrap" style={{ margin: 0 }}>
          <svg viewBox="0 0 800 310" role="img" aria-label="Service graph: productpage calls details and reviews; reviews calls ratings. Node colour shows rule risk.">
            <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--muted)" /></marker></defs>
            {edges.map((e) => {
              const a = POS[e.source], b = POS[e.destination];
              if (!a || !b) return null;
              const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy);
              const x1 = a.x + (dx / len) * R, y1 = a.y + (dy / len) * R, x2 = b.x - (dx / len) * (R + 6), y2 = b.y - (dy / len) * (R + 6);
              const slow = e.latency_p95 >= 100;
              return (
                <g key={e.source + e.destination}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={slow ? "var(--warn)" : "var(--muted)"} strokeWidth={slow ? 3 : 1.8} markerEnd="url(#arr)" />
                  <rect x={(x1 + x2) / 2 - 56} y={(y1 + y2) / 2 - 24} width="112" height="34" rx="6" fill="var(--bg)" stroke="var(--border)" />
                  <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 8} textAnchor="middle" fontSize="13" fontWeight="600">{e.latency_p95.toFixed(1)} ms p95</text>
                  <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 + 5} textAnchor="middle" fontSize="11" style={{ fill: "var(--muted)" }}>{e.request_rate.toFixed(2)} req/s</text>
                </g>
              );
            })}
            {NODES.map((n) => {
              const p = POS[n], ns = snap?.nodes[n];
              return (
                <g key={n}>
                  <circle cx={p.x} cy={p.y} r={R} fill={riskSoft(ns?.risk_rule)} stroke={riskColor(ns?.risk_rule)} strokeWidth="4" />
                  <text x={p.x} y={p.y - 2} textAnchor="middle" fontSize="13" fontWeight="700">{n}</text>
                  <text x={p.x} y={p.y + 15} textAnchor="middle" fontSize="12" style={{ fill: "var(--muted)" }}>{ns ? `risk ${ns.risk_rule.toFixed(2)}` : "no data"}</text>
                </g>
              );
            })}
          </svg>
        </figure>
        <div className="legend" aria-label="Legend">
          <span><i style={{ background: "var(--ok)" }} />risk below 0.5</span>
          <span><i style={{ background: "var(--warn)" }} />0.5 to 0.85</span>
          <span><i style={{ background: "var(--crit)" }} />0.85 or more (action threshold)</span>
          <span>Edge latency is a histogram p95, bucketed (e.g. 97.5, 241 ms). Snapshot {snap ? fmtTime(snap.ts) + "Z" : "n/a"}.</span>
        </div>
        <div className="two">
          {NODES.map((n) => {
            const ns = snap?.nodes[n];
            const vals = (state?.series ?? []).map((s) => s.risk[n] ?? 0);
            return (
              <div key={n} className="card flat">
                <div className="row" style={{ justifyContent: "space-between" }}><h3>{n}</h3><span className="pill" style={{ color: riskColor(ns?.risk_rule) }}>{ns ? ns.risk_rule.toFixed(3) : "n/a"}</span></div>
                <Sparkline values={vals} color={riskColor(ns?.risk_rule)} />
                <p>{ns ? `in ${ns.in_lat} ms · out ${ns.out_lat} ms · ${ns.in_rate} req/s in · errors ${ns.in_err}` : "no snapshot"}. Last {vals.length} snapshots, rule score.</p>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
