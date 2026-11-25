#!/usr/bin/env bash
# Second half of topo/after_run3.sh, after Docker Desktop died during episode 33 (run3 ended with 32 completed episodes).
# Excluded from the fresh test: the unlogged partial episode 33 (frontend crash from 08:05:27) and the outage plus
# 10 minutes of settling after the restart (until 08:50).
cd "$(dirname "$0")/.." || exit 1
PY=.venv/Scripts/python
say() { echo "[$(date -u +%H:%M:%S)] $*"; }
until [ "$(date -u +%H%M)" -ge 0910 ]; do sleep 20; done
CUT=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
say "data cut for the fresh test: $CUT"
$PY -m topo.fresh_test --tag phase4_fresh_run3 --snapshots topo/live_boutique_20261125c.jsonl \
    --fault-log topo/boutique_fault_log_run3.jsonl --mlp --until "$CUT" \
    --exclude 2026-11-25T08:05:27+00:00 2026-11-25T08:50:00+00:00 > topo/results/phase4_fresh_run3.out 2>&1 &
FT=$!
say "canary test starting"
$PY -u -m topo.canary_test --yes > topo/results/phase6_canary_live.out 2>&1
say "canary test exit code $?"
wait $FT
say "fresh test exit code $?"
say "left in boutique: $(kubectl get virtualservice,destinationrule -n boutique -o name | tr '\n' ' ')"
say "ALL DONE"
