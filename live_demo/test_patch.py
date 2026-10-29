#!/usr/bin/env python3
"""Check on the REAL cluster that KubeClient.set_weights (JSON merge patch) takes effect. `--yes` passed on 2026-10-28 (v1=100 read back, restored to 34/33/33).

Sets the `reviews` VirtualService to v1=100 through the same KubeClient the controller uses, reads the weights back
with `kubectl get`, and ALWAYS restores with `kubectl apply -f reviews-normal.yaml` in a finally block, then verifies 34/33/33.

kubectl/cluster writes: the patch (one call through the Python client) and `kubectl apply -f reviews-normal.yaml`.
Everything else is read-only. It never deletes the reviews VirtualService. Needs --yes.

  .venv/bin/python live_demo/test_patch.py --yes
Do not run it while live_demo/run_live.py or a controller is running.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "meshheal_controlplane"))
NS = "aws-us-east"
NORMAL = ROOT / "reviews-normal.yaml"


def weights():
    r = subprocess.run(["kubectl", "get", "virtualservice", "reviews", "-n", NS, "-o",
                        "jsonpath={range .spec.http[*].route[*]}{.destination.subset}={.weight} {end}"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return dict((k, int(v)) for k, v in (p.split("=") for p in r.stdout.split()))


def wait_for(expected, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if weights() == expected:
            return True
        time.sleep(1.0)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    normal = {"v1": 34, "v2": 33, "v3": 33}
    before = weights()
    print("current weights:", before)
    if before != normal:
        print("reviews is not at 34/33/33; fix that first (kubectl apply -f reviews-normal.yaml). Nothing changed.")
        return 1
    if not a.yes:
        print("pre-flight only (no --yes): nothing changed. Would patch reviews to v1=100, read back, restore 34/33/33.")
        return 0
    from controlplane.cluster import KubeClient
    ok = False
    try:
        KubeClient(NS).set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0})
        got = weights()
        print("after patch:", got)
        ok = got == {"v1": 100}
        print("PATCH TOOK EFFECT" if ok else f"UNEXPECTED weights after patch: {got}")
    except Exception as e:
        print("PATCH FAILED:", repr(e))
    finally:
        subprocess.run(["kubectl", "apply", "-n", NS, "-f", str(NORMAL)], check=False)
        restored = wait_for(normal)
        print("restored to 34/33/33:", restored, weights())
        ok = ok and restored
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
