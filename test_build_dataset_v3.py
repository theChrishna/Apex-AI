"""Checks that build_dataset_v3 differs from v2 only by the excluded snapshots. Run from the project root:
    python -m pytest -q test_build_dataset_v3.py
"""
import json

import pytest
import torch

import build_dataset_v2 as v2
import build_dataset_v3 as v3


@pytest.fixture(scope="module")
def recs2():
    return v2.load_all_records()


def test_record_to_graph_and_episodes_are_v2_objects():
    assert v3.record_to_graph is v2.record_to_graph
    assert v3.ALL_EPISODES is v2.ALL_EPISODES and v3.NODE_VOCAB is v2.NODE_VOCAB
    assert v3.classify_snapshot is v2.classify_snapshot


def test_records_outside_the_windows_equal_v2(recs2):
    ex = v3.EXCLUDED
    expected = [r for r in recs2 if r["timestamp"] not in ex]
    got = v3.load_all_records()
    assert got == expected                        # same dicts, same order
    assert len(recs2) - len(got) == len(ex)       # every excluded timestamp existed and was dropped


def test_graphs_outside_the_windows_equal_v2(recs2):
    ex = v3.EXCLUDED
    for r2, r3 in zip([r for r in recs2 if r["timestamp"] not in ex], v3.load_all_records()):
        g2, g3 = v2.record_to_graph(r2), v3.record_to_graph(r3)
        assert (g2 is None) == (g3 is None)
        if g2 is not None:
            assert torch.equal(g2.x, g3.x) and torch.equal(g2.y, g3.y) and torch.equal(g2.edge_index, g3.edge_index)


def test_holdout_is_v2_holdout_minus_excluded(recs2):
    h2 = v2.build_normal_holdout_ts(recs2)
    h3 = v3.build_normal_holdout_ts(v3.load_all_records())
    assert h3 == h2 - v3.EXCLUDED
    assert not (h3 & v3.EXCLUDED)
    assert len(h2) == 137 and len(h3) == 69


def test_only_normal_snapshots_are_excluded(recs2):
    ex = v3.EXCLUDED
    assert all(r["phase"] == "normal" for r in recs2 if r["timestamp"] in ex)


def test_counts_match_the_windows_file(recs2):
    c = json.load(open(v3.EXCLUDED_FILE))["counts"]
    h2 = v2.build_normal_holdout_ts(recs2)
    assert len(v3.EXCLUDED) == c["excluded_total"]
    assert sum(t in h2 for t in v3.EXCLUDED) == c["excluded_in_v2_holdout"]
    assert sum(t not in h2 for t in v3.EXCLUDED) == c["excluded_in_training_normals"]
