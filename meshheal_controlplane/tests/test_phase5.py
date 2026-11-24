"""Phase 5: shadow by default, pause switch, reroute-rate brake, state recorded in the cluster, restart recovery,
auto-expiry, health/metrics, size-capped files."""
import json
import os
import urllib.error
import urllib.request
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from controlplane import collect, run
from controlplane.audit import AuditLog
from controlplane.cluster import KEEP, ClusterError, DryRunClient, FakeClient, KubeClient, apply_state, read_state
from controlplane.config import Config
from controlplane.controller import PROBING, REROUTED, Controller
from controlplane.health import Health, start_server
from controlplane.playbook import default_playbook
from controlplane.scorer import RuleScorer
from controlplane.snapshot import parse_snapshot
from tests.test_controller import T0, events, snap_obj

pytest.importorskip("kubernetes")
from kubernetes.client.rest import ApiException  # noqa: E402


def make(client=None, box=None, audit=None, **cfg_kw):
    box = box if box is not None else {"now": T0}
    cfg = Config(**cfg_kw)
    ctrl = Controller(cfg, RuleScorer(cfg.self_lat_full_ms), client or FakeClient(), audit or AuditLog(None),
                      clock=lambda: box["now"], playbook=default_playbook())
    return ctrl, box


def go(ctrl, box, n, **kw):
    out = []
    for _ in range(n):
        box["now"] += timedelta(seconds=15)
        out += ctrl.step(parse_snapshot(snap_obj(box["now"], **kw)))
    return out


def reroute(client=None, **cfg_kw):
    """A controller that has just started the ratings reroute."""
    ctrl, box = make(client, **cfg_kw)
    go(ctrl, box, 3)
    ev = go(ctrl, box, 3, ratings_ms=150)
    assert events(ev, "REROUTE")
    return ctrl, box


# --------------------------------------------------------------------------------------------- shadow by default
def test_writing_needs_act_and_shadow_is_the_default():
    ap = run.build_parser()
    assert run.resolve_dry_run(ap, ap.parse_args([])) is True
    assert run.resolve_dry_run(ap, ap.parse_args(["--dry-run"])) is True           # old flag still means shadow
    assert run.resolve_dry_run(ap, ap.parse_args(["--act"])) is False
    with pytest.raises(SystemExit):
        run.resolve_dry_run(ap, ap.parse_args(["--act", "--dry-run"]))


class _Stop(BaseException):
    pass


