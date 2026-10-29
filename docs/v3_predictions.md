# Predictions for the v3 (cleaned data) comparison

Written before running anything for this job. UTC time of writing: 2026-10-26T17:44:23Z

What is being changed: remove the noisy "normal" snapshots (Sep 16 non-holdout snapshots with a reviews edge at p95 >= 97.5 ms and rate > 0.1, plus the Oct 6 holdout window), each with a 120 s buffer, from the normal pools used for training and for the holdout. Everything else stays the same (same seeds, same config, same folds).

The user's guess (to be checked, not mine):
1. GNN AP on the reviews folds goes up (fold 2, reviews 100 ms: AP 0.683 and root-cause top-1 0.815 in the v1 table; fold 5, reviews 200 ms is already 1.000).
2. The other folds change within noise.
3. The MLP and the p95 baseline barely change.

My additional expectations, with confidence:
4. The policy second-half false-action share drops for the GNN on the cleaned holdout, because 38 of the 69 second-half holdout snapshots are contaminated now. (medium)
5. The baseline and culprit-rule AP and root-cause numbers are unchanged or move by a few thousandths, because they are not trained and only their validation threshold can move. (medium-high; AP is threshold-free, so unchanged is the likelier result)
6. The final v3 GNN scores fewer Sep 16 snapshots above 0.85 in a normal-only replay of the cleaned normal data, simply because the flagged snapshots are gone; replaying the removed snapshots through it is a different question and I expect it still scores some of them high. (low-medium)
7. Fold 2 may not improve: the weakness could come from something else (small fold, 13 steady positives, seed spread). (low-medium)
8. Several GNN folds move by more than 0.01 AP just from the changed training set and seed noise, so "within noise" needs the seed std to judge. (medium)

Not predicted: any change to the LOEO folds' test sets; they are the same episodes.
