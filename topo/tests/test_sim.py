import math

import numpy as np
import pytest

from topo import sim
from topo.sim import bookinfo_topology, histogram_quantile, make_corpus, make_records, make_topology, snapshot


def test_histogram_quantile_reproduces_the_bucketed_values_seen_in_real_data():
    assert histogram_quantile(0.95, [60.0] * 20) == pytest.approx(97.5)        # all in (50,100]
    assert histogram_quantile(0.95, [150.0] * 20) == pytest.approx(242.5)      # all in (100,250]
    assert math.isnan(histogram_quantile(0.95, []))


def test_one_slow_request_among_seventeen_lifts_p95_to_the_next_bucket():
    fast = [4.0] * 16
    assert histogram_quantile(0.95, fast + [4.0]) < 5.0
    assert histogram_quantile(0.95, fast + [150.0]) > 100.0                    # the real-data "spike" mechanism


@pytest.mark.parametrize("family", sim.FAMILIES)
@pytest.mark.parametrize("n", [3, 4, 10, 25])
def test_every_topology_is_a_dag_reachable_from_the_root(family, n):
    topo = make_topology(family, n, np.random.default_rng(n))
    idx = {x: i for i, x in enumerate(topo.nodes)}
    assert all(idx[u] < idx[v] for u, v in topo.edges)                         # topological order = DAG
    reach, todo = {topo.root}, [topo.root]
    while todo:
        for c, _ in topo.children[todo.pop()]:
            if c not in reach:
                reach.add(c)
                todo.append(c)
    assert reach == set(topo.nodes)
    assert all(0.4 <= p <= 1.0 for p in topo.edges.values())


def test_same_seed_same_data_and_different_seed_different_data():
    a = make_records(make_topology("tree", 8, np.random.default_rng(1)), np.random.default_rng(2), n_normal=5, n_episodes=1)
    b = make_records(make_topology("tree", 8, np.random.default_rng(1)), np.random.default_rng(2), n_normal=5, n_episodes=1)
    c = make_records(make_topology("tree", 8, np.random.default_rng(1)), np.random.default_rng(3), n_normal=5, n_episodes=1)
    assert a == b and a != c


def test_a_delay_shows_on_the_faulted_node_and_its_waiting_callers_but_not_elsewhere():
    topo = bookinfo_topology()
    rng = np.random.default_rng(0)
    fault = ("ratings", 150)
    slow = {k: [] for k in topo.edges}
    for _ in range(40):
        for e in snapshot(topo, rng, fault=fault)["edges"]:
            slow[(e["source"], e["destination"])].append(e["latency_p95"])
    med = {k: float(np.median(v)) for k, v in slow.items()}
    assert med[("reviews", "ratings")] > 140                                   # the culprit edge
    assert med[("productpage", "reviews")] > 140                               # victim: reviews waits on ratings
    assert med[("productpage", "details")] < 50                                # unrelated branch unaffected


def test_error_rate_is_zero_and_idle_edges_are_absent():
    topo = make_topology("chain", 12, np.random.default_rng(5))
    topo.root_rate = 0.001                                                    # almost no traffic
    s = snapshot(topo, np.random.default_rng(0))
    assert all(e["error_rate"] == 0.0 for e in s["edges"])
    assert len(s["edges"]) < len(topo.edges)
    assert {n["id"] for n in s["nodes"]} == set(topo.nodes)                    # nodes are listed even when idle


def test_labels_follow_the_real_labelling_rule():
    topo = make_topology("layered", 9, np.random.default_rng(4))
    recs = make_records(topo, np.random.default_rng(1), n_normal=10, n_episodes=3, steady_per_episode=5)
    assert len(recs) == 10 + 3 * 5
    for r in recs:
        if r["phase"] == "normal":
            assert sum(r["labels"].values()) == 0
        else:
            assert sum(r["labels"].values()) == 1 and r["labels"][r["fault_node"]] == 1
            assert r["fault_node"] in topo.faultable() and r["fault_node"] != topo.root


def test_corpus_has_every_family_and_sizes_in_range():
    topos, recs = make_corpus(0, per_family=2, size_range=(4, 9), n_normal=3, n_episodes=1, steady_per_episode=2)
    assert {t.family for t in topos} == set(sim.FAMILIES) and len(topos) == 10
    assert all(4 <= len(t.nodes) <= 9 for t in topos)
    assert {r["family"] for r in recs} == set(sim.FAMILIES)