@pytest.mark.parametrize("flags,shadow", [([], True), (["--dry-run"], True), (["--act"], False)])
def test_main_wraps_the_client_in_a_dry_run_unless_act_is_given(monkeypatch, tmp_path, flags, shadow):
    seen = {}

    class StubController:
        def __init__(self, cfg, scorer, client, audit, dry_run=False, playbook=None):
            seen.update(client=client, dry_run=dry_run)
            self.audit = audit

        def reconcile(self):
            seen["reconciled"] = True

        def status(self):
            return {"active_reroutes": 0, "paused": False, "dry_run": seen["dry_run"]}

    monkeypatch.setattr(run, "KubeClient", lambda *a, **k: FakeClient())
    monkeypatch.setattr(run, "Controller", StubController)
    monkeypatch.setattr(run, "step_from_file", lambda ctrl, path: None)
    monkeypatch.setattr(run.time, "sleep", lambda s: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        run.main(["--snapshots", str(tmp_path / "s.jsonl"), "--audit", str(tmp_path / "a.jsonl")] + flags)
    assert seen["dry_run"] is shadow and isinstance(seen["client"], DryRunClient) is shadow
    assert seen["reconciled"] is True                                               # restart recovery runs before the loop


def test_shadow_controller_never_writes_or_records_state():
    inner = FakeClient()
    box = {"now": T0}
    cfg = Config()
    ctrl = Controller(cfg, RuleScorer(cfg.self_lat_full_ms), DryRunClient(inner, log=lambda *_: None), AuditLog(None),
                      clock=lambda: box["now"], dry_run=True, playbook=default_playbook())
    go(ctrl, box, 3)
    ev = go(ctrl, box, 3, ratings_ms=150)
    assert events(ev, "REROUTE") and ctrl.active                                    # it decides as usual...
    assert inner.calls == [] and inner.states == {} and inner.weights == {}          # ...but nothing reaches the cluster


# --------------------------------------------------------------------------------------------- pause switch
def test_paused_controller_blocks_a_new_reroute_and_resumes_when_unpaused():
    client = FakeClient()
    client.paused = True
    ctrl, box = make(client)
    go(ctrl, box, 3)
    ev = go(ctrl, box, 4, ratings_ms=150)
    assert not events(ev, "REROUTE") and client.calls == []
    assert any(e["event"] == "ACTION_BLOCKED" and e["reason"] == "paused" for e in ev)
    client.paused = False
    assert events(go(ctrl, box, 2, ratings_ms=150), "REROUTE")


def test_pause_freezes_probe_and_release_too_until_unpaused():
    client = FakeClient()
    ctrl, box = reroute(client)
    n_writes = len(client.calls)
    client.paused = True
    ev = go(ctrl, box, 12, ratings_ms=150)                                          # 180 s: past the 120 s cooldown
    assert not events(ev, "PROBE_START") and len(client.calls) == n_writes
    client.paused = False
    assert events(go(ctrl, box, 2, ratings_ms=150), "PROBE_START")


def test_if_the_pause_setting_cannot_be_read_the_controller_does_not_write():
    class Broken(FakeClient):
        def is_paused(self):
            raise RuntimeError("api down")
    client = Broken()
    ctrl, box = make(client)
    go(ctrl, box, 3)
    ev = go(ctrl, box, 4, ratings_ms=150)
    assert not events(ev, "REROUTE") and client.calls == []
    assert events(ev, "PAUSE_CHECK_FAILED") and any(e.get("reason") == "paused" for e in events(ev, "ACTION_BLOCKED"))


# --------------------------------------------------------------------------------------------- rate limit
def test_reroute_rate_limit_stops_flapping_but_zero_means_unlimited():
    for limit, expect_block in ((1, True), (0, False)):
        client = FakeClient()
        ctrl, box = reroute(client, max_actions_per_hour=limit)
        ctrl.active.clear()
        ctrl.last_action.clear()
        ctrl.history.clear()                                                         # as if it had been released again
        box["now"] += timedelta(seconds=300)
        ev = go(ctrl, box, 4, ratings_ms=150)
        blocked = [e for e in events(ev, "ACTION_BLOCKED") if e.get("reason") == "rate_limited"]
        assert bool(blocked) is expect_block and bool(events(ev, "REROUTE")) is not expect_block


def test_rate_limit_window_slides_after_an_hour():
    ctrl, box = reroute(max_actions_per_hour=1, max_reroute_s=0)
    ctrl.active.clear()
    ctrl.last_action.clear()
    ctrl.history.clear()
    box["now"] += timedelta(seconds=3700)
    ev = go(ctrl, box, 4, ratings_ms=150)
    assert events(ev, "REROUTE") and not [e for e in ev if e.get("reason") == "rate_limited"]


# --------------------------------------------------------------------------------------------- recorded state
def test_the_reroute_is_recorded_with_each_write_and_cleared_on_release():
    client = FakeClient()
    ctrl, box = reroute(client)
    st = client.states["reviews"]
    assert (st["culprit"], st["mode"], st["target_subset"]) == ("ratings", REROUTED, "v1")
    assert st["normal_weights"] == {"v1": 34, "v2": 33, "v3": 33} and st["started"] == st["since"]
    ev = go(ctrl, box, 9, ratings_ms=150)                                           # cooldown passes
    assert events(ev, "PROBE_START") and client.states["reviews"]["mode"] == PROBING
    assert client.states["reviews"]["started"] == st["started"]                      # when it began never moves
    ev = go(ctrl, box, 9)                                                           # healthy for a whole probe period
    assert events(ev, "RELEASE") and "reviews" not in client.states and not ctrl.active


def test_a_failed_probe_goes_back_to_rerouted_in_the_recorded_state():
    client = FakeClient()
    ctrl, box = reroute(client)
    go(ctrl, box, 9, ratings_ms=150)
    ev = go(ctrl, box, 9, ratings_ms=150)                                           # still faulty during the probe
    assert events(ev, "PROBE_FAILED") and client.states["reviews"]["mode"] == REROUTED


# --------------------------------------------------------------------------------------------- restart recovery
def test_a_restarted_controller_takes_over_the_recorded_reroute_and_later_releases_it():
    client = FakeClient()
    old, box = reroute(client)
    assert old.active and client.states
    fresh, _ = make(client, box=box)                                                # the process was restarted
    assert not fresh.active
    fresh.reconcile()
    assert fresh.active["ratings"]["mode"] == REROUTED and events(fresh.audit.events, "RECONCILED")
    assert client.weights["reviews"]["v1"] == 100                                    # reconcile changes nothing in the cluster
    ev = go(fresh, box, 9)                                                          # healthy again; cooldown passes, probe starts
    assert events(ev, "PROBE_START") and client.states["reviews"]["mode"] == PROBING
    ev = go(fresh, box, 8)                                                          # the probe period ends
    assert events(ev, "RELEASE") and "reviews" not in client.states
    assert client.weights["reviews"] == {"v1": 34, "v2": 33, "v3": 33}


def test_a_reroute_that_expired_while_the_controller_was_down_is_released_on_restart():
    client = FakeClient()
    _, box = reroute(client)
    box["now"] += timedelta(hours=2)
    fresh, _ = make(client, box=box, max_reroute_s=3600)
    fresh.reconcile()
    rel = events(fresh.audit.events, "RELEASE")
    assert rel and rel[0]["why"] == "expired_on_restart" and not fresh.active
    assert client.weights["reviews"] == {"v1": 34, "v2": 33, "v3": 33} and client.states == {}


def test_state_the_current_playbook_does_not_cover_is_released_to_the_recorded_normal_weights():
    client = FakeClient()
    client.weights["reviews"] = {"v1": 100, "v2": 0, "v3": 0}
    client.states["reviews"] = {"version": 1, "culprit": "details", "virtual_service": "reviews", "mode": REROUTED,
                                "target_subset": "v1", "normal_weights": {"v1": 50, "v2": 50},
                                "started": T0.isoformat(), "since": T0.isoformat()}
    fresh, _ = make(client)
    fresh.reconcile()
    rel = events(fresh.audit.events, "RELEASE")
    assert rel and "no_confirmed_playbook_entry" in rel[0]["why"]
    assert client.weights["reviews"] == {"v1": 50, "v2": 50} and client.states == {}


def test_corrupt_or_incomplete_state_is_reported_and_left_for_a_human():
    client = FakeClient()
    client.states["a"] = {"_error": "unparseable"}
    client.states["b"] = {"culprit": "ratings"}                                      # no timestamps
    client.states["c"] = {"version": 1, "culprit": "x", "started": T0.isoformat(), "since": T0.isoformat(),
                          "normal_weights": {"v1": 60}}                              # weights do not sum to 100
    fresh, _ = make(client)
    fresh.reconcile()
    assert len(events(fresh.audit.events, "RECONCILE_ORPHAN")) == 3
    assert client.calls == [] and len(client.states) == 3


def test_reconcile_does_not_write_while_paused():
    client = FakeClient()
    _, box = reroute(client)
    box["now"] += timedelta(hours=2)
    client.paused = True
    fresh, _ = make(client, box=box, max_reroute_s=3600)
    n = len(client.calls)
    fresh.reconcile()
    assert len(client.calls) == n and "reviews" in client.states


def test_a_running_reroute_is_released_when_it_gets_too_old():
    client = FakeClient()
    ctrl, box = reroute(client, max_reroute_s=200)
    ev = go(ctrl, box, 14, ratings_ms=150)                                          # 210 s later, still faulty
    rel = [e for e in events(ev, "RELEASE") if e.get("why") == "expired"]
    assert rel and "reviews" not in client.states and "ratings" not in ctrl.active


# --------------------------------------------------------------------------------------------- the real client
def vs():
    return {"metadata": {"name": "reviews", "resourceVersion": "5", "annotations": {"other": "keep"}},
            "spec": {"hosts": ["reviews"], "http": [{"route": [
                {"destination": {"host": "reviews", "subset": s}, "weight": w} for s, w in (("v1", 34), ("v2", 33), ("v3", 33))]}]}}


def kube():
    c = KubeClient.__new__(KubeClient)
    c.ns, c.custom, c.core = "aws-us-east", MagicMock(), MagicMock()
    c.app_label, c.version_label = "app", "version"
    return c


def test_weights_and_state_are_written_in_one_replace_call_and_other_annotations_survive():
    c = kube()
    c.custom.get_namespaced_custom_object.return_value = vs()
    state = {"culprit": "ratings", "mode": REROUTED}
    c.set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0}, state=state)
    c.custom.replace_namespaced_custom_object.assert_called_once()
    body = c.custom.replace_namespaced_custom_object.call_args.args[5]
    assert body["spec"]["http"][0]["route"][0]["weight"] == 100
    assert json.loads(body["metadata"]["annotations"]["meshheal.io/state"]) == state
    assert body["metadata"]["annotations"]["other"] == "keep" and body["metadata"]["resourceVersion"] == "5"


