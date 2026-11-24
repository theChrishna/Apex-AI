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

## What this does and does not show
- Shows: a learned per-service envelope removes most of the hand-set rule's portability problem, with no labels and no
  training, and is about as good as the best trained model on the one independent real app tested.
- Does not show: production readiness. 10% false alarms per snapshot is too high to act on without the controller's
  persistence rule (3 of 4 checks), whose effect on these numbers was not measured. Two real applications, delay faults
  only, one run per episode. Fault types other than delay, repeated runs and per-edge scoring remain open.
