import { ArrowRight, CircleAlert, ClipboardList, Radio, Route, Search, ShieldCheck } from "lucide-react";
import { useMesh } from "../App";
import { Evaluation as Ev, MdTable, NODES, usePoll } from "../api";
import { Mark } from "../components/common";
import { scorerInUse } from "../derive";
import facts from "../generated/facts.json";

type Facts = typeof facts;
const unavailable = "not available";

const STEPS = [
  { icon: Radio, title: "Read", text: "Istio telemetry, every 15 s" },
  { icon: Search, title: "Score", text: "Which service is the culprit" },
  { icon: ShieldCheck, title: "Check", text: "That the reroute is safe" },
  { icon: Route, title: "Act", text: "Patch the traffic split, probe, release" },
];

/** Mean AP and per-fold comparison from the same table the Evaluation page shows. Null when the table is not there. */
function ablation(ev: Ev | null) {
  const t: MdTable | undefined = ev?.controls?.tables.find((x) => x.heading.startsWith("Average Precision"));
  const mlp = t?.header.indexOf("MLP") ?? -1, gnn = t?.header.indexOf("GNN") ?? -1;
  if (!t || mlp < 0 || gnn < 0) return null;
  const folds = t.rows.filter((r) => /^\d+$/.test(r[0]));
  const mean = t.rows.find((r) => r[0].includes("Mean"));
  if (!folds.length || !mean) return null;
  return {
    folds: folds.length, file: ev!.controls.file, mlpMean: mean[mlp].replace(/\*/g, ""), gnnMean: mean[gnn].replace(/\*/g, ""),
    mlpGeGnn: folds.filter((r) => parseFloat(r[mlp]) >= parseFloat(r[gnn])).length,
  };
}

/** Decorative loop of the idea: ratings slows, its callers look slow, traffic moves to reviews v1. Not data. */
function MeshIllustration() {
  const node = (cls: string, x: number, y: number, name: string) => (
    <g key={name}>
      <circle className={`ill-ring ${cls}`} cx={x} cy={y} r="44" />
      <text x={x} y={y + 4} textAnchor="middle" fontSize="12.5" fontWeight="600">{name}</text>
    </g>
  );
  return (
    <figure className="ill">
      <svg viewBox="0 0 520 330" role="img" aria-label="Illustration: ratings slows down, productpage and reviews look slow because they wait on it, and traffic shifts to reviews v1.">
        <defs><marker id="ill-arr" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(--muted)" /></marker></defs>
        <g stroke="var(--muted)" strokeWidth="1.8" fill="none" markerEnd="url(#ill-arr)">
          <line x1="140" y1="150" x2="248" y2="82" />
          <line x1="140" y1="176" x2="248" y2="244" />
          <line className="ill-edge" x1="304" y1="244" x2="396" y2="244" />
        </g>
        {node("ill-caller", 96, 164, "productpage")}
        {node("ill-plain", 276, 64, "details")}
        {node("ill-caller", 276, 244, "reviews")}
        {node("ill-ratings", 440, 244, "ratings")}
        <g className="ill-v1"><rect x="216" y="296" width="120" height="26" rx="13" /><text x="276" y="313" textAnchor="middle" fontSize="11.5" fontWeight="600">all traffic → v1</text></g>
      </svg>
      <figcaption className="ill-caps">ratings slows down; MeshHeal blames it and shifts traffic to reviews v1</figcaption>
      <p className="note ill-note">Illustration of the idea, not measured data.</p>
    </figure>
  );
}