def test_state_none_removes_the_annotation_and_keep_leaves_it():
    marked = vs()
    marked["metadata"]["annotations"]["meshheal.io/state"] = '{"culprit": "ratings"}'
    assert "meshheal.io/state" not in apply_state(marked, "meshheal.io/state", None)["metadata"]["annotations"]
    assert apply_state(marked, "meshheal.io/state", KEEP) is marked
    only = vs()
    only["metadata"]["annotations"] = {"meshheal.io/state": "{}"}
    assert "annotations" not in apply_state(only, "meshheal.io/state", None)["metadata"]
    assert read_state(vs(), "meshheal.io/state") is None
    assert read_state(marked, "meshheal.io/state") == {"culprit": "ratings"}


def test_list_states_returns_marked_virtual_services_including_corrupt_ones():
    good, bad, plain = vs(), vs(), vs()
    good["metadata"]["annotations"]["meshheal.io/state"] = '{"culprit": "ratings"}'
    bad["metadata"]["name"], bad["metadata"]["annotations"]["meshheal.io/state"] = "b", "{not json"
    plain["metadata"]["name"] = "p"
    c = kube()
    c.custom.list_namespaced_custom_object.return_value = {"items": [good, bad, plain]}
    got = c.list_states()
    assert got["reviews"] == {"culprit": "ratings"} and got["b"] == {"_error": "unparseable"} and "p" not in got


