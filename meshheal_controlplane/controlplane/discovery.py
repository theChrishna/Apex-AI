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


def edge_queries(ns, window="1m"):
    ns = check_namespace(ns)
    by = "source_app, destination_app"
    return {
        "request_rate": f'sum(rate(istio_requests_total{{reporter="destination", source_workload_namespace="{ns}"}}[{window}])) by ({by})',
        "error_rate": f'sum(rate(istio_requests_total{{reporter="destination", source_workload_namespace="{ns}", response_code=~"5.*"}}[{window}])) by ({by})',
        # gRPC failures come back as HTTP 200 with grpc_response_status != 0 (Online Boutique is all gRPC); the label is
        # empty for plain HTTP, so this adds nothing on Bookinfo and does not double count 5xx.
        "grpc_error_rate": f'sum(rate(istio_requests_total{{reporter="destination", source_workload_namespace="{ns}", grpc_response_status=~"[1-9][0-9]*"}}[{window}])) by ({by})',
        "latency_p95": f'histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket{{reporter="source", source_workload_namespace="{ns}"}}[{window}])) by (le, {by}))',
    }


def discover_edges(query, ns, window="1m"):
    """Edges with request_rate / error_rate / latency_p95 for every service pair seen in namespace `ns`."""
    edges = {}
    for field, promql in edge_queries(ns, window).items():
        for (src, dst), v in _series(query(promql), ("source_app", "destination_app")):
            e = edges.setdefault((src, dst), {"source": src, "destination": dst})
            if field == "grpc_error_rate":          # same meaning as error_rate: add to the HTTP 5xx rate
                e["error_rate"] = e.get("error_rate", 0.0) + v
            elif field == "error_rate":
                e["error_rate"] = e.get("error_rate", 0.0) + v
            else:
                e[field] = v
    out = []
    for e in edges.values():
        e.setdefault("request_rate", 0.0)
        e.setdefault("error_rate", 0.0)
        e.setdefault("latency_p95", 0.0)
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
