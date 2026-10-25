"""Adapter that makes the trained GNN look like a Scorer.

TODO (wire to the real code in your repo, then verify with tests/test_live_path.py idea below):
  1. Build the 6 node features in EXACTLY the training order/scaling:
        [in_rate, in_err, in_lat, out_rate, out_err, out_lat]   (+ log1p flag as in training)
     stats from snapshot.node_stats() holds in_rate, in_err, in_lat, out_rate, out_lat (out_err is 0 here:
     add it to node_stats if your feature builder uses it).
  2. Node order must follow NODE_VOCAB from build_dataset_v2.py; edge_index from snapshot edges.
  3. Load the FINAL model (trained on all episodes), average over seeds, return {node: prob}.
  4. Check: run stored snapshots through this and compare against the offline scores (must match).
"""


class GnnScorer:
    name = "gnn"

    def __init__(self, model_paths):
        raise NotImplementedError("wire GnnScorer to model.py / build_dataset_v2.py (see module docstring)")

    def score(self, stats):
        raise NotImplementedError
