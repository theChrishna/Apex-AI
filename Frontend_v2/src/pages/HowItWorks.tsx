import { CodeBlock } from "../components/common";

const STEPS = [
  ["Read", "Every 15 s the newest snapshot is read. Stale (over 45 s), NaN or missing-node snapshots are rejected and logged."],
  ["Score", "The rule scorer uses in_lat − out_lat per node (a victim waiting on a slow callee cancels out). The GNN scorer has a 500 ms budget, then the rule takes over and the audit line says fallback."],
  ["Persist", "A node must be the top risk above 0.85 in 3 of the last 4 cycles, and also in the current cycle."],
  ["Check", "Playbook entry, target pod ready, no dependency on the faulty node, healthy alternative, cooldown. Otherwise ACTION_BLOCKED with the reason."],
  ["Act", "Patch the reviews VirtualService (all traffic to v1 when ratings is the culprit). After the cooldown, probe with 90/5/5."],
  ["Release", "Return to 34/33/33 only if risk is below 0.60 with real traffic (at least 0.05 req/s). Otherwise PROBE_FAILED and stay rerouted."],
];

export default function HowItWorks() {
  return (
    <>
      <div className="page-head">
        <span className="eyebrow">How it works</span>
        <h1 style={{ fontSize: "clamp(2rem,4.5vw,3rem)" }}>The loop, and how to run it</h1>
        <p>Run every command from the project root with the Python venv active. Commands marked read-only never write to the cluster.</p>
      </div>

      <section className="section" style={{ marginTop: 0 }} aria-labelledby="loop"><h2 id="loop">Control loop</h2>
        <div className="grid">
          {STEPS.map(([t, d], i) => (
            <div key={t} className="card step flat"><span className="n">{i + 1}</span><div><h3>{t}</h3><p>{d}</p></div></div>
          ))}
        </div>
      </section>

      <section className="section" aria-labelledby="run"><h2 id="run">Run this dashboard</h2>
        <div className="two">
          <div style={{ display: "grid", gap: 10 }}><h3>Live (reads the files in the repo)</h3>
            <CodeBlock code={"cd Frontend_v2 && npm install && npm run build && cd ..\n.venv/bin/python Frontend_v2/api/meshheal_api.py --mode live\n# open http://127.0.0.1:8765"} /></div>
          <div style={{ display: "grid", gap: 10 }}><h3>Replay of the shadow run (labelled REPLAY)</h3>
            <CodeBlock code={".venv/bin/python Frontend_v2/api/meshheal_api.py --mode replay --speed 10\n# open http://127.0.0.1:8765"} /></div>
          <div style={{ display: "grid", gap: 10 }}><h3>Development server</h3>
            <CodeBlock code={".venv/bin/python Frontend_v2/api/meshheal_api.py --mode live &\ncd Frontend_v2 && npm run dev"} /></div>
        </div>
      </section>

      <section className="section" aria-labelledby="cp"><h2 id="cp">Run the control plane</h2>
        <div className="two">
          <div style={{ display: "grid", gap: 10 }}><h3>Tests and replay (no cluster)</h3>
            <CodeBlock code={"cd meshheal_controlplane\n../.venv/bin/python -m pytest -q\n../.venv/bin/python -m controlplane.run --snapshots ../snapshots.jsonl --replay"} /></div>
          <div style={{ display: "grid", gap: 10 }}><h3>Dry-run against the cluster (read-only)</h3>
            <CodeBlock code={"cd meshheal_controlplane\n../.venv/bin/python -m controlplane.run --scorer gnn --dry-run \\\n  --snapshots ../shadow_run/snapshots.jsonl --audit ../shadow_run/audit_gnn.jsonl"} /></div>
          <div style={{ display: "grid", gap: 10 }}><h3>GNN kill switch for the demo</h3>
            <CodeBlock code={"# add --gnn-kill-file /tmp/gnn.off to the command above, then:\ntouch /tmp/gnn.off   # GNN raises, rule fallback scores\nrm /tmp/gnn.off      # GNN is back"} /></div>
        </div>
      </section>

      <section className="section" aria-labelledby="safe"><h2 id="safe">Before you inject faults</h2>
        <div className="card flat"><ul className="plain">
          <li><b>Always delete fault VirtualServices afterwards</b> and check with <code>kubectl get virtualservice -n aws-us-east</code>. Only the normal <code>reviews</code> rule should remain.</li>
          <li><b>Never delete the reviews VirtualService.</b> Restore it with <code>kubectl apply -f reviews-normal.yaml</code>.</li>
          <li>Keep the laptop plugged in and awake for any timed run; memory pressure on a 16 GB machine causes flaky errors.</li>
        </ul></div>
      </section>
    </>
  );
}
