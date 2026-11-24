"""BaselineScorer (learned normal envelope) and learn_baseline: the Phase 4 answer to the hand-set 100 ms rule that
false-alarms on most normal Online Boutique snapshots."""
import json

import pytest

from controlplane import learn_baseline as lb
from controlplane.scorer import BaselineScorer


def stats(svc, in_lat, out_lat, in_rate=1.0, out_rate=1.0):
    return {svc: dict(in_lat=in_lat, out_lat=out_lat, in_rate=in_rate, out_rate=out_rate, in_err=0.0)}


def env(median, high):
    return {"median": median, "high": high}


def test_without_a_baseline_it_behaves_like_the_hand_set_rule():
    s = BaselineScorer(full_ms=100.0, saturation="clamp")
    assert s.score(stats("ratings", 150, 0))["ratings"] == pytest.approx(1.0)
    assert s.score(stats("ratings", 90, 0))["ratings"] == pytest.approx(0.9)
    assert s.score(stats("ratings", 50, 0, in_rate=0.0))["ratings"] == 0.0        # rate floor


def test_anything_inside_the_normal_envelope_scores_zero():
    # Boutique frontend: normally ~95 ms, with normal jumps up to ~180 ms (one slow request lifts the bucketed p95).
    s = BaselineScorer(baselines={"frontend": {"in_lat": env(95.0, 180.0), "out_lat": env(6.0, 8.0)}})
    for ms in (90, 95, 103, 133, 180):
        assert s.score(stats("frontend", ms, 6))["frontend"] == 0.0               # the fixed rule would alarm on all of these


def test_a_bucket_jump_on_a_zero_spread_service_is_not_an_alarm():
    """Regression for the median+MAD version: checkoutservice sat on 48.75 ms (MAD 0) and every normal jump to the next
    bucket (90-97.5 ms) became a false alarm."""
    s = BaselineScorer(baselines={"checkoutservice": {"in_lat": env(48.75, 97.5), "out_lat": env(4.8, 6.0)}})
    for ms in (48.75, 90.0, 97.5):
        assert s.score(stats("checkoutservice", ms, 5))["checkoutservice"] == 0.0


def test_latency_well_above_the_envelope_lights_up():
    s = BaselineScorer(baselines={"ratings": {"in_lat": env(5.0, 9.0), "out_lat": env(0.0, 0.0)}})
    assert s.score(stats("ratings", 150, 0))["ratings"] == pytest.approx(1.0)      # (150-9)/10 >> 1
    assert s.score(stats("ratings", 5, 0))["ratings"] == 0.0


def test_the_floor_keeps_a_never_moving_service_from_being_infinitely_sensitive():
    s = BaselineScorer(baselines={"adservice": {"in_lat": env(4.8, 4.8)}}, floor_ms=10.0)
    assert s.score(stats("adservice", 9.6, 0))["adservice"] < 0.85                 # one bucket up: raw (9.6-4.8)/10 = 0.48
    assert s.score(stats("adservice", 97.5, 0))["adservice"] == pytest.approx(1.0)  # a 50+ ms fault


def test_a_victim_still_cancels_out():
    base = {"reviews": {"in_lat": env(25.0, 40.0), "out_lat": env(5.0, 10.0)}}
    s = BaselineScorer(baselines=base)
    # reviews slow only because ratings is slow: in_lat and out_lat rise by the same ~150 ms
    assert s.score(stats("reviews", 190, 160))["reviews"] < 0.2
    # reviews itself slow: in_lat rises, out_lat does not
    assert s.score(stats("reviews", 190, 6))["reviews"] == pytest.approx(1.0)


def test_the_rate_floor_mutes_an_idle_service():
    s = BaselineScorer(baselines={"x": {"in_lat": env(5.0, 9.0)}}, min_rate=0.05)
    assert s.score(stats("x", 150, 0, in_rate=0.04))["x"] == 0.0
    assert s.score(stats("x", 150, 0, in_rate=0.10))["x"] > 0.0


def test_coverage_is_recorded_so_the_caller_can_tell_what_was_learned():
    s = BaselineScorer(baselines={"a": {"in_lat": env(5.0, 9.0)}})
    s.score({"a": dict(in_lat=5, out_lat=0, in_rate=1, out_rate=1, in_err=0.0),
             "b": dict(in_lat=5, out_lat=0, in_rate=1, out_rate=1, in_err=0.0)})
    assert s.coverage == {"a": True, "b": False}


def test_quantile_and_envelope():
    assert lb.quantile([1, 2, 3, 4, 5], 0.5) == 3.0
    assert lb.quantile([1, 2, 3, 4, 5], 1.0) == 5.0
    assert lb.quantile([1, 2, 3, 4, 5], 0.75) == 4.0
    assert lb.quantile([7], 0.99) == 7.0
    assert lb.envelope([4, 5, 5, 6, 100], 0.5) == {"median": 5.0, "high": 5.0}


