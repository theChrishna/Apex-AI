import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from topo import live_decisions as L  # noqa: E402

T0 = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)


def ev(minutes, event, node=None):
    e = {"ts": (T0 + timedelta(minutes=minutes)).isoformat(), "event": event}
    return {**e, "node": node} if node else e


def test_caught_wrong_first_and_false_alarms():
    eps = [{"id": "1", "node": "a", "type": "abort", "start": T0 + timedelta(minutes=30), "end": T0 + timedelta(minutes=34)},
           {"id": "2", "node": "b", "type": "cpu", "start": T0 + timedelta(minutes=60), "end": T0 + timedelta(minutes=64)}]
    events = [ev(m / 4, "SCORED") for m in range(0, 400)]
    events += [ev(31.5, "ACTION_BLOCKED", "a"),                       # episode 1 caught after 90 s, right service first
               ev(61, "ACTION_BLOCKED", "c"), ev(62, "ACTION_BLOCKED", "b"),   # episode 2: wrong service first, then caught
               ev(10, "ACTION_BLOCKED", "d"), ev(10.25, "ACTION_BLOCKED", "d"),  # one false-alarm onset (two events)
               ev(90, "ACTION_BLOCKED", "e")]                         # inside an excluded window: ignored
    rows, onsets, hours = L.analyse(sorted(events, key=L._ts), eps,
                                    exclude=[(T0 + timedelta(minutes=85), T0 + timedelta(minutes=95))])
    assert [(r["caught"], r["delay_s"], r["wrong_first"]) for r in rows] == [(True, 90, False), (True, 120, True)]
    assert [o["node"] for o in onsets] == ["d"] and hours > 0
