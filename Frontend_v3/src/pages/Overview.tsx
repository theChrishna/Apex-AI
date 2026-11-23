import { CircleCheck, CircleHelp, Route, Timer } from "lucide-react";
import { useMesh } from "../App";
import { State, fmtAge, fmtTime } from "../api";
import { ModeBanner, PanelTitle } from "../components/common";
import { EdgeChart, RiskChart, SERIES } from "../components/charts";
import MeshGraph, { ACTION_RISK } from "../components/MeshGraph";
import { ACTION, Health, SLOW_MS, isDecision, outcome, scorerInUse, scorerLabel, serviceRows } from "../derive";

const BADGE_ICON: Record<Health, typeof Route> = { Healthy: CircleCheck, Slow: Timer, Rerouted: Route, Stale: CircleHelp, "No data": CircleHelp };

function Stat({ tone, k, v, sub }: { tone?: string; k: string; v: string; sub: string }) {
  return (
    <div className="stat">
      <span className="k"><i className={`dot ${tone ?? ""}`} aria-hidden="true" />{k}</span>
      <span className="v">{v}</span>
      <span className="sub">{sub}</span>
    </div>
  );
}

/** The one hero metric: the highest rule risk across the services in the latest snapshot (the same values the graph cards show). */
function HeroMetric({ s }: { s: State | null }) {
  const top = Object.entries(s?.snapshot?.nodes ?? {}).sort((a, b) => b[1].risk_rule - a[1].risk_rule)[0];
  const risk = top?.[1].risk_rule;
  const over = risk !== undefined && risk >= ACTION_RISK;
  return (
    <section className="hero-metric" aria-labelledby="hero">
      <PanelTitle id="hero">Highest rule risk</PanelTitle>
      <div className="hm-value">
        <span className="hm-num">{risk === undefined ? "n/a" : risk.toFixed(2)}</span>
        <span className="hm-unit">{top ? top[0] : s ? "no snapshot" : "…"}</span>
      </div>
      <div className="hm-bar" role="img" aria-label={risk === undefined ? "no risk value" : `risk ${risk.toFixed(2)} on a scale of 0 to 1, action threshold ${ACTION_RISK}`}>
        <i className={over ? "crit" : ""} style={{ width: `${Math.min(1, risk ?? 0) * 100}%` }} />
        <b style={{ left: `${ACTION_RISK * 100}%` }} />
      </div>
      <p className="hm-sub">{risk === undefined ? "No snapshot yet." : `${over ? "At or above" : "Below"} the ${ACTION_RISK} action threshold. Rule score, not GNN output.`}</p>
    </section>
  );
}

function Stats({ s }: { s: State | null }) {
  const st = s?.status;
  const { stream, label: scorer } = scorerInUse(s);
  const decisions = (s?.events ?? []).filter(isDecision);
  const counts = (s?.streams ?? []).map((x) => ({ name: x.name, n: decisions.filter((e) => e.stream === x.name).length }));
  const perStream = counts.map((c) => `${c.name} ${c.n}`).join(" · ");
  const capped = (s?.events.length ?? 0) >= 300;
  return (
    <div className="stats" aria-live="polite">
      <HeroMetric s={s} />
      <div className="stat-grid">
        <Stat tone={s ? (s.mode === "REPLAY" ? "warn" : "ok") : ""} k="Mode" v={s?.mode ?? "…"}
          sub={s?.replay ? `Recorded shadow run at ${s.replay.speed}×, not live data` : s ? "Reading the files in the repo" : ""} />
        <Stat tone={!st ? "" : !stream ? "crit" : scorer === "GNN" ? "ok" : scorer === "Rule" ? "" : "warn"} k="Scorer in use" v={scorer}
          sub={stream ? `${stream.name} stream · ${stream.fallback_scored} of ${stream.scored_total} scored via fallback` : st ? "No audit stream scored in the last 45 s" : ""} />
        <Stat tone={!st ? "" : st.snapshot_stale ? "crit" : "ok"} k="Snapshot age" v={st ? fmtAge(st.snapshot_age_s) : "…"}
          sub={st ? (st.snapshot_stale ? "Stale: older than 45 s" : `Fresh · ${s?.snapshot ? fmtTime(s.snapshot.ts) + "Z" : ""}`) : ""} />
        <Stat k="Incidents" v={s ? String(Math.max(0, ...counts.map((c) => c.n))) : "…"}
          sub={s ? `REROUTE or ACTION_BLOCKED events per controller: ${perStream}${capped ? " (latest 300 events only)" : ""}` : ""} />
      </div>
    </div>
  );
}

