#!/usr/bin/env bash
# demo_up.sh: start what the demo needs, the way shadow_run was started. Run on 2026-10-28 and 2026-10-29.
#
#   - kubectl port-forward  productpage -> localhost:9080, Prometheus -> localhost:9090
#   - traffic_gen.py        (cwd = project root)     keeps ~0.27 req/s flowing through Bookinfo
#   - telemetry.py          (cwd = shadow_run/)      appends a snapshot every 15 s to shadow_run/snapshots.jsonl
# Logs go to shadow_run/*.log (appended), PIDs to shadow_run/pids.txt as "name pid" lines (appended).
# It refuses to start if any of these already run (ports 9080/9090 in use, or a telemetry/traffic process exists).
# It only reads the cluster (kubectl get); it writes no cluster state. It does not start the controller.
#
#   ./demo_up.sh                 start everything
#   ./demo_up.sh --caffeinate    also run `caffeinate -dimsu` (keep the Mac awake; stays plugged in!)
# To stop later:  kill $(awk '{print $2}' shadow_run/pids.txt)   (check the file first: old PIDs are harmless "no such process")
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python"
RUN="$ROOT/shadow_run"
PIDS="$RUN/pids.txt"
CAFFEINATE=0
[ "${1:-}" = "--caffeinate" ] && CAFFEINATE=1

fail() { echo "demo_up.sh: $*" >&2; exit 1; }

command -v kubectl >/dev/null || fail "kubectl not found"
[ -x "$PY" ] || fail "missing $PY (create the venv first)"
mkdir -p "$RUN"

# ---- refuse if anything is already running
busy=""
for port in 9080 9090; do
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && busy="$busy port-$port"
done
pgrep -f "port-forward.*(productpage|prometheus)" >/dev/null 2>&1 && busy="$busy port-forward-process"
pgrep -f "traffic_gen.py" >/dev/null 2>&1 && busy="$busy traffic_gen"
pgrep -f "telemetry.py" >/dev/null 2>&1 && busy="$busy telemetry"
[ -z "$busy" ] || fail "already running ($busy). Not starting anything. Check with: ps aux | grep -E 'port-forward|traffic_gen|telemetry'"

# ---- read-only cluster checks
kubectl get ns aws-us-east >/dev/null 2>&1 || fail "cannot reach the cluster / namespace aws-us-east (Docker Desktop up? k3d cluster started? see docs/DEMO_SCRIPT.md fallbacks)"
bad=$(kubectl get pods -n aws-us-east --no-headers 2>/dev/null | grep -v -E "2/2 +Running" || true)
[ -z "$bad" ] || echo "WARNING: pods not all 2/2 Running:
$bad" >&2
vs=$(kubectl get virtualservice -n aws-us-east -o name 2>/dev/null | sed 's#.*/##' | sort | tr '\n' ' ')
[ "$vs" = "reviews " ] || echo "WARNING: VirtualServices are [$vs], expected only [reviews]. A fault rule may still be applied." >&2

start() {  # name logfile cwd cmd...
  local name="$1" log="$2" dir="$3"; shift 3
  ( cd "$dir" && nohup "$@" >>"$log" 2>&1 & echo "$name $!" >>"$PIDS" )
  echo "started $name"
}

start pf_productpage "$RUN/pf_productpage.log" "$ROOT" kubectl -n aws-us-east port-forward svc/productpage 9080:9080
start pf_prometheus  "$RUN/pf_prometheus.log"  "$ROOT" kubectl -n istio-system port-forward svc/prometheus 9090:9090

# wait for the forwards before traffic and telemetry need them
ok=0
for _ in $(seq 1 30); do
  if curl -s -o /dev/null -m 2 -w '%{http_code}' localhost:9080/productpage 2>/dev/null | grep -q 200 \
     && curl -s -m 2 localhost:9090/-/ready 2>/dev/null | grep -q Ready; then ok=1; break; fi
  sleep 1
done
[ "$ok" = 1 ] || echo "WARNING: 9080/9090 not answering after 30 s; traffic and telemetry started anyway, check shadow_run/pf_*.log" >&2

start traffic_gen "$RUN/traffic.log"   "$ROOT" "$PY" traffic_gen.py
start telemetry   "$RUN/telemetry.log" "$RUN"  env PYTHONUNBUFFERED=1 "$PY" ../telemetry.py

if [ "$CAFFEINATE" = 1 ]; then
  ( nohup caffeinate -dimsu >/dev/null 2>&1 & echo "caffeinate $!" >>"$PIDS" )
  echo "started caffeinate (keep the lid open and the charger plugged in)"
fi

echo
echo "Up. PIDs appended to $PIDS. Give telemetry about 30 s, then check:"
echo "  tail -2 shadow_run/telemetry.log        # 'Saved 4 nodes, 3 edges'"
echo "  curl -s -o /dev/null -w '%{http_code}\n' localhost:9080/productpage"
