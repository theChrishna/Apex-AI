"""Live closed-loop test of a CANARY ROLLBACK on Online Boutique. THIS WRITES TO THE CLUSTER.

  python -m topo.canary_test --plan        # print the steps (default)
  python -m topo.canary_test --yes         # run them (about 25 minutes)

Setting: productcatalogservice runs two versions behind one VirtualService, 50/50. A "bad release" of v2 adds 300 ms to
every request (EXTRA_LATENCY, a setting the Online Boutique service already supports). MeshHeal's Boutique release is put in
act mode for the test with one confirmed playbook entry: roll productcatalogservice back to v1. Expected: REROUTE to v1,
failed probes while v2 is still bad, RELEASE back to 50/50 after v2 is fixed.

Steps:
  1 label the existing deployment's pods version=v1 (a normal rollout), create productcatalogservice-v2 (same image),
    a DestinationRule with subsets v1/v2 and a VirtualService 50/50; wait for healthy per-version metrics
  2 helm upgrade meshheal-boutique: mode=act, canary playbook
  3 bad release: v2 gets EXTRA_LATENCY=300ms; wait for REROUTE (max 8 min), then let probes run (5 min)
  4 fix v2 (remove EXTRA_LATENCY); wait for RELEASE (max 10 min)
Always, even after an error or Ctrl+C: the release goes back to shadow mode with an empty playbook, the VirtualService,
DestinationRule and v2 deployment are deleted, and the version label is removed again. Prints a timeline and writes it to
--out. Only the `boutique` and `meshheal-system` namespaces are touched.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

NS, REL_NS, REL = "boutique", "meshheal-system", "meshheal-boutique"
SVC = "productcatalogservice"
HELM = r"C:\Users\mugiw\AppData\Local\Microsoft\WinGet\Links\helm.exe"
CHART = "deploy/helm/meshheal"

PLAYBOOK = f"""reroutes:
  - culprit: {SVC}
    virtual_service: {SVC}
    target_subset: v1
    normal_weights: {{v1: 50, v2: 50}}
    reason: roll back the bad canary to the stable version
    confirmed: true
depends: {{}}
"""
DR = f"""apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {{name: {SVC}, labels: {{meshheal-test: canary}}}}
spec:
  host: {SVC}
  subsets:
  - {{name: v1, labels: {{version: v1}}}}
  - {{name: v2, labels: {{version: v2}}}}
"""
VS = f"""apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {{name: {SVC}, labels: {{meshheal-test: canary}}}}
spec:
  hosts: [{SVC}]
  http:
  - route:
    - {{destination: {{host: {SVC}, subset: v1}}, weight: 50}}
    - {{destination: {{host: {SVC}, subset: v2}}, weight: 50}}
