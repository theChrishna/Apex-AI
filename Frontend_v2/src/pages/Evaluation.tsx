import { Evaluation as Ev, MdTable, usePoll } from "../api";

function pick(ev: Ev | null, key: string, headingStart: string): MdTable | undefined {
  return ev?.[key]?.tables.find((t) => t.heading.startsWith(headingStart));
}

function Table({ ev, k, heading, title, note }: { ev: Ev | null; k: string; heading: string; title: string; note?: string }) {
  const t = pick(ev, k, heading);
  return (
    <div>
      <h3 style={{ marginBottom: 8 }}>{title}</h3>
      {!ev ? <div className="banner">Loading…</div> : !t ? (
        <div className="banner problem" role="alert">Table “{heading}” not found in {ev[k]?.missing ? `${ev[k].file} (file missing)` : ev[k]?.file ?? k}.</div>
      ) : (
        <div className="table-wrap" tabIndex={0} role="region" aria-label={title}>
          <table>
            <thead><tr>{t.header.map((h, i) => <th key={i} scope="col">{h}</th>)}</tr></thead>
            <tbody>{t.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} style={c.startsWith("**") ? { fontWeight: 700 } : undefined}>{c.replace(/\*\*/g, "")}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      <p className="src">source: {ev?.[k]?.file ?? k} › {heading}{note ? ` · ${note}` : ""}</p>
    </div>
  );
}

export default function Evaluation() {
  const { data: ev, error } = usePoll<Ev>("/api/evaluation", 0);
  return (
    <>
      <div className="page-head">
        <span className="eyebrow">Evaluation</span>
        <h1 style={{ fontSize: "clamp(2rem,4.5vw,3rem)" }}>What the numbers say, and what they do not</h1>
        <p>Tables are read straight from the result files in the repository and shown unchanged; nothing is recomputed or rounded here. If a file or table is missing you will see an error, not a placeholder.</p>
      </div>
      {error && <div className="banner problem" role="alert">Cannot reach the API ({error}). No evaluation data is shown.</div>}

      <section className="section" style={{ marginTop: 0 }}>
        <div className="card flat">
          <h3>Read this first</h3>
          <ul className="plain">
            <li><b>No-graph MLP matches or beats the GNN.</b> The Control 3 tables below have an MLP column; per CLAUDE.md the MLP beats or ties the GNN on every fold. Message passing adds nothing measurable on 4 nodes.</li>
            <li><b>Two AP methods.</b> GNN mean AP is 0.923 with the trapezoidal method (results_loeo.md) and 0.928 with the distinct-threshold method (results_controls.md). The p95 baseline is 0.898 versus 0.930. Distinct-threshold is the correct one: the p95 baseline has many tied zero scores and the trapezoidal result depends on sort order among ties.</li>
            <li><b>One testbed, 8 episodes, 4 hardcoded services.</b> The deliverable is the pipeline (collect, label, train per deployment), not a model that transfers.</li>
            <li><b>Final model is in-sample.</b> The deployed GNN (5 seeds) is trained on all 8 episodes, so replaying those episodes through it is not an accuracy result. LOEO is the evaluation.</li>
            <li><b>Label noise in the "normal" data (found on 2026-10-06 and 2026-09-16, then checked with a sensitivity run).</b> 50 of the 70 holdout snapshots from 2026-10-06 show details p95 above 50 ms from 10:45 to 10:58 UTC, consistent with an unlogged details fault; 128 non-holdout snapshots from 2026-09-16 show productpage to reviews p95 of about 242 ms (at more than 0.1 req/s) yet are labelled normal. The v3 check (REPORT_V3.md) excludes 215 snapshots (147 training, 68 holdout) and retrains: the p95 baseline and the culprit rule are unchanged; GNN AP moves 0.928 to 0.898 and MLP AP 0.983 to 0.955, changes about the size of the seed noise (GNN seed std up to 0.39 in one fold), so I cannot say the removal caused them; holdout false-positive rate falls (baseline 0.140 to 0.039, GNN 0.128 to 0.031, on holdouts of 137 and 69 snapshots). The v3 policy false-action numbers are not comparable with v1 (the holdout split differs). The demo still uses the v1 model.</li>
            <li><b>GNN false-alarm rate is unstable across seeds</b> (3 to 20 % in the policy simulation, per CLAUDE.md) and thresholds vary per seed, so the GNN must be seed-averaged and gated by the rule detector.</li>
            <li><b>Shadow run is dry-run.</b> Controllers never wrote to the cluster, so probe and release show only when the score fell, not a recovery they caused. Only <code>ratings</code> has a reroute; faults on other services end as ACTION_BLOCKED.</li>
            <li><b>Two live closed-loop runs (2026-10-29), one run each, 150 ms fault on ratings.</b> Scenario A (GNN scores): REROUTE of ratings 78.2 s after the fault; median productpage latency 0.172 s while faulted, back to baseline (0.023 s) within about 2 s of the reroute; probe at 70/15/15, then RELEASE 174 s after the fault was removed; all 21 SCORED events from the GNN, none from the fallback. Scenario B (kill file, rule fallback scores): REROUTE 63.7 s after the fault; median 0.182 s to 0.024 s; RELEASE 174.9 s after the fault was removed; all 19 SCORED events from the fallback. The 14 s gap in detection is unexplained and is probably one extra controller cycle (A acted on the 4th high-risk cycle, B on the 3rd), not a scorer effect; detection is about 60 to 80 s, set by the persistence rule. In both runs the fault was removed before the probe started, so RELEASE shows the release logic works, not that the probe catches a fault that is still present. These are single runs: no rate or average.</li>
          </ul>
        </div>
      </section>

      <section className="section" aria-labelledby="loeo"><h2 id="loeo">Leave-one-episode-out (8 folds)</h2>
        <Table ev={ev} k="loeo" heading="1. Threshold-Free Metrics" title="AP and AUROC, trapezoidal AP" note="BL = p95 latency baseline" />
        <Table ev={ev} k="loeo" heading="3. Root-Cause Top-1" title="Root-cause top-1 accuracy" />
      </section>

      <section className="section" aria-labelledby="abl"><h2 id="abl">Ablation: no-graph MLP, culprit rule, distinct-threshold AP</h2>
        <Table ev={ev} k="controls" heading="Average Precision" title="AP by fold (distinct-threshold)" note="p95-BL, culprit rule, MLP, GNN" />
        <Table ev={ev} k="controls" heading="Root-Cause Top-1" title="Root-cause top-1 by fold" />
        <Table ev={ev} k="controls" heading="Control 4" title="AP: old trapezoidal vs distinct-threshold" />
      </section>

      <section className="section" aria-labelledby="shadow"><h2 id="shadow">Shadow run (2026-10-26, dry-run, rule and GNN)</h2>
        <Table ev={ev} k="shadow" heading="Fault windows" title="First decision event per fault window" note="4 faults of 5 min after a 30 min soak; produced by shadow_run/compare.py" />
        <Table ev={ev} k="shadow" heading="Scorer health" title="Scorer health" />
        <Table ev={ev} k="shadow" heading="Telemetry continuity" title="Telemetry continuity inside the run" />
        <p className="src">Detection times cluster at about 60 and 75 s, i.e. 4 or 5 controller cycles of 15 s: the persistence rule sets the timing, not the scorer. Predictions versus results are in shadow_run/results_shadow.md.</p>
      </section>
    </>
  );
}