def test_learn_baseline_cli_writes_a_file_the_scorer_loads(tmp_path):
    def snap(i, lat):
        e = lambda s, d, l, rate=5.0: {"source": s, "destination": d, "request_rate": rate,          # noqa: E731
                                       "error_rate": 0.0, "latency_p95": l}
        return {"timestamp": f"2026-11-24T10:{i:02}:00+00:00", "nodes": [{"id": n} for n in ("productpage", "reviews", "ratings")],
                "edges": [e("productpage", "reviews", 25), e("reviews", "ratings", lat)]}
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(snap(i, 5 if i % 10 else 9.6)) for i in range(40)), encoding="utf-8")
    out = tmp_path / "base.yaml"
    lb.main(["--snapshots", str(path), "--out", str(out), "--min-samples", "20", "--floor-ms", "10"])
    s = BaselineScorer.from_file(str(out))
    assert s.floor_ms == 10.0
    b = s.baselines["ratings"]["in_lat"]
    assert b["median"] == pytest.approx(5.0) and b["high"] > 5.0                    # the occasional 9.6 ms bucket jump is learned
    assert s.score(stats("ratings", 9.6, 0))["ratings"] == 0.0                       # so it is not an alarm
    assert s.score(stats("ratings", 150, 0))["ratings"] == pytest.approx(1.0)


def test_from_file_rejects_a_file_without_services(tmp_path):
    f = tmp_path / "b.yaml"
    f.write_text("k: 4\n", encoding="utf-8")
    with pytest.raises(ValueError):
        BaselineScorer.from_file(str(f))


def test_learn_baseline_cli_refuses_to_overwrite_and_protected_names(tmp_path):
    src = tmp_path / "s.jsonl"
    src.write_text(json.dumps({"timestamp": "2026-11-24T10:00:00+00:00", "nodes": [], "edges": []}) + "\n", encoding="utf-8")
    out = tmp_path / "base.yaml"
    out.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        lb.main(["--snapshots", str(src), "--out", str(out)])
    with pytest.raises(SystemExit):
        lb.main(["--snapshots", str(src), "--out", str(tmp_path / "snapshots.jsonl")])


def test_learn_baseline_cli_reports_and_exits_when_nothing_was_collectable(tmp_path, capsys):
    src = tmp_path / "s.jsonl"
    src.write_text(json.dumps({"timestamp": "2026-11-24T10:00:00+00:00", "nodes": [], "edges": []}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        lb.main(["--snapshots", str(src), "--out", str(tmp_path / "base.yaml")])
    assert "no baselines learned" in capsys.readouterr().err


def test_soft_saturation_crosses_the_act_threshold_exactly_where_clamp_does():
    """The decision (risk above 0.85) must not change between clamp and soft: only the ranking may."""
    base = {"x": {"in_lat": env(5.0, 15.0)}}
    soft, clamp = BaselineScorer(baselines=base), BaselineScorer(baselines=base, saturation="clamp")
    for ms in [15 + 0.1 * i for i in range(400)]:                                 # raw from 0 to ~4
        a, b = soft.score(stats("x", ms, 0))["x"], clamp.score(stats("x", ms, 0))["x"]
        assert (a > 0.85) == (b > 0.85), ms
    assert soft.score(stats("x", 23.5, 0))["x"] == pytest.approx(0.85)            # raw 0.85 -> 0.85 in both
    assert clamp.score(stats("x", 23.5, 0))["x"] == pytest.approx(0.85)


def test_soft_saturation_keeps_the_ranking_where_clamp_ties():
    """Regression: on Online Boutique a 50 ms productcatalog fault put productcatalog AND its caller frontend at the
    1.0 cap; the tie broke by name and frontend was blamed 14 of 14 times."""
    base = {"a": {"in_lat": env(5.0, 10.0)}, "b": {"in_lat": env(5.0, 10.0)}}
    st = {"a": dict(in_lat=40, out_lat=0, in_rate=1, out_rate=1, in_err=0.0),
          "b": dict(in_lat=80, out_lat=0, in_rate=1, out_rate=1, in_err=0.0)}
    clamp = BaselineScorer(baselines=base, saturation="clamp").score(st)
    soft = BaselineScorer(baselines=base).score(st)
    assert clamp["a"] == clamp["b"] == 1.0                                         # the tie
    assert soft["b"] > soft["a"] > 0.85                                            # ranking kept, both still above threshold
    assert all(0.0 <= v < 1.0 for v in soft.values())


def test_bad_saturation_is_rejected():
    with pytest.raises(ValueError):
        BaselineScorer(saturation="nope")



def test_run_builds_the_baseline_scorer_with_the_rule_as_fallback(tmp_path):
    from controlplane.config import Config
    from controlplane.run import build_scorer
    from controlplane.scorer import ResilientScorer, RuleScorer, as_result
    f = tmp_path / "b.yaml"
    f.write_text("floor_ms: 10\nmin_rate: 0.05\nservices:\n  ratings:\n    in_lat: {median: 5, high: 9}\n", encoding="utf-8")
    sc = build_scorer("baseline", Config(), baseline_path=str(f))
    assert isinstance(sc, ResilientScorer) and isinstance(sc.primary, BaselineScorer) and isinstance(sc.fallback, RuleScorer)
    res = as_result(sc, stats("ratings", 150, 0))
    assert res.source == "primary" and res.scores["ratings"] > 0.85
    with pytest.raises(SystemExit):
        build_scorer("baseline", Config())                                         # a learned scorer needs its file


def test_config_file_can_name_the_baseline(tmp_path):
    from controlplane.config import Config
    f = tmp_path / "m.yaml"
    f.write_text("baseline_path: /etc/meshheal/baseline.yaml\n", encoding="utf-8")
    assert Config.from_file(str(f)).baseline_path == "/etc/meshheal/baseline.yaml"