def test_pause_flag_comes_from_the_control_configmap_and_unreadable_means_error():
    c = kube()
    c.core.read_namespaced_config_map.return_value = MagicMock(data={"paused": "True"})
    assert c.is_paused() is True
    c.core.read_namespaced_config_map.return_value = MagicMock(data={"paused": "false"})
    assert c.is_paused() is False
    c.core.read_namespaced_config_map.return_value = MagicMock(data=None)
    assert c.is_paused() is False
    c.core.read_namespaced_config_map.side_effect = ApiException(status=404)
    assert c.is_paused() is False                                                   # no ConfigMap = not paused
    c.core.read_namespaced_config_map.side_effect = ApiException(status=500)
    with pytest.raises(ApiException):
        c.is_paused()                                                                # the controller then fails closed


def test_refused_write_with_state_still_raises_cluster_error_and_writes_nothing():
    c = kube()
    two = vs()
    two["spec"]["http"].append(json.loads(json.dumps(two["spec"]["http"][0])))
    c.custom.get_namespaced_custom_object.return_value = two
    with pytest.raises(ClusterError):
        c.set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0}, state={"x": 1})
    c.custom.replace_namespaced_custom_object.assert_not_called()


# --------------------------------------------------------------------------------------------- health / metrics
def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_healthz_and_metrics_over_http():
    clock = {"t": 1000.0}
    ctrl, box = reroute()
    h = Health(ctrl, interval_s=15, clock=lambda: clock["t"], grace_s=60)
    server, _ = start_server(h, 0, host="127.0.0.1")
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert get(base + "/healthz")[0] == 200                                     # still inside the start-up grace period
        clock["t"] += 100
        assert get(base + "/healthz")[0] == 503                                     # never completed a loop
        h.loop_done(True)
        assert get(base + "/healthz")[0] == 200
        clock["t"] += 200
        assert get(base + "/healthz")[0] == 503                                     # stalled
        h.loop_done(False)
        status, text = get(base + "/metrics")
        assert status == 200 and "meshheal_loops_total 2" in text and "meshheal_loop_errors_total 1" in text
        assert "meshheal_active_reroutes 1" in text and "meshheal_paused 0" in text and "meshheal_shadow_mode 0" in text
        assert 'meshheal_events_total{event="REROUTE"} 1' in text and 'meshheal_events_total{event="SCORED"}' in text
        assert get(base + "/nope")[0] == 404
    finally:
        server.shutdown()


