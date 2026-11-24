"""Mesh simulator: random service graphs with Istio-style bucketed p95 latency and caller-side delay faults.

It exists because the real data is one topology (Bookinfo). Results on simulated meshes measure how a model copes
with THIS simulator's family of meshes, not with real ones; always label them "synthetic".

What is modelled (and checked against the real Bookinfo data in topo/calibrate.py):
  * request rates: root rate x product of call probabilities along the path, counted per 60 s window (Poisson);
  * per-request latency: a service time (log-normal) + occasional slow requests + the calls the request makes;
  * latency is what the CALLER sees (reporter="source"), so an injected delay on service F shows up on every edge
    into F and on every upstream edge that waits for F (the victims), as in the real data;
  * p95 comes from a cumulative histogram with Istio's default buckets and Prometheus' histogram_quantile
    interpolation. With ~15 requests per window a single slow request moves p95 to the next bucket, which is why
    real Bookinfo normals show spikes to 97.5 / 242.5 ms;
  * errors: delay faults do not cause errors in the real episodes, so error_rate is 0.
What is NOT modelled: error faults, CPU/memory faults, retries/timeouts, load-dependent latency, time correlation.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

ISTIO_BUCKETS_MS = [0.5, 1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 300000,
                    600000, 1800000, 3600000]
FAMILIES = ["chain", "tree", "layered", "random", "star"]
FAULT_DELAYS_MS = [50, 100, 150, 200]
WINDOW_S = 60.0


def histogram_quantile(q, samples_ms, buckets=ISTIO_BUCKETS_MS):
    """Prometheus histogram_quantile over cumulative bucket counts of `samples_ms`. NaN when there are no samples."""
    n = len(samples_ms)
    if n == 0:
        return float("nan")
    counts = np.histogram(samples_ms, bins=[0.0] + list(buckets) + [math.inf])[0]
    rank = q * n
    cum = 0
    lower = 0.0
    for upper, c in zip(buckets, counts[:-1]):
        if cum + c >= rank and c > 0:
            return lower + (upper - lower) * (rank - cum) / c
        cum += c
        lower = upper
    return float(buckets[-1])                      # beyond the last finite bucket


@dataclass
class Topology:
    name: str
    family: str
    nodes: list
    edges: dict                                    # (src, dst) -> call probability
    root_rate: float
    mu_ms: dict                                    # node -> mean service time (ms)
    sigma: dict                                    # node -> log-normal sigma
    spike_p: dict                                  # node -> probability a request is slow (+50..250 ms)
    children: dict = field(default_factory=dict)

    def __post_init__(self):
        self.children = {n: [] for n in self.nodes}
        for (u, v), p in self.edges.items():
            self.children[u].append((v, p))

    @property
    def root(self):
        return self.nodes[0]

    def in_rates(self):
        """Request rate each node receives per second (root receives root_rate from outside the mesh)."""
        rate = {n: 0.0 for n in self.nodes}
        rate[self.root] = self.root_rate
        for u in self.nodes:                       # nodes are stored in topological order
            for v, p in self.children[u]:
                rate[v] += rate[u] * p
        return rate

    def faultable(self):
        """Nodes whose slowdown a caller can observe (they receive calls)."""
        return [n for n, r in self.in_rates().items() if n != self.root and r > 0]


# ----------------------------------------------------------------------------------------- topology generators
def _node_params(n, rng):
    names_mu = np.exp(rng.normal(math.log(5.0), 0.6, n))          # mean service time ~5 ms, wide spread
    return (names_mu, rng.uniform(0.25, 0.45, n), np.exp(rng.uniform(math.log(0.002), math.log(0.02), n)))


def _finish(name, family, n, pairs, rng):
    nodes = [f"{family}{name}-s{i}" for i in range(n)]
    mu, sg, sp = _node_params(n, rng)
    edges = {(nodes[u], nodes[v]): float(rng.uniform(0.4, 1.0)) for u, v in sorted(set(pairs))}
    return Topology(name=f"{family}{name}", family=family, nodes=nodes, edges=edges,
                    root_rate=float(np.exp(rng.uniform(math.log(0.15), math.log(1.0)))),
                    mu_ms=dict(zip(nodes, mu)), sigma=dict(zip(nodes, sg)), spike_p=dict(zip(nodes, sp)))


def make_topology(family, n, rng, name="0"):
    """A random DAG of `n` services. Node 0 is the entry service; nodes are in topological order."""
    if n < 3:
        raise ValueError("need at least 3 services")
    if family == "chain":
        pairs = [(i, i + 1) for i in range(n - 1)]
    elif family == "star":
        pairs = [(0, i) for i in range(1, n)]
    elif family == "tree":
        pairs = [(int(rng.integers(0, i)), i) for i in range(1, n)]
    elif family == "random":
        pairs = []
        for i in range(1, n):
            for p in rng.choice(i, size=min(i, int(rng.integers(1, 3))), replace=False):
                pairs.append((int(p), i))
    elif family == "layered":
        layers, left = [[0]], n - 1
        while left > 0:
            w = int(min(left, rng.integers(1, 4)))
            start = n - left
            layers.append(list(range(start, start + w)))
            left -= w
        pairs = []
        for a, b in zip(layers, layers[1:]):
            for v in b:
                pairs.append((int(rng.choice(a)), v))
            for u in a:
                if not any(x == u for x, _ in pairs):
                    pairs.append((u, int(rng.choice(b))))
    else:
        raise ValueError(f"unknown family {family}")
    return _finish(name, family, n, pairs, rng)


def bookinfo_topology():
    """Bookinfo as the simulator sees it, with parameters read off the real normal-phase data (see calibrate.py)."""
    nodes = ["productpage", "details", "reviews", "ratings"]
    edges = {("productpage", "details"): 1.0, ("productpage", "reviews"): 1.0, ("reviews", "ratings"): 0.65}
    return Topology(name="bookinfo", family="bookinfo", nodes=nodes, edges=edges, root_rate=0.28,
                    mu_ms={"productpage": 2.0, "details": 3.0, "reviews": 12.0, "ratings": 2.5},
                    sigma={"productpage": 0.3, "details": 0.35, "reviews": 0.4, "ratings": 0.35},
                    spike_p={"productpage": 0.004, "details": 0.006, "reviews": 0.02, "ratings": 0.002})


# ----------------------------------------------------------------------------------------- latency sampling
def _handle(topo, v, k, rng, fault):
    """Server-side time of k requests handled by v: its own service time plus the calls it makes."""
    t = rng.lognormal(math.log(topo.mu_ms[v]), topo.sigma[v], k)
    slow = rng.random(k) < topo.spike_p[v]
    t = t + slow * rng.uniform(50.0, 250.0, k)
    for c, p in topo.children[v]:
        sel = np.flatnonzero(rng.random(k) < p)
        if sel.size:
            t[sel] += _call(topo, c, sel.size, rng, fault)
    return t


def _call(topo, c, k, rng, fault):
    """What the caller sees for k calls into c: c's handling time, plus the injected delay if c is the faulted node."""
    d = _handle(topo, c, k, rng, fault)
    if fault is not None and c == fault[0]:
        d = d + fault[1] + rng.normal(0.0, 0.5, k)
    return d


