import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from topo import real, run_boutique_faults as rb  # noqa: E402

T0 = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
EP = [{"id": "1", "node": "cart", "delay_ms": 100, "start": T0, "end": T0 + timedelta(minutes=5)}]


@pytest.mark.parametrize("sec,phase", [(-1000, "normal"), (-121, "normal"), (-100, "near"), (0, "lag"), (89, "lag"),
                                       (90, "steady"), (300, "steady"), (301, "recovery"), (390, "recovery"),
                                       (391, "near"), (510, "near"), (600, "normal")])
def test_phases_follow_the_bookinfo_rules(sec, phase):
    assert real.classify(T0 + timedelta(seconds=sec), EP)[0] == phase


def test_label_records_keeps_only_steady_and_normal_and_labels_only_the_faulted_node(tmp_path):
    snaps, log = tmp_path / "s.jsonl", tmp_path / "f.jsonl"
    log.write_text(json.dumps({"episode": 1, "node": "cart", "delay_ms": 100, "start": T0.isoformat(),
                               "end": (T0 + timedelta(minutes=5)).isoformat(), "completed": True}) + "\n"
                   + json.dumps({"episode": 2, "node": "x", "delay_ms": 50, "start": T0.isoformat(),
                                 "end": T0.isoformat(), "completed": False}) + "\n", encoding="utf-8")
    nodes = [{"id": "cart"}, {"id": "db"}]
    rows = [{"timestamp": (T0 + timedelta(seconds=s)).isoformat(), "nodes": nodes, "edges": []} for s in (-1000, 10, 120, 350, 900)]
    snaps.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = real.label_records(str(snaps), str(log), "shop")
    assert [r["phase"] for r in out] == ["normal", "steady", "normal"]          # lag + recovery dropped; ep 2 not completed
    assert out[1]["labels"] == {"cart": 1, "db": 0} and out[0]["labels"] == {"cart": 0, "db": 0}
    assert out[1]["fault_node"] == "cart" and out[0]["fault_node"] is None and out[1]["topology"] == "shop"


def test_fault_virtualservice_is_a_100_percent_delay_on_the_service_and_named_as_ours():
    y = rb.vs_yaml("cartservice", 150)
    assert "name: cartservice-fault-inj" in y and "fixedDelay: 150ms" in y and "value: 100.0" in y
    assert "- cartservice" in y and rb.SUFFIX == "-fault-inj"


def test_schedule_covers_every_target_before_repeating_and_is_reproducible():
    t = ["a", "b", "c"]
    s = rb.schedule(t, 7, seed=3)
    assert len(s) == 7 and sorted(x for x, _, _ in s[:3]) == t and sorted(x for x, _, _ in s[3:6]) == t
    assert all(ft == "delay" and d in rb.DELAYS_MS for _, ft, d in s) and s == rb.schedule(t, 7, seed=3)


def test_without_yes_nothing_is_run(monkeypatch, capsys):
    monkeypatch.setattr(rb, "kubectl", lambda *a, **k: pytest.fail("kubectl must not be called without --yes"))
    rb.main(["--namespace", "boutique", "--episodes", "2"])
    out = capsys.readouterr().out
    assert "Nothing was changed" in out and "episode 1" in out


