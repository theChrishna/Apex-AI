import { useMesh } from "../App";
import { ModeBanner, StatusStrip } from "../components/common";

const CARDS = [
  { href: "#/mesh", title: "Live mesh", desc: "Four services, per-node rule risk, edge latency and the reroute state.", action: "Open the graph" },
  { href: "#/incidents", title: "Incidents", desc: "Every audited decision: reroutes, blocked actions, probes, releases.", action: "Read the timeline" },
  { href: "#/evaluation", title: "Evaluation", desc: "LOEO, no-graph ablation and shadow-run tables, with the limits next to them.", action: "See the numbers" },
  { href: "#/how", title: "How it works", desc: "The control loop, the safety checks and copy-able commands to run it.", action: "Run it yourself" },
];

export default function Overview() {
  const { state, error, reload } = useMesh();
  const r = state?.replay;
  const ctl = async (q: string) => { await fetch(`/api/replay/control?${q}`); reload(); };
  return (
    <>
      <section className="hero">
        <span className="eyebrow">Autonomous service-mesh orchestrator</span>
        <h1>Catch silent degradation. Reroute before users notice.</h1>
        <p className="lead">MeshHeal AI reads per-edge latency from Istio telemetry, scores which service is the culprit, checks that rerouting is safe, then shifts traffic and verifies the recovery. A student prototype on one Bookinfo testbed.</p>
        <div className="row">
          <a className="btn primary" href="#/mesh">Open live mesh</a>
          <a className="btn" href="#/how">Run it</a>
        </div>
      </section>

      <div className="section" style={{ marginTop: 8 }}>
        <ModeBanner s={state} error={error} />
        <StatusStrip s={state} />
        {state && !state.status.controller_running && <div className="banner problem" role="status">{state.status.note ?? "no controller running"}. Incidents below are history from the audit files.</div>}
        {r && (
          <div className="row" aria-label="Replay controls">
            <span className="pill warn">REPLAY position {state!.now.slice(11, 19)}Z</span>
            <button className="btn small" aria-pressed={r.speed === 1} onClick={() => ctl("speed=1")}>1×</button>
            <button className="btn small" aria-pressed={r.speed === 10} onClick={() => ctl("speed=10")}>10×</button>
            <button className="btn small" onClick={() => ctl("restart=1")}>Restart</button>
          </div>
        )}
      </div>

      <section className="section" aria-labelledby="explore">
        <h2 id="explore">Explore</h2>
        <div className="grid">
          {CARDS.map((c) => (
            <a key={c.href} className="card" href={c.href}>
              <h3>{c.title}</h3><p>{c.desc}</p><span className="action">{c.action} →</span>
            </a>
          ))}
        </div>
      </section>
    </>
  );
}
