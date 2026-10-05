import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GCNConv

class RiskGNN(nn.Module):
    def __init__(self, num_node_features, hidden_dim=16):
        super().__init__()
        self.conv1 = GCNConv(num_node_features, hidden_dim)
        self.conv2 = GCNConv(hidden_dim, hidden_dim)
        self.output = nn.Linear(hidden_dim, 1)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = self.conv2(x, edge_index)
        x = F.relu(x)
        x = self.output(x)
        return x.squeeze(-1)

if __name__ == "__main__":
    from build_graph_dataset import load_all_graphs

    graphs = load_all_graphs()
    sample = graphs[0]

    model = RiskGNN(num_node_features=sample.x.shape[1])
    output = model(sample.x, sample.edge_index)

    print("Input x shape:", sample.x.shape)
    print("Output shape:", output.shape)
    print("Output (raw logits):", output)