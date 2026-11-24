"""Build PyG graphs for ANY set of services (build_dataset_v2.record_to_graph is locked to four Bookinfo names).

Same six node features as v2, computed the same way (plain mean over a node's incoming / outgoing edges, log1p on
rates and latencies, error rates unscaled), so a model trained on these graphs sees the same kind of numbers.

    features = [in_rate, in_err, in_lat, out_rate, out_err, out_lat]      (+ [in_degree, out_degree] if degree=True)

`node_order` fixes the node order (pass NODE_VOCAB to reproduce v2 exactly). Without it nodes are sorted by name.
The record format is the snapshot format used everywhere: {"nodes": [{"id"}], "edges": [{"source","destination",
"request_rate","error_rate","latency_p95"}], "labels": {node: 0/1}, ...}.
"""
import math

import torch
from torch_geometric.data import Data

BASE_FEATURES = ["in_rate", "in_err", "in_lat", "out_rate", "out_err", "out_lat"]
DEGREE_FEATURES = ["in_degree", "out_degree"]


def node_ids_of(record):
    ids = {n["id"] for n in record.get("nodes", [])}
    for e in record["edges"]:
        ids.add(e["source"])
        ids.add(e["destination"])
    ids.discard("unknown")
    return sorted(ids)


def record_to_graph(record, node_order=None, scale=True, degree=False):
    """PyG Data for one snapshot. Edges touching a node outside `node_order` are ignored (as in v2)."""
    order = list(node_order) if node_order is not None else node_ids_of(record)
    index = {n: i for i, n in enumerate(order)}
    ins = {n: [] for n in order}
    outs = {n: [] for n in order}
    ei = [[], []]
    for e in record["edges"]:
        s, d = e["source"], e["destination"]
        if s not in index or d not in index:
            continue
        ei[0].append(index[s])
        ei[1].append(index[d])
        v = (e["request_rate"], e["error_rate"], e["latency_p95"])
        outs[s].append(v)
        ins[d].append(v)

    def avg(vals):
        if not vals:
            return (0.0, 0.0, 0.0)
        n = len(vals)
        return tuple(sum(v[i] for v in vals) / n for i in range(3))

    def sc(v):
        return math.log1p(v) if scale else v

    feats, raw = [], []
    for n in order:
        ir, ie, il = avg(ins[n])
        orr, oe, ol = avg(outs[n])
        row = [sc(ir), ie, sc(il), sc(orr), oe, sc(ol)]
        raw.append([ir, ie, il, orr, oe, ol])
        if degree:
            row += [math.log1p(len(ins[n])), math.log1p(len(outs[n]))]
        feats.append(row)

    labels = record.get("labels", {})
    g = Data(x=torch.tensor(feats, dtype=torch.float),
             edge_index=torch.tensor(ei, dtype=torch.long),
             y=torch.tensor([float(labels.get(n, 0)) for n in order], dtype=torch.float))
    g.raw = torch.tensor(raw, dtype=torch.float)          # unscaled features, for the rule baseline
    g.node_ids = order
    # Metadata is always a string: PyG silently drops attributes set to None, and a batch that mixes graphs with and
    # without an attribute then fails at collation (KeyError) - which happens as soon as normal and fault snapshots mix.
    for name in ("phase", "fault_node", "topology", "family", "timestamp"):
        setattr(g, name, record.get(name) or "")
    return g
