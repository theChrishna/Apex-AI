# REPORT_PHASE4: a learned per-service baseline instead of the hand-set 100 ms rule

Written 2026-11-25. Numbers only from runs in this repo; every table names its result file. Nothing existing was overwritten.

## The problem
The rule scorer (`in_lat - out_lat`, scaled by a fixed 100 ms) was tuned on Bookinfo. On real Online Boutique it
false-alarmed on **92% of normal snapshots** (`topo/results/phase4_models_vs_baseline_boutique.md`, row `rule`): Boutique's
frontend normally reads about 95 ms, so a fixed 100 ms scale sees constant risk. A scorer that cannot move between
applications without hand-retuning is not deployable.

## What was built
`BaselineScorer` (`meshheal_controlplane/controlplane/scorer.py`) and `python -m controlplane.learn_baseline`.
For each service it learns, from fault-free traffic only (no fault labels, no training), the median and the 99th
percentile of its incoming and outgoing latency. Risk rises only when incoming latency goes **above that normal high
value** by more than the outgoing calls went above theirs (so a victim still cancels, as in the rule), measured in units
of the service's own normal spread (at least 10 ms). Services without a baseline fall back to the hand-set rule.
Available as `--scorer baseline --baseline FILE` and as the optional `baseline` value of the Helm chart. **Not the
default**: the rule scorer stays the default.

## How the design changed, and what that means for the numbers (read this before quoting anything)
The design was iterated **twice on the Online Boutique test data**, which makes the Boutique numbers optimistic:
1. First version: median + MAD. Boutique false alarms 92% -> 32% (`phase4_baseline_boutique_MAD.md`). Inspecting the
   remaining alarms showed the cause: Istio's p95 is bucketed, a low-traffic service sits on one bucket value (MAD 0),
   and normal one-bucket jumps became huge outliers.
2. Upper envelope (q0.99) instead of MAD: false alarms 32% -> 10.5%.
3. Inspecting misses showed the 0..1 risk was hard-capped, so a culprit and its victim could both sit at 1.0 and tie.
   The cap was replaced by a smooth curve anchored at the act threshold, so **exactly the same snapshots cross 0.85**
   (proved by `test_soft_saturation_crosses_the_act_threshold_exactly_where_clamp_does`): false-alarm rates cannot change,
   only the ranking. Both versions are reported (`baseline` = smooth, `baseline_clamp` = capped).

**Bookinfo is the check the design was not shaped on.**

## Result 1: real Bookinfo (independent of the design iterations)
Learn: normal snapshots outside the holdout. Test: all 8 fault episodes (147 steady snapshots) + the holdout normals (the
latest 25% of normal traffic, the same holdout as the original evaluation). Lag and recovery excluded.

With the noisy windows that `REPORT_V3.md` excluded on 2026-10-27 (`excluded_windows_v3.json`; not chosen now) also
excluded (`topo/results/phase4_baseline_bookinfo_v3clean.md`, 69 holdout normals):

| scorer | AP | RC@1 | FPR@0.85 |
|---|---|---|---|
| learned envelope | 0.960 | 1.000 | 0.029 (2 of 69) |
| learned envelope, capped | 0.891 | 0.946 | 0.029 |
| hand-set rule | 0.849 | 0.901 | 0.072 |
| p95 baseline | 0.797 | 0.881 | n/a |

With those windows kept (`phase4_baseline_bookinfo.md`, 137 holdout normals) the learned envelope has AP 0.842, RC@1 0.959
and FPR 0.394; the rule 0.670 / 0.901 / 0.438. **52 of the 54 envelope false alarms fall inside window B1 (Oct 6,
10:42-10:59)**, which REPORT_V3 had already flagged as labelled normal but with elevated latency; most blame `details`.
That is probably a real unlogged anomaly, but it cannot be proven from the data, so both numbers are given.

