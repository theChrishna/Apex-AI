import pytest

from controlplane.playbook import DEFAULT_PATH, Playbook
from controlplane.playbook_gen import equal_split, generate, to_yaml

V = lambda *names: {n: {"version": n} for n in names}       # noqa: E731  subsets whose label is version=<name>

BOOKINFO_SUBSETS = {"reviews": V("v1", "v2", "v3")}
BOOKINFO_CALLS = {("productpage", "v1"): {"details", "reviews"}, ("reviews", "v2"): {"ratings"},
                  ("reviews", "v3"): {"ratings"}}
BOOKINFO_RATES = {("reviews", "v1"): 0.09, ("reviews", "v2"): 0.09, ("reviews", "v3"): 0.09}
NORMAL = {"reviews": {"v1": 34, "v2": 33, "v3": 33}}


def gen(subsets=BOOKINFO_SUBSETS, weights=NORMAL, calls=BOOKINFO_CALLS, rates=BOOKINFO_RATES):
    return generate(subsets, weights, calls, rates)


def test_rediscovers_the_hand_written_bookinfo_reroute_but_unconfirmed():
    pb, notes = gen()
    mine, hand = pb.reroutes["ratings"], Playbook.from_file(DEFAULT_PATH).reroutes["ratings"]
    assert (mine.virtual_service, mine.target_subset, mine.normal_weights) == \
           (hand.virtual_service, hand.target_subset, hand.normal_weights)
    assert mine.confirmed is False and hand.confirmed is True
    assert "CHECK THIS" in mine.reason
    assert list(pb.reroutes) == ["ratings"]


def test_dependencies_are_filled_from_metrics():
    pb, _ = gen()
    assert pb.deps_of("reviews", "v1") == () and pb.deps_of("reviews", "v2") == ("ratings",)
    assert pb.deps_of("productpage", "v1") == ("details", "reviews")   # unversioned service -> "*" fallback


def test_live_reroute_weights_are_not_recorded_as_the_normal_state():
    pb, _ = gen(weights={"reviews": {"v1": 100, "v2": 0, "v3": 0}})
    assert dict(pb.reroutes["ratings"].normal_weights) == {"v1": 34, "v2": 33, "v3": 33}


def test_idle_candidate_is_not_proposed():
    pb, notes = gen(rates={("reviews", "v1"): 0.0, ("reviews", "v2"): 0.09, ("reviews", "v3"): 0.09})
    assert not pb.reroutes and any("no subset of reviews is a candidate" in n for n in notes)


def test_indirect_dependency_on_the_culprit_disqualifies_a_subset():
    calls = dict(BOOKINFO_CALLS)
    calls[("reviews", "v1")] = {"cache"}
    calls[("cache", "v1")] = {"ratings"}                 # v1 reaches ratings through cache
    pb, _ = gen(calls=calls)
    assert "ratings" not in pb.reroutes


def test_no_virtualservice_or_ambiguous_route_proposes_nothing():
    pb, notes = gen(weights={})
    assert not pb.reroutes and any("no VirtualService" in n for n in notes)
    pb, notes = gen(weights={"reviews": None})
    assert not pb.reroutes and any("catch-all" in n for n in notes)


def test_single_subset_services_are_skipped_and_one_reroute_per_culprit():
    pb, _ = gen(subsets={"reviews": V("v1")})
    assert not pb.reroutes
    subsets = {"a": V("v1", "v2"), "b": V("v1", "v2")}
    calls = {("a", "v2"): {"db"}, ("b", "v2"): {"db"}}
    rates = {("a", "v1"): 1.0, ("a", "v2"): 1.0, ("b", "v1"): 1.0, ("b", "v2"): 1.0}
    pb, notes = generate(subsets, {"a": {"v1": 50, "v2": 50}, "b": {"v1": 50, "v2": 50}}, calls, rates)
    assert pb.reroutes["db"].virtual_service == "a" and any("also reachable" in n for n in notes)


def test_subset_names_are_mapped_to_versions_through_the_destination_rule_labels():
    subsets = {"reviews": {"stable": {"version": "v1"}, "canary": {"version": "v2"}}}
    calls = {("reviews", "v2"): {"ratings"}}
    pb, _ = generate(subsets, {"reviews": {"stable": 90, "canary": 10}}, calls,
                     {("reviews", "v1"): 1.0, ("reviews", "v2"): 0.1})
    assert pb.reroutes["ratings"].target_subset == "stable"
    assert pb.deps_of("reviews", "canary") == ("ratings",)


def test_yaml_output_is_loadable_unconfirmed_and_says_so():
    pb, _ = gen()
    text = to_yaml(pb)
    assert text.startswith("# DRAFT playbook")
    import yaml
    again = Playbook.from_dict(yaml.safe_load(text))
    assert again.reroutes["ratings"].confirmed is False
    assert again.reroutes["ratings"].normal_weights == (("v1", 34), ("v2", 33), ("v3", 33))


@pytest.mark.parametrize("n", [1, 2, 3, 7, 10])
def test_equal_split_always_sums_to_100(n):
    w = equal_split([f"s{i}" for i in range(n)])
    assert sum(w.values()) == 100 and len(w) == n
