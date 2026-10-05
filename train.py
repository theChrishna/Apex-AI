import torch
import torch.nn as nn
from build_graph_dataset import load_all_graphs, train_test_split_stratified_chronological
from model import RiskGNN

graphs = load_all_graphs()
train_graphs, test_graphs = train_test_split_stratified_chronological(graphs)

model = RiskGNN(num_node_features=train_graphs[0].x.shape[1])
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

pos_weight = torch.tensor([34.0])
loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

EPOCHS = 50

for epoch in range(EPOCHS):
    model.train()
    total_loss = 0.0

    for graph in train_graphs:
        optimizer.zero_grad()
        output = model(graph.x, graph.edge_index)
        loss = loss_fn(output, graph.y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    avg_loss = total_loss / len(train_graphs)
    if epoch % 10 == 0 or epoch == EPOCHS - 1:
        print(f"Epoch {epoch:3d} | Train loss: {avg_loss:.4f}")

torch.save(model.state_dict(), "risk_gnn.pt")
print("\nModel saved to risk_gnn.pt")