function shadowFact(f: Facts["shadow"]) {
  if (!f) return null;
  const per = Object.entries(f.perScorer);
  const same = per.every(([, x]) => x.correct === per[0][1].correct && x.faults === per[0][1].faults);
  const soak = Object.entries(f.falseEvents);
  const noFalse = soak.every(([, x]) => x.soak === 0);
  const decay = soak[0]?.[1];
  const correct = per.map(([name, x]) => `${name} ${x.correct} of ${x.faults}`).join(", ");
  return {
    big: same ? `${per[0][1].correct} of ${per[0][1].faults}` : correct,
    line: `${same ? "faults blamed correctly" : "faults blamed correctly, per scorer"}${noFalse ? `, 0 false events in a ${f.soakMinutes}-minute soak` : `; false events in the soak: ${soak.map(([n, x]) => `${n} ${x.soak}`).join(", ")}`}`,
    detail: `${same ? "Both the rule scorer and the GNN blamed the right service." : `Blamed correctly: ${correct}.`} Dry-run: the controllers logged their decisions but moved no traffic.${decay ? ` ${decay.decayEvents} more decision events fell inside the ${decay.decaySeconds} s after faults ended; the file counts those separately.` : ""}`,
    file: f.file,
  };
}

function liveFact(runs: Facts["live"]) {
  if (!runs) return null;
  const perScenario = runs.reduce<Record<string, number>>((m, r) => ({ ...m, [r.scenario]: (m[r.scenario] ?? 0) + 1 }), {});
  const once = Object.values(perScenario).every((n) => n === 1);
  const culprits = [...new Set(runs.map((r) => r.culprit))].join(", ");
  const label = (r: (typeof runs)[number]) => `${r.scenario} (${r.scoredViaFallback > 0 ? "rule fallback scores" : "GNN scores"}) ${r.detectS} s`;
  return {
    big: runs.map((r) => ({ t: `${r.detectS} s`, scenario: r.scenario })),
    line: `${culprits} rerouted after the fault started, ${once ? "one run each" : `runs per scenario: ${Object.entries(perScenario).map(([k, n]) => `${k} ${n}`).join(", ")}`}`,
    detail: `Scenarios: ${runs.map(label).join("; ")}. No rate or average. The timing is set by the persistence rule, not by the scorer.`,
    files: runs.map((r) => r.file).join(" · "),
    once, perScenario,
  };
}