## Result 2: real Online Boutique (optimistic: the design was iterated on this data)
Learn: first half of the fault-free collection (70 snapshots, 09:32-09:49 UTC). Test: the 10 fault episodes (139 steady)
+ the 27 normals of the fault run + the second half of the fault-free collection (70 snapshots, 09:50-10:07 UTC); 95
normals in total. Models were trained on simulated data only (5 seeds); `±` is the seed std
(`topo/results/phase4_models_vs_baseline_boutique.md`).

| scorer | AP | RC@1 | FPR@0.85 | needs |
|---|---|---|---|---|
| MLP | 0.556 ± 0.044 | 0.783 ± 0.040 | 0.099 ± 0.013 | training, torch |
| **learned envelope** | **0.569** | **0.714** | **0.105** | about 17 min of normal traffic, no labels |
| learned envelope, capped | 0.446 | 0.563 | 0.105 | same |
| GNN + degree features | 0.411 ± 0.073 | 0.719 ± 0.081 | 0.011 ± 0.007 | training, torch |
| GNN | 0.334 ± 0.036 | 0.591 ± 0.039 | 0.040 ± 0.015 | training, torch |
| hand-set rule | 0.303 | 0.418 | 0.916 | nothing |
| p95 baseline | 0.293 | 0.295 | n/a | nothing |

The learned envelope is about level with the MLP on AP and false alarms and somewhat behind on root cause (0.71 vs
0.78, about 1.7 seed std), with no training and no torch. Given the iteration on this data, read it as "comparable to
the MLP", not "better".

## Where it still fails on Boutique (per episode)
Found first in every steady snapshot: adservice 50 ms, cartservice 150 ms, currencyservice 200 ms, frontend 200 ms,
recommendationservice 50 ms (13/13). Misses, with causes:
- **checkout path** (checkoutservice, emailservice, paymentservice, shippingservice): these get about 0.04 req/s, under the
  0.05 req/s evidence floor, so their score is forced to 0. The floor prevents noise from a handful of requests but
  makes rarely used paths invisible. Lowering it was not tried (that would be more tuning on this data).
- **victims hidden by aggregation**: frontend's outgoing latency is a rate-weighted average over all its calls, so one
  slow, rarely called edge (e.g. to shipping) barely moves it, and the victim does not cancel. This is a limit of
  scoring per service; scoring per edge is the fix and was not built.
- **false alarms**: all 10 on Boutique come from frontend, whose page latency has a heavy tail that 70 learning samples
  did not fully capture.

## Result 3: per-edge scoring (the fix for "victims hidden by aggregation")
`EdgeScorer` learns an envelope per caller -> callee edge (latency and failure share, from the caller's side, so
aborts and crashes that never reach a pod are counted). A service's own trouble is what it receives minus its single
worst outgoing edge, so a victim cancels against the one slow call it makes instead of against a rate-weighted average.
Same learning data, same test as Results 1 and 2 (`topo/results/phase4_edge_*.md`):

| data | scorer | AP | RC@1 | FPR@0.85 |
|---|---|---|---|---|
| Boutique | per edge | 0.648 | 0.821 | 0.105 |
| Boutique | per service | 0.569 | 0.714 | 0.105 |
| Bookinfo (v3 windows excluded) | per edge | 0.949 | 1.000 | 0.058 |
| Bookinfo (v3 windows excluded) | per service | 0.960 | 1.000 | 0.029 |

Better root cause on Boutique (0.71 -> 0.82), slightly worse on Bookinfo, same caveat about iterating on Boutique.

## Result 4: what the controller would do (persistence replay)
The real snapshot streams replayed in time order through the controller's own persistence rule (risk > 0.85 in 3 of the
last 4 checks). A false alarm is an alarm ONSET on fault-free traffic, i.e. one reroute or ACTION_BLOCKED
(`topo/results/phase4_persistence*.md`):

