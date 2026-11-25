import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from dashboard.agent import Agent, Tail  # noqa: E402
from dashboard.server import Fleet, serve  # noqa: E402
from dashboard.store import Store  # noqa: E402
from dashboard.tokens import Tokens, digest  # noqa: E402

NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)


def snap(ts, slow=None, services=("web", "cart", "db")):
    a, b, c = services
    lat = lambda svc, base: base + (200 if svc == slow else 0)          # noqa: E731
    return {"timestamp": ts.isoformat(), "nodes": [{"id": s} for s in services],
            "edges": [{"source": a, "destination": b, "request_rate": 2.0, "error_rate": 0.0, "latency_p95": lat(b, 10) + lat(c, 0) - (0 if slow != c else 0)},
                      {"source": b, "destination": c, "request_rate": 2.0, "error_rate": 0.0, "latency_p95": lat(c, 5)}]}


@pytest.fixture()
def api(tmp_path):
    t = Tokens()
    read = t.add_read("dash")
    ing_a = t.add_ingest("shop-eu")
    ing_b = t.add_ingest("bank-us")
    store = Store(str(tmp_path / "fleet.db"))
    fleet = Fleet(store, t, clock=lambda: NOW)
    srv = serve(fleet, 0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield {"base": base, "read": read, "a": ing_a, "b": ing_b, "store": store, "tokens": t, "fleet": fleet}
    srv.shutdown()


def call(base, path, token=None, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_tokens_are_stored_as_hashes_and_scoped():
    t = Tokens()
    r, i = t.add_read("x"), t.add_ingest("shop-eu")
    assert r not in json.dumps(t.data) and i not in json.dumps(t.data)
    assert t.data["read"]["x"] == digest(r)
    assert t.can_read(r) and not t.can_read(i) and not t.can_read("") and not t.can_read(None)
    assert t.ingest_cluster(i) == "shop-eu" and t.ingest_cluster(r) is None
    with pytest.raises(ValueError):
        t.add_ingest("Bad Name")


def test_health_needs_no_token_but_everything_else_does(api):
    assert call(api["base"], "/api/v1/health") == (200, {"ok": True})
    assert call(api["base"], "/api/v1/clusters")[0] == 401
    assert call(api["base"], "/api/v1/clusters", api["a"])[0] == 403            # an ingest token cannot read
    assert call(api["base"], "/api/v1/clusters", "made-up")[0] == 403


def test_an_ingest_token_may_only_push_for_its_own_cluster(api):
    s = [snap(NOW)]
    assert call(api["base"], "/api/v1/ingest/shop-eu/snapshots", api["a"], s)[0] == 200
    assert call(api["base"], "/api/v1/ingest/bank-us/snapshots", api["a"], s)[0] == 403
    assert call(api["base"], "/api/v1/ingest/shop-eu/snapshots", api["read"], s)[0] == 403   # a read token cannot push
    assert call(api["base"], "/api/v1/ingest/shop-eu/snapshots", None, s)[0] == 401


def test_pushed_data_is_validated_and_duplicates_ignored(api):
    good, bad = snap(NOW), {"timestamp": NOW.isoformat(), "nodes": [], "edges": [{"source": "a", "destination": "b",
                                                                                   "request_rate": 1.0, "error_rate": 0.0, "latency_p95": "x"}]}
    code, r = call(api["base"], "/api/v1/ingest/shop-eu/snapshots", api["a"], [good, bad, {"no": "timestamp"}])
    assert code == 200 and r == {"accepted": 1, "new": 1, "rejected": 2}
    assert call(api["base"], "/api/v1/ingest/shop-eu/snapshots", api["a"], [good])[1]["new"] == 0   # resent: ignored
    assert call(api["base"], "/api/v1/ingest/shop-eu/snapshots", api["a"], {"not": "a list"})[0] == 400
    assert call(api["base"], "/api/v1/ingest/shop-eu/snapshots", api["a"], [good] * 501)[0] == 413
    assert call(api["base"], "/api/v1/ingest/BAD!/snapshots", api["a"], [good])[0] in (400, 404)


def test_state_works_for_any_mesh_and_keeps_clusters_apart(api):
    b = api["base"]
    for i in range(6):
        t = NOW - timedelta(seconds=15 * (5 - i))
        call(b, "/api/v1/ingest/shop-eu/snapshots", api["a"], [snap(t, slow="db" if i >= 3 else None)])
        call(b, "/api/v1/ingest/bank-us/snapshots", api["b"], [snap(t, services=("gateway", "ledger", "vault"))])
    call(b, "/api/v1/ingest/shop-eu/events", api["a"], [
        {"ts": (NOW - timedelta(seconds=20)).isoformat(), "event": "SCORED", "top": "db", "risk": 1.0, "dry_run": True},
        {"ts": (NOW - timedelta(seconds=10)).isoformat(), "event": "REROUTE", "culprit": "db", "dry_run": True}])
    code, clusters = call(b, "/api/v1/clusters", api["read"])
    assert code == 200 and [c["name"] for c in clusters] == ["bank-us", "shop-eu"]
    assert all(not c["stale"] for c in clusters)
    code, st = call(b, "/api/v1/clusters/shop-eu/state", api["read"])
    assert code == 200 and st["scorer"] == "rule"
    ids = [n["id"] for n in st["graph"]["nodes"]]
    assert ids == ["cart", "db", "web"]
    top = max(st["graph"]["nodes"], key=lambda n: n["risk"])
    assert top["id"] == "db" and top["risk"] > 0.85                              # the slow service, not its callers
    assert len(st["series"]) == 6 and st["mesh"]["state"] == "REROUTED" and st["controller"]["shadow"] is True
    assert [d["event"] for d in st["decisions"]] == ["REROUTE"]
    _, other = call(b, "/api/v1/clusters/bank-us/state", api["read"])
    assert {n["id"] for n in other["graph"]["nodes"]} == {"gateway", "ledger", "vault"} and other["decisions"] == []
    assert call(b, "/api/v1/clusters/nope/state", api["read"])[0] == 404


def test_a_learned_baseline_is_used_and_named(api, tmp_path):
    f = tmp_path / "b.yaml"
    f.write_text("edges:\n  web>cart: {lat: {median: 10, high: 15}, err: {median: 0, high: 0}}\n"
                 "  cart>db: {lat: {median: 5, high: 8}, err: {median: 0, high: 0}}\n", encoding="utf-8")
    fleet = Fleet(api["store"], api["tokens"], {"shop-eu": str(f)}, clock=lambda: NOW)
    call(api["base"], "/api/v1/ingest/shop-eu/snapshots", api["a"], [snap(NOW, slow="db")])
    st = fleet.state("shop-eu")
    assert st["scorer"] == "edge" and max(st["graph"]["nodes"], key=lambda n: n["risk"])["id"] == "db"


def test_store_prunes_old_data(tmp_path):
    s = Store(str(tmp_path / "f.db"), retention_days=1)
    s.add_snapshots("c", [snap(NOW - timedelta(days=3)), snap(NOW)], now=NOW)
    assert s.prune(now=NOW) == (1, 0) and len(s.snapshots("c")) == 1


def test_tail_reads_only_complete_lines_and_restarts_after_rotation(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b'{"n": 1}\n{"n": 2}\n{"n": 3')                               # last line still being written
    t = Tail(str(p))
    items, off = t.read()
    assert [i["n"] for i in items] == [1, 2]
    t.offset = off
    p.write_bytes(b'{"n": 9}\n')                                                 # rotated: smaller than the offset
    items, _ = t.read()
    assert [i["n"] for i in items] == [9]


def test_agent_pushes_new_lines_resumes_and_keeps_the_offset_on_failure(tmp_path):
    snaps, audit, state = tmp_path / "s.jsonl", tmp_path / "a.jsonl", tmp_path / "state.json"
    snaps.write_text("\n".join(json.dumps(snap(NOW + timedelta(seconds=15 * i))) for i in range(3)) + "\n", encoding="utf-8")
    audit.write_text(json.dumps({"ts": NOW.isoformat(), "event": "SCORED"}) + "\n", encoding="utf-8")
    sent = []
    agent = Agent("http://x", "shop-eu", "tok", str(snaps), str(audit), str(state), post_fn=lambda u, t, items: sent.append((u, len(items))))
    assert agent.once() == {"snapshots": 3, "events": 1}
    assert sent[0][0] == "http://x/api/v1/ingest/shop-eu/snapshots"
    with open(snaps, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap(NOW + timedelta(minutes=5))) + "\n")
    again = Agent("http://x", "shop-eu", "tok", str(snaps), str(audit), str(state), post_fn=lambda u, t, items: sent.append((u, len(items))))
    assert again.once() == {"snapshots": 1, "events": 0}                           # resumed from the saved offset

    def down(*_):
        raise OSError("connection refused")
    with open(snaps, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap(NOW + timedelta(minutes=6))) + "\n")
    failing = Agent("http://x", "shop-eu", "tok", str(snaps), None, str(state), post_fn=down)
    before = failing.tails["snapshots"].offset
    with pytest.raises(OSError):
        failing.once()
    assert failing.tails["snapshots"].offset == before                            # nothing lost: it will be resent


def test_agent_against_the_real_api_end_to_end(api, tmp_path):
    snaps = tmp_path / "s.jsonl"
    snaps.write_text(json.dumps(snap(NOW)) + "\n", encoding="utf-8")
    tok = tmp_path / "tok"
    tok.write_text(api["a"], encoding="utf-8")
    from dashboard import agent as ag
    ag.main(["--url", api["base"], "--cluster", "shop-eu", "--token-file", str(tok), "--snapshots", str(snaps), "--once"])
    assert len(api["store"].snapshots("shop-eu")) == 1
