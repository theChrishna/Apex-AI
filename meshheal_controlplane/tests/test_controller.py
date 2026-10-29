import json
from datetime import datetime, timedelta, timezone

import pytest

from controlplane.audit import AuditLog
from controlplane.cluster import FakeClient
from controlplane.config import Config
from controlplane.controller import Controller, step_from_file
from controlplane.playbook import depends_on
from controlplane.scorer import ResilientScorer, RuleScorer
from controlplane.snapshot import BadSnapshot, parse_snapshot

T0 = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
NODES = [{"id": n, "region": "aws-us-east"} for n in ("productpage", "details", "reviews", "ratings")]


def snap_obj(ts, ratings_ms=0, details_ms=0, rate=5.0):
    """ratings fault: ratings in-latency AND reviews in/out latency are high (reviews is a victim)."""
    def e(s, d, lat):
        return {"source": s, "destination": d, "request_rate": rate, "error_rate": 0.0, "latency_p95": lat}
    return {"timestamp": ts.isoformat(), "nodes": NODES, "edges": [
        e("productpage", "details", 10 + details_ms),
        e("productpage", "reviews", 25 + ratings_ms),
        e("reviews", "ratings", 10 + ratings_ms)]}


def victim_obj(ts, rate=5.0):
    """Bucketed-p95 pattern seen in replay ep 3: reviews' inbound lands in a higher bucket than its
    outbound call to ratings, so reviews out-scores ratings even though it is only waiting on it."""
    def e(s, d, lat):
        return {"source": s, "destination": d, "request_rate": rate, "error_rate": 0.0, "latency_p95": lat}
    return {"timestamp": ts.isoformat(), "nodes": NODES, "edges": [
        e("productpage", "details", 10), e("productpage", "reviews", 240), e("reviews", "ratings", 97.5)]}


def run_victim(ctrl, box, n):
    out = []
    for _ in range(n):
        box["now"] += timedelta(seconds=15)
        out += ctrl.step(parse_snapshot(victim_obj(box["now"])))
    return out


def make(client=None, scorer=None, **cfg_kw):
    box = {"now": T0}
    cfg = Config(**cfg_kw)
    ctrl = Controller(cfg, scorer or RuleScorer(cfg.self_lat_full_ms), client or FakeClient(),
                      AuditLog(None), clock=lambda: box["now"])
    return ctrl, box


def run(ctrl, box, n, **kw):
    out = []
    for _ in range(n):
        box["now"] += timedelta(seconds=15)
        out += ctrl.step(parse_snapshot(snap_obj(box["now"], **kw)))
    return out


def events(ev, name):
    return [e for e in ev if e["event"] == name]


def test_normal_traffic_does_nothing():
    ctrl, box = make()
    ev = run(ctrl, box, 20)
    assert not events(ev, "REROUTE") and not events(ev, "ACTION_BLOCKED")


def test_ratings_fault_triggers_reroute_after_3_of_4():
    client = FakeClient()
    ctrl, box = make(client)
    run(ctrl, box, 3)
    ev = run(ctrl, box, 2, ratings_ms=150)
    assert not events(ev, "REROUTE")
    ev = run(ctrl, box, 1, ratings_ms=150)
    rr = events(ev, "REROUTE")
    assert len(rr) == 1 and rr[0]["culprit"] == "ratings"
    assert client.weights["reviews"] == {"v1": 100, "v2": 0, "v3": 0}


def test_persistence_needs_a_hit_in_the_current_cycle():
    ctrl, _ = make()
    hot, cooling = {"details": 0.9, "reviews": 0.1}, {"details": 0.7, "reviews": 0.1}
    assert [ctrl._persistent_top(hot) for _ in range(3)] == [None, None, "details"]
    assert ctrl._persistent_top(cooling) is None      # 3 of last 4 are hits, but not this one


def test_recovered_node_is_not_acted_on():
    ctrl, box = make(blocked_relog_s=0)              # no throttling, so every decision is logged
    ev = run(ctrl, box, 3, details_ms=150)
    assert len(events(ev, "ACTION_BLOCKED")) == 1
    ev = run(ctrl, box, 1, details_ms=60)            # details still top, risk 0.7 < 0.85
    assert not events(ev, "ACTION_BLOCKED")


