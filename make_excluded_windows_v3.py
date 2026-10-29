"""Build excluded_windows_v3.json from the data (nothing typed by hand except the two criteria).

(a) Sep 16 non-holdout snapshots where any edge has p95 >= 97.5 ms at request_rate > 0.1, grouped into runs
    (a new run when the gap between flagged snapshots exceeds the buffer), each run padded by 120 s on both sides.
(b) The 2026-10-06 holdout stretch 10:42:56 to 10:59:59 UTC (found by the earlier investigation), padded by 120 s.
Only snapshots of phase "normal" are ever excluded; the script asserts that no episode snapshot is touched.

    python make_excluded_windows_v3.py        # from the project root; writes excluded_windows_v3.json (refuses to overwrite)
"""
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from build_dataset_v2 import SNAPSHOTS_PATH, build_normal_holdout_ts, load_all_records

OUT = "excluded_windows_v3.json"
BUFFER = timedelta(seconds=120)
P95_MS, MIN_RATE = 97.5, 0.1
A_DATE = "2026-09-16"
B_START = datetime.fromisoformat("2026-10-06T10:42:56+00:00")
B_END = datetime.fromisoformat("2026-10-06T10:59:59+00:00")


def ts(s):
    return datetime.fromisoformat(s)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def iso(dt):
    return dt.isoformat()


def main():
    if os.path.exists(OUT):
        sys.exit(f"refusing to overwrite {OUT}")
    recs = load_all_records()
    hold = build_normal_holdout_ts(recs)
    recs = sorted(recs, key=lambda r: r["timestamp"])

    # (a) flagged Sep 16 non-holdout snapshots
    flagged = []
    for r in recs:
        if not r["timestamp"].startswith(A_DATE) or r["timestamp"] in hold:
            continue
        hits = [e for e in r["edges"] if (e["latency_p95"] or 0) >= P95_MS and (e["request_rate"] or 0) > MIN_RATE]
        if hits:
            flagged.append((r, hits))
    runs = []
    for r, hits in flagged:
        t = ts(r["timestamp"])
        if runs and t - runs[-1]["_last"] <= BUFFER:
            run = runs[-1]
        else:
            run = {"_first": t, "_last": t, "n_flagged": 0, "max_p95_ms": 0.0, "edges": Counter()}
            runs.append(run)
        run["_last"] = t
        run["n_flagged"] += 1
        for e in hits:
            run["max_p95_ms"] = max(run["max_p95_ms"], e["latency_p95"])
            run["edges"][f"{e['source']}>{e['destination']}"] += 1
    windows = []
    for i, run in enumerate(runs):
        windows.append({"id": f"A{i + 1}", "kind": "sep16_edge_p95_ge_97.5_at_rate_gt_0.1",
                        "run_first": iso(run["_first"]), "run_last": iso(run["_last"]), "n_flagged_snapshots": run["n_flagged"],
                        "max_p95_ms": round(run["max_p95_ms"], 1), "edges": dict(run["edges"]),
                        "start": iso(run["_first"] - BUFFER), "end": iso(run["_last"] + BUFFER)})
    windows.append({"id": "B1", "kind": "oct6_holdout_unlogged_fault_stretch", "run_first": iso(B_START), "run_last": iso(B_END),
                    "start": iso(B_START - BUFFER), "end": iso(B_END + BUFFER)})

    excluded, per_window = [], Counter()
    for r in recs:
        t = ts(r["timestamp"])
        w = [w["id"] for w in windows if ts(w["start"]) <= t <= ts(w["end"])]
        if not w:
            continue
        assert r["phase"] == "normal", f"episode snapshot inside an excluded window: {r['timestamp']} {r['phase']}"
        excluded.append(r["timestamp"])
        for x in w:
            per_window[x] += 1
    ex = set(excluded)
    out = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "criteria": {"a": f"{A_DATE} non-holdout snapshots with any edge p95 >= {P95_MS} ms at request_rate > {MIN_RATE}, grouped into runs "
                          f"(new run when flagged snapshots are more than the buffer apart), padded by the buffer",
                     "b": "2026-10-06 holdout stretch 10:42:56 to 10:59:59 UTC, padded by the buffer",
                     "buffer_s": int(BUFFER.total_seconds()), "applies_to": "phase=normal snapshots only (training normals and the holdout)"},
        "data": {"snapshots_path": SNAPSHOTS_PATH, "snapshots_sha256": sha256(SNAPSHOTS_PATH), "snapshot_records": len(recs)},
        "windows": windows,
        "counts": {
            "flagged_sep16_non_holdout": len(flagged),
            "excluded_total": len(excluded),
            "excluded_per_window": dict(per_window),
            "excluded_in_v2_holdout": sum(t in hold for t in ex),
            "excluded_in_training_normals": sum(t not in hold for t in ex),
            "v2_holdout_size": len(hold),
            "v3_holdout_size": len(hold - ex),
        },
        "excluded_timestamps": excluded,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    c = out["counts"]
    print(f"flagged Sep 16 non-holdout snapshots: {c['flagged_sep16_non_holdout']} in {len(runs)} runs")
    for w in windows:
        print(f"  {w['id']}: run {w['run_first'][5:19]} .. {w['run_last'][5:19]}  window {w['start'][5:19]} .. {w['end'][5:19]}"
              + (f"  flagged={w['n_flagged_snapshots']} max={w['max_p95_ms']} edges={w['edges']}" if "n_flagged_snapshots" in w else ""))
    print("counts:", {k: v for k, v in c.items()})


if __name__ == "__main__":
    main()
