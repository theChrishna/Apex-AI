// Reads the result files that the API does not expose (it only passes markdown tables through) and writes
// src/generated/facts.json for the Home page. Read-only on everything outside Frontend_v3. A fact that cannot be
// parsed is written as null and the page says it is unavailable; nothing is filled in by hand.
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const warn = (msg) => console.warn(`extract-facts: ${msg}`);
const read = (rel) => {
  const p = join(root, rel);
  if (!existsSync(p)) { warn(`${rel} not found`); return null; }
  return readFileSync(p, "utf8");
};
const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
const secs = (hms) => { const [h, m, s] = hms.split(":").map(Number); return h * 3600 + m * 60 + s; };

function shadow() {
  const file = "shadow_run/results_shadow.md";
  const text = read(file);
  if (!text) return null;
  const lines = text.split("\n");

  const start = lines.findIndex((l) => l.startsWith("## Fault windows"));
  const rows = [];
  let header = null;
  for (const l of lines.slice(start + 1)) {
    if (l.startsWith("## ")) break;
    if (!l.startsWith("|")) continue;
    const c = cells(l);
    if (!header) header = c;
    else if (!c.every((x) => /^:?-{2,}:?$/.test(x))) rows.push(Object.fromEntries(header.map((h, i) => [h, c[i]])));
  }
  const scorers = {};
  for (const r of rows) {
    const s = (scorers[r.scorer] ??= { faults: new Set(), correct: new Set() });
    s.faults.add(r.fault);
    if (r.correct === "yes") s.correct.add(r.fault);
  }
  const perScorer = Object.fromEntries(Object.entries(scorers).map(([k, v]) => [k, { faults: v.faults.size, correct: v.correct.size }]));

  const soak = text.match(/Soak (\d\d:\d\d:\d\d)-(\d\d:\d\d:\d\d)/);
  const soakMinutes = soak ? (secs(soak[2]) - secs(soak[1])) / 60 : null;
  const falseEv = {};
  for (const m of text.matchAll(/\*\*(\w+)\*\*: soak false events (\d+); rest-period false events (\d+); decision events inside a (\d+) s decay (\d+)/g)) {
    falseEv[m[1]] = { soak: Number(m[2]), rest: Number(m[3]), decaySeconds: Number(m[4]), decayEvents: Number(m[5]) };
  }
  if (!Object.keys(perScorer).length || !Object.keys(falseEv).length || soakMinutes === null) { warn(`could not parse ${file}`); return null; }
  return { file, perScorer, soakMinutes, falseEvents: falseEv };
}

function live() {
  const dir = join(root, "live_demo");
  if (!existsSync(dir)) { warn("live_demo/ not found"); return null; }
  const runs = readdirSync(dir).filter((f) => /^result_[A-Z]_.*\.json$/.test(f)).sort().map((f) => {
    const j = JSON.parse(readFileSync(join(dir, f), "utf8"));
    return { file: `live_demo/${f}`, scenario: j.scenario, scorer: j.scorer, culprit: j.reroute_culprit, detectS: j.detect_s_after_fault, scoredViaFallback: j.scored_via_fallback, firstSource: j.first_scored?.source ?? null };
  });
  if (!runs.length || runs.some((r) => typeof r.detectS !== "number")) { warn("could not parse live_demo/result_*.json"); return null; }
  return runs;
}

function namespace() {
  const m = read("meshheal_controlplane/controlplane/config.py")?.match(/namespace:\s*str\s*=\s*"([^"]+)"/);
  if (!m) warn("namespace not found in config.py");
  return m ? { value: m[1], file: "meshheal_controlplane/controlplane/config.py" } : null;
}

const facts = { generated: new Date().toISOString(), shadow: shadow(), live: live(), namespace: namespace() };
mkdirSync(join(here, "..", "src", "generated"), { recursive: true });
writeFileSync(join(here, "..", "src", "generated", "facts.json"), JSON.stringify(facts, null, 2) + "\n");
console.log("extract-facts: wrote src/generated/facts.json", JSON.stringify({ shadow: !!facts.shadow, live: facts.live?.length ?? null, namespace: !!facts.namespace }));
