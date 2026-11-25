"""Inject faults one at a time into a namespace and log them. THIS WRITES TO THE CLUSTER.

  python -m topo.run_boutique_faults --namespace boutique --plan                       # prints the schedule only (default)
  python -m topo.run_boutique_faults --namespace boutique --episodes 10 --yes          # delay faults, as in the first run
  python -m topo.run_boutique_faults --namespace boutique --types delay abort cpu crash --per-type 10 --yes

Fault types (each one targets ONE service for the whole episode, so the culprit label is unambiguous):
  delay  Istio fault.delay, 100% of requests, 50 to 200 ms. A VirtualService named <service>-fault-inj.
  abort  Istio fault.abort on 50% of requests (gRPC UNAVAILABLE, or HTTP 503 for the HTTP frontend). Same VirtualService.
         These failures are produced in the CALLER's sidecar and never reach the service: only caller-side metrics see them.
  cpu    The service's own container is limited to 25m CPU (Deployment patch, a new pod rolls out): a bad config / noisy
         neighbour slowdown that Istio does not cause. The original resources are put back afterwards.
  crash  The service's pod is deleted every 60 s for the whole episode; Kubernetes restarts it each time, so callers see
         connection failures and slow responses while it comes back.
Every episode is appended to the fault log AFTER it finishes, and each fault is undone in a `finally` even on Ctrl+C or
an error (VirtualService deleted, resources restored, the pod left to be recreated). It refuses to run without --yes,
never touches a VirtualService it did not create (names end in -fault-inj), and waits for the service to be ready again
before the next episode.
"""
import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone

DEFAULT_TARGETS = ["adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice", "frontend",
                   "paymentservice", "productcatalogservice", "recommendationservice", "shippingservice"]
DELAYS_MS = [50, 100, 150, 200]
TYPES = ("delay", "abort", "cpu", "crash")
SUFFIX = "-fault-inj"
HTTP_SERVICES = {"frontend"}          # the rest of Online Boutique speaks gRPC
ABORT_PCT = 50.0
CPU_LIMIT = "25m"
CRASH_EVERY_S = 60.0


def _vs(service, fault):
    return f"""apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: {service}{SUFFIX}
spec:
  hosts:
  - {service}
  http:
  - fault:
{fault}
    route:
    - destination:
        host: {service}
"""


def vs_yaml(service, delay_ms):
    """Kept for the first run's tests and logs: a 100% fixed delay."""
    return _vs(service, f"""      delay:
        percentage:
          value: 100.0
        fixedDelay: {delay_ms}ms""")


def abort_yaml(service, pct=ABORT_PCT):
    status = "httpStatus: 503" if service in HTTP_SERVICES else 'grpcStatus: "UNAVAILABLE"'
    return _vs(service, f"""      abort:
        percentage:
          value: {pct}
        {status}""")


def describe(ft, p):
    """Human text for one planned episode (built per type, so a text parameter like "25m" is never number-formatted)."""
    if ft == "delay":
        return f"+{p} ms"
    if ft == "abort":
        return f"{float(p):.0f}% errors"
    if ft == "cpu":
        return f"CPU limit {p}"
    return f"pod killed every {float(p):.0f} s"


def kubectl(*args, stdin=None):
    return subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True, check=False)


def schedule(targets, episodes, seed, types=("delay",)):
    """Round-robin over shuffled targets so every service gets faulted before any repeats; with several types, every
    (service, type) pair appears once per block and the order is shuffled, so time of day does not line up with type."""
    rng = random.Random(seed)
    order = []
    while len(order) < episodes:
        block = [(t, ft) for t in targets for ft in types] if len(types) > 1 else [(t, types[0]) for t in targets]
        rng.shuffle(block)
        order += block
    plan = []
    for svc, ft in order[:episodes]:
        if ft == "delay":
            plan.append((svc, "delay", rng.choice(DELAYS_MS)))
        elif ft == "abort":
            plan.append((svc, "abort", ABORT_PCT))
        elif ft == "cpu":
            plan.append((svc, "cpu", CPU_LIMIT))
        else:
            plan.append((svc, "crash", CRASH_EVERY_S))
    return plan


def _server_container(ns, svc):
    r = kubectl("get", "deployment", svc, "-n", ns, "-o", "json")
    if r.returncode != 0:
        raise RuntimeError(f"cannot read deployment {svc}: {r.stderr.strip()}")
    dep = json.loads(r.stdout)
    containers = dep["spec"]["template"]["spec"]["containers"]
    idx = next((i for i, c in enumerate(containers) if c["name"] == "server"), 0)
    return idx, containers[idx].get("resources", {})


def _set_resources(ns, svc, idx, resources):
    patch = json.dumps([{"op": "replace" if resources is not None else "remove",
                         "path": f"/spec/template/spec/containers/{idx}/resources", **({"value": resources} if resources is not None else {})}])
    r = kubectl("patch", "deployment", svc, "-n", ns, "--type=json", "-p", patch)
    if r.returncode != 0:
        raise RuntimeError(f"patch {svc} failed: {r.stderr.strip()}")


