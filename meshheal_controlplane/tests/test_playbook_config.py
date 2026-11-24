import pytest

from controlplane.config import Config
from controlplane.playbook import DEFAULT_PATH, Playbook, PlaybookError, default_playbook, reroute_weights


def good():
    return {"reroutes": [{"culprit": "ratings", "virtual_service": "reviews", "target_subset": "v1",
                          "normal_weights": {"v1": 34, "v2": 33, "v3": 33}, "reason": "r", "confirmed": True}],
            "depends": {"reviews": {"v1": [], "v2": ["ratings"]}, "ratings": {"*": []}}}


def test_bookinfo_yaml_matches_the_original_hardcoded_playbook():
    pb = Playbook.from_file(DEFAULT_PATH)
    r = pb.reroutes["ratings"]
    assert (r.virtual_service, r.target_subset, r.confirmed) == ("reviews", "v1", True)
    assert r.normal_weights == (("v1", 34), ("v2", 33), ("v3", 33))
    assert list(pb.reroutes) == ["ratings"]
    assert pb.deps_of("reviews", "v1") == () and pb.deps_of("reviews", "v2") == ("ratings",)
    assert pb.deps_of("productpage", "anything") == ("details", "reviews")        # "*" fallback
    assert pb.depends_on("productpage", "ratings") and not pb.depends_on("ratings", "reviews")
    assert reroute_weights(r) == {"v1": 100, "v2": 0, "v3": 0}
    assert reroute_weights(r, 30) == {"v2": 15, "v3": 15, "v1": 70}
    assert default_playbook() is default_playbook()


def test_round_trip_through_to_dict():
    pb = Playbook.from_dict(good())
    again = Playbook.from_dict(pb.to_dict())
    assert again.reroutes == pb.reroutes and again.depends == pb.depends


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["reroutes"][0]["normal_weights"].update(v1=50), "not 100"),
    (lambda d: d["reroutes"][0].update(target_subset="v9"), "not in normal_weights"),
    (lambda d: d["reroutes"][0].pop("virtual_service"), "missing field"),
    (lambda d: d["reroutes"][0]["normal_weights"].update(v1=-1, v2=68), "non-negative"),
    (lambda d: d["reroutes"][0].update(normal_weights={}), "non-empty"),
    (lambda d: d["reroutes"].append(dict(d["reroutes"][0])), "more than one reroute"),
    (lambda d: d["depends"].update(reviews=["ratings"]), "must map subset"),
])
def test_invalid_playbooks_are_rejected(mutate, msg):
    d = good()
    mutate(d)
    with pytest.raises(PlaybookError, match=msg):
        Playbook.from_dict(d)


def test_a_plan_is_unconfirmed_unless_the_file_says_so():
    d = good()
    del d["reroutes"][0]["confirmed"]
    assert Playbook.from_dict(d).reroutes["ratings"].confirmed is False


def test_config_file_overrides_defaults_and_cli_wins(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("namespace: shop\nexpected_nodes: []\nact_threshold: 0.7\n", encoding="utf-8")
    cfg = Config.from_file(str(f))
    assert (cfg.namespace, cfg.expected_nodes, cfg.act_threshold) == ("shop", (), 0.7)
    assert cfg.interval_s == 15.0                                     # untouched default
    assert Config.from_file(str(f), namespace="other", audit_path=None).namespace == "other"


def test_config_file_with_a_typo_is_an_error(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("namepsace: shop\n", encoding="utf-8")
    with pytest.raises(ValueError, match="namepsace"):
        Config.from_file(str(f))


def test_default_config_is_unchanged_for_bookinfo():
    cfg = Config()
    assert cfg.namespace == "aws-us-east" and cfg.expected_nodes == ("productpage", "details", "reviews", "ratings")