| data | scorer | caught | wrong service first | median delay | false alarms per hour (normal hours) |
|---|---|---|---|---|---|
| Boutique | hand-set rule | 6/10 | 8 | 149 s | 27.1 (0.41 h) |
| Boutique | per service | 10/10 | 0 | 63 s | 7.4 (0.41 h) |
| Boutique | per edge | 10/10 | 1 | 66 s | 7.4 (0.41 h) |
| Boutique | MLP (5 seeds) | 3/10 | 2 | 64 s | 7.4 (0.41 h) |
| Bookinfo, v3 windows excluded | per service / per edge | 8/8 | 0 | 57 s | 0 (0.29 h) |

The persistence rule turns a 10% per-snapshot false-alarm rate into a few alarm onsets per hour. The MLP's probabilities
are not calibrated to the 0.85 threshold, so it rarely persists (3/10 Boutique, 0/8 Bookinfo). Normal-traffic time is
short (under half an hour per app), so the per-hour rates are rough.

## Result 5: run3, four fault types, scorers frozen beforehand
Online Boutique, 2026-11-25, `topo/run_boutique_faults.py`: 32 episodes, 8 each of delay (50/100/200 ms), abort (50% of
requests fail: gRPC UNAVAILABLE, HTTP 503 for frontend), CPU starvation (limit 25m) and crash (the pod deleted every 60 s),
4 min each with 3 min gaps, services and order shuffled (seed 7). Planned: 40 episodes. Docker Desktop stopped during
episode 33 (a known problem on this PC); the 32 completed episodes are balanced across types and are used as they are.
The unlogged partial episode 33 and the outage are excluded from every number below (08:05:27 to 08:50 UTC). Nothing
was left behind: no VirtualService in `boutique`, every CPU limit back to its normal value.

**5a. The deployed controller, live.** The in-cluster `meshheal-boutique` controller (shadow mode, per-edge scorer,
baseline learned that morning from fault-free traffic before the run) made its decisions during the run as it would in
production. Its events were exported from the fleet API's store (`topo/results/run3_controller_boutique_events.jsonl`,
985 checks) and matched to the fault log by `topo/live_decisions.py` (`topo/results/phase4_live_shadow_run3.md`). With
no playbook for Boutique, a persistent alarm appears as ACTION_BLOCKED (`no_healthy_alternative`).

| fault type | caught | wrong service first | median detection delay |
|---|---|---|---|
| abort | 7/8 | 1 | 75 s |
| CPU starvation | 7/8 | 3 | 88 s |
| crash | 8/8 | 1 | 91 s |
| delay | 7/8 | 1 | 90 s |

29/32 caught, 26 with the right service alarmed first. Missed: a 100 ms delay on checkoutservice (no alarm), an abort on
emailservice (no alarm; it is on the rarely used checkout path, cause not investigated further) and CPU starvation of shippingservice
(currencyservice alarmed instead). CPU starvation is the hardest: slow callees and slow callers look alike. No false
alarm in the 0.30 h of fault-free time away from episodes during the live run, too little time to give a rate.

**5b. Offline fresh test** (`topo/fresh_test.py`, `topo/results/phase4_fresh_run3.md`). Scorer designs were frozen
before run3 existed. Baselines learned ONLY from the first 60% of the fault-free snapshots before the run (108 snapshots,
about 27 min); false alarms measured on the other 164 fault-free snapshots (before the run, and 08:50-09:10 after the
restart; 0.69 h). Persistence replay, as the controller would act:

| scorer | abort | CPU | crash | delay | wrong service first | false-alarm onsets (0.69 h) |
|---|---|---|---|---|---|---|
| **per edge** | **7/8** | **7/8** | **8/8** | **6/8** | 9 of 32 | **0** |
| per service | 1/8 | 2/8 | 3/8 | 3/8 | 5 of 32 | 0 |
| MLP (5 seeds) | 0/8 | 2/8 | 2/8 | 2/8 | 2 of 32 | 0 |
| hand-set rule | 1/8 | 1/8 | 2/8 | 3/8 | 29 of 32 | 18 (26 per hour) |

