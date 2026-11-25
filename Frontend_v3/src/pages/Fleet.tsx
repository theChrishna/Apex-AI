import { FormEvent, useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FleetCluster, FleetState, getToken, riskTone, setToken, useFleet } from "../fleet";
import FleetGraph from "../components/FleetGraph";
import { PanelTitle } from "../components/common";

const COLORS = ["#4f7cff", "#e0703a", "#2f9e72", "#b94fd6", "#c79a12", "#d6455d", "#3aa8c2", "#7a8a2e"];
const DECISION_TEXT: Record<string, string> = {
  REROUTE: "rerouted", PROBE_START: "probing", PROBE_FAILED: "probe failed", RELEASE: "released", ACTION_BLOCKED: "blocked",
  ACTION_FAILED: "write refused", SUPPRESSED_VICTIM: "victim, not acted on", RECONCILED: "taken over after restart",
  RECONCILE_ORPHAN: "state needs a human", SNAPSHOT_REJECTED: "snapshot rejected", LOOP_ERROR: "loop error", PAUSE_CHECK_FAILED: "pause check failed",
};

function SignIn({ onToken, problem }: { onToken: (t: string) => void; problem: string | null }) {
  const [value, setValue] = useState("");
  const submit = (e: FormEvent) => { e.preventDefault(); if (value.trim()) onToken(value.trim()); };
  return (
    <section className="card" aria-labelledby="signin">
      <PanelTitle id="signin">Fleet sign-in</PanelTitle>
      <p className="note">The fleet API needs a read token (<code>python -m dashboard.tokens add-read</code>). It is kept in this browser tab only and sent as a bearer token.</p>
      {problem && <div className="banner problem" role="alert">{problem}</div>}
      <form onSubmit={submit} className="token-form">
        <label htmlFor="tok">Read token</label>
        <input id="tok" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn" type="submit">Sign in</button>
      </form>
    </section>
  );
}

function Clusters({ list, current, pick }: { list: FleetCluster[]; current: string | null; pick: (c: string) => void }) {
  return (
    <div className="cluster-list" role="tablist" aria-label="Clusters">
      {list.map((c) => (
        <button key={c.name} role="tab" aria-selected={c.name === current} className={`cluster-btn${c.name === current ? " on" : ""}`} onClick={() => pick(c.name)}>
          <b>{c.name}</b>
          <span className={`pill ${c.stale ? "" : "ok"}`}>{c.stale ? (c.snapshot_age_s === null ? "no data" : `stale ${Math.round(c.snapshot_age_s)}s`) : "live"}</span>
          <span className="pill">{c.scorer} scorer</span>
        </button>
      ))}
    </div>
  );
}

