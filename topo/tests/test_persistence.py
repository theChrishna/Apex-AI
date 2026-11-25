import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from topo import persistence as P  # noqa: E402

T0 = datetime(2026, 11, 25, tzinfo=timezone.utc)


def seq(*tops, gap_at=None):
    out, t = [], T0
    for i, top in enumerate(tops):
        if gap_at is not None and i == gap_at:
            t += timedelta(seconds=300)
        out.append((t, {"a": 0.9 if top == "a" else 0.1, "b": 0.9 if top == "b" else 0.1}))
        t += timedelta(seconds=15)
    return out


def test_alarm_needs_three_of_four_like_the_controller():
    al = [n for _, n in P.alarms(seq("a", "a", "a", "a"))]
    assert al == [None, None, "a", "a"]


def test_history_resets_after_a_gap():
    al = [n for _, n in P.alarms(seq("a", "a", "a", "a", gap_at=2))]
    assert al == [None, None, None, None]                    # 2 before the gap and 2 after are never 3 in a row


def test_onsets_count_new_alarms_only():
    assert P.onsets([(T0, None), (T0, "a"), (T0, "a"), (T0, None), (T0, "a"), (T0, "b")]) == 3


def test_hours_caps_gaps():
    s = [(T0, None), (T0 + timedelta(seconds=15), None), (T0 + timedelta(hours=5), None)]
    assert abs(P.hours(s) - 30 / 3600) < 1e-9                # the 5 h gap counts as one 15 s step


def test_each_bookinfo_variant_gets_its_own_baseline_file():
    """Regression: both variants once wrote the same temp file, so the first was scored with the second's baseline."""
    with tempfile.TemporaryDirectory() as t:
        _, _, a = P.bookinfo(True, t)
        _, _, b = P.bookinfo(False, t)
        assert a != b and os.path.exists(a) and os.path.exists(b)
