"""
build_dataset_v3.py
===================
build_dataset_v2 plus one change: the noisy "normal" snapshots listed in excluded_windows_v3.json are dropped from
the normal pools (training normals and the holdout). Nothing else differs from v2: record_to_graph, the phase
labelling, the episode catalogue and the lag/recovery rules are v2's own objects (re-exported, not copied).

How the exclusion is applied (so v1 and v3 differ only by the removed snapshots):
  load_all_records()          = v2's records minus the excluded timestamps.
  build_normal_holdout_ts()   = v2's holdout (selected on v2's FULL record list, same 25% rule) minus the excluded
                                timestamps. It deliberately ignores its `records` argument for the selection, because
                                re-selecting "the latest 25%" on the filtered list would move the cut and change
                                which clean snapshots are in the holdout.
Only phase == "normal" snapshots are ever excluded (asserted when the windows file is built and again in the tests).

Use it without editing the v2 consumers (loeo_eval.py, results_policy.py, controls_eval.py): run_v3.py patches the two
function names on build_dataset_v2 before running a script.
"""
import hashlib
import json
import os

import build_dataset_v2 as v2
from build_dataset_v2 import *   # noqa: F401,F403  (re-export ALL_EPISODES, NODE_VOCAB, record_to_graph, constants, ...)
from build_dataset_v2 import HOLDOUT_FRAC, SNAPSHOTS_PATH

_HERE = os.path.dirname(os.path.abspath(__file__))
EXCLUDED_FILE = os.environ.get("MESHHEAL_EXCLUDED_WINDOWS", os.path.join(_HERE, "excluded_windows_v3.json"))

with open(EXCLUDED_FILE, "rb") as _f:
    _raw = _f.read()
EXCLUDED_SHA256 = hashlib.sha256(_raw).hexdigest()
EXCLUDED = frozenset(json.loads(_raw)["excluded_timestamps"])

# v2's own functions, captured at import time: run_v3.py later replaces the names on build_dataset_v2 with the
# functions below, and these references keep pointing at the originals.
_v2_load_all_records = v2.load_all_records
_v2_build_normal_holdout_ts = v2.build_normal_holdout_ts

_full = None


def _full_records(snapshots_path=SNAPSHOTS_PATH):
    global _full
    if _full is None or _full[0] != snapshots_path:
        _full = (snapshots_path, _v2_load_all_records(snapshots_path))
    return _full[1]


def load_all_records(snapshots_path=SNAPSHOTS_PATH):
    """v2's records without the excluded snapshots (every other record is v2's, unchanged)."""
    return [r for r in _full_records(snapshots_path) if r["timestamp"] not in EXCLUDED]


def build_normal_holdout_ts(records=None, frac=HOLDOUT_FRAC):
    """v2's holdout minus the excluded snapshots (selection done on v2's full record list; see module docstring)."""
    full = _full_records()
    if records is not None:
        known = {r["timestamp"] for r in full}
        assert all(r["timestamp"] in known for r in records), "records are not from this snapshots file"
    return frozenset(_v2_build_normal_holdout_ts(full, frac) - EXCLUDED)
