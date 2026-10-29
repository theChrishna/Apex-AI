# Shadow run: rule vs GNN (dry-run)

Run range 2026-10-26 05:48:25 .. 07:02:26 UTC. Soak 05:48:25-06:18:25. Decay after each fault: 120 s. Telemetry gap threshold: 30 s.

## Telemetry continuity

| window | span (UTC) | status |
|---|---|---|
| soak | 05:48:25-06:18:25 | valid |
| ratings 150ms | 06:18:25-06:25:26 | valid |
| details 75ms | 06:29:26-06:36:26 | valid |
| reviews 150ms | 06:40:26-06:47:26 | valid |
| ratings 75ms | 06:51:26-06:58:26 | valid |

Gaps > 30 s inside the run range: 0

## Fault windows

| fault | scorer | first decision event | s after start | blamed | correct | events in window |
|---|---|---|---|---|---|---|
| ratings 150ms | rule | REROUTE @ 06:19:42 | 76.4 | ratings | yes | 1 |
| ratings 150ms | gnn | REROUTE @ 06:19:42 | 76.4 | ratings | yes | 1 |
| details 75ms | rule | ACTION_BLOCKED no_healthy_alternative @ 06:30:41 | 75.6 | details | yes | 4 |
| details 75ms | gnn | ACTION_BLOCKED no_healthy_alternative @ 06:30:41 | 75.6 | details | yes | 4 |
| reviews 150ms | rule | ACTION_BLOCKED no_healthy_alternative @ 06:41:41 | 75.5 | reviews | yes | 4 |
| reviews 150ms | gnn | ACTION_BLOCKED no_healthy_alternative @ 06:41:41 | 75.5 | reviews | yes | 4 |
| ratings 75ms | rule | REROUTE @ 06:52:27 | 60.5 | ratings | yes | 1 |
| ratings 75ms | gnn | REROUTE @ 06:52:27 | 60.5 | ratings | yes | 1 |

## False events and decay events

**rule**: soak false events 0; rest-period false events 0; decision events inside a 120 s decay 3.
- decay after details 75ms: ACTION_BLOCKED details @ 06:34:41 (+16 s, risk 0.975) after fault end
- decay after reviews 150ms: ACTION_BLOCKED reviews @ 06:45:42 (+15 s, risk 1.0) after fault end
- decay after reviews 150ms: ACTION_BLOCKED reviews @ 06:46:42 (+75 s, risk 0.128) after fault end

**gnn**: soak false events 0; rest-period false events 0; decision events inside a 120 s decay 3.
- decay after details 75ms: ACTION_BLOCKED details @ 06:34:41 (+16 s, risk 0.933) after fault end
- decay after reviews 150ms: ACTION_BLOCKED reviews @ 06:45:41 (+15 s, risk 0.96) after fault end
- decay after reviews 150ms: ACTION_BLOCKED reviews @ 06:46:41 (+75 s, risk 0.0) after fault end

## Scorer health

| scorer | SCORED | source=fallback | LOOP_ERROR | SNAPSHOT_REJECTED |
|---|---|---|---|---|
| rule | 291 | 0 | 0 | 0 |
| gnn | 291 | 0 | 0 | 0 |

GNN fallback count must be 0: OK.

## RELEASE events

- rule: RELEASE ratings @ 06:26:41, 195.7 s after ratings 150ms ended (risk 0.034)
- rule: RELEASE ratings @ 06:59:27, 180.5 s after ratings 75ms ended (risk 0.046)
- gnn: RELEASE ratings @ 06:26:41, 195.6 s after ratings 150ms ended (risk 0.0)
- gnn: RELEASE ratings @ 06:59:27, 180.4 s after ratings 75ms ended (risk 0.0)

Dry-run: the reroute was never applied, so the probe and release only show when the culprit's score fell after the fault was removed, not a recovery caused by the controller.

## Predictions (predictions_shadow.md) vs result

- **WRONG**: ratings 150ms: rule REROUTE blaming ratings, 30-75 s after start; GNN same. (confidence high)
  - ok: rule first event is REROUTE ratings
  - wrong: rule latency in 30-75 s (got 76.4)
  - ok: GNN first event is REROUTE ratings
  - wrong: GNN latency in 30-75 s (got 76.4)
- **WRONG**: ratings 75ms: rule may blame reviews (ACTION_BLOCKED); GNN REROUTE blaming ratings. (medium)
  - wrong: rule blames reviews with ACTION_BLOCKED
  - ok: GNN first event is REROUTE ratings
- **RIGHT**: details 75ms: ACTION_BLOCKED no_healthy_alternative blaming details, both scorers. (medium)
  - ok: rule first event is ACTION_BLOCKED details no_healthy_alternative
  - ok: gnn first event is ACTION_BLOCKED details no_healthy_alternative
- **RIGHT**: reviews 150ms: ACTION_BLOCKED blaming reviews, both scorers. (medium-high)
  - ok: rule first event is ACTION_BLOCKED reviews
  - ok: gnn first event is ACTION_BLOCKED reviews
- **RIGHT**: 30 min no fault: 0-2 false events per scorer, 0 REROUTE. (low)
  - ok: rule soak false events in 0-2 (got 0)
  - ok: rule soak REROUTEs = 0
  - ok: gnn soak false events in 0-2 (got 0)
  - ok: gnn soak REROUTEs = 0
- **WRONG**: Detection time for caught faults: 30-120 s after start, median about 60 s.
  - ok: all 8 correct detections in 30-120 s (got [60.5, 60.5, 75.5, 75.5, 75.6, 75.6, 76.4, 76.4])
  - wrong: median within 45-75 s, my reading of 'about 60' (got 75.5)

Correct detections used for the timing line: 8; median 75.5 s.

## After the run range (not analysed)

- rule: 37 audit events after 07:02:26, 0 of them decision events
- gnn: 37 audit events after 07:02:26, 0 of them decision events
