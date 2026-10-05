import json
import torch
from torch_geometric.data import Data

NODE_VOCAB = ["details", "productpage", "ratings", "reviews"]
NODE_INDEX = {name: i for i, name in enumerate(NODE_VOCAB)}

def snapshot_to_graph(record):
    node_ids_present = set(n["id"] for n in record["nodes"])
    if not node_ids_present.issuperset(NODE_VOCAB):
        return None

    in_vals = {n: [] for n in NODE_VOCAB}
    out_vals = {n: [] for n in NODE_VOCAB}

    edge_index = [[], []]
    edge_attr = []

    for edge in record["edges"]:
        src, dst = edge["source"], edge["destination"]
        if src not in NODE_INDEX or dst not in NODE_INDEX:
            continue

        edge_index[0].append(NODE_INDEX[src])
        edge_index[1].append(NODE_INDEX[dst])
        edge_attr.append([edge["request_rate"], edge["error_rate"], edge["latency_p95"]])

        out_vals[src].append((edge["request_rate"], edge["error_rate"], edge["latency_p95"]))
        in_vals[dst].append((edge["request_rate"], edge["error_rate"], edge["latency_p95"]))

    def avg(vals):
        if not vals:
            return (0.0, 0.0, 0.0)
        n = len(vals)
        return tuple(sum(v[i] for v in vals) / n for i in range(3))

    node_features = []
    for node in NODE_VOCAB:
        in_rate, in_err, in_lat = avg(in_vals[node])
        out_rate, out_err, out_lat = avg(out_vals[node])
        node_features.append([in_rate, in_err, in_lat, out_rate, out_err, out_lat])

    labels = record["labels"]
    y = [labels.get(node, 0) for node in NODE_VOCAB]

    x = torch.tensor(node_features, dtype=torch.float)
    edge_index_t = torch.tensor(edge_index, dtype=torch.long)
    edge_attr_t = torch.tensor(edge_attr, dtype=torch.float)
    y_t = torch.tensor(y, dtype=torch.float)

    return Data(x=x, edge_index=edge_index_t, edge_attr=edge_attr_t, y=y_t)

def load_all_graphs(path="labeled_dataset.jsonl"):
    graphs = []
    with open(path) as f:
        for line in f:
            record = json.loads(line)
            graph = snapshot_to_graph(record)
            if graph is not None:
                graphs.append(graph)
    return graphs

def train_test_split_stratified_chronological(graphs, test_fraction=0.2):
    normal_graphs = [g for g in graphs if g.y.sum().item() == 0]
    anomalous_graphs = [g for g in graphs if g.y.sum().item() > 0]

    def split(group):
        split_idx = int(len(group) * (1 - test_fraction))
        return group[:split_idx], group[split_idx:]

    normal_train, normal_test = split(normal_graphs)
    anomalous_train, anomalous_test = split(anomalous_graphs)

    train_graphs = normal_train + anomalous_train
    test_graphs = normal_test + anomalous_test

    return train_graphs, test_graphs

def count_positive_labels(graphs):
    return sum(int(g.y.sum().item()) for g in graphs)

# adding this at the botton
if __name__ == "__main__":
    graphs = load_all_graphs()
    train_graphs, test_graphs = train_test_split_stratified_chronological(graphs)

    print(f"Total graphs: {len(graphs)}")
    print(f"Train: {len(train_graphs)} graphs, {count_positive_labels(train_graphs)} positive labels")
    print(f"Test:  {len(test_graphs)} graphs, {count_positive_labels(test_graphs)} positive labels")