def wait_ready(ns, svc, timeout_s=240):
    r = kubectl("rollout", "status", f"deployment/{svc}", "-n", ns, f"--timeout={int(timeout_s)}s")
    return r.returncode == 0


def run_episode(ns, svc, delay_ms, hold_s, ftype="delay", param=None, sleep=None, clock=None):
    """One fault episode; always undone. Returns the log row (start/end in UTC)."""
    sleep = sleep or time.sleep          # looked up at call time, so tests (and Ctrl+C simulations) can replace it
    clock = clock or (lambda: datetime.now(timezone.utc))
    name = svc + SUFFIX
    start = clock()
    completed = False
    original = None
    try:
        if ftype in ("delay", "abort"):
            y = vs_yaml(svc, delay_ms) if ftype == "delay" else abort_yaml(svc, param or ABORT_PCT)
            r = kubectl("apply", "-n", ns, "-f", "-", stdin=y)
            if r.returncode != 0:
                raise RuntimeError(f"apply failed: {r.stderr.strip()}")
            sleep(hold_s)
        elif ftype == "cpu":
            idx, original = _server_container(ns, svc)
            starved = json.loads(json.dumps(original or {}))
            starved.setdefault("limits", {})["cpu"] = param or CPU_LIMIT
            starved.setdefault("requests", {})["cpu"] = param or CPU_LIMIT       # requests may not exceed limits
            _set_resources(ns, svc, idx, starved)
            sleep(hold_s)
        elif ftype == "crash":
            every = float(param or CRASH_EVERY_S)
            t_end = time.monotonic() + hold_s
            while True:
                kubectl("delete", "pod", "-n", ns, "-l", f"app={svc}", "--wait=false")
                left = t_end - time.monotonic()
                if left <= 0:
                    break
                sleep(min(every, left))
                if time.monotonic() >= t_end:
                    break
        else:
            raise ValueError(f"unknown fault type {ftype}")
        completed = True
    finally:
        end = clock()
        if ftype in ("delay", "abort"):
            d = kubectl("delete", "virtualservice", name, "-n", ns, "--ignore-not-found")
            if d.returncode != 0:
                print(f"!! could not delete {name}: {d.stderr.strip()}  DELETE IT BY HAND", file=sys.stderr)
        elif ftype == "cpu" and original is not None:
            try:
                _set_resources(ns, svc, idx, original if original else None)
            except Exception as e:
                print(f"!! could not restore resources of {svc}: {e}  RESTORE THEM BY HAND", file=sys.stderr)
    row = {"node": svc, "type": ftype, "delay_ms": delay_ms if ftype == "delay" else 0,
           "param": param if ftype != "delay" else delay_ms,
           "start": start.isoformat(), "end": end.isoformat(), "completed": completed}
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--targets", nargs="+", default=DEFAULT_TARGETS)
    ap.add_argument("--types", nargs="+", default=["delay"], choices=TYPES)
    ap.add_argument("--episodes", type=int, default=None, help="total episodes (default: per-type x types)")
    ap.add_argument("--per-type", type=int, default=10)
    ap.add_argument("--hold-s", type=float, default=300.0, help="fault duration (real Bookinfo episodes: 300 s)")
    ap.add_argument("--gap-s", type=float, default=180.0, help="wait after each episode (recovery + normal traffic)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--log", default="topo/boutique_fault_log.jsonl")
    ap.add_argument("--first-episode-id", type=int, default=1)
    ap.add_argument("--yes", action="store_true", help="actually inject faults (otherwise only print the plan)")
    ap.add_argument("--plan", action="store_true", help="print the plan and exit")
    a = ap.parse_args(argv)

    n = a.episodes if a.episodes is not None else a.per_type * len(a.types)
    plan = schedule(a.targets, n, a.seed, tuple(a.types))
    total_min = n * (a.hold_s + a.gap_s) / 60
    print(f"namespace={a.namespace} types={a.types} episodes={n} hold={a.hold_s:.0f}s gap={a.gap_s:.0f}s  (about {total_min:.0f} min)")
    for i, (svc, ft, p) in enumerate(plan, a.first_episode_id):
        print(f"  episode {i}: {ft:<5} {svc} {describe(ft, p)}")
    if a.plan or not a.yes:
        print("\nNothing was changed. Pass --yes to inject these faults.")
        return
    print()
    for i, (svc, ft, p) in enumerate(plan, a.first_episode_id):
        print(f"[{datetime.now():%H:%M:%S}] episode {i}: {ft} {svc} {p}", flush=True)
        row = run_episode(a.namespace, svc, p if ft == "delay" else 0, a.hold_s, ftype=ft, param=None if ft == "delay" else p)
        with open(a.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"episode": i, **row}) + "\n")
        if not wait_ready(a.namespace, svc):
            print(f"!! {svc} not ready after the episode; check it", file=sys.stderr, flush=True)
        time.sleep(a.gap_s)
    left = kubectl("get", "virtualservice", "-n", a.namespace, "-o", "name")
    print("VirtualServices left in", a.namespace + ":", left.stdout.split() or "none")


if __name__ == "__main__":
    main()
