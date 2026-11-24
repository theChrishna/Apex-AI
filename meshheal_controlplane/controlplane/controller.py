"""Decision engine: persistence rule, safety checks (FR-3.3), reroute / probe / release state machine.

Phase 5: every write that changes a reroute also records the reroute in the cluster (an annotation on the
VirtualService, written in the same API call as the weights). After a restart, reconcile() rebuilds the in-memory
state from those annotations, so a crash can never leave a service rerouted with nobody responsible for releasing it.
"""
from collections import deque
from datetime import datetime, timezone

from .cluster import KEEP, ClusterError
from .playbook import Reroute, default_playbook, reroute_weights
from .scorer import as_result
from .snapshot import BadSnapshot, node_stats, parse_ts

NORMAL, REROUTED, PROBING = "NORMAL", "REROUTED", "PROBING"


class Controller:
    def __init__(self, cfg, scorer, client, audit, clock=None, dry_run=False, playbook=None):
        self.cfg, self.scorer, self.client, self.audit = cfg, scorer, client, audit
        self.playbook = playbook or default_playbook()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.dry_run = dry_run
        self.history = deque(maxlen=cfg.persist_window)   # top node above threshold, or None
        self.active = {}                                  # culprit -> {"mode","since","started","plan"}
        self.last_action = {}                             # culprit -> ts of last write
        self._blocked = {}                                # culprit -> (reason, ts)
        self._last_snap_ts = None                         # newest snapshot timestamp already processed
        self._reroute_times = deque()                     # when new reroutes were started (rate limit)
        self._paused = False                              # frozen by the control ConfigMap (refreshed every step)

    # ------------------------------------------------------------------ helpers
    def _log(self, event, **kw):
        return self.audit.write(self.clock(), event, dry_run=self.dry_run, **kw)

    def status(self):
        return {"active_reroutes": len(self.active), "paused": self._paused, "dry_run": self.dry_run}

    def _check_paused(self, now):
        """Operators freeze the controller with the control ConfigMap. If that cannot be read (anything but "not
        found"), assume paused: not writing is the safe direction."""
        fn = getattr(self.client, "is_paused", None)
        if not fn:
            return False
        try:
            return bool(fn())
        except Exception as e:
            self._log_throttled("PAUSE_CHECK_FAILED", "_control", str(e), now, error=str(e), treated_as="paused")
            return True

    def _persistent_top(self, scores):
        top = max(scores, key=scores.get)
        self.history.append(top if scores[top] > self.cfg.act_threshold else None)
        hits = sum(1 for h in self.history if h == top)
        # the current cycle must be a hit too: 3 old hits + a recovered reading is not a fault
        return top if hits >= self.cfg.persist_required and self.history[-1] == top else None

    def _rate_limited(self, now):
        limit = self.cfg.max_actions_per_hour
        if not limit:
            return False
        while self._reroute_times and (now - self._reroute_times[0]).total_seconds() >= 3600:
            self._reroute_times.popleft()
        return len(self._reroute_times) >= limit

    def _safety(self, node, plan, scores, now):
        """Return a block reason or None (FR-3.3)."""
        if plan is None:
            return "no_healthy_alternative"
        if not plan.confirmed:
            return "playbook_unconfirmed"   # a generated draft: a human must set confirmed: true
        if self._paused:
            return "paused"
        if self._rate_limited(now):
            return "rate_limited"
        if node in self.last_action and (now - self.last_action[node]).total_seconds() < self.cfg.cooldown_s:
            return "cooldown"
        if not self.client.subset_ready(plan.virtual_service, plan.target_subset):
            return "target_pod_not_ready"
        if plan.virtual_service == node or node in self.playbook.deps_of(plan.virtual_service, plan.target_subset):
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
        return next((c for c in self.active if self.playbook.depends_on(node, c)), None)

    def _state(self, node, plan, mode, started, since):
        """What is recorded on the VirtualService while a reroute is active."""
        return {"version": 1, "culprit": node, "virtual_service": plan.virtual_service, "mode": mode,
                "target_subset": plan.target_subset, "normal_weights": dict(plan.normal_weights),
                "started": started.isoformat(), "since": since.isoformat()}

    def _apply(self, node, plan, weights, now, event, state=KEEP, **kw):
        """Write the weights (and the recorded state, in the same call) and log `event`. Returns False, with nothing
        changed, if the controller is paused or the cluster refused the change."""
        if self._paused:
            self._log_throttled("ACTION_BLOCKED", node, "paused", now, reason="paused", attempted=event)
            return False
        try:
            self.client.set_weights(plan.virtual_service, weights, state=state)
        except ClusterError as e:
            self._log_throttled("ACTION_FAILED", node, f"{event}:{e}", now, attempted=event,
                                virtual_service=plan.virtual_service, error=str(e))
            return False
        self.last_action[node] = now
        self._log(event, node=node, virtual_service=plan.virtual_service, weights=weights, **kw)
        return True

    # ------------------------------------------------------------------ restart safety
    def reconcile(self):
        """Call once at startup. Rebuild `active` from the reroutes recorded in the cluster; release any that are too
        old or that this playbook no longer covers (restoring the recorded normal weights: the safe direction)."""
        now = self.clock()
        try:
            states = self.client.list_states()
        except Exception as e:
            self._log("RECONCILE_FAILED", error=str(e))
            return
        self._paused = self._check_paused(now)
        for vs, st in sorted(states.items()):
            culprit = st.get("culprit")
            try:
                started, since = parse_ts(st["started"]), parse_ts(st["since"])
            except (KeyError, ValueError, TypeError):
                started = since = None
            if "_error" in st or not culprit or started is None:
                self._log("RECONCILE_ORPHAN", virtual_service=vs, reason=st.get("_error", "incomplete state"),
                          action="none: needs a human")
                continue
            plan = self.playbook.reroutes.get(culprit)
            usable = plan is not None and plan.virtual_service == vs and plan.confirmed
            expired = bool(self.cfg.max_reroute_s) and (now - started).total_seconds() > self.cfg.max_reroute_s
            if usable and not expired:
                mode = st.get("mode") if st.get("mode") in (REROUTED, PROBING) else REROUTED
                self.active[culprit] = {"mode": mode, "since": since, "started": started, "plan": plan}
                self.last_action[culprit] = since
                self._log("RECONCILED", node=culprit, virtual_service=vs, mode=mode, since=since.isoformat(),
                          started=started.isoformat())
                continue
            weights = dict(plan.normal_weights) if usable else st.get("normal_weights")
            if not isinstance(weights, dict) or not weights or sum(weights.values()) != 100:
                self._log("RECONCILE_ORPHAN", virtual_service=vs, reason="no valid normal weights recorded",
                          action="none: needs a human")
                continue
            release_plan = plan if usable else Reroute(culprit=culprit, virtual_service=vs,
                                                       target_subset=str(st.get("target_subset", "")),
                                                       normal_weights=tuple(weights.items()),
                                                       reason="recovered from cluster state", confirmed=False)
            self._apply(culprit, release_plan, weights, now, "RELEASE", state=None, culprit=culprit,
                        why="expired_on_restart" if usable else "no_confirmed_playbook_entry_on_restart")

    # ------------------------------------------------------------------ main step
    def step(self, snap):
        """One control iteration on a validated snapshot. Returns the audit events it produced."""
        n0 = len(self.audit.events)
        now = self.clock()
        age = (now - snap.ts).total_seconds()
        if age > self.cfg.max_snapshot_age_s:
            self._log("SNAPSHOT_REJECTED", reason="stale", age_s=round(age, 1))
            return self.audit.events[n0:]

        self._paused = self._check_paused(now)
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
            plan = self.playbook.reroutes.get(node)
            reason = self._safety(node, plan, scores, now)
            if reason:
                self._block(node, reason, scores[node], now)
            else:
                if self._apply(node, plan, reroute_weights(plan), now, "REROUTE",
                               state=self._state(node, plan, REROUTED, now, now),
                               culprit=node, risk=round(scores[node], 3), why=plan.reason):
                    self.active[node] = {"mode": REROUTED, "since": now, "started": now, "plan": plan}
                    self._reroute_times.append(now)
                    self._blocked.pop(node, None)
        return self.audit.events[n0:]

    def _manage_active(self, stats, scores, now):
        for node, st in list(self.active.items()):
            plan, elapsed = st["plan"], (now - st["since"]).total_seconds()
            started = st.get("started", st["since"])
            if self.cfg.max_reroute_s and (now - started).total_seconds() > self.cfg.max_reroute_s:
                # a reroute must never be permanent: give the traffic back, and let the normal rules decide again
                if self._apply(node, plan, dict(plan.normal_weights), now, "RELEASE", state=None,
                               culprit=node, why="expired", risk=round(scores.get(node, 0.0), 3)):
                    del self.active[node]
                    self.history.clear()
                continue
            if st["mode"] == REROUTED and elapsed >= self.cfg.cooldown_s:
                if self._apply(node, plan, reroute_weights(plan, self.cfg.probe_share), now, "PROBE_START",
                               state=self._state(node, plan, PROBING, started, now), culprit=node):
                    st.update(mode=PROBING, since=now)
            elif st["mode"] == PROBING and elapsed >= self.cfg.probe_s:
                evidence = stats[node]["in_rate"] >= self.cfg.min_evidence_rate
                if evidence and scores[node] < self.cfg.release_threshold:
                    if self._apply(node, plan, dict(plan.normal_weights), now, "RELEASE", state=None,
                                   culprit=node, risk=round(scores[node], 3)):
                        del self.active[node]
                        self.history.clear()
                else:
                    why = "no_evidence" if not evidence else f"risk={scores[node]:.2f}"
                    if self._apply(node, plan, reroute_weights(plan), now, "PROBE_FAILED",
                                   state=self._state(node, plan, REROUTED, started, now), culprit=node, why=why):
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