export default function Home() {
  const { state } = useMesh();
  const { data: ev } = usePoll<Ev>("/api/evaluation", 0);
  const { stream, label } = scorerInUse(state);
  const sh = shadowFact(facts.shadow), lv = liveFact(facts.live);
  const ab = ablation(ev);
  const nodes = state?.snapshot ? Object.keys(state.snapshot.nodes) : NODES;
  const built = facts.generated.slice(0, 16).replace("T", " ");

  return (
    <div className="landing">
      <section className="l-hero" aria-labelledby="home-title">
        <div className="l-hero-copy">
          <div className="l-brand"><Mark size={40} />
            {state && <span className={`chip status ${state.mode === "REPLAY" ? "warn" : "ok"}`} title={state.label}>{state.mode}</span>}
          </div>
          <h1 id="home-title">MeshHeal AI</h1>
          <p className="l-lead">Detects silent latency degradation in a microservice mesh, finds the true culprit service, and reroutes traffic.</p>
          <div className="row">
            <a className="btn primary big" href="#/overview">Open live mesh <ArrowRight size={16} aria-hidden="true" /></a>
            <a className="btn big" href="#/evaluation">See evaluation</a>
          </div>
        </div>
        <MeshIllustration />
      </section>

      <section className="l-problem" aria-labelledby="problem">
        <span className="l-eyebrow">The problem</span>
        <h2 id="problem">One slow service makes the services that call it look slow too.</h2>
        <p>So alerts blame the wrong one. MeshHeal scores the latency a service adds itself, not the latency it is waiting on.</p>
      </section>

      <section className="l-flow" aria-labelledby="how">
        <span className="l-eyebrow">How it works</span>
        <h2 id="how">Four steps, every 15 seconds</h2>
        <ol className="flow">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <span className="flow-icon"><s.icon size={26} aria-hidden="true" /></span>
              <b><span className="n">{i + 1}</span> {s.title}</b>
              <span>{s.text}</span>
            </li>
          ))}
        </ol>
        <p className="l-audit"><ClipboardList size={16} aria-hidden="true" /><span>Every decision is written to an audit log. <a href="#/incidents">Read it on Incidents <ArrowRight size={13} aria-hidden="true" /></a></span></p>
      </section>

      <section className="l-proof" aria-labelledby="proof">
        <span className="l-eyebrow">What it did</span>
        <h2 id="proof">Tried on one real mesh</h2>
        <div className="proof">
          <div className="big-fact">
            <span className="k">Scorer in use now</span>
            <span className="num">{label}</span>
            <span className="line">{!state ? "waiting for the API" : stream ? `${stream.fallback_scored} of ${stream.scored_total} cycles scored via the rule fallback` : "no controller is scoring right now"}</span>
          </div>
          <div className="big-fact">
            <span className="k">Testbed</span>
            <span className="num">Bookinfo</span>
            <span className="line">on Istio, one cluster, {nodes.length} services</span>
          </div>
          <div className="big-fact">
            <span className="k">Shadow run <i className="tag">dry-run</i></span>
            <span className="num">{sh?.big ?? unavailable}</span>
            <span className="line">{sh?.line ?? "result file could not be read at build time"}</span>
          </div>
          <div className="big-fact">
            <span className="k">Live closed-loop runs</span>
            <span className="num stack">{lv ? lv.big.map((r) => <span key={r.scenario} className="nw">{r.t} <small>run {r.scenario}</small></span>) : unavailable}</span>
            <span className="line">{lv?.line ?? "result files could not be read at build time"}</span>
          </div>
        </div>
        <details className="l-details">
          <summary>Details and sources</summary>
          <ul className="plain">
            <li><b>Scorer in use</b> is read live from <code>/api/state</code>. The service list ({nodes.join(", ")}) comes from there too{facts.namespace ? `; the namespace (${facts.namespace.value}) from ${facts.namespace.file}` : ""}.</li>
            {sh && <li><b>Shadow run.</b> {sh.detail} Source: <code>{sh.file}</code>.</li>}
            {lv && <li><b>Live runs.</b> {lv.detail} Sources: <code>{lv.files}</code>.</li>}
            <li>Shadow and live figures were read from the result files when this page was built ({built} UTC). Rebuild after a new run.</li>
          </ul>
        </details>
      </section>

      <section className="l-limits" aria-labelledby="not">
        <span className="l-eyebrow"><CircleAlert size={14} aria-hidden="true" /> Honest limits</span>
        <h2 id="not">What this does not claim</h2>
        <div className="limits">
          <div><b>One testbed</b><p>Istio Bookinfo in one cluster. The model is hardcoded to its {nodes.length} services; the pipeline is what carries over.</p></div>
          <div><b>{ab ? ab.folds : "A few"} fault episodes</b><p>Leave-one-episode-out over recorded faults: a small sample.</p></div>
          <div><b>No better than a plain MLP</b><p>{ab ? `A no-graph MLP matched or beat the GNN on ${ab.mlpGeGnn} of ${ab.folds} folds (mean AP ${ab.mlpMean} against ${ab.gnnMean}).` : "A no-graph MLP matched or beat the GNN on detection."}</p></div>
          <div><b>{lv?.once ? "One live run each" : "Few live runs"}</b><p>RELEASE shows the release logic works, not that the probe catches a fault that is still there.</p></div>
        </div>
        <a className="l-more" href="#/evaluation">The Evaluation page has every table and caveat <ArrowRight size={14} aria-hidden="true" /></a>
      </section>

      <section className="l-cta" aria-labelledby="cta">
        <h2 id="cta">See it for yourself</h2>
        <div className="row">
          <a className="btn primary big" href="#/overview">Open live mesh <ArrowRight size={16} aria-hidden="true" /></a>
          <a className="btn big" href="#/evaluation">See evaluation</a>
        </div>
      </section>

      <footer className="l-footer">MeshHeal AI · Semester 5 mini project</footer>
    </div>
  );
}
