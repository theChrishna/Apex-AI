"""Run an existing v2 script on the cleaned (v3) data without editing it.

    python run_v3.py loeo_eval.py          # also: results_policy.py, controls_eval.py
    (set the output env vars first: LOEO_RESULT_MD, LOEO_RESULT_CSV, POLICY_RESULT_MD, CONTROLS_RESULT_MD)

Patches load_all_records / build_normal_holdout_ts on build_dataset_v2 BEFORE the script imports them, then runs it
as __main__. Refuses to run unless an output override is set for the script, so a v2 results file cannot be overwritten.
"""
import os
import runpy
import sys

script = sys.argv[1]
needs = {"loeo_eval.py": ("LOEO_RESULT_MD", "LOEO_RESULT_CSV"), "results_policy.py": ("POLICY_RESULT_MD", "LOEO_RESULT_CSV"),
         "controls_eval.py": ("CONTROLS_RESULT_MD", "LOEO_RESULT_CSV")}
for var in needs.get(script, ()):
    if not os.environ.get(var) or "v3" not in os.environ[var]:
        sys.exit(f"{var} must be set to a v3 path before running {script} on v3 data")

import build_dataset_v2 as v2   # noqa: E402
import build_dataset_v3 as v3   # noqa: E402

v2.load_all_records = v3.load_all_records
v2.build_normal_holdout_ts = v3.build_normal_holdout_ts
print(f"[run_v3] {script} on v3 data; excluded_windows_v3.json sha256={v3.EXCLUDED_SHA256[:16]}...; "
      f"{len(v3.EXCLUDED)} snapshots excluded", flush=True)
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