function RiskHistory({ state }: { state: FleetState }) {
  const top = useMemo(() => {
    const peak: Record<string, number> = {};
    for (const p of state.series) for (const [n, v] of Object.entries(p.risk)) peak[n] = Math.max(peak[n] ?? 0, v);
    return Object.entries(peak).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([n]) => n);
  }, [state.series]);
  const data = state.series.map((p) => ({ t: p.ts.slice(11, 19), ...Object.fromEntries(top.map((n) => [n, p.risk[n] ?? 0])) }));
  return (
    <section className="card" aria-labelledby="hist">
      <PanelTitle id="hist">Risk over the last 30 minutes (6 highest services)</PanelTitle>
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="t" tick={{ fontSize: 11 }} minTickGap={40} />
            <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
            <Tooltip />
            {top.map((n, i) => <Line key={n} type="stepAfter" dataKey={n} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={1.8} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="note">Risk is computed by the fleet API with this cluster's <b>{state.scorer}</b> scorer (a learned baseline when one is configured, else the hand-set rule). The controller acts at 0.85 held for 3 of 4 checks.</p>
    </section>
  );
}

export default function Fleet() {
  const [token, setTok] = useState(getToken);
  const [cluster, setCluster] = useState<string | null>(() => new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("c"));
  const clusters = useFleet<FleetCluster[]>("/api/v1/clusters", token, 10000);
  const state = useFleet<FleetState>(cluster ? `/api/v1/clusters/${encodeURIComponent(cluster)}/state?minutes=30` : null, token, 5000);
  useEffect(() => { if (!cluster && clusters.data?.length) setCluster(clusters.data[0].name); }, [cluster, clusters.data]);
  const authProblem = clusters.error && (clusters.error.status === 401 || clusters.error.status === 403) ? "That token was refused. Use a read token." : null;
  if (!token || authProblem) return <SignIn problem={authProblem} onToken={(t) => { setToken(t); setTok(t); }} />;

  const s = state.data;
  const top = s?.graph ? [...s.graph.nodes].sort((a, b) => b.risk - a.risk).slice(0, 8) : [];
  return (
    <div className="page fleet">
      <div className="page-head">
        <h1>Fleet</h1>
        <button className="btn small" onClick={() => { setToken(""); setTok(""); }}>Sign out</button>
      </div>
      {clusters.error && <div className="banner problem" role="alert">Fleet API not reachable: {clusters.error.message}</div>}
      {clusters.data && clusters.data.length === 0 && <p className="note">No cluster has pushed data yet. Start an agent: <code>python -m dashboard.agent --url … --cluster NAME --token-file … --snapshots … --audit …</code></p>}
      {clusters.data && clusters.data.length > 0 && <Clusters list={clusters.data} current={cluster} pick={setCluster} />}
      {s && (
        <>
          <section className="card" aria-labelledby="ctl">
            <PanelTitle id="ctl">{s.cluster}</PanelTitle>
            <div className="ctl-state">
              <span className={`pill ${s.mesh.state === "NORMAL" ? "ok" : s.mesh.state === "REROUTED" ? "crit" : "warn"}`}>{s.mesh.state}</span>
              {Object.entries(s.mesh.culprits).map(([c, m]) => <span key={c} className="pill crit">{c}: {m}</span>)}
              <span className={`pill ${s.controller.running ? "ok" : ""}`}>{s.controller.running ? "controller running" : "controller not reporting"}</span>
              {s.controller.shadow !== null && <span className="pill">{s.controller.shadow ? "shadow mode (reads only)" : "acting"}</span>}
              {s.graph && <span className={`pill ${s.graph.stale ? "warn" : "ok"}`}>snapshot {Math.round(s.graph.age_s)} s old</span>}
            </div>
          </section>
          <section className="card mesh-card" aria-labelledby="graph">
            <PanelTitle id="graph">Service graph ({s.graph?.nodes.length ?? 0} services)</PanelTitle>
            <FleetGraph state={s} />
            <div className="legend">
              <span><i className="sw" style={{ background: "var(--accent)" }} />traffic flowing</span>
              <span><i className="sw" style={{ background: "var(--warn)" }} />p95 100 ms or more</span>
              <span><i className="sw" style={{ background: "var(--crit)" }} />5% or more failed (as the caller saw it)</span>
              <span>Card outline and bar: red at risk 0.85 or when rerouted, amber at 0.6</span>
            </div>
          </section>
          <div className="grid-2">
            <section className="card" aria-labelledby="top">
              <PanelTitle id="top">Highest risk now</PanelTitle>
              <table className="tbl"><thead><tr><th>Service</th><th>Risk</th><th>In p95</th><th>Req/s in</th></tr></thead>
                <tbody>{top.map((n) => <tr key={n.id}><td>{n.id}</td><td><span className={`pill ${riskTone(n.risk)}`}>{n.risk.toFixed(2)}</span></td><td>{n.in_lat} ms</td><td>{n.in_rate}</td></tr>)}</tbody></table>
              {s.graph?.subsets && Object.entries(s.graph.subsets).map(([svc, vers]) => (
                <p key={svc} className="note"><b>{svc}</b> versions: {Object.entries(vers).map(([v, d]) => `${v} ${d.p95 === null ? "–" : d.p95.toFixed(0) + " ms"} at ${d.rate.toFixed(2)} req/s${d.err ? `, ${(d.err * 100).toFixed(0)}% failed` : ""}`).join(" · ")}</p>
              ))}
            </section>
            <section className="card" aria-labelledby="dec">
              <PanelTitle id="dec">Controller decisions (last 30 minutes)</PanelTitle>
              {s.decisions.length === 0 ? <p className="note">None: no service stayed above the action threshold.</p> : (
                <ul className="events">{[...s.decisions].reverse().slice(0, 40).map((e, i) => (
                  <li key={i}><code>{e.ts.slice(11, 19)}Z</code> <b>{e.culprit ?? e.node ?? ""}</b> {DECISION_TEXT[e.event] ?? e.event}{e.reason ? ` (${e.reason})` : ""}{e.why ? ` (${e.why})` : ""}{e.dry_run ? " · shadow" : ""}</li>
                ))}</ul>
              )}
            </section>
          </div>
          <RiskHistory state={s} />
        </>
      )}
      {state.error && cluster && <div className="banner problem" role="alert">Cluster {cluster}: {state.error.message}</div>}
    </div>
  );
}
