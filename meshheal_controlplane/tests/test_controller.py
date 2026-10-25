import json
from datetime import datetime, timedelta, timezone

import pytest

from controlplane.audit import AuditLog
from controlplane.cluster import FakeClient
from controlplane.config import Config
from controlplane.controller import Controller, step_from_file
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
    assert client.weights["reviews"]["v1"] == 90
    ev = run(ctrl, box, 4)
    assert events(ev, "RELEASE")
    assert client.weights["reviews"] == {"v1": 34, "v2": 33, "v3": 33}


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
