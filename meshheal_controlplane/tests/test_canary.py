"""Canary rollback: moving a culprit's OWN traffic to another of its versions, allowed only on per-version evidence."""
from datetime import timedelta

from controlplane.audit import AuditLog
from controlplane.cluster import FakeClient
from controlplane.config import Config
from controlplane.controller import Controller, subset_rollback_block
from controlplane.discovery import discover_subsets
from controlplane.playbook import Playbook
from controlplane.scorer import RuleScorer
from controlplane.snapshot import parse_snapshot
from tests.test_controller import T0, events

PB = Playbook.from_dict({
    "reroutes": [{"culprit": "cart", "virtual_service": "cart", "target_subset": "v1",
                  "normal_weights": {"v1": 50, "v2": 50}, "reason": "roll back to the stable version", "confirmed": True}],
    "depends": {"web": {"*": ["cart"]}, "cart": {"*": []}}})


def subs(v1_p95, v2_p95, v1_rate=1.0, v2_rate=1.0, v2_err=0.0):
    return {"cart": {"v1": {"rate": v1_rate, "err": 0.0, "p95": v1_p95}, "v2": {"rate": v2_rate, "err": v2_err, "p95": v2_p95}}}


def test_rollback_needs_the_target_clearly_better_than_another_version():
    cfg = Config()
    assert subset_rollback_block(subs(8, 400), "cart", "v1", cfg) is None              # v2 is the bad canary
    assert subset_rollback_block(subs(8, 9), "cart", "v1", cfg) == "target_subset_not_better"
    assert subset_rollback_block(subs(8, 40), "cart", "v1", cfg) == "target_subset_not_better"   # 5x but only 32 ms
    assert subset_rollback_block(subs(8, 9, v2_err=0.3), "cart", "v1", cfg) is None    # failing, not slow
    assert subset_rollback_block(subs(400, 8), "cart", "v1", cfg) == "target_subset_not_better"  # the target IS the bad one
    assert subset_rollback_block(subs(8, 400, v1_rate=0.0), "cart", "v1", cfg) == "target_subset_no_traffic"
    assert subset_rollback_block(None, "cart", "v1", cfg) == "no_subset_evidence"
    assert subset_rollback_block(subs(None, 400), "cart", "v1", cfg) == "target_subset_not_better"   # no latency data


def snap(ts, cart_ms, subsets=None):
    obj = {"timestamp": ts.isoformat(), "nodes": [{"id": "web"}, {"id": "cart"}],
           "edges": [{"source": "lg", "destination": "web", "request_rate": 2.0, "error_rate": 0.0, "latency_p95": 30 + cart_ms},
                     {"source": "web", "destination": "cart", "request_rate": 2.0, "error_rate": 0.0, "latency_p95": cart_ms}]}
    if subsets is not None:
        obj["subsets"] = subsets
    return parse_snapshot(obj)


def run(ctrl, box, n, cart_ms, subsets):
    out = []
    for _ in range(n):
        box["now"] += timedelta(seconds=15)
        out += ctrl.step(snap(box["now"], cart_ms, subsets))
    return out


def make():
    box = {"now": T0}
    client = FakeClient()
    cfg = Config(expected_nodes=())
    return Controller(cfg, RuleScorer(cfg.self_lat_full_ms), client, AuditLog(None), clock=lambda: box["now"], playbook=PB), box, client


def test_bad_canary_is_rolled_back_to_the_stable_version():
    ctrl, box, client = make()
    run(ctrl, box, 3, 8, subs(8, 8))
    ev = run(ctrl, box, 4, 250, subs(8, 480))
    rr = events(ev, "REROUTE")
    assert rr and rr[0]["culprit"] == "cart" and client.weights["cart"] == {"v1": 100, "v2": 0}


def test_without_per_version_evidence_the_culprit_is_not_rerouted():
    ctrl, box, client = make()
    run(ctrl, box, 3, 8, None)
    ev = run(ctrl, box, 4, 250, None)                                                  # an older collector: no subsets
    assert not events(ev, "REROUTE") and client.calls == []
    assert any(e.get("reason") == "no_subset_evidence" for e in events(ev, "ACTION_BLOCKED"))


def test_when_every_version_is_slow_rolling_back_would_not_help():
    ctrl, box, client = make()
    run(ctrl, box, 3, 8, subs(8, 8))
    ev = run(ctrl, box, 4, 250, subs(240, 250))
    assert not events(ev, "REROUTE") and client.calls == []
    assert any(e.get("reason") == "target_subset_not_better" for e in events(ev, "ACTION_BLOCKED"))


def vec(*rows):
    return {"data": {"result": [{"metric": m, "value": [0, str(v)]} for m, v in rows]}}


def test_discover_subsets_only_reports_services_with_two_known_versions():
    def q(promql):
        if "istio_request_duration" in promql:
            return vec(({"destination_app": "cart", "destination_version": "v1"}, 8.0),
                       ({"destination_app": "cart", "destination_version": "v2"}, 480.0))
        if "response_code" in promql:
            return vec(({"destination_app": "cart", "destination_version": "v2"}, 0.5))
        return vec(({"destination_app": "cart", "destination_version": "v1"}, 2.0),
                   ({"destination_app": "cart", "destination_version": "v2"}, 2.0),
                   ({"destination_app": "web", "destination_version": "unknown"}, 3.0),
                   ({"destination_app": "ads", "destination_version": "v1"}, 1.0))
    s = discover_subsets(q, "shop")
    assert set(s) == {"cart"}                                                          # web: unknown, ads: one version
    assert s["cart"]["v2"] == {"rate": 2.0, "err": 0.25, "p95": 480.0}                 # 0.5 failed of 2.0 req/s
