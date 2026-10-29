"""Decision engine: persistence rule, safety checks (FR-3.3), reroute / probe / release state machine."""
from collections import deque
from datetime import datetime, timezone

from .playbook import PLAYBOOK, deps_of, depends_on, reroute_weights
from .scorer import as_result
from .snapshot import BadSnapshot, node_stats

NORMAL, REROUTED, PROBING = "NORMAL", "REROUTED", "PROBING"


class Controller:
    def __init__(self, cfg, scorer, client, audit, clock=None, dry_run=False):
        self.cfg, self.scorer, self.client, self.audit = cfg, scorer, client, audit
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.dry_run = dry_run
        self.history = deque(maxlen=cfg.persist_window)   # top node above threshold, or None
        self.active = {}                                  # culprit -> {"mode","since","plan"}
        self.last_action = {}                             # culprit -> ts of last write
        self._blocked = {}                                # culprit -> (reason, ts)
        self._last_snap_ts = None                         # newest snapshot timestamp already processed

    # ------------------------------------------------------------------ helpers
    def _log(self, event, **kw):
        return self.audit.write(self.clock(), event, dry_run=self.dry_run, **kw)

    def _persistent_top(self, scores):
        top = max(scores, key=scores.get)
        self.history.append(top if scores[top] > self.cfg.act_threshold else None)
        hits = sum(1 for h in self.history if h == top)
        # the current cycle must be a hit too: 3 old hits + a recovered reading is not a fault
        return top if hits >= self.cfg.persist_required and self.history[-1] == top else None

    def _safety(self, node, plan, scores, now):
        """Return a block reason or None (FR-3.3)."""
        if plan is None:
            return "no_healthy_alternative"
        if node in self.last_action and (now - self.last_action[node]).total_seconds() < self.cfg.cooldown_s:
            return "cooldown"
        if not self.client.subset_ready(plan.virtual_service, plan.target_subset):
            return "target_pod_not_ready"
        if plan.virtual_service == node or node in deps_of(plan.virtual_service, plan.target_subset):
            return "circular_route"   # target path depends on the faulty node
        if scores.get(plan.virtual_service, 0.0) >= self.cfg.act_threshold:
            return "alternative_unhealthy"
        return None

    def _log_throttled(self, event, node, key, now, **kw):
        prev = self._blocked.get(node)
        if prev and prev[0] == key and (now - prev[1]).total_seconds() < self.cfg.blocked_relog_s:
            return
        self._blocked[node] = (key, now)
        self._log(event, node=node, **kw)

    def _block(self, node, reason, risk, now):
        self._log_throttled("ACTION_BLOCKED", node, reason, now, risk=round(risk, 3), reason=reason)

    def _victim_of(self, node):
        """Active (rerouted) culprit that `node` depends on, if any."""
        return next((c for c in self.active if depends_on(node, c)), None)

    def _apply(self, node, plan, weights, now, event, **kw):
        self.client.set_weights(plan.virtual_service, weights)
        self.last_action[node] = now
        self._log(event, node=node, virtual_service=plan.virtual_service, weights=weights, **kw)

    # ------------------------------------------------------------------ main step
    def step(self, snap):
        """One control iteration on a validated snapshot. Returns the audit events it produced."""
        n0 = len(self.audit.events)
        now = self.clock()
        age = (now - snap.ts).total_seconds()
        if age > self.cfg.max_snapshot_age_s:
            self._log("SNAPSHOT_REJECTED", reason="stale", age_s=round(age, 1))
            return self.audit.events[n0:]

        stats = node_stats(snap)
        res = as_result(self.scorer, stats, snap)
        scores = res.scores
        top = max(scores, key=scores.get)
        self._log("SCORED", top=top, risk=round(scores[top], 3), source=res.source,
                  **({"note": res.note} if res.note else {}))

        self._manage_active(stats, scores, now)

        node = self._persistent_top(scores)
        culprit = self._victim_of(node) if node and node not in self.active else None
        if culprit:
            self._log_throttled("SUPPRESSED_VICTIM", node, f"victim_of:{culprit}", now,
                                culprit=culprit, risk=round(scores[node], 3))
        elif node and node not in self.active:
            plan = PLAYBOOK.get(node)
            reason = self._safety(node, plan, scores, now)
            if reason:
                self._block(node, reason, scores[node], now)
            else:
                self._apply(node, plan, reroute_weights(plan), now, "REROUTE",
                            culprit=node, risk=round(scores[node], 3), why=plan.reason)
                self.active[node] = {"mode": REROUTED, "since": now, "plan": plan}
                self._blocked.pop(node, None)
        return self.audit.events[n0:]

    def _manage_active(self, stats, scores, now):
        for node, st in list(self.active.items()):
            plan, elapsed = st["plan"], (now - st["since"]).total_seconds()
            if st["mode"] == REROUTED and elapsed >= self.cfg.cooldown_s:
                self._apply(node, plan, reroute_weights(plan, self.cfg.probe_share), now,
                            "PROBE_START", culprit=node)
                st.update(mode=PROBING, since=now)
            elif st["mode"] == PROBING and elapsed >= self.cfg.probe_s:
                evidence = stats[node]["in_rate"] >= self.cfg.min_evidence_rate
                if evidence and scores[node] < self.cfg.release_threshold:
                    self._apply(node, plan, dict(plan.normal_weights), now, "RELEASE",
                                culprit=node, risk=round(scores[node], 3))
                    del self.active[node]
                    self.history.clear()
                else:
                    why = "no_evidence" if not evidence else f"risk={scores[node]:.2f}"
                    self._apply(node, plan, reroute_weights(plan), now, "PROBE_FAILED",
                                culprit=node, why=why)
                    st.update(mode=REROUTED, since=now)


def step_from_file(ctrl, path):
    """Read newest snapshot from disk, validate, step. Bad input -> SNAPSHOT_REJECTED, never a crash."""
    from .snapshot import read_last_snapshot
    try:
        snap = read_last_snapshot(path, ctrl.cfg.expected_nodes)
    except BadSnapshot as e:
        ctrl._log("SNAPSHOT_REJECTED", reason=e.reason)
        return None
    if snap.ts == ctrl._last_snap_ts:
        return None
    ctrl._last_snap_ts = snap.ts
    return ctrl.step(snap)
