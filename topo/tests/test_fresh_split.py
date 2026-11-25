import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from topo import fresh_test as F  # noqa: E402

T0 = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)


def test_learning_data_never_overlaps_the_test_data(tmp_path):
    snaps = tmp_path / "s.jsonl"
    rows = [{"timestamp": (T0 + timedelta(seconds=15 * i)).isoformat(), "nodes": [{"id": "a"}], "edges": []} for i in range(400)]
    snaps.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    start, end = T0 + timedelta(minutes=40), T0 + timedelta(minutes=45)       # one episode inside the file
    log = tmp_path / "f.jsonl"
    log.write_text(json.dumps({"episode": 1, "node": "a", "type": "abort", "delay_ms": 0, "start": start.isoformat(),
                               "end": end.isoformat(), "completed": True}) + "\n", encoding="utf-8")
    learn, recs, eps = F.split(str(snaps), str(log), learn_share=0.6)
    learned = {r["timestamp"] for r in learn}
    tested = {r["timestamp"] for r in recs}
    assert learned and tested and not (learned & tested)                        # no snapshot is in both
    assert max(learned) < min(r["timestamp"] for r in recs if r["phase"] == "steady")   # learning ends before the run
    assert all(datetime.fromisoformat(t) < start - timedelta(minutes=5) for t in learned)
    assert {r["phase"] for r in recs} >= {"steady", "normal"} and eps[0]["type"] == "abort"


def test_excluded_windows_are_dropped_everywhere(tmp_path):
    snaps = tmp_path / "s.jsonl"
    rows = [{"timestamp": (T0 + timedelta(seconds=15 * i)).isoformat(), "nodes": [{"id": "a"}], "edges": []} for i in range(400)]
    snaps.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    start, end = T0 + timedelta(minutes=40), T0 + timedelta(minutes=45)
    log = tmp_path / "f.jsonl"
    log.write_text(json.dumps({"episode": 1, "node": "a", "type": "crash", "delay_ms": 0, "start": start.isoformat(),
                               "end": end.isoformat(), "completed": True}) + "\n", encoding="utf-8")
    gap = (T0 + timedelta(minutes=60), T0 + timedelta(minutes=70))          # e.g. an unlogged partial episode
    learn, recs, _ = F.split(str(snaps), str(log), learn_share=0.6, exclude=[gap])
    kept = [datetime.fromisoformat(r["timestamp"]) for r in learn + recs]
    assert kept and not any(gap[0] <= t <= gap[1] for t in kept)
    assert any(t > gap[1] for t in kept)                                     # data after the window is still used
