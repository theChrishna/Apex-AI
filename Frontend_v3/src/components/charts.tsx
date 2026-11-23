import { Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { NODES, NodeId, State, fmtTime, isoMs } from "../api";
import { SLOW_MS } from "../derive";

/** Fixed per service, so a colour always means the same service. Dash pattern is the second cue for colour-blind readers. */
export const SERIES: Record<NodeId, { color: string; dash?: string }> = {
  productpage: { color: "var(--series-1)", dash: "2 3" },
  details: { color: "var(--series-2)", dash: "7 3" },
  reviews: { color: "var(--series-3)" },
  ratings: { color: "var(--series-4)" },
};
const tick = { fill: "var(--muted)", fontSize: 11 };
const clock = (t: number) => new Date(t).toISOString().slice(11, 19);

function Swatch({ n }: { n: NodeId }) {
  return <svg width="20" height="8" aria-hidden="true"><line x1="0" y1="4" x2="20" y2="4" stroke={SERIES[n].color} strokeWidth="2.5" strokeDasharray={SERIES[n].dash} /></svg>;
}

/** REROUTE / RELEASE inside the plotted window. Two controllers acting on the same cycle share one marker. */
function markers(s: State, from: number, to: number) {
  const out: { t: number; event: string; culprit: string; streams: string[]; dry: boolean }[] = [];
  for (const e of s.events) {
    if (e.event !== "REROUTE" && e.event !== "RELEASE") continue;
    const t = isoMs(e.ts);
    if (t < from || t > to) continue;
    const culprit = e.culprit ?? e.node ?? "";
    const same = out.find((m) => m.event === e.event && m.culprit === culprit && Math.abs(m.t - t) < 15000);
    if (same) { same.streams.push(e.stream); same.dry = same.dry || !!e.dry_run; }
    else out.push({ t, event: e.event, culprit, streams: [e.stream], dry: !!e.dry_run });
  }
  return out;
}

function RiskTip({ active, payload, label }: { active?: boolean; payload?: { dataKey?: string | number; value?: number }[]; label?: number }) {
  if (!active || !payload?.length) return null;
  const at = (n: NodeId) => payload.find((p) => p.dataKey === n)?.value;
  return (
    <div className="chart-tip">
      <b>{label !== undefined ? clock(label) : ""}Z</b>
      {NODES.map((n) => { const v = at(n); return <span key={n}><em><Swatch n={n} />{n}</em>{v === undefined ? "n/a" : v.toFixed(3)}</span>; })}
    </div>
  );
}

export function RiskChart({ state }: { state: State | null }) {
  const data = (state?.series ?? []).map((p) => ({ t: isoMs(p.ts), ...p.risk }));
  const from = data[0]?.t ?? 0, to = data[data.length - 1]?.t ?? 0;
  const ms = state ? markers(state, from, to) : [];
  const dry = ms.some((m) => m.dry);
  return (
    <>
      <div className="chart-legend" aria-label="Legend">
        {NODES.map((n) => <span key={n}><Swatch n={n} />{n}</span>)}
      </div>
      <div className="chart-box" style={{ height: 250 }}>
        {data.length < 2 ? <div className="chart-empty">Waiting for snapshots: {data.length} so far.</div> : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 18, right: 12, bottom: 0, left: -8 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis dataKey="t" type="number" scale="time" domain={[from, to]} tickFormatter={clock} tick={tick} tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={56} />
              <YAxis domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tick={tick} tickLine={false} axisLine={false} width={44} />
              <ReferenceLine y={0.85} stroke="var(--axis)" label={{ value: "act 0.85", position: "insideTopLeft", fill: "var(--muted)", fontSize: 11 }} />
              <ReferenceLine y={0.6} stroke="var(--axis)" label={{ value: "release 0.60", position: "insideTopLeft", fill: "var(--muted)", fontSize: 11 }} />
              {ms.map((m) => <ReferenceLine key={m.event + m.t} x={m.t} stroke={m.event === "REROUTE" ? "var(--crit)" : "var(--ok)"} strokeWidth={1.5} label={{ value: m.event, position: "top", fill: "var(--text)", fontSize: 10, fontWeight: 600 }} />)}
              <Tooltip content={<RiskTip />} cursor={{ stroke: "var(--axis)" }} isAnimationActive={false} />
              {NODES.map((n) => <Line key={n} dataKey={n} name={n} type="monotone" stroke={SERIES[n].color} strokeDasharray={SERIES[n].dash} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />)}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <p className="note">
        Rule score (in_lat − out_lat) / 100 ms per service, last {data.length} snapshots. It is not GNN output: the audit files hold only the top node's GNN risk.
        {dry ? " Markers come from the audit log; this run was dry-run, so no traffic actually moved." : ""}
      </p>
    </>
  );
}

function EdgeTip({ active, payload }: { active?: boolean; payload?: { payload: { name: string; p95: number; rate: number; err: number | null } }[] }) {
  if (!active || !payload?.length) return null;
  const e = payload[0].payload;
  return (
    <div className="chart-tip">
      <b>{e.name}</b>
      <span><em>p95</em>{e.p95.toFixed(1)} ms</span>
      <span><em>rate</em>{e.rate.toFixed(2)} req/s</span>
      <span><em>errors</em>{e.err ?? "n/a"}</span>
    </div>
  );
}

export function EdgeChart({ state }: { state: State | null }) {
  const snap = state?.snapshot;
  const data = (snap?.edges ?? []).map((e) => ({ name: `${e.source} → ${e.destination}`, p95: e.latency_p95, rate: e.request_rate, err: e.error_rate }));
  const top = Math.max(300, ...data.map((d) => d.p95));   // fixed floor: a healthy 5 ms bar must not fill the chart
  return (
    <>
      <div className="chart-box" style={{ height: 250 }}>
        {!data.length ? <div className="chart-empty">No snapshot yet.</div> : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 18, right: 56, bottom: 0, left: 0 }} barCategoryGap="34%">
              <CartesianGrid horizontal={false} stroke="var(--grid)" />
              <XAxis type="number" domain={[0, top]} tick={tick} tickLine={false} axisLine={{ stroke: "var(--axis)" }} unit=" ms" />
              <YAxis type="category" dataKey="name" width={148} tickFormatter={(n: string) => n.replace(/ /g, "\u00a0")} tick={tick} tickLine={false} axisLine={false} />
              <ReferenceLine x={SLOW_MS} stroke="var(--axis)" label={{ value: `slow ${SLOW_MS} ms`, position: "top", fill: "var(--muted)", fontSize: 11 }} />
              <Tooltip content={<EdgeTip />} cursor={{ fill: "var(--surface-2)" }} isAnimationActive={false} />
              <Bar dataKey="p95" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                {data.map((d) => <Cell key={d.name} fill={d.p95 >= SLOW_MS ? "var(--warn)" : "var(--accent)"} />)}
                <LabelList dataKey="p95" position="right" formatter={(v: number) => `${v.toFixed(1)}\u00a0ms`} style={{ fill: "var(--text)", fontSize: 12, fontWeight: 600 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
      <p className="note">Snapshot {snap ? `${fmtTime(snap.ts)}Z` : "n/a"}. Istio histogram p95, so values are bucketed (e.g. 97.5, 241 ms). Amber means {SLOW_MS} ms or more.</p>
    </>
  );
}
