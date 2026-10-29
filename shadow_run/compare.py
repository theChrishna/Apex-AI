"""Compare the rule and GNN dry-run controllers on the shadow run. Read-only; writes results_shadow.md.

Definitions (all computed from the logs in this folder):
  run range      soak_start .. "done" in schedule_log.jsonl; audit events after it are counted but not analysed
  decision event REROUTE, ACTION_BLOCKED, SUPPRESSED_VICTIM
  detection      first decision event in [fault start, fault end]
  decay          (fault end, fault end + 120 s]: decision events here are neither detections nor false events
  false event    decision event in the run range outside every fault window and its decay (soak reported separately)
  INVALID        a telemetry gap > 30 s overlaps the soak, or a fault window plus its decay;
                 such a window is not counted as a detection or a miss
  RELEASE        reported with seconds after the end of the latest fault that ended before it
"""
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECAY = timedelta(seconds=120)
MAX_GAP_S = 30
DECISIONS = ("REROUTE", "ACTION_BLOCKED", "SUPPRESSED_VICTIM")
SCORERS = ("rule", "gnn")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def jsonl(name):
    return [json.loads(l) for l in open(HERE / name) if l.strip()]


def load():
    sched = {e["phase"]: ts(e["utc"]) for e in jsonl("schedule_log.jsonl") if e["phase"] in ("soak_start", "soak_end", "done")}
    faults = [dict(f, start=ts(f["start_utc"]), end=ts(f["end_utc"])) for f in jsonl("fault_log_shadow.jsonl")]
    snaps = sorted(ts(s["timestamp"]) for s in jsonl("snapshots.jsonl"))
    audits = {s: [dict(e, t=ts(e["ts"])) for e in jsonl(f"audit_{s}.jsonl")] for s in SCORERS}
    return sched, faults, snaps, audits


def gaps_in(snaps, lo, hi):
    """Gaps > MAX_GAP_S between consecutive snapshots that overlap [lo, hi]; a window with no snapshot is one gap."""
    out = [(a, b) for a, b in zip(snaps, snaps[1:]) if (b - a).total_seconds() > MAX_GAP_S and b > lo and a < hi]
    if not any(lo <= t <= hi for t in snaps):
        out.append((lo, hi))
    return out


def blamed(e):
    return e.get("culprit") if e["event"] == "SUPPRESSED_VICTIM" else e.get("node")


def fmt_ev(e, ref):
    return f"{e['event']} {blamed(e)} @ {e['t']:%H:%M:%S} (+{(e['t'] - ref).total_seconds():.0f} s, risk {e.get('risk')})"


def analyse(sched, faults, snaps, audits):
    run_lo, run_hi = sched["soak_start"], sched["done"]
    soak = (sched["soak_start"], sched["soak_end"])
    valid = {"soak": not gaps_in(snaps, *soak)}
    for i, f in enumerate(faults):
        valid[i] = not gaps_in(snaps, f["start"], f["end"] + DECAY)

    res = {}
    for s, evs in audits.items():
        run = [e for e in evs if run_lo <= e["t"] <= run_hi]
        dec = [e for e in run if e["event"] in DECISIONS]
        r = {"faults": [], "soak_false": [], "rest_false": [], "decay": [], "releases": [],
             "fallback": sum(1 for e in run if e["event"] == "SCORED" and e.get("source") == "fallback"),
             "scored": sum(1 for e in run if e["event"] == "SCORED"),
             "loop_errors": sum(1 for e in run if e["event"] == "LOOP_ERROR"),
             "rejected": sum(1 for e in run if e["event"] == "SNAPSHOT_REJECTED"),
             "after_run": sum(1 for e in evs if e["t"] > run_hi),
             "after_run_decisions": [e for e in evs if e["t"] > run_hi and e["event"] in DECISIONS]}
        for i, f in enumerate(faults):
            inwin = [e for e in dec if f["start"] <= e["t"] <= f["end"]]
            first = inwin[0] if inwin else None
            r["faults"].append({"fault": f, "valid": valid[i], "first": first, "all": inwin,
                                "latency_s": round((first["t"] - f["start"]).total_seconds(), 1) if first else None,
                                "correct": blamed(first) == f["node"] if first else None})
            r["decay"] += [(f, e) for e in dec if f["end"] < e["t"] <= f["end"] + DECAY]
        covered = [(f["start"], f["end"] + DECAY) for f in faults]
        for e in dec:
            if any(lo <= e["t"] <= hi for lo, hi in covered):
                continue
            (r["soak_false"] if soak[0] <= e["t"] <= soak[1] else r["rest_false"]).append(e)
        for e in run:
            if e["event"] == "RELEASE":
                prev = [f for f in faults if f["end"] <= e["t"]]
                r["releases"].append((e, prev[-1] if prev else None))
        res[s] = r
    return res, valid


