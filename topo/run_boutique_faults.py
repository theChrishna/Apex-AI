"""Inject delay faults one at a time into a namespace and log them. THIS WRITES TO THE CLUSTER.

  python -m topo.run_boutique_faults --namespace boutique --plan             # prints the schedule only (default)
  python -m topo.run_boutique_faults --namespace boutique --episodes 10 --yes   # really runs it

Each episode: apply a VirtualService with `fault.delay` (100%) on one service, hold it, delete it, wait. The same
shape as the Bookinfo episodes: 5 min fault, then a gap for recovery and normal traffic. Every episode is appended to
the fault log AFTER it finishes, and the VirtualService is deleted in a `finally` even on Ctrl+C or an error; at the end
it prints the remaining VirtualServices so you can check nothing is left behind.
It refuses to run without --yes and never touches a VirtualService that it did not create (names end in -fault-inj).
"""
import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

DEFAULT_TARGETS = ["adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice", "frontend",
                   "paymentservice", "productcatalogservice", "recommendationservice", "shippingservice"]
DELAYS_MS = [50, 100, 150, 200]
SUFFIX = "-fault-inj"


def vs_yaml(service, delay_ms):
    return f"""apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: {service}{SUFFIX}
spec:
  hosts:
  - {service}
  http:
  - fault:
      delay:
        percentage:
          value: 100.0
        fixedDelay: {delay_ms}ms
    route:
    - destination:
        host: {service}
"""


def kubectl(*args, stdin=None):
    return subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True, check=False)


def schedule(targets, episodes, seed):
    """Round-robin over shuffled targets so every service gets faulted before any repeats; random delay each time."""
    rng = random.Random(seed)
    order = []
    while len(order) < episodes:
        block = list(targets)
        rng.shuffle(block)
        order += block
    return [(svc, rng.choice(DELAYS_MS)) for svc in order[:episodes]]


def run_episode(ns, svc, delay_ms, hold_s):
    name = svc + SUFFIX
    start = datetime.now(timezone.utc)
    try:
        r = kubectl("apply", "-n", ns, "-f", "-", stdin=vs_yaml(svc, delay_ms))
        if r.returncode != 0:
            raise RuntimeError(f"apply failed: {r.stderr.strip()}")
        time.sleep(hold_s)
        completed = True
    except BaseException:
        completed = False
        raise
    finally:
        end = datetime.now(timezone.utc)
        d = kubectl("delete", "virtualservice", name, "-n", ns, "--ignore-not-found")
        if d.returncode != 0:
            print(f"!! could not delete {name}: {d.stderr.strip()}  DELETE IT BY HAND", file=sys.stderr)
        log_row = {"node": svc, "delay_ms": delay_ms, "start": start.isoformat(), "end": end.isoformat(), "completed": completed}
    return log_row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--targets", nargs="+", default=DEFAULT_TARGETS)
    ap.add_argument("--episodes", type=int, default=10)
    ap.add_argument("--hold-s", type=float, default=300.0, help="fault duration (real Bookinfo episodes: 300 s)")
    ap.add_argument("--gap-s", type=float, default=180.0, help="wait after each episode (recovery + normal traffic)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--log", default="topo/boutique_fault_log.jsonl")
    ap.add_argument("--first-episode-id", type=int, default=1)
    ap.add_argument("--yes", action="store_true", help="actually inject faults (otherwise only print the plan)")
    ap.add_argument("--plan", action="store_true", help="print the plan and exit")
    a = ap.parse_args(argv)

    plan = schedule(a.targets, a.episodes, a.seed)
    total_min = a.episodes * (a.hold_s + a.gap_s) / 60
    print(f"namespace={a.namespace} episodes={a.episodes} hold={a.hold_s:.0f}s gap={a.gap_s:.0f}s  (about {total_min:.0f} min)")
    for i, (svc, d) in enumerate(plan, a.first_episode_id):
        print(f"  episode {i}: {svc} +{d} ms")
    if a.plan or not a.yes:
        print("\nNothing was changed. Pass --yes to inject these faults.")
        return
    print()
    for i, (svc, d) in enumerate(plan, a.first_episode_id):
        print(f"[{datetime.now():%H:%M:%S}] episode {i}: {svc} +{d} ms", flush=True)
        row = run_episode(a.namespace, svc, d, a.hold_s)
        with open(a.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"episode": i, **row}) + "\n")
        time.sleep(a.gap_s)
    left = kubectl("get", "virtualservice", "-n", a.namespace, "-o", "name")
    print("VirtualServices left in", a.namespace + ":", left.stdout.split() or "none")


if __name__ == "__main__":
    main()
