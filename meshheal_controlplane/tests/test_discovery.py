import json
import math

import pytest

from controlplane import collect
from controlplane.discovery import (check_namespace, discover_edges, discover_version_calls,
                                    discover_version_rates, edge_queries, nodes_from_edges, valid_edge)


def vec(*rows):
    return {"status": "success", "data": {"resultType": "vector",
                                          "result": [{"metric": m, "value": [0, str(v)]} for m, v in rows]}}


def fake_prom(ns="shop"):
    """A Prometheus answering by query text. Mesh: web -> cart -> db, web -> ads (ads never answers latency)."""
    def q(promql):
        assert f'"{ns}"' in promql
        if "istio_request_duration" in promql:
            return vec(({"source_app": "web", "destination_app": "cart"}, 12.5),
                       ({"source_app": "cart", "destination_app": "db"}, 5), ({"source_app": "web", "destination_app": "ads"}, "NaN"))
        if "response_code" in promql:
            return vec(({"source_app": "web", "destination_app": "cart"}, 0.01))
        if "source_version" in promql:
            return vec(({"source_app": "web", "source_version": "v1", "destination_app": "cart"}, 1.0),
                       ({"source_app": "cart", "source_version": "v1", "destination_app": "db"}, 1.0),
                       ({"source_app": "cart", "source_version": "v2", "destination_app": "db"}, 0.0),
                       ({"source_app": "cart", "source_version": "v2", "destination_app": "cache"}, 1.0))
        if "destination_version" in promql:
            return vec(({"destination_app": "cart", "destination_version": "v1"}, 2.0),
                       ({"destination_app": "cart", "destination_version": "v2"}, 0.0))
        return vec(({"source_app": "web", "destination_app": "cart"}, 4.0), ({"source_app": "cart", "destination_app": "db"}, 4.0),
                   ({"source_app": "web", "destination_app": "ads"}, 1.0))
    return q


def test_edges_are_merged_across_the_three_metrics_with_defaults_for_missing_ones():
    edges = {(e["source"], e["destination"]): e for e in discover_edges(fake_prom(), "shop")}
    assert set(edges) == {("web", "cart"), ("cart", "db"), ("web", "ads")}
    assert edges[("web", "cart")] == {"source": "web", "destination": "cart", "request_rate": 4.0,
                                      "error_rate": 0.01, "latency_p95": 12.5}
    assert edges[("cart", "db")]["error_rate"] == 0.0                         # no 5xx series -> 0, not missing
    assert math.isnan(edges[("web", "ads")]["latency_p95"])                    # idle edge: NaN kept, filtered later


def test_invalid_edges_are_filtered_and_nodes_come_from_the_graph():
    edges = discover_edges(fake_prom(), "shop")
    ok = [e for e in edges if valid_edge(e)]
    assert len(ok) == 2
    assert nodes_from_edges(ok, "shop") == [{"id": "cart", "region": "shop"}, {"id": "db", "region": "shop"}, {"id": "web", "region": "shop"}]
    assert nodes_from_edges([{"source": "unknown", "destination": "a"}], "n") == [{"id": "a", "region": "n"}]


def test_queries_keep_the_documented_reporters():
    q = edge_queries("shop")
    assert 'reporter="destination"' in q["request_rate"] and 'reporter="destination"' in q["error_rate"]
    assert 'reporter="source"' in q["latency_p95"]                              # fault delay is applied caller-side


@pytest.mark.parametrize("bad", ['x"}) or vector(1) #', "Shop", "a b", "", None, "-a", "a" * 64])
def test_namespace_is_validated_before_it_reaches_promql(bad):
    with pytest.raises(ValueError):
        check_namespace(bad)
    with pytest.raises(ValueError):
        edge_queries(bad)


def test_version_calls_and_rates():
    calls = discover_version_calls(fake_prom(), "shop")
    assert calls[("web", "v1")] == {"cart"} and calls[("cart", "v1")] == {"db"}
    assert calls[("cart", "v2")] == {"cache"}                                   # v2 has a zero-rate edge to db: not a call
    assert discover_version_rates(fake_prom(), "shop") == {("cart", "v1"): 2.0, ("cart", "v2"): 0.0}


def test_collect_builds_the_same_snapshot_format_the_controller_reads(tmp_path):
    from controlplane.snapshot import parse_snapshot
    snap = collect.build_snapshot(fake_prom(), "shop")
    assert snap["skipped_edges"] == 1
    out = tmp_path / "live.jsonl"
    collect.append_snapshot(str(out), snap)
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert "skipped_edges" not in obj and set(obj) == {"timestamp", "nodes", "edges"}
    parsed = parse_snapshot(obj, expected_nodes=("web", "cart", "db"))
    assert len(parsed.edges) == 2


def test_collect_returns_none_when_nothing_is_valid():
    assert collect.build_snapshot(lambda p: vec(), "shop") is None


def test_collect_refuses_to_append_to_the_uploaded_data_file():
    with pytest.raises(SystemExit):
        collect.main(["--namespace", "shop", "--out", "somewhere/snapshots.jsonl", "--once"])
