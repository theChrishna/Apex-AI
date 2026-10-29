"""Shadow-run schedule: 30 min soak, then 4 faults (5 min each, 6 min rest after each).

Only kubectl writes: apply a fault YAML, delete the ratings/details fault VirtualService,
apply reviews-normal.yaml. The `reviews` VirtualService is never deleted.

  fault_log_shadow.jsonl  one line per fault {node, delay, start_utc, end_utc}, written when the fault is restored
                          (or when cleanup interrupts it, with "aborted": true)
  schedule_log.jsonl      every phase boundary (soak, apply, restore, rest, done) as it happens
"""
import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NS = "aws-us-east"
REVIEWS_NORMAL = ROOT / "reviews-normal.yaml"
FAULT_LOG = HERE / "fault_log_shadow.jsonl"
SCHED_LOG = HERE / "schedule_log.jsonl"

SOAK_S, FAULT_S, REST_S = 30 * 60, 5 * 60, 6 * 60
FAULTS = [  # (node, delay, yaml, restore)
    ("ratings", "150ms", "fault-ratings-150.yaml", "delete"),
    ("details", "75ms", "fault-details-75.yaml", "delete"),
    ("reviews", "150ms", "fault-reviews-150.yaml", "apply_normal"),
    ("ratings", "75ms", "fault-ratings-75.yaml", "delete"),
]


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def append(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")


def kubectl(*args):
    r = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    print(f"[{utc()}] kubectl {' '.join(args)} -> rc={r.returncode} {r.stdout.strip()} {r.stderr.strip()}", flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} failed: {r.stderr.strip()}")


def restore(node, how):
    if how == "delete":
        kubectl("delete", "virtualservice", node, "-n", NS, "--ignore-not-found")
    else:
        kubectl("apply", "-n", NS, "-f", str(REVIEWS_NORMAL))


def cleanup():
    """Never raises: try every step."""
    for vs in ("ratings", "details"):
        try:
            kubectl("delete", "virtualservice", vs, "-n", NS, "--ignore-not-found")
        except Exception as e:
            print("cleanup error:", e, flush=True)
    try:
        kubectl("apply", "-n", NS, "-f", str(REVIEWS_NORMAL))
    except Exception as e:
        print("cleanup error:", e, flush=True)


def on_signal(signum, frame):
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, on_signal)
    current = None   # (node, delay, how, start_utc) while a fault is applied
    try:
        append(SCHED_LOG, {"phase": "soak_start", "utc": utc(), "duration_s": SOAK_S})
        time.sleep(SOAK_S)
        append(SCHED_LOG, {"phase": "soak_end", "utc": utc()})
        for node, delay, yml, how in FAULTS:
            start = utc()
            current = (node, delay, how, start)
            kubectl("apply", "-n", NS, "-f", str(HERE / yml))
            start = utc()   # stamp after the apply returns
            current = (node, delay, how, start)
            append(SCHED_LOG, {"phase": "fault_applied", "node": node, "delay": delay, "utc": start})
            time.sleep(FAULT_S)
            restore(node, how)
            end = utc()
            append(FAULT_LOG, {"node": node, "delay": delay, "start_utc": start, "end_utc": end})
            append(SCHED_LOG, {"phase": "fault_restored", "node": node, "delay": delay, "utc": end})
            current = None
            append(SCHED_LOG, {"phase": "rest_start", "utc": utc(), "duration_s": REST_S})
            time.sleep(REST_S)
        append(SCHED_LOG, {"phase": "done", "utc": utc()})
    except KeyboardInterrupt:
        append(SCHED_LOG, {"phase": "interrupted", "utc": utc()})
        print("interrupted, cleaning up", flush=True)
    finally:
        cleanup()
        if current:
            node, delay, _, start = current
            append(FAULT_LOG, {"node": node, "delay": delay, "start_utc": start, "end_utc": utc(), "aborted": True})
        append(SCHED_LOG, {"phase": "cleanup_done", "utc": utc()})


if __name__ == "__main__":
    sys.exit(main())
