import torch
from build_graph_dataset import load_all_graphs, train_test_split_stratified_chronological
from model import RiskGNN

graphs = load_all_graphs()
train_graphs, test_graphs = train_test_split_stratified_chronological(graphs)

model = RiskGNN(num_node_features=test_graphs[0].x.shape[1])
model.load_state_dict(torch.load("risk_gnn.pt"))
model.eval()

THRESHOLD = 0.5

true_positives = 0
false_positives = 0
false_negatives = 0
true_negatives = 0

with torch.no_grad():
    for graph in test_graphs:
        logits = model(graph.x, graph.edge_index)
        probs = torch.sigmoid(logits)
        preds = (probs > THRESHOLD).float()

        for pred, true in zip(preds, graph.y):
            if pred == 1 and true == 1:
                true_positives += 1
            elif pred == 1 and true == 0:
                false_positives += 1
            elif pred == 0 and true == 1:
                false_negatives += 1
            else:
                true_negatives += 1

precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0

print(f"True Positives:  {true_positives}")
print(f"False Positives: {false_positives}")
print(f"False Negatives: {false_negatives}")
print(f"True Negatives:  {true_negatives}")
print(f"\nPrecision: {precision:.3f}")
print(f"Recall:    {recall:.3f}")