"""


def run(*cmd, stdin=None, check=True):
    r = subprocess.run(list(cmd), input=stdin, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} failed: {r.stderr.strip()[:300]}")
    return r


def k(*args, **kw):
    return run("kubectl", *args, **kw)


class Log:
    def __init__(self):
        self.t0, self.rows = time.time(), []

    def __call__(self, msg, **kw):
        now = datetime.now(timezone.utc)
        row = {"utc": now.strftime("%H:%M:%S"), "t_s": round(time.time() - self.t0), "msg": msg, **kw}
        self.rows.append(row)
        print(f"[{row['utc']} +{row['t_s']:>4}s] {msg}" + (f"  {kw}" if kw else ""), flush=True)


def controller_events(since_utc):
    r = k("logs", "-n", REL_NS, f"deploy/{REL}-controlplane", "-c", "controller", "--tail=2000", check=False)
    out = []
    for line in r.stdout.splitlines():
        if line.startswith("{"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") != "SCORED" and e.get("ts", "") >= since_utc:
                out.append(e)
    return out


def wait_event(name, since_utc, timeout_s, log, node=SVC):
    end = time.time() + timeout_s
    while time.time() < end:
        for e in controller_events(since_utc):
            if e["event"] == name and (e.get("node") == node or e.get("culprit") == node):
                return e
        time.sleep(10)
    return None


def vs_weights():
    r = k("get", "virtualservice", SVC, "-n", NS, "-o", "json", check=False)
    if r.returncode != 0:
        return None, None
    vs = json.loads(r.stdout)
    w = {d["destination"].get("subset"): d.get("weight") for d in vs["spec"]["http"][0]["route"]}
    return w, (vs["metadata"].get("annotations") or {}).get("meshheal.io/state")


def set_v2_latency(value):
    patch = [{"op": "replace", "path": "/spec/template/spec/containers/0/env",
              "value": [{"name": "PORT", "value": "3550"}, {"name": "DISABLE_PROFILER", "value": "1"}]
              + ([{"name": "EXTRA_LATENCY", "value": value}] if value else [])}]
    k("patch", "deployment", f"{SVC}-v2", "-n", NS, "--type=json", "-p", json.dumps(patch))
    k("rollout", "status", f"deployment/{SVC}-v2", "-n", NS, "--timeout=180s")


def helm_release(mode, playbook_file=None):
    args = [HELM, "upgrade", REL, CHART, "-n", REL_NS, "--reuse-values", "--set", f"mode={mode}"]
    if not playbook_file:                       # an empty playbook, from a file: `--set` would read {} and [] as list syntax
        playbook_file = "topo/empty_playbook.yaml"
        with open(playbook_file, "w", encoding="utf-8") as f:
            f.write("reroutes: []\ndepends: {}\n")
    args += ["--set-file", f"playbook={playbook_file}"]
    run(*args)
    k("rollout", "status", f"deployment/{REL}-controlplane", "-n", REL_NS, "--timeout=180s")


def setup(log):
    k("patch", "deployment", SVC, "-n", NS, "--type=json",
      "-p", json.dumps([{"op": "add", "path": "/spec/template/metadata/labels/version", "value": "v1"}]))
    k("rollout", "status", f"deployment/{SVC}", "-n", NS, "--timeout=180s")
    dep = json.loads(k("get", "deployment", SVC, "-n", NS, "-o", "json").stdout)
    v2 = {"apiVersion": "apps/v1", "kind": "Deployment",
          "metadata": {"name": f"{SVC}-v2", "namespace": NS, "labels": {"app": SVC, "meshheal-test": "canary"}},
          "spec": {"replicas": 1, "selector": {"matchLabels": {"app": SVC, "version": "v2"}},
                   "template": {"metadata": {"labels": {"app": SVC, "version": "v2"}}, "spec": dep["spec"]["template"]["spec"]}}}
    k("apply", "-f", "-", stdin=json.dumps(v2))
    k("rollout", "status", f"deployment/{SVC}-v2", "-n", NS, "--timeout=180s")
    k("apply", "-n", NS, "-f", "-", stdin=DR)
    k("apply", "-n", NS, "-f", "-", stdin=VS)
    log("canary set up: v1 and v2 healthy, VirtualService 50/50")


def cleanup(log):
    for step, fn in [
        ("release back to shadow mode, empty playbook", lambda: helm_release("shadow")),
        ("VirtualService deleted", lambda: k("delete", "virtualservice", SVC, "-n", NS, "--ignore-not-found")),
        ("DestinationRule deleted", lambda: k("delete", "destinationrule", SVC, "-n", NS, "--ignore-not-found")),
        ("v2 deployment deleted", lambda: k("delete", "deployment", f"{SVC}-v2", "-n", NS, "--ignore-not-found")),
        ("version label removed from v1", lambda: k("patch", "deployment", SVC, "-n", NS, "--type=json",
                                                     "-p", json.dumps([{"op": "remove", "path": "/spec/template/metadata/labels/version"}]), check=False)),
    ]:
        try:
            fn()
            log(f"cleanup: {step}")
        except Exception as e:
            log(f"!! cleanup step failed: {step}: {e}  DO IT BY HAND")
    k("rollout", "status", f"deployment/{SVC}", "-n", NS, "--timeout=180s", check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--latency", default="300ms")
    ap.add_argument("--out", default="topo/results/phase6_canary_live.json")
    ap.add_argument("--playbook-file", default="topo/canary_playbook.yaml")
    a = ap.parse_args(argv)
    if a.plan or not a.yes:
        print(__doc__)
        print("Nothing was changed. Pass --yes to run it.")
        return
    with open(a.playbook_file, "w", encoding="utf-8") as f:
        f.write(PLAYBOOK)
    log = Log()
    result = {"latency": a.latency}
    pre = k("get", "virtualservice,destinationrule", "-n", NS, "-o", "name", check=False).stdout.split()
    if pre:
        raise SystemExit(f"refusing: boutique already has {pre}")
    try:
        setup(log)
        time.sleep(180)                                                     # per-version metrics need a full rate window
        helm_release("act", a.playbook_file)
        log("MeshHeal Boutique release in ACT mode with the canary playbook")
        time.sleep(60)
        bad_at = datetime.now(timezone.utc).isoformat()
        set_v2_latency(a.latency)
        log(f"BAD RELEASE: v2 now adds {a.latency} to every request")
        ev = wait_event("REROUTE", bad_at, 480, log)
        result["reroute"] = ev
        if not ev:
            blocked = [e for e in controller_events(bad_at) if e["event"] == "ACTION_BLOCKED"]
            log("NO REROUTE within 8 minutes", blocked=blocked[-3:])
        else:
            log("REROUTE", weights=ev.get("weights"), risk=ev.get("risk"))
            w, st = vs_weights()
            log("VirtualService after the reroute", weights=w, state_recorded=bool(st))
            time.sleep(300)
            result["probe_failed"] = [e for e in controller_events(bad_at) if e["event"] == "PROBE_FAILED"]
            log(f"{len(result['probe_failed'])} probe(s) failed while v2 was still bad")
        fixed_at = datetime.now(timezone.utc).isoformat()
        set_v2_latency(None)
        log("v2 FIXED (extra latency removed)")
        if ev:
            rel = wait_event("RELEASE", fixed_at, 600, log)
            result["release"] = rel
            w, st = vs_weights()
            log("RELEASE" if rel else "NO RELEASE within 10 minutes", weights=w, state_left=st)
            result["final_weights"], result["final_state"] = w, st
        result["events"] = controller_events(bad_at)
    finally:
        cleanup(log)
        left = k("get", "virtualservice,destinationrule,deployment", "-n", NS, "-l", "meshheal-test=canary", "-o", "name", check=False).stdout.split()
        log("left behind with meshheal-test=canary", objects=left or "none")
        result["timeline"] = log.rows
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, default=str)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