def fault_label(f):
    return f"{f['node']} {f['delay']}"


def predictions(res, valid):
    """Each prediction line from predictions_shadow.md, split into checkable claims."""
    def fr(s, node, delay):
        return next(x for x in res[s]["faults"] if x["fault"]["node"] == node and x["fault"]["delay"] == delay)

    def is_(x, event, node):
        return bool(x["first"]) and x["first"]["event"] == event and blamed(x["first"]) == node

    lines = []
    r150, g150 = fr("rule", "ratings", "150ms"), fr("gnn", "ratings", "150ms")
    in_band = lambda x, lo, hi: x["latency_s"] is not None and lo <= x["latency_s"] <= hi
    lines.append(("ratings 150ms: rule REROUTE blaming ratings, 30-75 s after start; GNN same. (confidence high)", [
        ("rule first event is REROUTE ratings", is_(r150, "REROUTE", "ratings")),
        (f"rule latency in 30-75 s (got {r150['latency_s']})", in_band(r150, 30, 75)),
        ("GNN first event is REROUTE ratings", is_(g150, "REROUTE", "ratings")),
        (f"GNN latency in 30-75 s (got {g150['latency_s']})", in_band(g150, 30, 75))]))
    r75, g75 = fr("rule", "ratings", "75ms"), fr("gnn", "ratings", "75ms")
    lines.append(("ratings 75ms: rule may blame reviews (ACTION_BLOCKED); GNN REROUTE blaming ratings. (medium)", [
        ("rule blames reviews with ACTION_BLOCKED", is_(r75, "ACTION_BLOCKED", "reviews")),
        ("GNN first event is REROUTE ratings", is_(g75, "REROUTE", "ratings"))]))
    for node, delay, text in (("details", "75ms", "details 75ms: ACTION_BLOCKED no_healthy_alternative blaming details, both scorers. (medium)"),
                              ("reviews", "150ms", "reviews 150ms: ACTION_BLOCKED blaming reviews, both scorers. (medium-high)")):
        claims = []
        for s in SCORERS:
            x = fr(s, node, delay)
            ok = is_(x, "ACTION_BLOCKED", node) and (node != "details" or x["first"].get("reason") == "no_healthy_alternative")
            claims.append((f"{s} first event is ACTION_BLOCKED {node}" + (" no_healthy_alternative" if node == "details" else ""), ok))
        lines.append((text, claims))
    claims = []
    for s in SCORERS:
        n = len(res[s]["soak_false"])
        claims.append((f"{s} soak false events in 0-2 (got {n})", 0 <= n <= 2))
        claims.append((f"{s} soak REROUTEs = 0", not any(e["event"] == "REROUTE" for e in res[s]["soak_false"])))
    lines.append(("30 min no fault: 0-2 false events per scorer, 0 REROUTE. (low)", claims))
    lats = [x["latency_s"] for s in SCORERS for x in res[s]["faults"] if x["valid"] and x["latency_s"] is not None and x["correct"]]
    med = round(statistics.median(lats), 1) if lats else None
    lines.append(("Detection time for caught faults: 30-120 s after start, median about 60 s.", [
        (f"all {len(lats)} correct detections in 30-120 s (got {sorted(lats)})", bool(lats) and all(30 <= v <= 120 for v in lats)),
        (f"median within 45-75 s, my reading of 'about 60' (got {med})", med is not None and 45 <= med <= 75)]))
    return lines, lats, med


