#!/usr/bin/env bash
# Runs the steps that follow fault run3, unattended. Log: topo/after_run3.log
#   1 wait for run3 to end; check nothing was left behind
#   2 save the in-cluster Boutique shadow controller's log BEFORE the canary test restarts its pod
#   3 wait 20 min of clean traffic (fault-free snapshots after the run, for false alarms)
#   4 fresh test (data cut at the canary start) in the background, and the live canary test
cd "$(dirname "$0")/.." || exit 1
PY=.venv/Scripts/python
say() { echo "[$(date -u +%H:%M:%S)] $*"; }

say "waiting for run3 to finish"
until grep -qE "VirtualServices left in|Traceback" topo/boutique_faults_run3.log; do sleep 30; done
say "run3 ended: $(tail -1 topo/boutique_faults_run3.log)"
grep -E "Traceback|!!" topo/boutique_faults_run3.log && say "!! run3 reported problems: check before trusting results"
say "fault-log episodes: $(wc -l < topo/boutique_fault_log_run3.jsonl)"
say "virtualservices in boutique: $(kubectl get virtualservice -n boutique -o name | tr '\n' ' ')"
kubectl get deploy -n boutique -o jsonpath='{range .items[*]}{.metadata.name} {.spec.template.spec.containers[0].resources.limits.cpu}{"\n"}{end}' > topo/results/run3_cpu_after.txt
say "cpu limits after run saved to topo/results/run3_cpu_after.txt"

kubectl logs -n meshheal-system deploy/meshheal-boutique-controlplane -c controller --tail=-1 > topo/results/run3_controller_boutique.log
say "controller log saved: $(wc -l < topo/results/run3_controller_boutique.log) lines"

say "collecting 20 min of fault-free traffic"
sleep 1200
CUT=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
say "data cut for the fresh test: $CUT"
$PY -m topo.fresh_test --tag phase4_fresh_run3 --snapshots topo/live_boutique_20261125c.jsonl \
    --fault-log topo/boutique_fault_log_run3.jsonl --mlp --until "$CUT" > topo/results/phase4_fresh_run3.out 2>&1 &
FT=$!
say "canary test starting"
$PY -u -m topo.canary_test --yes > topo/results/phase6_canary_live.out 2>&1
say "canary test exit code $?"
wait $FT
say "fresh test exit code $?"
say "virtualservices in boutique now: $(kubectl get virtualservice,destinationrule -n boutique -o name | tr '\n' ' ')"
say "ALL DONE"