def snapshot(topo, rng, fault=None, window_s=WINDOW_S):
    """One snapshot: nodes + edges with request_rate, error_rate (0) and bucketed latency_p95. Idle edges are absent."""
    rates = topo.in_rates()
    edges = []
    for (u, v), p in topo.edges.items():
        rate = rates[u] * p
        n = int(rng.poisson(rate * window_s))
        if n == 0:
            continue
        durations = _call(topo, v, n, rng, fault)
        edges.append({"source": u, "destination": v, "request_rate": n / window_s, "error_rate": 0.0,
                      "latency_p95": histogram_quantile(0.95, durations)})
    return {"nodes": [{"id": n, "region": topo.name} for n in topo.nodes], "edges": edges}


# ----------------------------------------------------------------------------------------- datasets
def make_records(topo, rng, n_normal=60, n_episodes=6, steady_per_episode=14, start=None):
    """Labelled snapshots for one topology, following the real labelling rule: during an episode only the faulted
    node is positive; normal snapshots are all negative. (Real lag/recovery snapshots are excluded there, so they
    are simply not generated here.)"""
    t = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []

    def add(snap, phase, fault_node, episode):
        nonlocal t
        snap.update(timestamp=t.isoformat(), phase=phase, fault_node=fault_node, episode_id=episode,
                    topology=topo.name, family=topo.family,
                    labels={n["id"]: int(phase == "steady" and n["id"] == fault_node) for n in snap["nodes"]})
        records.append(snap)
        t += timedelta(seconds=15)

    for _ in range(n_normal):
        add(snapshot(topo, rng), "normal", None, None)
    candidates = topo.faultable()
    for e in range(n_episodes):
        node = str(rng.choice(candidates))
        delay = int(rng.choice(FAULT_DELAYS_MS))
        # In the real episodes (100% fixedDelay) the measured duration is a few ms under the nominal delay, so a
        # nominal 100 ms fault often reads in the (50,100] bucket (p95 97.5) instead of (100,250]. Draw a shortfall
        # per episode instead of fixing one number, so training data covers both cases.
        effective = delay - float(rng.uniform(0.0, 8.0))
        for _ in range(steady_per_episode):
            add(snapshot(topo, rng, fault=(node, effective)), "steady", node, f"{topo.name}-e{e}-{node}-{delay}ms")
    return records


def make_corpus(seed, per_family=8, families=FAMILIES, size_range=(4, 25), **kw):
    """Topologies from every family (sizes spread over `size_range`) and their labelled records."""
    rng = np.random.default_rng(seed)
    topos, records = [], []
    for fam in families:
        for i in range(per_family):
            n = int(rng.integers(size_range[0], size_range[1] + 1))
            topo = make_topology(fam, n, rng, name=f"{i}")
            topos.append(topo)
            records.extend(make_records(topo, rng, **kw))
    return topos, records
