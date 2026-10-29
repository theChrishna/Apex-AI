#!/usr/bin/env python3
"""Closed-loop live demo with the REAL ACTING controller (not dry-run). Run once per scenario on 2026-10-29.

  Scenario A: GNN scorer. Apply the ratings 150 ms fault, record the first REROUTE, watch productpage latency
              recover, remove the fault, record the RELEASE.
  Scenario B: same, but the kill file is touched first, so the rule fallback is the one that acts.

kubectl writes this script makes (nothing else):
  apply  -f shadow_run/fault-ratings-150.yaml        (the fault)
  delete virtualservice ratings / details --ignore-not-found   (fault removal and cleanup)
  apply  -f reviews-normal.yaml                      (cleanup only)
The controller it starts patches the `reviews` VirtualService by itself; that is its job.
Everything else is read-only (`kubectl get`, curl, file reads). It never deletes the reviews VirtualService.

Needs --yes to do anything; without it only the read-only pre-flight runs and the plan is printed.
Cleanup runs in a finally block and on Ctrl-C / SIGTERM.

Results (one run each, ratings 150 ms; see live_demo/README.md and result_*_20261029T*.json):
  A: REROUTE 78.2 s after the fault, latency back to baseline within about 2 s of the reroute, RELEASE 174 s after
     the fault was removed, 21 SCORED events all primary.
  B: REROUTE 63.7 s, RELEASE 174.9 s after fault removal, 19 SCORED events all fallback.
The fault was removed before the probe started in both runs, so RELEASE does not show the probe catches a persisting fault.
latency.csv is appended to by both scenarios (column `scenario`).

Usage (project root, venv active, laptop plugged in):
  caffeinate -i .venv/bin/python live_demo/run_live.py --scenario A --yes
  caffeinate -i .venv/bin/python live_demo/run_live.py --scenario B --yes
  .venv/bin/python live_demo/run_live.py --scenario A            # pre-flight only
"""
import argparse
import csv
import json
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "live_demo"
NS = "aws-us-east"
FAULT_YAML = ROOT / "shadow_run" / "fault-ratings-150.yaml"
NORMAL_YAML = ROOT / "reviews-normal.yaml"
SNAPSHOTS = ROOT / "shadow_run" / "snapshots.jsonl"
KILL_FILE = DEMO / "gnn.off"
LATENCY_CSV = DEMO / "latency.csv"
PRODUCTPAGE = "http://localhost:9080/productpage"
SLOW_S = 0.1
STOP = threading.Event()


def utc():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or utc()).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log(msg):
    print(f"[{iso()}] {msg}", flush=True)


def sh(args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    log(f"{' '.join(str(a) for a in args)} -> rc={r.returncode} {r.stdout.strip()} {r.stderr.strip()}".rstrip())
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(str(a) for a in args)}")
    return r


def kubectl_get(*args):
    return subprocess.run(["kubectl", "get", *args, "-n", NS], capture_output=True, text=True)


# ------------------------------------------------------------------ pre-flight (read-only)
def preflight():
    problems = []
    vs = kubectl_get("virtualservice", "-o", "name")
    names = {l.split("/")[-1] for l in vs.stdout.split()}
    if vs.returncode != 0:
        problems.append(f"kubectl get virtualservice failed: {vs.stderr.strip()}")
    elif names != {"reviews"}:
        problems.append(f"expected only the `reviews` VirtualService, found: {sorted(names)}")
    w = kubectl_get("virtualservice", "reviews", "-o", "jsonpath={range .spec.http[*].route[*]}{.destination.subset}={.weight} {end}|{.spec.http[0].fault}")
    if w.stdout.split("|")[0].split() != ["v1=34", "v2=33", "v3=33"] or w.stdout.split("|")[-1].strip():
        problems.append(f"reviews is not the normal 34/33/33 without a fault: {w.stdout.strip()}")
    pods = kubectl_get("pods", "--no-headers")
    bad = [l for l in pods.stdout.splitlines() if "2/2" not in l or "Running" not in l]
    if pods.returncode != 0 or bad:
        problems.append(f"pods not all 2/2 Running: {bad or pods.stderr.strip()}")
    try:
        code = urllib.request.urlopen(PRODUCTPAGE, timeout=5).status
        if code != 200:
            problems.append(f"productpage returned {code}")
    except Exception as e:
        problems.append(f"productpage not reachable on 9080 (port-forward?): {e}")
    age = snapshot_age()
    if age is None or age > 45:
        problems.append(f"newest snapshot in shadow_run/snapshots.jsonl is {age} s old (telemetry running? controller rejects over 45 s)")
    b = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    if "discharging" in b:
        problems.append("laptop is on battery: plug in (a sleep mid-run leaves a fault applied until cleanup)")
    return problems


