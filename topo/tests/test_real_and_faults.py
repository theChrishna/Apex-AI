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
    assert len(s) == 7 and sorted(x for x, _ in s[:3]) == t and sorted(x for x, _ in s[3:6]) == t
    assert all(d in rb.DELAYS_MS for _, d in s) and s == rb.schedule(t, 7, seed=3)


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