function IncidentLog({ s }: { s: State | null }) {
  const rows = (s?.events ?? []).filter((e) => e.event !== "SCORED").slice(-7).reverse();
  return (
    <section className="card" aria-labelledby="log">
      <div className="card-head">
        <div><PanelTitle id="log">Incident log</PanelTitle><p>Latest decisions, newest first, UTC. Fallback scoring cycles are on the Incidents page.</p></div>
        <a className="card-link" href="#/incidents">View all</a>
      </div>
      {rows.length === 0 ? <p>{s ? "The audit files have no incident events yet." : "Loading…"}</p> : (
        <div className="table-wrap bare" tabIndex={0} role="region" aria-label="Incident log">
          <table>
            <thead><tr>{["Time", "Culprit", "Action", "Source", "Status"].map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
            <tbody>{rows.map((e, i) => {
              const [label, tone] = outcome(e);
              return (
                <tr key={e.stream + e.ts + e.event + i}>
                  <td>{e.ts.slice(5, 10)} {fmtTime(e.ts)}</td>
                  <td>{e.culprit ?? e.node ?? "n/a"}</td>
                  <td title={e.reason ?? e.why}>{ACTION[e.event] ?? e.event}</td>
                  <td>{scorerLabel(e)}</td>
                  <td><span className={`pill ${tone}`}>{label}</span>{e.dry_run && <span className="pill">dry-run</span>}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Services({ s }: { s: State | null }) {
  return (
    <section className="card" aria-labelledby="svc">
      <div className="card-head">
        <div><PanelTitle id="svc">Services</PanelTitle><p>From the latest snapshot and the audit state.</p></div>
      </div>
      <ul className="svc">
        {serviceRows(s).map((r) => {
          const Icon = BADGE_ICON[r.health];
          return (
            <li key={r.id}>
              <span className="dot" style={{ background: SERIES[r.id].color }} aria-hidden="true" />
              <div><b>{r.id}</b><small>{r.note}</small></div>
              <span className={`pill ${r.tone}`}><Icon size={13} aria-hidden="true" />{r.health}</span>
            </li>
          );
        })}
      </ul>
      <p className="note">Slow: p95 in or out of the service at {SLOW_MS} ms or more, which includes victims waiting on a slow callee. Rerouted: a controller's audit state.</p>
    </section>
  );
}

export default function Overview() {
  const { state, error } = useMesh();
  return (
    <div className="page">
      <div className="page-head">
        <h1>Overview</h1>
        <p>The four services, their health and every decision the controllers took, from the latest snapshot and the audit files.</p>
      </div>
      <ModeBanner s={state} error={error} />
      {state && !state.status.controller_running && <div className="banner problem" role="status">{state.status.note ?? "no controller running"}. Incidents below are history from the audit files.</div>}
      <Stats s={state} />
      <MeshGraph state={state} />
      <div className="charts">
        <section className="card" aria-labelledby="risk">
          <div className="card-head"><PanelTitle id="risk">Risk per service</PanelTitle></div>
          <RiskChart state={state} />
        </section>
        <section className="card" aria-labelledby="edges">
          <div className="card-head"><PanelTitle id="edges">Latency per edge</PanelTitle></div>
          <EdgeChart state={state} />
        </section>
      </div>
      <div className="bottom">
        <IncidentLog s={state} />
        <Services s={state} />
      </div>
    </div>
  );
}
