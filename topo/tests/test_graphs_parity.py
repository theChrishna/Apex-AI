"""The generic builder must reproduce build_dataset_v2.record_to_graph exactly on the real Bookinfo data."""
import os
import sys

import pytest
import torch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)                                   # build_dataset_v2 reads snapshots.jsonl by relative path

from build_dataset_v2 import NODE_VOCAB, load_all_records, record_to_graph as v2_graph  # noqa: E402
from topo.graphs import record_to_graph  # noqa: E402


@pytest.fixture(scope="module")
def records():
    if not os.path.exists(os.path.join(ROOT, "snapshots.jsonl")):
        pytest.skip("snapshots.jsonl not available")
    return load_all_records()


def test_identical_graphs_on_every_real_snapshot(records):
    n = 0
    for r in records:
        old = v2_graph(r)
        if old is None:
            continue
        new = record_to_graph(r, node_order=NODE_VOCAB)
        assert torch.equal(old.x, new.x), r["timestamp"]
        assert torch.equal(old.edge_index, new.edge_index)
        assert torch.equal(old.y, new.y)
        n += 1
    assert n > 700                                # 808 snapshots in the uploaded data


def test_node_order_is_sorted_by_name_when_not_given(records):
    full = next(r for r in records if v2_graph(r) is not None)       # a snapshot with all four services
    g = record_to_graph(full)
    assert g.node_ids == sorted(g.node_ids) == ["details", "productpage", "ratings", "reviews"]


def test_works_for_other_service_names_and_sizes():
    rec = {"nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}, {"id": "e"}],
           "edges": [{"source": "a", "destination": "b", "request_rate": 1.0, "error_rate": 0.0, "latency_p95": 10.0},
                     {"source": "a", "destination": "c", "request_rate": 1.0, "error_rate": 0.1, "latency_p95": 20.0},
                     {"source": "c", "destination": "d", "request_rate": 0.5, "error_rate": 0.0, "latency_p95": 5.0}],
           "labels": {"c": 1}}
    g = record_to_graph(rec)
    assert g.x.shape == (5, 6) and g.edge_index.shape == (2, 3)
    assert g.y.tolist() == [0, 0, 1, 0, 0]                      # e has no edges: all-zero features
    assert g.x[4].tolist() == [0.0] * 6
    gd = record_to_graph(rec, degree=True)
    assert gd.x.shape == (5, 8) and gd.raw.shape == (5, 6)


def test_unknown_source_is_not_a_node():
    rec = {"nodes": [], "edges": [{"source": "unknown", "destination": "a", "request_rate": 1.0,
                                   "error_rate": 0.0, "latency_p95": 3.0}]}
    assert record_to_graph(rec).node_ids == ["a"]


def test_normal_and_fault_graphs_can_share_a_batch():
    """Regression: metadata set to None was dropped by PyG, so mixed batches crashed in collation."""
    from torch_geometric.loader import DataLoader
    e = [{"source": "a", "destination": "b", "request_rate": 1.0, "error_rate": 0.0, "latency_p95": 5.0}]
    normal = record_to_graph({"nodes": [], "edges": e, "phase": "normal", "labels": {}})
    fault = record_to_graph({"nodes": [], "edges": e, "phase": "steady", "fault_node": "b", "labels": {"b": 1}})
    assert normal.fault_node == "" and fault.fault_node == "b"
    batch = next(iter(DataLoader([normal, fault], batch_size=2)))
    assert batch.num_graphs == 2
