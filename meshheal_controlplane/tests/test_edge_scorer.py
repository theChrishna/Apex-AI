"""EdgeScorer: per-edge envelopes of latency and error fraction."""
import json

import pytest

from controlplane import learn_baseline as lb
from controlplane.scorer import EdgeScorer, as_result
from controlplane.snapshot import Snapshot, node_stats, parse_ts

T = "2026-11-25T10:00:00+00:00"


def edge(s, d, lat, rate=1.0, err=0.0, src_rate=None, src_err=None):
    e = {"source": s, "destination": d, "request_rate": rate, "error_rate": err, "latency_p95": lat}
    if src_rate is not None:
        e["src_request_rate"], e["src_error_rate"] = src_rate, src_err or 0.0
    return e


def snap(*edges):
    ids = sorted({x["source"] for x in edges} | {x["destination"] for x in edges})
    return Snapshot(ts=parse_ts(T), nodes=[{"id": i} for i in ids], edges=list(edges))


def score(scorer, sn):
    return scorer.score(node_stats(sn), sn)


def env(m, h):
    return {"median": m, "high": h}


# A Boutique-like shape: frontend calls catalog a lot and shipping rarely.
BASE = {
    "lg>frontend": {"lat": env(95, 180), "err": env(0, 0)},
    "frontend>catalog": {"lat": env(5, 9), "err": env(0, 0)},
    "frontend>shipping": {"lat": env(5, 9), "err": env(0, 0)},
}


def normal():
    return snap(edge("lg", "frontend", 100), edge("frontend", "catalog", 5, rate=4.0), edge("frontend", "shipping", 5, rate=0.15))


def test_normal_traffic_inside_the_envelopes_scores_zero():
    s = score(EdgeScorer(edges=BASE), normal())
    assert all(v == 0.0 for v in s.values())


def test_a_slow_rarely_called_edge_blames_the_callee_not_the_caller():
    """The per-service scorer averaged frontend's outgoing latency over all calls, so a slow rare edge did not cancel
    the frontend's rise and frontend was blamed. Per edge, frontend cancels against its worst outgoing edge."""
    sn = snap(edge("lg", "frontend", 380), edge("frontend", "catalog", 5, rate=4.0), edge("frontend", "shipping", 210, rate=0.15))
    s = score(EdgeScorer(edges=BASE), sn)
    assert max(s, key=s.get) == "shipping" and s["shipping"] > 0.85
    assert s["frontend"] < 0.85


def test_a_rare_edge_is_scored_down_to_one_request_a_minute():
    slow = lambda r: snap(edge("lg", "frontend", 100), edge("frontend", "shipping", 210, rate=r))   # noqa: E731
    assert score(EdgeScorer(edges=BASE), slow(0.04))["shipping"] > 0.85       # 0.04 req/s: the old service floor hid this
    assert score(EdgeScorer(edges=BASE), slow(0.01))["shipping"] == 0.0       # under 1 request a minute: no evidence


def test_injected_errors_are_seen_on_the_caller_side_counts_and_blame_the_callee():
    base = {"web>cart": {"lat": env(5, 9), "err": env(0, 0.01)}, "lg>web": {"lat": env(20, 40), "err": env(0, 0.01)}}
    # Istio abort: the destination never sees the failed requests; the caller-side counts do. web passes errors on.
    sn = snap(edge("lg", "web", 20, rate=2.0, src_rate=2.0, src_err=0.9), edge("web", "cart", 1, rate=1.0, src_rate=2.0, src_err=1.0))
    s = score(EdgeScorer(edges=base), sn)
    assert max(s, key=s.get) == "cart" and s["cart"] > 0.85
    assert s["web"] < 0.85                                                     # web only relays cart's failures


def test_error_fraction_prefers_caller_counts_and_handles_idle_edges():
    assert EdgeScorer.error_fraction(edge("a", "b", 5, rate=2.0, err=0.5)) == 0.25
    assert EdgeScorer.error_fraction(edge("a", "b", 5, rate=1.0, err=0.0, src_rate=2.0, src_err=1.0)) == 0.5
    assert EdgeScorer.error_fraction(edge("a", "b", 5, rate=0.0)) == 0.0


def test_an_unknown_edge_behaves_like_the_hand_set_rule():
    s = score(EdgeScorer(edges={}), snap(edge("a", "b", 150)))
    assert s["b"] > 0.85 and score(EdgeScorer(edges={}), snap(edge("a", "b", 50)))["b"] < 0.85


def test_needs_the_snapshot_and_rejects_a_bad_file(tmp_path):
    with pytest.raises(ValueError):
        EdgeScorer().score({})
    f = tmp_path / "b.yaml"
    f.write_text("services: {}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        EdgeScorer.from_file(str(f))


def test_learn_baseline_writes_edges_and_run_builds_the_edge_scorer(tmp_path):
    from controlplane.config import Config
    from controlplane.run import build_scorer
    rows = []
    for i in range(40):
        rows.append({"timestamp": f"2026-11-25T10:{i:02}:00+00:00", "nodes": [{"id": n} for n in ("lg", "frontend", "catalog")],
                     "edges": [edge("lg", "frontend", 95 + (i % 3)), edge("frontend", "catalog", 5 if i % 10 else 9.6, rate=4.0)]})
    src = tmp_path / "n.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tmp_path / "b.yaml"
    lb.main(["--snapshots", str(src), "--out", str(out)])
    es = EdgeScorer.from_file(str(out))
    assert set(es.edges) == {"lg>frontend", "frontend>catalog"} and es.edges["frontend>catalog"]["lat"]["high"] > 5
    sc = build_scorer("edge", Config(), baseline_path=str(out))
    sn = snap(edge("lg", "frontend", 96), edge("frontend", "catalog", 160, rate=4.0))
    res = as_result(sc, node_stats(sn), sn)
    assert res.source == "primary" and max(res.scores, key=res.scores.get) == "catalog"
