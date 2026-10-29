# Commit split for three people

Proposal only; nothing has been committed. Counts are from `git status --short -uall` on 2026-10-29: 120 files split 43 / 39 / 38, plus 19 files that should not be committed (last section). Each person commits their own group under their own git identity. Check each file list before `git add`; if your team prefers a different grouping, move lines between groups, but keep every file in exactly one group.

## Order and cautions
- **Commit Person 1 first.** `meshheal_controlplane/controlplane/gnn_adapter.py` (Person 2) imports `build_dataset_v2.py` and `model.py` (Person 1), so Person 2's group does not run on a checkout without them. Person 3's Evaluation page reads Person 1's `results_*.md` at run time.
- **Model weights are not in any group.** `.gitignore` excludes `*.pt`, so `models/gnn_final_seed*.pt` and `models/gnn_final_v3_seed*.pt` will not be committed, and a fresh clone cannot run the GNN scorer until `train_final.py` is run again (about 3 minutes here) or the weights are shared another way. Decide this before submission; `git add -f` would force them in.
- `snapshots.jsonl` (Person 1) is a modified tracked file (+319 lines) and the training data. Its sha256 was `776c55321d77...79ac05` on 2026-10-28. Do not overwrite it.
- `shadow_run/snapshots.jsonl` (Person 2, about 3.5 MB) is the recorded telemetry the dashboard REPLAY fallback needs. Keep it unless the repo size matters.
- Run `python -m pytest -q` in `meshheal_controlplane` (35 passed) before the Person 2 commit.

## Person 1: data, training and evaluation (43 files)

Data and labelling scripts, model and training code, all LOEO / controls / policy evaluation scripts and their result files. Suggested commit message: "data pipeline, GNN training, LOEO and control evaluation, v3 cleanup check".

```bash
git add -- build_graph_dataset.py \
  model.py \
  train.py \
  snapshots.jsonl \
  labeled_dataset_v2.jsonl \
  latency_mean.jsonl \
  fault_log.jsonl \
  label_dataset_v2.py \
  build_dataset_v2.py \
  build_dataset_v3.py \
  make_excluded_windows_v3.py \
  excluded_windows_v3.json \
  check_episodes.py \
  check_parity_v3.py \
  test_build_dataset_v3.py \
  train_final.py \
  train_final_v3.py \
  run_v3.py \
  run_faults.py \
  models/gnn_final_manifest.json \
  models/gnn_final_v3_manifest.json \
  fault-details-delay.yaml \
  experiment_a.py \
  experiment_b.py \
  experiment_b_v2.py \
  generalization_test.py \
  diagnose.py \
  baseline.py \
  evaluate.py \
  loeo_eval.py \
  loeo_diagnostics.py \
  controls_eval.py \
  results_policy.py \
  results_controls.md \
  results_controls_v3.md \
  results_loeo.md \
  results_loeo.csv \
  results_loeo_v3.md \
  results_loeo_v3.csv \
  results_loeo_diagnostics.md \
  results_loeo_invalid_zerofill.md \
  results_policy.md \
  results_policy_v3.md
```

## Person 2: control plane, live demo and shadow run (39 files)

The controller package and its tests, the closed-loop live demo with the 2026-10-29 results, the shadow run, the Istio YAMLs, `demo_up.sh`, `CLAUDE.md` and the demo script. Suggested message: "control plane (GNN adapter, kill file, merge patch), live closed-loop runs, shadow run".

