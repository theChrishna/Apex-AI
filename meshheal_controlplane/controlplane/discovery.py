"""Discover the service graph from Istio metrics in Prometheus (no kubectl, no hardcoded service names).

Same metric choices as telemetry.py (documented in CLAUDE.md): request and error rate from the destination
side, latency from the source side (Istio applies injected fault delay caller-side).
"""
import math
import re

_NS_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def check_namespace(ns):
    """Namespaces go into PromQL text, so accept only Kubernetes DNS labels."""
    if not isinstance(ns, str) or not _NS_RE.match(ns) or len(ns) > 63:
        raise ValueError(f"invalid namespace {ns!r}")
    return ns


def prom_query_fn(url, timeout=10):
    """Return query(promql) -> parsed JSON, for a Prometheus at `url`."""
    import requests

    def query(promql):
        r = requests.get(f"{url}/api/v1/query", params={"query": promql}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    return query


def _series(resp, keys):
    """[(label tuple, float value)] from an instant-vector response."""
    out = []
    for s in (resp.get("data", {}).get("result") or []):
        m = s.get("metric", {})
        try:
            v = float(s["value"][1])
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        out.append((tuple(m.get(k, "unknown") for k in keys), v))
    return out


# Envoy response flags that mean the request failed (https://www.envoyproxy.io/docs/envoy/latest/configuration/observability/access_log/usage)
FAILURE_FLAGS = ".*(FI|UH|UF|UO|NR|URX|UC|UT|LR|DC|UMSDR|NC).*"
SRC_DEST_LABEL = "destination_service_name"
# Endpoints that are not services: an unknown peer, and Istio's own catch-all clusters (traffic leaving the mesh, or
# dropped by policy). Grouping by service name exposes them, so they are dropped here.
NOT_SERVICES = {"unknown", "PassthroughCluster", "BlackHoleCluster", "InboundPassthroughClusterIpv4",
                "InboundPassthroughClusterIpv6", "InboundPassthroughCluster"}


def edge_queries(ns, window="1m"):
    ns = check_namespace(ns)
    by = "source_app, destination_app"
    src_by = f"source_app, {SRC_DEST_LABEL}"
    src = f'reporter="source", source_workload_namespace="{ns}"'
    return {
        "request_rate": f'sum(rate(istio_requests_total{{reporter="destination", source_workload_namespace="{ns}"}}[{window}])) by ({by})',
        "error_rate": f'sum(rate(istio_requests_total{{reporter="destination", source_workload_namespace="{ns}", response_code=~"5.*"}}[{window}])) by ({by})',
        # gRPC failures come back as HTTP 200 with grpc_response_status != 0 (Online Boutique is all gRPC); the label is
        # empty for plain HTTP, so this adds nothing on Bookinfo and does not double count 5xx.
        "grpc_error_rate": f'sum(rate(istio_requests_total{{reporter="destination", source_workload_namespace="{ns}", grpc_response_status=~"[1-9][0-9]*"}}[{window}])) by ({by})',
        "latency_p95": f'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket{{reporter="source", source_workload_namespace="{ns}"}}[{window}])) by (le, {by}))',
        # The same counts as the CALLER sees them (kept as separate fields so older snapshots keep their meaning).
        # Failures that never reach a pod - an Istio fault.abort, or a crashed pod with no healthy endpoint - are
        # recorded by the caller with destination_app="unknown", often with HTTP 200 and an empty gRPC status; only
        # Envoy's response_flags mark them (FI = fault injected, UH = no healthy upstream, ...). Verified on the live
        # cluster on 2026-11-25. So these are grouped by the destination SERVICE name, which is still known, and a
        # request counts as failed on a 5xx, a non-zero gRPC status OR an Envoy failure flag (DI = delay injected is
        # not a failure). `or` keeps each series once, so a request matching two conditions is not counted twice.
        "src_request_rate": f'sum(rate(istio_requests_total{{{src}}}[{window}])) by ({src_by})',
        "src_error_rate": (f'sum(rate(istio_requests_total{{{src}, response_code=~"5.*"}}[{window}])'
                           f' or rate(istio_requests_total{{{src}, grpc_response_status=~"[1-9][0-9]*"}}[{window}])'
                           f' or rate(istio_requests_total{{{src}, response_flags=~"{FAILURE_FLAGS}"}}[{window}]))'
                           f' by ({src_by})'),
    }


def discover_edges(query, ns, window="1m"):
    """Edges with request_rate / error_rate / latency_p95 for every service pair seen in namespace `ns`."""
    edges = {}
    for field, promql in edge_queries(ns, window).items():
        dest_label = SRC_DEST_LABEL if field.startswith("src_") else "destination_app"
        for (src, dst), v in _series(query(promql), ("source_app", dest_label)):
            if src in NOT_SERVICES or dst in NOT_SERVICES:
                continue
            e = edges.setdefault((src, dst), {"source": src, "destination": dst})
            if field in ("grpc_error_rate", "error_rate"):          # HTTP 5xx + gRPC failures (no double count)
                e["error_rate"] = e.get("error_rate", 0.0) + v
            else:
                e[field] = v
    out = []
    for e in edges.values():
        e.setdefault("request_rate", 0.0)
        e.setdefault("error_rate", 0.0)
        e.setdefault("latency_p95", 0.0)
        e.setdefault("src_request_rate", 0.0)
        e.setdefault("src_error_rate", 0.0)
        out.append(e)
    return sorted(out, key=lambda e: (e["source"], e["destination"]))


def valid_edge(e):
    return all(isinstance(e[k], (int, float)) and math.isfinite(e[k])
               for k in ("request_rate", "error_rate", "latency_p95"))


def nodes_from_edges(edges, ns, extra=()):
    ids = sorted({e["source"] for e in edges} | {e["destination"] for e in edges} | set(extra))
    return [{"id": n, "region": ns} for n in ids if n != "unknown"]


def discover_version_calls(query, ns, window="10m"):
    """Which version of a service calls which service, from metrics: {(service, version): {callee, ...}}.

    Absence of an edge in the window can mean "does not call it" OR "got no traffic", so callers must treat
    this as evidence for a human to check, not proof.
    """
    ns = check_namespace(ns)
    promql = (f'sum(rate(istio_requests_total{{reporter="destination", source_workload_namespace="{ns}"}}[{window}])) '
              f'by (source_app, source_version, destination_app)')
    calls = {}
    for (src, ver, dst), v in _series(query(promql), ("source_app", "source_version", "destination_app")):
        calls.setdefault((src, ver), set())
        if v > 0:
            calls[(src, ver)].add(dst)
    return calls


def discover_version_rates(query, ns, window="10m"):
    """Request rate each (service, version) receives: {(service, version): req/s}. Used to tell 'idle' from 'does not call'."""
    ns = check_namespace(ns)
    promql = (f'sum(rate(istio_requests_total{{reporter="destination", destination_workload_namespace="{ns}"}}[{window}])) '
              f'by (destination_app, destination_version)')
    return {(a, v): r for (a, v), r in _series(query(promql), ("destination_app", "destination_version"))}


def subset_queries(ns, window="1m"):
    """Per-version request rate, failed share and latency p95 of each service, as its pods / its callers see it."""
    ns = check_namespace(ns)
    dst = f'reporter="destination", destination_workload_namespace="{ns}"'
    by = "destination_app, destination_version"
    return {
        "rate": f'sum(rate(istio_requests_total{{{dst}}}[{window}])) by ({by})',
        "err": (f'sum(rate(istio_requests_total{{{dst}, response_code=~"5.*"}}[{window}])'
                f' or rate(istio_requests_total{{{dst}, grpc_response_status=~"[1-9][0-9]*"}}[{window}])) by ({by})'),
        "p95": (f'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket'
                f'{{reporter="source", destination_workload_namespace="{ns}"}}[{window}])) by (le, {by}))'),
    }


def discover_subsets(query, ns, window="1m"):
    """{service: {version: {"rate", "err", "p95"}}} for services with at least two known versions (else nothing)."""
    raw = {}
    for field, promql in subset_queries(ns, window).items():
        for (app, ver), v in _series(query(promql), ("destination_app", "destination_version")):
            if app in NOT_SERVICES or ver in ("unknown", ""):
                continue
            raw.setdefault(app, {}).setdefault(ver, {"rate": 0.0, "err": 0.0, "p95": None})[field] = v
    out = {}
    for app, vers in raw.items():
        if len(vers) < 2:
            continue
        for ver, d in vers.items():
            d["err"] = min(1.0, d["err"] / d["rate"]) if d["rate"] > 0 else 0.0     # failed share, not a rate
            if not (isinstance(d["p95"], (int, float)) and math.isfinite(d["p95"])):
                d["p95"] = None                                                       # no samples: null, not NaN
        out[app] = vers
    return out

