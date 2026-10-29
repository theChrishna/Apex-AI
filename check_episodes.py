"""
check_episodes.py - sanity-check the data collected by run_faults.py.

Reads snapshots.jsonl, latency_mean.jsonl and fault_log.jsonl (same folder) and,
for each completed episode, compares the faulted node's INCOMING edge latency
before the fault vs during the steady part of the fault.

Usage:  python check_episodes.py
"""
import json
import statistics
from datetime import datetime, timedelta

SNAPSHOTS = "snapshots.jsonl"
MEANS = "latency_mean.jsonl"
FAULT_LOG = "fault_log.jsonl"
LAG_SECONDS = 90      # first part of a fault: the 1-minute rate window is still catching up
PRE_SECONDS = 60      # last minute of recovery, used as the "normal" reference


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def ts(text):
    return datetime.fromisoformat(text)


def incoming_values(rows, node, field, lo, hi):
    """Values of `field` on edges whose destination is `node`, for rows with lo <= time < hi."""
    values = []
    for row in rows:
        if lo <= ts(row["timestamp"]) < hi:
            for edge in row["edges"]:
                if edge["destination"] == node and field in edge:
                    value = edge[field]
                    if value == value:   # skip NaN
                        values.append(value)
    return values


def med(values):
    return f"{statistics.median(values):7.1f}" if values else "    n/a"


def main():
    snaps = load(SNAPSHOTS)
    means = load(MEANS)
    episodes = [e for e in load(FAULT_LOG) if e.get("completed")]
    if not episodes:
        print("No completed episodes in fault_log.jsonl")
        return

    print(f"{'ep':>2} {'node':8} {'delay':>6} | {'p95 pre':>7} {'p95 fault':>9} | "
          f"{'mean pre':>8} {'mean fault':>10} | snaps (lag/steady)")
    for e in episodes:
        node, start, end = e["node"], ts(e["start"]), ts(e["end"])
        pre_lo = start - timedelta(seconds=PRE_SECONDS)
        steady_lo = start + timedelta(seconds=LAG_SECONDS)
        lag_n = len(incoming_values(snaps, node, "latency_p95", start, steady_lo))
        steady_n = len(incoming_values(snaps, node, "latency_p95", steady_lo, end))
        p95_pre = incoming_values(snaps, node, "latency_p95", pre_lo, start)
        p95_fault = incoming_values(snaps, node, "latency_p95", steady_lo, end)
        mean_pre = incoming_values(means, node, "latency_mean", pre_lo, start)
        mean_fault = incoming_values(means, node, "latency_mean", steady_lo, end)
        print(f"{e['episode']:>2} {node:8} {e['delay_ms']:>4}ms | {med(p95_pre):>7} {med(p95_fault):>9} | "
              f"{med(mean_pre):>8} {med(mean_fault):>10} | {lag_n}/{steady_n}")

    # Coverage: did telemetry.py keep saving for the whole run?
    run_lo = ts(episodes[0]["start"]) - timedelta(minutes=3)
    run_hi = ts(episodes[-1]["end"]) + timedelta(minutes=3)
    times = sorted(ts(r["timestamp"]) for r in snaps if run_lo <= ts(r["timestamp"]) <= run_hi)
    print(f"\nSnapshots saved during the run window: {len(times)} "
          f"(expected about {int((run_hi - run_lo).total_seconds() // 15)})")
    if len(times) > 1:
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        big = [(times[i], g) for i, g in enumerate(gaps) if g > 30]
        print(f"Largest gap between snapshots: {max(gaps):.0f}s; gaps over 30s: {len(big)}")
        for when, gap in big[:10]:
            print(f"  gap of {gap:.0f}s after {when.isoformat()}")
    print(f"First snapshot in window: {times[0].isoformat() if times else 'none'}")
    print(f"Last snapshot in window:  {times[-1].isoformat() if times else 'none'}")
    print(f"Run window ended at:      {run_hi.isoformat()}")


if __name__ == "__main__":
    main()