```bash
git add -- meshheal_controlplane/README_controlplane.md \
  meshheal_controlplane/controlplane/cluster.py \
  meshheal_controlplane/controlplane/config.py \
  meshheal_controlplane/controlplane/controller.py \
  meshheal_controlplane/controlplane/gnn_adapter.py \
  meshheal_controlplane/controlplane/run.py \
  meshheal_controlplane/controlplane/scorer.py \
  meshheal_controlplane/tests/test_controller.py \
  live_demo/README.md \
  live_demo/audit_A_20261029T053627Z.jsonl \
  live_demo/audit_B_20261029T064550Z.jsonl \
  live_demo/controller_A_20261029T053627Z.log \
  live_demo/controller_B_20261029T064550Z.log \
  live_demo/latency.csv \
  live_demo/result_A_20261029T053627Z.json \
  live_demo/result_B_20261029T064550Z.json \
  live_demo/run_live.py \
  live_demo/test_patch.py \
  meshheal_controlplane/tests/test_cluster.py \
  meshheal_controlplane/tests/test_gnn_adapter.py \
  demo_up.sh \
  destinationrule-reviews.yaml \
  reviews-normal.yaml \
  reviews-reroute-v1.yaml \
  CLAUDE.md \
  docs/DEMO_SCRIPT.md \
  shadow_run/compare.py \
  shadow_run/run_schedule.py \
  shadow_run/audit_gnn.jsonl \
  shadow_run/audit_rule.jsonl \
  shadow_run/fault-details-75.yaml \
  shadow_run/fault-ratings-150.yaml \
  shadow_run/fault-ratings-75.yaml \
  shadow_run/fault-reviews-150.yaml \
  shadow_run/fault_log_shadow.jsonl \
  shadow_run/schedule_log.jsonl \
  shadow_run/predictions_shadow.md \
  shadow_run/results_shadow.md \
  shadow_run/snapshots.jsonl
```

## Person 3: dashboard, figures and written material (39 files)

The Frontend_v2 dashboard and API, the figures, the reports and the report/viva/prediction docs, plus this file. Suggested message: "Frontend_v2 dashboard, figures, reports and viva notes".

```bash
git add -- Frontend_v2/.gitignore \
  Frontend_v2/.oxlintrc.json \
  Frontend_v2/README.md \
  Frontend_v2/api/meshheal_api.py \
  Frontend_v2/index.html \
  Frontend_v2/package-lock.json \
  Frontend_v2/package.json \
  Frontend_v2/src/App.tsx \
  Frontend_v2/src/api.ts \
  Frontend_v2/src/components/common.tsx \
  Frontend_v2/src/main.tsx \
  Frontend_v2/src/pages/Evaluation.tsx \
  Frontend_v2/src/pages/HowItWorks.tsx \
  Frontend_v2/src/pages/Incidents.tsx \
  Frontend_v2/src/pages/LiveMesh.tsx \
  Frontend_v2/src/pages/Overview.tsx \
  Frontend_v2/src/styles.css \
  Frontend_v2/tsconfig.app.json \
  Frontend_v2/tsconfig.json \
  Frontend_v2/tsconfig.node.json \
  Frontend_v2/vite.config.ts \
  figures/README.md \
  figures/fig_a_shadow_risk_dark.png \
  figures/fig_a_shadow_risk_light.png \
  figures/fig_b_detection_time_dark.png \
  figures/fig_b_detection_time_light.png \
  figures/fig_c_loeo_ap_dark.png \
  figures/fig_c_loeo_ap_light.png \
  figures/fig_d_pipeline_dark.png \
  figures/fig_d_pipeline_light.png \
  figures/make_figures.py \
  meshheal_results_v2.md \
  REPORT_V3.md \
  REPORT_HOUR.md \
  REPORT_AWAY.md \
  docs/REPORT_UPDATE_NOTES.md \
  docs/VIVA_QA.md \
  docs/v3_predictions.md \
  docs/COMMIT_SPLIT.md
```

## Do not commit (19 files)

Runtime logs, build output and backups. Leave them untracked, or add them to `.gitignore`.

- Logs and process files in `shadow_run/`: `traffic.log` (5.8 MB), `pf_productpage.log`, `pf_prometheus.log`, `telemetry.log`, `ctrl_gnn.log`, `ctrl_rule.log`, `dashboard.log`, `run_schedule.log`, `run_live_A.out`, `run_live_B.out`, `pids.txt`.
- Build info: `Frontend/tsconfig.app.tsbuildinfo` (modified), `Frontend_v2/tsconfig.app.tsbuildinfo`, `Frontend_v2/tsconfig.node.tsbuildinfo`.
- Backups: `Frontend/src/data/replayAdapter.ts.bak-20261022`, `Frontend/src/data/simulatedDataSource.ts.bak-20261022`, `results_controls.md.bak-20261022`, `results_loeo.md.bak-20261022`, `meshheal_gnn_backup.zip`.