def test_sustained_fault_triggers_on_the_same_cycle():
    ctrl, box = make()
    run(ctrl, box, 3)
    per_cycle = [bool(events(run(ctrl, box, 1, details_ms=150), "ACTION_BLOCKED")) for _ in range(4)]
    assert per_cycle == [False, False, True, False]  # 3rd fault cycle, then throttled


def test_victim_reviews_is_not_blamed():
    ctrl, box = make()
    ev = run(ctrl, box, 8, ratings_ms=150)
    assert all(e.get("culprit", "ratings") == "ratings" for e in events(ev, "REROUTE"))
    assert not [e for e in ev if e["event"] == "SCORED" and e["top"] == "reviews"]


def test_single_version_service_is_blocked_once():
    client = FakeClient()
    ctrl, box = make(client)
    ev = run(ctrl, box, 8, details_ms=150)
    blocked = events(ev, "ACTION_BLOCKED")
    assert blocked and blocked[0]["reason"] == "no_healthy_alternative"
    assert len(blocked) == 2          # 8 cycles = 120s -> logged once, re-logged after 60s (not 6 times)
    assert not client.calls


def test_pod_not_ready_blocks():
    client = FakeClient(ready={("reviews", "v1"): False})
    ctrl, box = make(client)
    ev = run(ctrl, box, 6, ratings_ms=150)
    assert [e["reason"] for e in events(ev, "ACTION_BLOCKED")][:1] == ["target_pod_not_ready"]
    assert not client.calls


def test_stale_snapshot_rejected():
    ctrl, box = make()
    old = parse_snapshot(snap_obj(T0 - timedelta(seconds=300), ratings_ms=150))
    ev = ctrl.step(old)
    assert ev[0]["event"] == "SNAPSHOT_REJECTED" and ev[0]["reason"] == "stale"


def test_nan_and_missing_nodes_rejected():
    o = snap_obj(T0)
    o["edges"][0]["latency_p95"] = float("nan")
    with pytest.raises(BadSnapshot):
        parse_snapshot(o, ("ratings",))
    o = snap_obj(T0)
    o["nodes"] = o["nodes"][:3]
    with pytest.raises(BadSnapshot):
        parse_snapshot(o, ("ratings",))
    o = snap_obj(T0, rate=0.0)
    o["edges"][0]["latency_p95"] = float("nan")
    parse_snapshot(o, ("ratings",))


def test_probe_then_release_when_fault_gone():
    client = FakeClient()
    ctrl, box = make(client, cooldown_s=60, probe_s=45)
    run(ctrl, box, 3, ratings_ms=150)
    assert client.weights["reviews"]["v1"] == 100
    ev = run(ctrl, box, 4, ratings_ms=150)
    assert events(ev, "PROBE_START")
    assert client.weights["reviews"]["v1"] == 100 - Config().probe_share
    ev = run(ctrl, box, 4)
    assert events(ev, "RELEASE")
    assert client.weights["reviews"] == {"v1": 34, "v2": 33, "v3": 33}


def test_probe_share_gives_enough_traffic_for_evidence():
    # reviews gets ~0.27 req/s in the demo, so probe_share% of it reaches ratings (via v2/v3)
    cfg = Config()
    assert cfg.probe_share / 100 * 0.27 >= cfg.min_evidence_rate


def test_probe_fails_back_to_reroute_if_fault_persists():
    client = FakeClient()
    ctrl, box = make(client, cooldown_s=60, probe_s=45)
    run(ctrl, box, 3, ratings_ms=150)
    ev = run(ctrl, box, 12, ratings_ms=150)
    assert events(ev, "PROBE_FAILED")
    assert not events(ev, "RELEASE")


def test_probe_without_traffic_is_not_trusted():
    client = FakeClient()
    ctrl, box = make(client, cooldown_s=60, probe_s=45)
    run(ctrl, box, 3, ratings_ms=150)
    run(ctrl, box, 4, ratings_ms=150)
    ev = run(ctrl, box, 4, rate=0.0)
    assert events(ev, "PROBE_FAILED") and not events(ev, "RELEASE")


class SlowGnn:
    name = "slow"
    def score(self, stats):
        import time; time.sleep(1.0); return {n: 0.0 for n in stats}


