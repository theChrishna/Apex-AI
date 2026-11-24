import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from topo import generate  # noqa: E402

ARGS = ["--seed", "3", "--families", "chain", "star", "--per-family", "1", "--min-nodes", "4", "--max-nodes", "8",
        "--normal", "4", "--episodes", "2", "--steady", "3"]


def test_generates_labelled_snapshots_and_topology_file(tmp_path, capsys):
    out = tmp_path / "sim.jsonl"
    generate.main(["--out", str(out)] + ARGS)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 * (4 + 2 * 3)                                   # 2 topologies x (normal + episodes x steady)
    assert {r["phase"] for r in rows} == {"normal", "steady"}
    for r in rows:
        assert {"timestamp", "nodes", "edges", "labels", "topology", "family"} <= set(r)
        assert sum(r["labels"].values()) == (1 if r["phase"] == "steady" else 0)
        assert all({"source", "destination", "request_rate", "error_rate", "latency_p95"} <= set(e) for e in r["edges"])
    meta = json.loads((tmp_path / "sim.jsonl.topologies.json").read_text(encoding="utf-8"))
    assert meta["synthetic"] is True and len(meta["topologies"]) == 2
    assert "SYNTHETIC" in capsys.readouterr().out


def test_same_seed_gives_identical_files_and_never_overwrites(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    generate.main(["--out", str(a)] + ARGS)
    generate.main(["--out", str(b)] + ARGS)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        generate.main(["--out", str(a)] + ARGS)                            # exists
    with pytest.raises(SystemExit):
        generate.main(["--out", str(tmp_path / "snapshots.jsonl")] + ARGS)  # protected name
    with pytest.raises(SystemExit):
        generate.main(["--out", str(tmp_path / "c.jsonl"), "--min-nodes", "2"])