Per snapshot (314 steady fault snapshots): per edge AP 0.512, root cause first 0.592 (abort 0.79, delay 0.70, crash
0.63, CPU 0.25); per service 0.231 / 0.283; MLP 0.275 / 0.229; rule 0.201 / 0.154. False alarms per snapshot: 0 for the
learned scorers and the MLP, 0.573 for the rule.

What this says, plainly:
- Only the per-edge scorer handles the new fault types, because only it looks at failures (aborts and crashes show up
  as failed calls from the caller's side, not as latency). The per-service envelope is latency only, so it was never
  going to see them.
- The offline replay (28/32) and the deployed controller (29/32, 5a) agree, with baselines learned from different
  fault-free windows. That is the closest thing here to a repeat measurement.
- CPU starvation is caught but poorly ranked per snapshot (root cause first 0.25): the starved service and its callers
  slow down together.
- **Not repeatable as hoped on delay faults:** per service caught 10/10 delay faults in run2 but 3/8 here; per edge 10/10
  in run2, 6/8 here. Run3's baseline came from 27 min of traffic and produced no false alarms at all (run2: about 10% per
  snapshot), which suggests a wider envelope and so less sensitivity; this was not investigated further. Run2's numbers
  were also measured on the data the design was iterated on, so run3 is the more honest figure.
- Small numbers: 8 episodes per type and 0.69 h of fault-free time. "0 false alarms" in 0.69 h only bounds the rate at
  roughly 4 per hour (95%, rule of three).

## Result 6: run4, a fresh measurement of image 0.7.1 (fan-out weighting)
The fan-out fix (REPORT_PHASE6.md) was made after a live failure and had only been checked on data the design was
developed on. Run4 is new data: 2026-11-25, 11:03-16:47 UTC, `topo/run4.sh`. 30 min of fault-free traffic, 40 episodes
(10 per type, same fault sizes and timing as run3, new order and services, seed 11), 20 min of fault-free traffic. All 40
episodes completed; nothing was left behind (no VirtualService in `boutique`, every CPU limit back to its default,
`topo/results/run4_cpu_after.txt`).

One incident, excluded from every number below: after the crash episode on currencyservice (episode 12) its new pod was
scheduled on agent-1, which had no copy of the image (the node had re-registered that morning) and failed to pull it.
currencyservice was down from 13:02:18 to 13:09:42 UTC, in the gap before episode 13 (no episode overlaps it). The
window 13:02:18-13:10:30 is excluded. Without the exclusion the per-edge scorer has one false-alarm onset, inside that
window (`phase4_fresh_run4_noexclude.md`). All Boutique images were then imported into the cluster so later crashes
could not hit the same problem.

**6a. The deployed controller, live** (`meshheal-boutique`, image 0.7.1, shadow mode, per-edge scorer with the baseline
learned that morning; 1358 checks exported read-only from the fleet store to `run4_controller_boutique_events.jsonl`;
`phase4_live_shadow_run4.md`):

| fault type | caught | wrong service first | median detection delay |
|---|---|---|---|
| abort | 7/10 | 5 | 78 s |
| CPU starvation | 9/10 | 1 | 81 s |
| crash | 9/10 | 4 | 77 s |
| delay | 9/10 | 4 | 74 s |

34/40 caught. In 14 of the 40 episodes another service alarmed first (10 of them later caught, 4 missed); 12 of those
14 first alarms were on frontend or checkoutservice, the callers on the checkout path. Missed: aborts on recommendationservice,
emailservice and checkoutservice, the currencyservice crash (episode 12, the one followed by the outage), a delay on
checkoutservice, CPU starvation of productcatalogservice. One false-alarm onset (paymentservice, 12:24:14) in 0.80 h of
fault-free time.

**6b. Offline fresh test** (`phase4_fresh_run4.md`; baselines from the first 60% of the fault-free snapshots before the
run, 59 snapshots, about 17 min; false alarms on the other 131 fault-free snapshots, 0.55 h):