def report(sched, faults, snaps, res, valid):
    L = ["# Shadow run: rule vs GNN (dry-run)", "",
         f"Run range {sched['soak_start']:%Y-%m-%d %H:%M:%S} .. {sched['done']:%H:%M:%S} UTC. "
         f"Soak {sched['soak_start']:%H:%M:%S}-{sched['soak_end']:%H:%M:%S}. Decay after each fault: {DECAY.seconds} s. "
         f"Telemetry gap threshold: {MAX_GAP_S} s.", ""]
    L += ["## Telemetry continuity", "", "| window | span (UTC) | status |", "|---|---|---|",
          f"| soak | {sched['soak_start']:%H:%M:%S}-{sched['soak_end']:%H:%M:%S} | {'valid' if valid['soak'] else 'INVALID'} |"]
    for i, f in enumerate(faults):
        L.append(f"| {fault_label(f)} | {f['start']:%H:%M:%S}-{(f['end'] + DECAY):%H:%M:%S} | {'valid' if valid[i] else 'INVALID'} |")
    gaps = [(a, b) for a, b in zip(snaps, snaps[1:]) if (b - a).total_seconds() > MAX_GAP_S and b > sched["soak_start"] and a < sched["done"]]
    L += ["", f"Gaps > {MAX_GAP_S} s inside the run range: {len(gaps)}" + "".join(f"\n- {a:%H:%M:%S} -> {b:%H:%M:%S}" for a, b in gaps), ""]

    L += ["## Fault windows", "", "| fault | scorer | first decision event | s after start | blamed | correct | events in window |",
          "|---|---|---|---|---|---|---|"]
    for i, f in enumerate(faults):
        for s in SCORERS:
            x = res[s]["faults"][i]
            if not x["valid"]:
                L.append(f"| {fault_label(f)} | {s} | INVALID (not counted) | | | | |")
            elif x["first"]:
                e = x["first"]
                L.append(f"| {fault_label(f)} | {s} | {e['event']}{' ' + e['reason'] if e.get('reason') else ''} @ {e['t']:%H:%M:%S} | "
                         f"{x['latency_s']:.1f} | {blamed(e)} | {'yes' if x['correct'] else 'NO'} | {len(x['all'])} |")
            else:
                L.append(f"| {fault_label(f)} | {s} | none (miss) | | | | 0 |")
    L.append("")

    L += ["## False events and decay events", ""]
    for s in SCORERS:
        r = res[s]
        L.append(f"**{s}**: soak false events {len(r['soak_false'])}; rest-period false events {len(r['rest_false'])}; "
                 f"decision events inside a 120 s decay {len(r['decay'])}.")
        for e in r["soak_false"]:
            L.append(f"- soak: {fmt_ev(e, sched['soak_start'])} from soak start")
        for e in r["rest_false"]:
            L.append(f"- rest: {fmt_ev(e, sched['soak_start'])} from soak start")
        for f, e in r["decay"]:
            L.append(f"- decay after {fault_label(f)}: {fmt_ev(e, f['end'])} after fault end")
        L.append("")

    L += ["## Scorer health", "", "| scorer | SCORED | source=fallback | LOOP_ERROR | SNAPSHOT_REJECTED |", "|---|---|---|---|---|"]
    for s in SCORERS:
        r = res[s]
        L.append(f"| {s} | {r['scored']} | {r['fallback']} | {r['loop_errors']} | {r['rejected']} |")
    L += ["", f"GNN fallback count must be 0: {'OK' if res['gnn']['fallback'] == 0 else 'FAILED'}.", ""]

    L += ["## RELEASE events", ""]
    for s in SCORERS:
        for e, f in res[s]["releases"]:
            rel = f"{(e['t'] - f['end']).total_seconds():.1f} s after {fault_label(f)} ended" if f else "before any fault ended"
            L.append(f"- {s}: RELEASE {e.get('culprit')} @ {e['t']:%H:%M:%S}, {rel} (risk {e.get('risk')})")
        if not res[s]["releases"]:
            L.append(f"- {s}: none")
    L += ["", "Dry-run: the reroute was never applied, so the probe and release only show when the culprit's "
          "score fell after the fault was removed, not a recovery caused by the controller.", ""]

    lines, lats, med = predictions(res, valid)
    L += ["## Predictions (predictions_shadow.md) vs result", ""]
    for text, claims in lines:
        ok = all(c[1] for c in claims)
        L.append(f"- **{'RIGHT' if ok else 'WRONG'}**: {text}")
        for c, v in claims:
            L.append(f"  - {'ok' if v else 'wrong'}: {c}")
    L += ["", f"Correct detections used for the timing line: {len(lats)}; median {med} s.", ""]

    L += ["## After the run range (not analysed)", ""]
    for s in SCORERS:
        r = res[s]
        L.append(f"- {s}: {r['after_run']} audit events after {sched['done']:%H:%M:%S}, "
                 f"{len(r['after_run_decisions'])} of them decision events")
    return "\n".join(L) + "\n"


def main():
    sched, faults, snaps, audits = load()
    res, valid = analyse(sched, faults, snaps, audits)
    text = report(sched, faults, snaps, res, valid)
    (HERE / "results_shadow.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