def snapshot_age():
    try:
        with open(SNAPSHOTS, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            lines = [l for l in f.read().splitlines() if l.strip()]
        for raw in reversed(lines):
            try:
                ts = datetime.fromisoformat(json.loads(raw)["timestamp"].replace("Z", "+00:00"))
                return round((utc() - ts).total_seconds(), 1)
            except (json.JSONDecodeError, KeyError):
                continue
    except OSError:
        pass
    return None


# ------------------------------------------------------------------ latency sampler
class Sampler(threading.Thread):
    """curl productpage every 2 s into latency.csv: utc, scenario, http_code, time_total_s."""

    def __init__(self, scenario):
        super().__init__(daemon=True)
        self.scenario, self.samples = scenario, []   # (datetime, seconds or None)
        new = not LATENCY_CSV.exists()
        self.f = open(LATENCY_CSV, "a", newline="")
        self.w = csv.writer(self.f)
        if new:
            self.w.writerow(["utc", "scenario", "http_code", "time_total_s"])

    def run(self):
        while not STOP.is_set():
            t0 = utc()
            r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "5", "-w", "%{http_code} %{time_total}", PRODUCTPAGE], capture_output=True, text=True)
            try:
                code, secs = r.stdout.split()
                secs = float(secs) if code == "200" else None
            except ValueError:
                code, secs = "000", None
            self.samples.append((t0, secs))
            self.w.writerow([iso(t0), self.scenario, code, "" if secs is None else f"{secs:.3f}"])
            self.f.flush()
            STOP.wait(max(0.0, 2.0 - (utc() - t0).total_seconds()))
        self.f.close()

    def recovered_after(self, t, n=3):
        """Time of the first of n consecutive samples (taken after t) below SLOW_S, else None."""
        run = [s for s in self.samples if s[0] >= t]
        for i in range(len(run) - n + 1):
            if all(x[1] is not None and x[1] < SLOW_S for x in run[i:i + n]):
                return run[i][0]
        return None

    def median_between(self, a, b):
        v = [s for t, s in self.samples if a <= t <= b and s is not None]
        return round(statistics.median(v), 3) if v else None


# ------------------------------------------------------------------ audit file
def read_audit(path):
    out = []
    try:
        for raw in open(path, "rb").read().splitlines():
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return out


def wait_for(pred, timeout_s, what):
    end = time.time() + timeout_s
    while time.time() < end and not STOP.is_set():
        hit = pred()
        if hit:
            return hit
        STOP.wait(2.0)
    log(f"TIMEOUT waiting for {what} ({timeout_s:.0f} s)")
    return None