| scorer | abort | CPU | crash | delay | wrong service first | false-alarm onsets (0.55 h) |
|---|---|---|---|---|---|---|
| **per edge (0.7.1)** | **7/10** | **7/10** | **9/10** | **6/10** | 12 of 40 | **0** |
| per service | 1/10 | 4/10 | 5/10 | 6/10 | 15 of 40 | 0 |
| MLP (5 seeds) | 0/10 | 2/10 | 3/10 | 3/10 | 5 of 40 | 0 |
| hand-set rule | 1/10 | 2/10 | 3/10 | 6/10 | 31 of 40 | 15 (27 per hour) |

Per snapshot (377 steady fault snapshots): per edge AP 0.403, root cause first 0.539 (abort 0.64, crash 0.66, delay
0.65, CPU 0.18); per service 0.197 / 0.266; MLP 0.285 / 0.268; rule 0.177 / 0.196.

Run3 and run4 side by side (per-edge scorer):

| | run3 (0.7.0 design, 32 episodes) | run4 (0.7.1, 40 episodes) |
|---|---|---|
| offline caught | 28/32 (88%) | 29/40 (73%) |
| live caught | 29/32 (91%) | 34/40 (85%) |
| live: another service alarmed first | 6 of 32 | 14 of 40 |
| AP / root cause first, per snapshot | 0.512 / 0.592 | 0.403 / 0.539 |
| false-alarm onsets | 0 offline (0.69 h), 0 live (0.30 h) | 0 offline (0.55 h), 1 live (0.80 h) |

What this says, plainly:
- The per-edge scorer is still far ahead of the alternatives on new data, and the only one that handles aborts and
  crashes. Its false alarms stay low (one onset in about 1.4 h of fault-free time across both measurements).
- Run4 is **worse than run3** on detection and clearly worse on ranking (another service alarmed first live: 6 of 32 -> 14 of 40).
  **The fan-out change is not the cause.** Run4 re-scored offline with fan-out switched off (`--no-fanout`,
  `phase4_fresh_run4_nofanout.md`, same learning data and exclusions) gives the same 29/40 caught and AP 0.398 vs
  0.403. Exactly one episode differs: a 200 ms delay on currencyservice (episode 35), where with fan-out the right
  service alarmed first after 67 s and without it checkoutservice alarmed first (right service at 128 s). On run3
  the only change was AP 0.512 -> 0.513; every episode was the same. So on unseen data the fix is neutral to slightly helpful, and it fixed the
  canary case it was made for. The drop from run3 comes from something else: the two runs differ in which services
  got which fault, in order, and in learning data (run4 learned from about 17 min, run3 from 27 min); which of these
  matters was not tested.
- CPU starvation is still ranked poorly per snapshot (0.18); delay detection is 6/10 offline, about as in run3 (6/8).
- 10 episodes per type and under an hour of fault-free time per measurement: the per-type rates move by 10-20 points
  with one episode, so differences of one or two episodes are noise.

## What this does and does not show
- Shows: a learned per-service envelope removes most of the hand-set rule's portability problem, with no labels and no
  training, and is about as good as the best trained model on the one independent real app tested.
- Shows (run3, run4): with per-edge scoring the controller caught 28-29 of 32 (run3) and 29-34 of 40 (run4) faults of
  four types on fresh data, offline and live, with one false-alarm onset in about 2.3 h of fault-free time across both.
  Another service often alarms first (live: 6 of 32 episodes in run3, 14 of 40 in run4).
- Does not show: production readiness. Two real applications on one laptop cluster, injected faults, load-generated
  traffic, under an hour of fault-free time per measurement, 8 episodes per fault type. Delay detection dropped between
  run2 and run3 and the reason is not established. On run4 the 0.7.1 fan-out fix changed one episode of 40 (for the better); it is not the cause of the drop. Remediation for Boutique was not tested (no playbook).
