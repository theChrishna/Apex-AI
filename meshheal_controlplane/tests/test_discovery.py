import json
import math

import pytest

from controlplane import collect
from controlplane.discovery import (check_namespace, discover_edges, discover_version_calls,
                                    discover_version_rates, edge_queries, nodes_from_edges, valid_edge)


def vec(*rows):
    """Series as Prometheus returns them. Every series also carries destination_service_name (= destination_app here),
    the label the caller-side queries group by."""
    def lab(m):
        m = dict(m)
        if "destination_app" in m:
            m.setdefault("destination_service_name", m["destination_app"])
        return m
    return {"status": "success", "data": {"resultType": "vector",
                                          "result": [{"metric": lab(m), "value": [0, str(v)]} for m, v in rows]}}


def fake_prom(ns="shop", src_abort=False):
    """A Prometheus answering by query text. Mesh: web -> cart -> db, web -> ads (ads never answers latency).
    src_abort: the caller-side counts show an injected abort on web -> cart that the destination never saw."""
    def q(promql):
        assert f'"{ns}"' in promql
        if src_abort and 'reporter="source"' in promql and "istio_requests_total" in promql:
            # as recorded live: an aborted request has destination_app="unknown" and only the service name is known
            if "response_flags" in promql:
                return vec(({"source_app": "web", "destination_app": "unknown", "destination_service_name": "cart"}, 2.0))
            return vec(({"source_app": "web", "destination_app": "unknown", "destination_service_name": "cart"}, 4.0))
        if "istio_request_duration" in promql:
            return vec(({"source_app": "web", "destination_app": "cart"}, 12.5),
                       ({"source_app": "cart", "destination_app": "db"}, 5), ({"source_app": "web", "destination_app": "ads"}, "NaN"))
        if "grpc_response_status" in promql:
            return vec(({"source_app": "web", "destination_app": "cart"}, 0.02), ({"source_app": "cart", "destination_app": "db"}, 0.5))
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
                                      "error_rate": pytest.approx(0.03), "latency_p95": 12.5,
                                      "src_request_rate": 4.0, "src_error_rate": 0.02}   # one combined caller-side query
    assert edges[("web", "cart")]["error_rate"] == pytest.approx(0.01 + 0.02)  # HTTP 5xx + gRPC failures
    assert edges[("cart", "db")]["error_rate"] == 0.5                          # gRPC-only failures are counted
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
    assert "skipped_edges" not in obj and set(obj) == {"timestamp", "nodes", "edges", "subsets"}
    assert obj["subsets"]["cart"]["v2"]["p95"] is None                    # a version without samples: null, not NaN
    parsed = parse_snapshot(obj, expected_nodes=("web", "cart", "db"))
    assert len(parsed.edges) == 2


def test_collect_returns_none_when_nothing_is_valid():
    assert collect.build_snapshot(lambda p: vec(), "shop") is None


def test_collect_refuses_to_append_to_the_uploaded_data_file():
    with pytest.raises(SystemExit):
        collect.main(["--namespace", "shop", "--out", "somewhere/snapshots.jsonl", "--once"])


def test_errors_injected_at_the_caller_are_only_visible_in_the_source_side_fields():
    """Istio fault.abort answers in the caller's sidecar: the destination never sees those requests, so error_rate (the
    destination's count) stays 0 while src_error_rate shows them."""
    edges = {(e["source"], e["destination"]): e for e in discover_edges(fake_prom(src_abort=True), "shop")}
    wc = edges[("web", "cart")]
    assert wc["src_error_rate"] == 2.0 and wc["src_request_rate"] == 4.0
    assert wc["error_rate"] == pytest.approx(0.03)                             # destination view unchanged
    assert edges[("cart", "db")]["src_error_rate"] == 0.0                      # defaults when there is no series


def test_caller_side_failure_query_counts_flags_and_groups_by_service_name():
    from controlplane.discovery import edge_queries
    q = edge_queries("shop")
    assert "by (source_app, destination_service_name)" in q["src_error_rate"]
    assert 'response_flags=~".*(FI|UH' in q["src_error_rate"] and " or " in q["src_error_rate"]
    assert "DI" not in q["src_error_rate"].split("response_flags")[1]                # a delay is not a failure
    assert "destination_app" in q["request_rate"]                                      # the old fields are unchanged


def test_unknown_endpoints_never_become_services():
    edges = discover_edges(lambda p: vec(({"source_app": "web", "destination_app": "unknown"}, 1.0)), "shop")
    assert edges == []


def test_istio_catch_all_clusters_are_not_services():
    rows = [({"source_app": "frontend", "destination_app": "unknown", "destination_service_name": n}, 1.0)
            for n in ("PassthroughCluster", "BlackHoleCluster")]
    assert discover_edges(lambda p: vec(*rows), "shop") == []