# ------------------------------------------------------------------ cleanup
def cleanup(controller):
    log("cleanup: stopping sampler/controller, removing fault VirtualServices, restoring reviews-normal.yaml")
    STOP.set()
    if controller and controller.poll() is None:
        controller.terminate()
        try:
            controller.wait(timeout=10)
        except subprocess.TimeoutExpired:
            controller.kill()
    for vs in ("ratings", "details"):
        sh(["kubectl", "delete", "virtualservice", vs, "-n", NS, "--ignore-not-found"], check=False)
    sh(["kubectl", "apply", "-n", NS, "-f", str(NORMAL_YAML)], check=False)
    KILL_FILE.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=["A", "B"], required=True)
    ap.add_argument("--yes", action="store_true", help="actually run (applies the fault and starts the ACTING controller)")
    ap.add_argument("--detect-timeout", type=float, default=240, help="s to wait for the first REROUTE")
    ap.add_argument("--recover-timeout", type=float, default=120, help="s to wait for latency < 0.1 s after the REROUTE")
    ap.add_argument("--hold", type=float, default=30, help="s to keep the fault after latency recovers")
    ap.add_argument("--release-timeout", type=float, default=480, help="s to wait for RELEASE after the fault is removed (cooldown 120 s + probe 90 s)")
    a = ap.parse_args()

    problems = preflight()
    for p in problems:
        log(f"PRE-FLIGHT PROBLEM: {p}")
    if not a.yes:
        log("pre-flight only (no --yes): nothing was changed." + ("" if not problems else " Fix the problems above first."))
        return 1 if problems else 0
    if problems:
        log("refusing to run with pre-flight problems")
        return 1

    scenario = a.scenario
    stamp = utc().strftime("%Y%m%dT%H%M%SZ")
    audit = DEMO / f"audit_{scenario}_{stamp}.jsonl"
    result = {"scenario": scenario, "scorer": "gnn" + (" (kill file touched: rule fallback acts)" if scenario == "B" else ""), "audit_file": str(audit.relative_to(ROOT))}
    controller = None
    sampler = None
    def on_term(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_term)
    try:
        KILL_FILE.unlink(missing_ok=True)
        if scenario == "B":
            KILL_FILE.touch()
            log(f"kill file touched: {KILL_FILE}")
        cmd = [sys.executable, "-m", "controlplane.run", "--scorer", "gnn", "--gnn-kill-file", str(KILL_FILE),
               "--snapshots", str(SNAPSHOTS), "--audit", str(audit)]   # no --dry-run: this controller acts
        log("starting ACTING controller: " + " ".join(cmd))
        controller = subprocess.Popen(cmd, cwd=ROOT / "meshheal_controlplane", stdout=open(DEMO / f"controller_{scenario}_{stamp}.log", "w"), stderr=subprocess.STDOUT)
        want = "fallback" if scenario == "B" else "primary"
        ok = wait_for(lambda: [e for e in read_audit(audit) if e["event"] == "SCORED" and e.get("source") == want], 90, f"SCORED with source={want}")
        if not ok:
            raise RuntimeError(f"controller never logged SCORED source={want}; not injecting a fault")
        result["first_scored"] = {"ts": ok[0]["ts"], "source": ok[0]["source"], "note": ok[0].get("note")}

        sampler = Sampler(scenario)
        sampler.start()
        STOP.wait(10)   # baseline latency samples
        result["baseline_median_s"] = sampler.median_between(utc().replace(year=2000), utc())

        sh(["kubectl", "apply", "-n", NS, "-f", str(FAULT_YAML)])
        t_fault = utc()
        result["fault_start_utc"] = iso(t_fault)

        def first_reroute():
            ev = [e for e in read_audit(audit) if e["event"] == "REROUTE"]
            return ev[0] if ev else None
        rr = wait_for(first_reroute, a.detect_timeout, "first REROUTE")
        if rr:
            t_rr = datetime.fromisoformat(rr["ts"])
            result["first_reroute_audit_ts"] = rr["ts"]
            result["detect_s_after_fault"] = round((t_rr - t_fault).total_seconds(), 1)
            result["reroute_culprit"] = rr.get("culprit")
            rec = wait_for(lambda: sampler.recovered_after(t_rr), a.recover_timeout, "3 consecutive productpage samples < 0.1 s")
            if rec:
                result["latency_recovered_utc"] = iso(rec)
                result["recover_s_after_reroute"] = round((rec - t_rr).total_seconds(), 1)
                result["latency_median_s_faulted_before_reroute"] = sampler.median_between(t_fault, t_rr)
                STOP.wait(a.hold)
                result["latency_median_s_after_recovery"] = sampler.median_between(rec, utc())
        t_removed = utc()
        sh(["kubectl", "delete", "virtualservice", "ratings", "-n", NS, "--ignore-not-found"])
        result["fault_removed_utc"] = iso(t_removed)
        if rr:
            rel = wait_for(lambda: next((e for e in read_audit(audit) if e["event"] == "RELEASE"), None), a.release_timeout, "RELEASE")
            if rel:
                result["release_audit_ts"] = rel["ts"]
                result["release_s_after_fault_removed"] = round((datetime.fromisoformat(rel["ts"]) - t_removed).total_seconds(), 1)
        result["audit_events"] = [{k: e.get(k) for k in ("ts", "event", "node", "culprit", "reason", "risk", "source", "note")} for e in read_audit(audit) if e["event"] != "SCORED"]
        result["scored_via_fallback"] = sum(1 for e in read_audit(audit) if e["event"] == "SCORED" and e.get("source") == "fallback")
    except KeyboardInterrupt:
        log("interrupted")
        result["interrupted"] = True
    except Exception as e:
        log(f"ERROR: {e!r}")
        result["error"] = repr(e)
    finally:
        cleanup(controller)
        out = DEMO / f"result_{scenario}_{stamp}.json"
        out.write_text(json.dumps(result, indent=1))
        log(f"wrote {out.relative_to(ROOT)}")
    print(json.dumps(result, indent=1))
    return 1 if ("error" in result or "interrupted" in result) else 0


if __name__ == "__main__":
    sys.exit(main())