def test_virtualservice_is_deleted_even_when_the_episode_is_interrupted(monkeypatch):
    calls = []

    class R:
        returncode, stderr, stdout = 0, "", ""
    monkeypatch.setattr(rb, "kubectl", lambda *a, **k: calls.append(a) or R())
    monkeypatch.setattr(rb.time, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        rb.run_episode("boutique", "cartservice", 100, 300)
    assert calls[0][0] == "apply" and calls[-1][:3] == ("delete", "virtualservice", "cartservice-fault-inj")


def test_normal_only_records_are_all_negative_and_skip_the_warmup(tmp_path):
    f = tmp_path / "n.jsonl"
    f.write_text("\n".join(json.dumps({"timestamp": (T0 + timedelta(seconds=15 * i)).isoformat(),
                                       "nodes": [{"id": "a"}, {"id": "b"}], "edges": []}) for i in range(5)), encoding="utf-8")
    out = real.normal_records(str(f), "shop")
    assert len(out) == 3 and all(r["phase"] == "normal" and sum(r["labels"].values()) == 0 for r in out)
    assert out[0]["topology"] == "shop" and out[0]["fault_node"] is None


def test_eval_does_not_claim_a_verdict_without_a_held_out_synthetic_protocol():
    from topo import eval as ev
    ok, lines = ev.adoption({"boutique": {"gnn": {}, "mlp": {}}})
    assert ok is None and "not evaluated" in lines[0]


def test_boutique_graphs_keep_a_faulted_service_that_had_no_traffic_in_that_window(tmp_path):
    from topo import eval as ev
    e = lambda s, d: {"source": s, "destination": d, "request_rate": 1.0, "error_rate": 0.0, "latency_p95": 5.0}  # noqa: E731
    snaps, log = tmp_path / "s.jsonl", tmp_path / "f.jsonl"
    log.write_text(json.dumps({"episode": 1, "node": "pay", "delay_ms": 100, "start": T0.isoformat(),
                               "end": (T0 + timedelta(minutes=5)).isoformat(), "completed": True}) + "\n", encoding="utf-8")
    full = {"nodes": [{"id": "web"}, {"id": "pay"}], "edges": [e("web", "pay")]}
    idle = {"nodes": [{"id": "web"}, {"id": "cart"}], "edges": [e("web", "cart")]}         # pay has no edge, so it is not listed
    rows = [{"timestamp": (T0 + timedelta(seconds=s)).isoformat(), **(full if s == 100 else idle)} for s in (100, 200, -500)]
    snaps.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    graphs = ev.real_boutique_graphs(str(snaps), str(log))
    assert {tuple(g.node_ids) for g in graphs} == {("cart", "pay", "web")}                 # same full universe in every graph
    steady = [g for g in graphs if g.phase == "steady"]
    assert len(steady) == 2 and all(g.node_ids.index(g.fault_node) >= 0 and g.y.sum() == 1 for g in steady)
    assert ev.evaluate(steady, [g.rule.numpy() for g in steady])["rc1"] >= 0.0             # no crash looking up the faulted node


def test_abort_fault_is_grpc_unavailable_for_grpc_services_and_503_for_the_http_frontend():
    g, h = rb.abort_yaml("cartservice"), rb.abort_yaml("frontend")
    assert 'grpcStatus: "UNAVAILABLE"' in g and "value: 50.0" in g and "name: cartservice-fault-inj" in g
    assert "httpStatus: 503" in h and "grpcStatus" not in h


def test_mixed_schedule_covers_every_service_and_type_once_per_block():
    plan = rb.schedule(["a", "b"], 8, seed=4, types=("delay", "abort", "cpu", "crash"))
    assert sorted((s, t) for s, t, _ in plan) == sorted((s, t) for s in "ab" for t in rb.TYPES)
    assert all(p in rb.DELAYS_MS for _, t, p in plan if t == "delay")
    assert plan == rb.schedule(["a", "b"], 8, seed=4, types=("delay", "abort", "cpu", "crash"))


class _R:
    returncode, stderr = 0, ""

    def __init__(self, stdout=""):
        self.stdout = stdout


def test_cpu_fault_starves_the_container_and_always_restores_its_resources(monkeypatch):
    original = {"limits": {"cpu": "200m", "memory": "128Mi"}, "requests": {"cpu": "100m", "memory": "64Mi"}}
    dep = {"spec": {"template": {"spec": {"containers": [{"name": "server", "resources": original}]}}}}
    calls = []

    def fake(*args, stdin=None):
        calls.append(args)
        return _R(json.dumps(dep)) if args[:2] == ("get", "deployment") else _R()
    monkeypatch.setattr(rb, "kubectl", fake)
    with pytest.raises(KeyboardInterrupt):
        rb.run_episode("boutique", "cartservice", 0, 300, ftype="cpu", param="25m",
                       sleep=lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
    patches = [json.loads(c[-1]) for c in calls if c[0] == "patch"]
    starved, restored = patches[0][0]["value"], patches[-1][0]["value"]
    assert starved["limits"]["cpu"] == "25m" and starved["requests"]["cpu"] == "25m"
    assert starved["limits"]["memory"] == "128Mi"                                     # only CPU is touched
    assert restored == original                                                       # put back even after Ctrl+C


def test_crash_fault_deletes_the_pod_repeatedly_and_logs_the_type(monkeypatch):
    calls = []
    monkeypatch.setattr(rb, "kubectl", lambda *a, **k: calls.append(a) or _R())
    clock = {"t": 0.0}
    monkeypatch.setattr(rb.time, "monotonic", lambda: clock["t"])

    def sleep(s):
        clock["t"] += s
    row = rb.run_episode("boutique", "cartservice", 0, 150, ftype="crash", param=60, sleep=sleep)
    deletes = [c for c in calls if c[:2] == ("delete", "pod")]
    assert len(deletes) == 3 and all("app=cartservice" in c for c in deletes)      # at 0, 60 and 120 s
    assert row["type"] == "crash" and row["completed"] is True and row["delay_ms"] == 0


def test_episodes_from_a_mixed_log_keep_their_type(tmp_path):
    log = tmp_path / "f.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"episode": 1, "node": "a", "type": "abort", "delay_ms": 0, "param": 50.0, "start": T0.isoformat(),
         "end": (T0 + timedelta(minutes=5)).isoformat(), "completed": True},
        {"episode": 2, "node": "b", "delay_ms": 100, "start": T0.isoformat(), "end": T0.isoformat(), "completed": True}]),
        encoding="utf-8")
    eps = real.load_episodes(str(log))
    assert [(e["type"], e["param"]) for e in eps] == [("abort", 50.0), ("delay", 100)]


def test_plan_prints_every_fault_type(capsys):
    """Regression: the plan text was built for all types at once and crashed on the CPU parameter "25m"."""
    rb.main(["--namespace", "boutique", "--types", "delay", "abort", "cpu", "crash", "--per-type", "2", "--targets", "a", "b"])
    out = capsys.readouterr().out
    assert "CPU limit 25m" in out and "50% errors" in out and "pod killed every 60 s" in out and "Nothing was changed" in out
