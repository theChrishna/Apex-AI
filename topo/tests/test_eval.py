import os
import sys

import numpy as np
import pytest
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from topo import eval as ev  # noqa: E402
from topo import sim  # noqa: E402


class G:   # minimal graph stand-in for the metrics
    def __init__(self, y, phase, fault, ids):
        self.y = torch.tensor(y, dtype=torch.float)
        self.phase, self.fault_node, self.node_ids = phase, fault, ids


def test_rc1_counts_ties_as_random_tiebreak_not_as_a_win():
    ids = ["a", "b", "c", "d"]
    steady = G([0, 1, 0, 0], "steady", "b", ids)
    assert ev.evaluate([steady], [np.array([0.1, 0.9, 0.2, 0.0])])["rc1"] == 1.0
    assert ev.evaluate([steady], [np.array([0.1, 0.3, 0.9, 0.0])])["rc1"] == 0.0
    assert ev.evaluate([steady], [np.array([0.0, 0.0, 0.0, 0.0])])["rc1"] == pytest.approx(0.25)   # 4-way tie
    assert ev.evaluate([steady], [np.array([0.5, 0.5, 0.1, 0.0])])["rc1"] == pytest.approx(0.5)    # 2-way tie


def test_ap_and_fpr():
    ids = ["a", "b"]
    steady, normal = G([0, 1], "steady", "b", ids), G([0, 0], "normal", None, ids)
    m = ev.evaluate([steady, normal], [np.array([0.1, 0.9]), np.array([0.9, 0.1])])
    assert m["fpr"] == 1.0                                         # the normal snapshot's top score 0.9 > 0.85
    m = ev.evaluate([steady, normal], [np.array([0.1, 0.9]), np.array([0.2, 0.1])])
    assert m["fpr"] == 0.0 and m["ap"] == 1.0
    assert np.isnan(ev.evaluate([steady, normal], [np.array([0.1, 0.9]), np.array([0.2, 0.1])], risk_scale=False)["fpr"])


@pytest.fixture(scope="module")
def graphs():
    topos, recs = sim.make_corpus(3, per_family=2, size_range=(4, 14), n_normal=6, n_episodes=2, steady_per_episode=3)
    return ev.build_graphs(recs)


def test_family_folds_never_leak_a_topology_or_family(graphs):
    for proto, name, tr, te in ev.family_folds(graphs):
        assert {g.family for g in tr}.isdisjoint({g.family for g in te})
        assert {g.topology for g in tr}.isdisjoint({g.topology for g in te})
        assert len(tr) + len(te) == len(graphs)


def test_size_fold_separates_small_from_large(graphs):
    (proto, name, tr, te), = ev.size_fold(graphs, 6, 10)
    assert max(len(g.node_ids) for g in tr) <= 6 and min(len(g.node_ids) for g in te) >= 10
    assert ev.size_fold(graphs, 1, 99) == []


def test_graphs_carry_the_deployed_rule_score_and_eight_features(graphs):
    g = graphs[0]
    assert g.x.shape[1] == 8 and g.rule.shape[0] == len(g.node_ids)
    assert all(0.0 <= v <= 1.0 for gr in graphs for v in gr.rule.tolist())
    assert ev.view([g], 6)[0].x.shape[1] == 6 and g.x.shape[1] == 8        # view does not modify the original


def test_smoke_train_predict_and_run(graphs):
    for spec in ev.MODELS:
        model = ev.train(spec, graphs, seed=1, epochs=1)
        preds = ev.predict(spec, model, graphs)
        assert len(preds) == len(graphs) and all(len(p) == len(g.node_ids) for p, g in zip(preds, graphs))
        assert all(0.0 <= v <= 1.0 for p in preds for v in p)
    folds = ev.family_folds(graphs)[:1]
    rows = ev.run(folds, [1], 1, log=lambda *_: None)
    assert {r["model"] for r in rows} == set(ev.MODELS) | set(ev.BASELINES)
    summary = ev.summarise(rows)
    assert set(summary["family"]) >= {"gnn", "mlp", "rule", "p95"}


def test_training_is_reproducible_for_a_seed(graphs):
    a = ev.predict("gnn", ev.train("gnn", graphs, seed=5, epochs=2), graphs[:5])
    b = ev.predict("gnn", ev.train("gnn", graphs, seed=5, epochs=2), graphs[:5])
    assert all(np.allclose(x, y) for x, y in zip(a, b))


def test_adoption_rule_requires_beating_both_by_more_than_the_seed_spread():
    def s(g, m, r, std=0.01):
        mk = lambda v, sd: {"ap": (v, sd), "rc1": (v, sd), "fpr": (0.0, 0.0)}   # noqa: E731
        return {"family": {"gnn": mk(g, std), "mlp": mk(m, std), "rule": mk(r, 0.0)}}
    assert ev.adoption(s(0.9, 0.8, 0.7))[0] is True
    assert ev.adoption(s(0.9, 0.895, 0.7))[0] is False                         # inside the seed spread
    assert ev.adoption(s(0.9, 0.8, 0.95))[0] is False                          # loses to the rule