# --------------------------------------------------------------------------------------------- files that cannot grow forever
def test_audit_log_rotates_and_counts(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    a = AuditLog(path, max_bytes=300)
    for i in range(12):
        a.write(T0, "SCORED", i=i, pad="x" * 40)
    assert os.path.exists(path + ".1") and os.path.getsize(path) < 600
    assert a.counts["SCORED"] == 12 and len(a.events) == 12
    assert AuditLog(str(tmp_path / "unbounded.jsonl"), max_bytes=0).write(T0, "X")["event"] == "X"


def test_collector_output_rotates(tmp_path):
    out = str(tmp_path / "snaps.jsonl")
    snap = {"timestamp": "t", "nodes": [], "edges": [], "skipped_edges": 0}
    for _ in range(30):
        collect.append_snapshot(out, snap, max_bytes=200)
    assert os.path.exists(out + ".1") and os.path.getsize(out) <= 400
    collect.append_snapshot(out, snap)                                              # no limit: plain append still works


def test_new_settings_load_from_a_config_file(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("max_actions_per_hour: 2\nmax_reroute_s: 120\ncontrol_configmap: my-control\n", encoding="utf-8")
    cfg = Config.from_file(str(f))
    assert (cfg.max_actions_per_hour, cfg.max_reroute_s, cfg.control_configmap) == (2, 120, "my-control")
    d = Config()
    assert (d.max_actions_per_hour, d.max_reroute_s, d.state_annotation) == (6, 3600.0, "meshheal.io/state")


# --------------------------------------------------------------------------------------------- the chart must be runnable
def test_chart_snapshot_path_is_one_file_and_not_a_protected_data_file_name():
    """Regression: the first live install crash-looped because the chart used /data/snapshots.jsonl and the collector
    refuses that name. Read the chart text, since no helm is needed for this."""
    import re
    path = os.path.join(os.path.dirname(__file__), "..", "..", "deploy", "helm", "meshheal", "templates", "deployment.yaml")
    text = open(path, encoding="utf-8").read()
    out = re.search(r"--out=(\S+)", text).group(1)
    snap = re.search(r"--snapshots=(\S+)", text).group(1)
    assert out == snap                                                    # the controller reads what the collector writes
    assert os.path.basename(out) not in collect.PROTECTED


def test_audit_events_can_also_go_to_stdout_for_container_logs(tmp_path, capsys):
    a = AuditLog(str(tmp_path / "a.jsonl"), echo=True)
    a.write(T0, "SCORED", top="ratings", risk=0.9)
    line = json.loads(capsys.readouterr().out.strip())
    assert line["event"] == "SCORED" and line["top"] == "ratings"
    AuditLog(None).write(T0, "QUIET")
    assert capsys.readouterr().out == ""                                            # off by default
    assert Config().audit_stdout is False and Config.from_file.__name__ == "from_file"
