import { useState } from "react";
import { State, fmtAge } from "../api";

/** Simple own mark: four linked nodes. */
export function Mark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <g stroke="#fff" strokeWidth="2" fill="none"><path d="M9 9l14 5M9 9l5 14M23 14l-9 9" /></g>
      <g fill="#fff"><circle cx="9" cy="9" r="3" /><circle cx="23" cy="14" r="3" /><circle cx="14" cy="23" r="3" /></g>
    </svg>
  );
}

export function CodeBlock({ code, label = "bash" }: { code: string; label?: string }) {
  const [state, setState] = useState<"idle" | "done" | "fail">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setState("done");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = code; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); setState("done"); } catch { setState("fail"); }
      ta.remove();
    }
    window.setTimeout(() => setState("idle"), 1800);
  };
  return (
    <div className="code">
      <div className="code-head">
        <span className="dots" aria-hidden="true"><i /><i /><i /><span style={{ marginLeft: 8 }}>{label}</span></span>
        <button className="copy" onClick={copy} aria-label={`Copy ${label} commands`}>{state === "done" ? "Copied" : state === "fail" ? "Copy failed" : "Copy"}</button>
      </div>
      <pre tabIndex={0}>{code.split("\n").map((l, i) => (
        <div key={i}>{l.startsWith("#") || !l ? <span style={{ color: "var(--code-muted)" }}>{l}</span> : <><span className="prompt">$ </span>{l}</>}</div>
      ))}</pre>
    </div>
  );
}

export function ModeBanner({ s, error }: { s: State | null; error: string | null }) {
  if (error && !s) return <div className="banner problem" role="alert">Cannot reach the local API ({error}). Start it with <code>python Frontend_v2/api/meshheal_api.py --mode live</code>. Nothing below is real data.</div>;
  if (!s) return <div className="banner">Loading…</div>;
  return (
    <>
      <div className={`banner ${s.mode === "REPLAY" ? "replay" : "live"}`} role="status">
        <b>{s.mode}</b>: {s.label}. {s.import_error ? `Per-node risk unavailable: ${s.import_error}` : ""}
      </div>
      {error && <div className="banner problem" role="alert">Connection lost ({error}); showing the last data received.</div>}
    </>
  );
}

export function StatusStrip({ s }: { s: State | null }) {
  const st = s?.status;
  const age = st?.snapshot_age_s ?? null;
  const cell = (k: string, v: React.ReactNode, tone?: string) => (
    <div><span className="k">{k}</span><span className="v">{tone ? <span className={`pill ${tone}`}>{v}</span> : v}</span></div>
  );
  return (
    <div className="strip" aria-live="polite">
      {cell("Mode", s?.mode ?? "…", s?.mode === "REPLAY" ? "warn" : "ok")}
      {cell("Scorer in use", st?.scorer_in_use ? st.scorer_in_use.toUpperCase() : "none running", st?.scorer_in_use ? "accent" : "crit")}
      {cell("GNN or fallback", st?.scorer_source ?? "n/a", st?.scorer_source ? (st.scorer_source.startsWith("FALLBACK") ? "warn" : st.scorer_source === "GNN" ? "ok" : "accent") : "")}
      {cell("Last snapshot age", fmtAge(age), st ? (st.snapshot_stale ? "crit" : "ok") : "")}
    </div>
  );
}

export const riskColor = (r: number | undefined) =>
  r === undefined ? "var(--surface-2)" : r >= 0.85 ? "var(--crit)" : r >= 0.5 ? "var(--warn)" : "var(--ok)";
export const riskSoft = (r: number | undefined) =>
  r === undefined ? "var(--surface-2)" : r >= 0.85 ? "var(--crit-soft)" : r >= 0.5 ? "var(--warn-soft)" : "var(--ok-soft)";
