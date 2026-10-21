// update after final results
// Leave-one-episode-out, 8 folds, GNN averaged over 5 seeds, vs rule baseline "flag if incoming p95 > threshold"

export interface EvalFoldResult {
  episode: string;
  node: "ratings" | "details" | "reviews" | "productpage";
  delay_ms: number;
  gnn_ap: number;
  gnn_ap_std: number;
  bl_ap: number;
  gnn_rc1: number;
  bl_rc1: number;
  winner: "gnn" | "tie" | "baseline";
}

export const EVALUATION_DATA: EvalFoldResult[] = [
  {
    episode: "A",
    node: "ratings",
    delay_ms: 200,
    gnn_ap: 1.000,
    gnn_ap_std: 0.000,
    bl_ap: 0.821,
    gnn_rc1: 1.000,
    bl_rc1: 0.942,
    winner: "gnn",
  },
  {
    episode: "B",
    node: "details",
    delay_ms: 100,
    gnn_ap: 1.000,
    gnn_ap_std: 0.000,
    bl_ap: 1.000,
    gnn_rc1: 1.000,
    bl_rc1: 1.000,
    winner: "tie",
  },
  {
    episode: "1",
    node: "reviews",
    delay_ms: 100,
    gnn_ap: 0.658,
    gnn_ap_std: 0.185,
    bl_ap: 1.000,
    gnn_rc1: 0.815,
    bl_rc1: 1.000,
    winner: "baseline",
  },
  {
    episode: "2",
    node: "details",
    delay_ms: 50,
    gnn_ap: 0.728,
    gnn_ap_std: 0.315,
    bl_ap: 1.000,
    gnn_rc1: 0.786,
    bl_rc1: 1.000,
    winner: "baseline",
  },
  {
    episode: "3",
    node: "ratings",
    delay_ms: 100,
    gnn_ap: 1.000,
    gnn_ap_std: 0.000,
    bl_ap: 0.376,
    gnn_rc1: 1.000,
    bl_rc1: 0.071,
    winner: "gnn",
  },
  {
    episode: "4",
    node: "reviews",
    delay_ms: 200,
    gnn_ap: 1.000,
    gnn_ap_std: 0.000,
    bl_ap: 1.000,
    gnn_rc1: 1.000,
    bl_rc1: 1.000,
    winner: "tie",
  },
  {
    episode: "5",
    node: "details",
    delay_ms: 200,
    gnn_ap: 1.000,
    gnn_ap_std: 0.000,
    bl_ap: 1.000,
    gnn_rc1: 1.000,
    bl_rc1: 1.000,
    winner: "tie",
  },
  {
    episode: "6",
    node: "ratings",
    delay_ms: 50,
    gnn_ap: 1.000,
    gnn_ap_std: 0.000,
    bl_ap: 0.984,
    gnn_rc1: 1.000,
    bl_rc1: 0.929,
    winner: "gnn",
  },
];

export const EVALUATION_FOOTNOTES = [
  "Fold 2 averages 4 of 5 seeds; one seed collapsed. Counting it as 0 gives AP 0.582.",
  "About 13-14 positive readings per fold, so results are suggestive, not conclusive.",
  "Ties = within 0.01.",
  "Each held-out fold has other episodes of the same service in training.",
];

export const EVALUATION_SUMMARY = {
  totalFolds: 8,
  gnnWins: 3,
  ties: 3,
  baselineWins: 2,
  description: "GNN better on 3 folds, tied on 3, worse on 2",
};