class BrokenGnn:
    name = "broken"
    def score(self, stats):
        raise RuntimeError("model file missing")


@pytest.mark.parametrize("primary", [SlowGnn(), BrokenGnn()])
def test_gnn_failure_falls_back_to_rules_and_still_acts(primary):
    client = FakeClient()
    scorer = ResilientScorer(primary, RuleScorer(100.0), timeout_s=0.2)
    ctrl, box = make(client, scorer=scorer)
    ev = run(ctrl, box, 5, ratings_ms=150)
    assert events(ev, "REROUTE")
    assert all(e["source"] == "fallback" for e in events(ev, "SCORED"))


def test_step_from_file_survives_garbage(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("not json\n")
    ctrl, box = make()
    assert step_from_file(ctrl, str(p)) is None
    assert ctrl.audit.events[-1]["event"] == "SNAPSHOT_REJECTED"
    good = json.dumps(snap_obj(box["now"]))
    p.write_text(good + "\n" + '{"timestamp": "2026')
    assert step_from_file(ctrl, str(p)) is not None


def test_step_from_file_skips_already_processed_snapshot(tmp_path):
    p = tmp_path / "s.jsonl"
    ctrl, box = make()
    p.write_text(json.dumps(snap_obj(box["now"], ratings_ms=150)) + "\n")
    assert step_from_file(ctrl, str(p)) is not None
    n_events, n_hist = len(ctrl.audit.events), len(ctrl.history)
    assert step_from_file(ctrl, str(p)) is None       # same timestamp: no event, no history entry
    assert (len(ctrl.audit.events), len(ctrl.history)) == (n_events, n_hist)
    box["now"] += timedelta(seconds=15)
    p.write_text(json.dumps(snap_obj(box["now"], ratings_ms=150)) + "\n")
    assert step_from_file(ctrl, str(p)) is not None   # newer timestamp is processed


def test_depends_on_is_transitive_over_any_subset():
    assert depends_on("reviews", "ratings")          # v2/v3 call ratings
    assert depends_on("productpage", "ratings")      # via reviews
    assert depends_on("productpage", "details")
    assert not depends_on("details", "ratings")
    assert not depends_on("ratings", "reviews")


def test_victim_after_ratings_reroute_is_suppressed():
    client = FakeClient()
    ctrl, box = make(client, cooldown_s=600)
    ev = run(ctrl, box, 3, ratings_ms=150)
    assert len(events(ev, "REROUTE")) == 1
    n_calls = len(client.calls)
    ev = run_victim(ctrl, box, 8)
    sup = events(ev, "SUPPRESSED_VICTIM")
    assert sup and sup[0]["node"] == "reviews" and sup[0]["culprit"] == "ratings"
    assert len(sup) == 2              # 8 cycles = 120 s -> logged once, re-logged after 60 s
    assert not events(ev, "ACTION_BLOCKED") and not events(ev, "REROUTE")
    assert len(client.calls) == n_calls


def test_reviews_victim_not_suppressed_without_active_reroute():
    ctrl, box = make(cooldown_s=600)
    ev = run_victim(ctrl, box, 8)
    assert not events(ev, "SUPPRESSED_VICTIM")
    assert events(ev, "ACTION_BLOCKED")


def test_non_dependent_node_still_blocked_while_ratings_rerouted():
    client = FakeClient()
    ctrl, box = make(client, cooldown_s=600)
    run(ctrl, box, 3, ratings_ms=150)
    n_calls = len(client.calls)
    ev = run(ctrl, box, 6, details_ms=150)
    blocked = events(ev, "ACTION_BLOCKED")
    assert blocked and blocked[0]["node"] == "details" and blocked[0]["reason"] == "no_healthy_alternative"
    assert not events(ev, "SUPPRESSED_VICTIM")
    assert len(client.calls) == n_calls


def test_ratings_culprit_still_rerouted_in_fresh_controller():
    client = FakeClient()
    ctrl, box = make(client)
    ev = run(ctrl, box, 3, ratings_ms=150)
    assert [e["culprit"] for e in events(ev, "REROUTE")] == ["ratings"]
    assert not events(ev, "SUPPRESSED_VICTIM")
