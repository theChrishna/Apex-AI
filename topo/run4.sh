#!/usr/bin/env bash
# Run4: fresh measurement of image 0.7.1 (per-edge scorer with fan-out weighting) on unseen Online Boutique data.
# Unattended. Log: topo/run4.log
#   1 Prometheus port-forward (restarted if it drops) + collector -> topo/live_boutique_run4.jsonl
#   2 30 min fault-free traffic (learning data + false alarms)
#   3 40 episodes, 10 each of delay/abort/cpu/crash, seed 11 (run3 used 7) -> topo/boutique_fault_log_run4.jsonl
#   4 20 min fault-free traffic, then the fresh test (with the MLP) on the run
# The deployed shadow controller keeps deciding throughout; its events are read from the fleet API afterwards.
cd "$(dirname "$0")/.." || exit 1
PY="$PWD/.venv/Scripts/python"
say() { echo "[$(date -u +%H:%M:%S)] $*"; }

( while true; do kubectl port-forward -n istio-system svc/prometheus 9090:9090 >/dev/null 2>&1; sleep 5; done ) &
PF=$!
until curl -s -m 2 localhost:9090/-/ready >/dev/null; do sleep 2; done
say "prometheus reachable"
( cd meshheal_controlplane && while true; do
    "$PY" -u -m controlplane.collect --namespace boutique --out ../topo/live_boutique_run4.jsonl >> ../topo/collector_run4.log 2>&1
    sleep 5; done ) &
COL=$!
trap 'kill $PF $COL 2>/dev/null' EXIT

say "collecting 30 min of fault-free traffic"
sleep 1800
say "fault run starting"
"$PY" -u -m topo.run_boutique_faults --namespace boutique --types delay abort cpu crash --per-type 10 \
    --hold-s 240 --gap-s 180 --seed 11 --log topo/boutique_fault_log_run4.jsonl --yes > topo/boutique_faults_run4.log 2>&1
say "fault run exit code $? ; $(tail -1 topo/boutique_faults_run4.log)"
say "virtualservices in boutique: $(kubectl get virtualservice -n boutique -o name | tr '\n' ' ')"
kubectl get deploy -n boutique -o jsonpath='{range .items[*]}{.metadata.name} {.spec.template.spec.containers[0].resources.limits.cpu}{"\n"}{end}' > topo/results/run4_cpu_after.txt
say "collecting 20 min of fault-free traffic after the run"
sleep 1200
CUT=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
say "data cut: $CUT; fresh test starting"
"$PY" -m topo.fresh_test --tag phase4_fresh_run4 --snapshots topo/live_boutique_run4.jsonl \
    --fault-log topo/boutique_fault_log_run4.jsonl --mlp --until "$CUT" > topo/results/phase4_fresh_run4.out 2>&1
say "fresh test exit code $?"
say "ALL DONE"
