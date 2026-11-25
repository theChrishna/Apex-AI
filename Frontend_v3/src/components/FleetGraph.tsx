import { FleetState, errShare, layout, riskTone } from "../fleet";

const W = 196, H = 74, GX = 96, GY = 30, PAD = 24;
const TONE: Record<string, string> = { ok: "var(--accent)", warn: "var(--warn)", crit: "var(--crit)" };

function elbow(x1: number, y1: number, x2: number, y2: number, r = 14) {
  if (x2 <= x1) return `M${x1} ${y1}C${x1 + 60} ${y1} ${x2 - 60} ${y2} ${x2} ${y2}`;      // back edge (cycle)
  const mx = (x1 + x2) / 2;
  if (Math.abs(y1 - y2) < 1) return `M${x1} ${y1}H${x2}`;
  const d = y2 > y1 ? 1 : -1;
  const rr = Math.min(r, Math.abs(y2 - y1) / 2);
  return `M${x1} ${y1}H${mx - rr}Q${mx} ${y1} ${mx} ${y1 + d * rr}V${y2 - d * rr}Q${mx} ${y2} ${mx + rr} ${y2}H${x2}`;
}

/** Service graph for ANY mesh: laid out from the edges, coloured by the risk the fleet API computed. */
export default function FleetGraph({ state }: { state: FleetState }) {
  const g = state.graph;
  if (!g) return <p className="note">No snapshot yet.</p>;
  const ids = g.nodes.map((n) => n.id);
  const { level, row, columns, rows } = layout(ids, g.edges);
  const pos = (n: string) => ({ x: PAD + level[n] * (W + GX), y: PAD + 26 + row[n] * (H + GY) });
  const width = PAD * 2 + columns * W + (columns - 1) * GX, height = PAD * 2 + 26 + rows * H + (rows - 1) * GY;
  const rerouted = state.mesh.culprits;
  const label = `Service graph of ${state.cluster}: ${ids.length} services, ${g.edges.length} edges.`;
  return (
    <figure className="mesh-wrap mesh-canvas fleet-graph">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} style={{ minWidth: Math.min(width, 900) }}>
        {g.edges.map((e) => {
          if (!(e.source in level) || !(e.destination in level)) return null;
          const a = pos(e.source), b = pos(e.destination);
          const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
          const err = errShare(e);
          const c = e.request_rate <= 0 && !e.src_request_rate ? "var(--axis)" : err >= 0.05 ? "var(--crit)" : e.latency_p95 >= 100 ? "var(--warn)" : "var(--accent)";
          return (
            <g key={`${e.source}>${e.destination}`}>
              <title>{`${e.source} → ${e.destination}: p95 ${e.latency_p95.toFixed(1)} ms, ${e.request_rate.toFixed(2)} req/s, ${(err * 100).toFixed(0)}% failed`}</title>
              <path d={elbow(x1, y1, x2, y2)} fill="none" stroke={c} strokeWidth="1.6" />
              <path d={`M${x2 - 8} ${y2 - 5}L${x2} ${y2}L${x2 - 8} ${y2 + 5}`} fill="none" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </g>
          );
        })}
        {g.nodes.map((n) => {
          const { x, y } = pos(n.id), tone = rerouted[n.id] ? "crit" : riskTone(n.risk);
          const badge = rerouted[n.id] ? rerouted[n.id] : `risk ${n.risk.toFixed(2)}`;
          return (
            <g key={n.id}>
              <title>{`${n.id}: ${state.scorer} risk ${n.risk.toFixed(3)}; in ${n.in_lat} ms at ${n.in_rate} req/s; out ${n.out_lat} ms`}</title>
              <rect className="node-card" x={x} y={y} width={W} height={H} rx="16" style={{ stroke: TONE[tone] }} />
              <text x={x + 14} y={y + 26} className="node-title">{n.id.length > 22 ? n.id.slice(0, 21) + "…" : n.id}</text>
              <text x={x + 14} y={y + 46} className="node-sub">{n.in_rate > 0 ? `in ${n.in_lat} ms · ${n.in_rate} req/s` : "entry / no incoming traffic"}</text>
              <rect x={x + 14} y={y + 54} width={Math.max(2, (W - 28) * Math.min(1, n.risk))} height="6" rx="3" style={{ fill: TONE[tone] }} />
              <rect x={x + 14} y={y + 54} width={W - 28} height="6" rx="3" style={{ fill: "none", stroke: "var(--axis)" }} />
              <text x={x + W - 14} y={y - 8} textAnchor="end" className="node-badge" style={{ fill: TONE[tone] }}>{badge}</text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
