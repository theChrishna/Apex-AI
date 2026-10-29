"""GnnScorer checks. Skipped when torch / torch_geometric or the trained weights are not available."""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

pytest.importorskip("torch")
pytest.importorskip("torch_geometric")

from controlplane.audit import AuditLog
from controlplane.cluster import FakeClient
from controlplane.config import Config
from controlplane.controller import Controller
from controlplane.scorer import ResilientScorer, RuleScorer, as_result
from controlplane.snapshot import BadSnapshot, node_stats, parse_snapshot

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST = os.path.join(REPO, "models", "gnn_final_manifest.json")
SNAPSHOTS = os.path.join(REPO, "snapshots.jsonl")
NODES = ("productpage", "details", "reviews", "ratings")

if not os.path.exists(MANIFEST):
    pytest.skip("models/gnn_final_manifest.json missing (run train_final.py)", allow_module_level=True)

from controlplane.gnn_adapter import GnnScorer   # noqa: E402


@pytest.fixture(scope="module")
def gnn():
    return GnnScorer(MANIFEST, REPO)


@pytest.fixture(scope="module")
def stored():
    """(raw record, parsed snapshot) for every stored snapshot the control plane accepts."""
    out = []
    with open(SNAPSHOTS) as f:
        for line in f:
            if not line.strip():
                continue
            raw = json.loads(line)
            try:
                snap = parse_snapshot(json.loads(line), NODES)
            except BadSnapshot:
                continue
            out.append((raw, snap))
    return out


@pytest.fixture(scope="module")
def offline():
    """What the offline training code gives: record_to_graph on the raw record, each seed's model,
    loaded independently of GnnScorer."""
    import torch
    sys.path.insert(0, REPO)
    from build_dataset_v2 import NODE_VOCAB, record_to_graph
    from model import RiskGNN
    with open(MANIFEST) as f:
        man = json.load(f)
    nets = []
    for seed in man["train_config"]["seeds"]:
        net = RiskGNN(man["model"]["num_node_features"], hidden_dim=man["model"]["hidden_dim"])
        net.load_state_dict(torch.load(os.path.join(REPO, "models", man["weights"][str(seed)]), weights_only=True))
        net.eval()
        nets.append(net)

    def scores(raw):
        g = record_to_graph({**raw, "labels": {}, "phase": None, "episode_id": None, "fault_node": None})
        with torch.no_grad():
            per_seed = [torch.sigmoid(net(g.x, g.edge_index)).tolist() for net in nets]
        return {n: sum(p[i] for p in per_seed) / len(per_seed) for i, n in enumerate(NODE_VOCAB)}
    return scores


def test_live_path_matches_offline_on_every_stored_snapshot(gnn, stored, offline):
    assert len(stored) > 700
    worst = 0.0
    for raw, s in stored:
        live, ref = gnn.score(node_stats(s), s), offline(raw)
        worst = max(worst, max(abs(live[n] - ref[n]) for n in NODES))
    assert worst < 1e-6


def test_features_follow_training_order_and_scaling(gnn, stored):
    import math
    raw, snap = stored[-1]
    x = gnn.graph(snap).x.tolist()
    assert gnn.node_vocab == ["details", "productpage", "ratings", "reviews"]
    rr = [e for e in raw["edges"] if e["source"] == "reviews" and e["destination"] == "ratings"][0]
    ratings = x[gnn.node_vocab.index("ratings")]
    assert ratings[0] == pytest.approx(math.log1p(rr["request_rate"]), abs=1e-6)
    assert ratings[1] == pytest.approx(rr["error_rate"], abs=1e-6)
    assert ratings[2] == pytest.approx(math.log1p(rr["latency_p95"]), abs=1e-6)


def test_score_is_mean_of_seeds_and_in_unit_interval(gnn, stored):
    _, snap = stored[len(stored) // 2]
    runs = gnn.per_seed(snap)
    assert len(runs) == len(gnn.manifest["train_config"]["seeds"]) == 5
    s = gnn.score(node_stats(snap), snap)
    assert set(s) == set(NODES)
    for n in NODES:
        assert s[n] == pytest.approx(sum(r[n] for r in runs) / len(runs), abs=1e-9)
        assert 0.0 <= s[n] <= 1.0


def test_missing_snapshot_or_node_falls_back_to_rule(gnn, stored):
    _, snap = stored[0]
    rs = ResilientScorer(gnn, RuleScorer(100.0), timeout_s=2.0)
    assert as_result(rs, node_stats(snap), snap).source == "primary"
    assert as_result(rs, node_stats(snap)).source == "fallback"            # no snapshot passed
    broken = type(snap)(ts=snap.ts, nodes=[n for n in snap.nodes if n["id"] != "ratings"], edges=snap.edges)
    assert as_result(rs, node_stats(snap), broken).source == "fallback"    # node missing


def test_bad_manifest_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        GnnScorer(str(tmp_path / "nope.json"), REPO)


def test_controller_runs_on_gnn(gnn, stored):
    _, snap = stored[-1]
    cfg = Config()
    ctrl = Controller(cfg, ResilientScorer(gnn, RuleScorer(cfg.self_lat_full_ms), 2.0), FakeClient(),
                      AuditLog(None), clock=lambda: snap.ts, dry_run=True)
    ev = ctrl.step(snap)
    assert ev[0]["event"] == "SCORED" and ev[0]["source"] == "primary"


@pytest.fixture(scope="module")
def killable(tmp_path_factory):
    """GNN built the way run.py builds it with --gnn-kill-file, plus the kill-file path (not created)."""
    from controlplane.run import build_scorer
    kill = tmp_path_factory.mktemp("kill") / "gnn.off"
    return build_scorer("gnn", Config(), MANIFEST, str(kill)), kill


def scored_event(scorer, snap):
    cfg = Config()
    ctrl = Controller(cfg, scorer, FakeClient(), AuditLog(None), clock=lambda: snap.ts, dry_run=True)
    return ctrl.step(snap)[0]


def test_kill_file_switches_gnn_to_rule_fallback(killable, stored):
    scorer, kill = killable
    _, snap = stored[-1]
    assert scored_event(scorer, snap)["source"] == "primary"
    kill.write_text("")
    try:
        ev = scored_event(scorer, snap)
        assert ev["source"] == "fallback"
        assert "GNN disabled by kill file" in ev["note"] and str(kill) in ev["note"]
        rule = RuleScorer(Config().self_lat_full_ms).score(node_stats(snap))
        assert ev["top"] == max(rule, key=rule.get)
    finally:
        kill.unlink(missing_ok=True)


def test_removing_kill_file_restores_gnn(killable, stored):
    scorer, kill = killable
    _, snap = stored[-1]
    kill.write_text("")
    assert scored_event(scorer, snap)["source"] == "fallback"
    kill.unlink()
    ev = scored_event(scorer, snap)
    assert ev["source"] == "primary" and "note" not in ev


def test_no_kill_file_option_means_no_change(gnn, stored):
    _, snap = stored[-1]
    assert gnn.kill_file is None
    assert scored_event(ResilientScorer(gnn, RuleScorer(100.0), 2.0), snap)["source"] == "primary"
