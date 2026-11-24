import copy
from unittest.mock import MagicMock

import pytest

from controlplane.cluster import ClusterError, DryRunClient, KubeClient, apply_weights

pytest.importorskip("kubernetes")
from kubernetes.client.rest import ApiException  # noqa: E402


def make_client():
    c = KubeClient.__new__(KubeClient)     # skip kube-config loading: no cluster needed
    c.ns, c.custom, c.core = "aws-us-east", MagicMock(), MagicMock()
    c.app_label, c.version_label = "app", "version"
    return c


def vs_bookinfo():
    return {"apiVersion": "networking.istio.io/v1", "kind": "VirtualService",
            "metadata": {"name": "reviews", "resourceVersion": "123"},
            "spec": {"hosts": ["reviews"], "http": [{"route": [
                {"destination": {"host": "reviews", "subset": s}, "weight": w}
                for s, w in (("v1", 34), ("v2", 33), ("v3", 33))]}]}}


def vs_with_extras():
    """Someone else's VirtualService: a header match rule, plus a default rule with retries, timeout and a port."""
    return {"metadata": {"name": "reviews", "resourceVersion": "9", "labels": {"owner": "team-a"}},
            "spec": {"hosts": ["reviews"], "http": [
                {"match": [{"headers": {"end-user": {"exact": "jason"}}}],
                 "route": [{"destination": {"host": "reviews", "subset": "v2"}}]},
                {"retries": {"attempts": 3}, "timeout": "2s",
                 "route": [{"destination": {"host": "reviews", "subset": "v1", "port": {"number": 9080}}, "weight": 50},
                           {"destination": {"host": "reviews", "subset": "v3"}, "weight": 50}]}]}}


def test_set_weights_changes_only_weights_and_sends_resource_version():
    c = make_client()
    c.custom.get_namespaced_custom_object.return_value = vs_bookinfo()
    c.set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0})
    args = c.custom.replace_namespaced_custom_object.call_args.args
    assert args[:5] == ("networking.istio.io", "v1", "aws-us-east", "virtualservices", "reviews")
    body = args[5]
    assert body["metadata"]["resourceVersion"] == "123"          # optimistic concurrency token is carried
    assert body["spec"]["http"][0]["route"] == [{"destination": {"host": "reviews", "subset": "v1"}, "weight": 100}]


def test_zero_weight_subsets_are_left_out_and_probe_split_is_kept():
    c = make_client()
    c.custom.get_namespaced_custom_object.return_value = vs_bookinfo()
    c.set_weights("reviews", {"v1": 70, "v2": 15, "v3": 15})
    route = c.custom.replace_namespaced_custom_object.call_args.args[5]["spec"]["http"][0]["route"]
    assert [(d["destination"]["subset"], d["weight"]) for d in route] == [("v1", 70), ("v2", 15), ("v3", 15)]


def test_other_fields_of_someone_elses_virtualservice_survive():
    vs = vs_with_extras()
    out = apply_weights(vs, "reviews", {"v1": 100, "v3": 0})
    assert out["metadata"] == vs["metadata"]                                  # labels, resourceVersion untouched
    assert out["spec"]["http"][0] == vs["spec"]["http"][0]                    # header-match rule untouched
    default = out["spec"]["http"][1]
    assert default["retries"] == {"attempts": 3} and default["timeout"] == "2s"
    assert default["route"] == [{"destination": {"host": "reviews", "subset": "v1", "port": {"number": 9080}}, "weight": 100}]
    assert vs == vs_with_extras()                                             # input object not mutated


def test_subset_not_yet_in_route_is_added():
    out = apply_weights(vs_with_extras(), "reviews", {"v1": 60, "v2": 40})
    route = out["spec"]["http"][1]["route"]
    assert [(d["destination"]["subset"], d["weight"]) for d in route] == [("v1", 60), ("v2", 40)]


def test_ambiguous_or_missing_catch_all_route_is_refused():
    two = vs_bookinfo()
    two["spec"]["http"].append(copy.deepcopy(two["spec"]["http"][0]))
    with pytest.raises(ClusterError, match="found 2"):
        apply_weights(two, "reviews", {"v1": 100})
    only_match = vs_with_extras()
    del only_match["spec"]["http"][1]
    with pytest.raises(ClusterError, match="found 0"):
        apply_weights(only_match, "reviews", {"v1": 100})
    with pytest.raises(ClusterError, match="not 100"):
        apply_weights(vs_bookinfo(), "reviews", {"v1": 90})


def test_nothing_is_written_when_the_change_is_refused():
    c = make_client()
    two = vs_bookinfo()
    two["spec"]["http"].append(copy.deepcopy(two["spec"]["http"][0]))
    c.custom.get_namespaced_custom_object.return_value = two
    with pytest.raises(ClusterError):
        c.set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0})
    c.custom.replace_namespaced_custom_object.assert_not_called()


def test_conflict_from_the_api_server_becomes_cluster_error():
    c = make_client()
    c.custom.get_namespaced_custom_object.return_value = vs_bookinfo()
    c.custom.replace_namespaced_custom_object.side_effect = ApiException(status=409, reason="Conflict")
    with pytest.raises(ClusterError, match="409"):
        c.set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0})


def test_dry_run_never_writes_but_still_reports_an_unsafe_change():
    inner = make_client()
    inner.custom.get_namespaced_custom_object.return_value = vs_bookinfo()
    logs = []
    DryRunClient(inner, log=logs.append).set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0})
    assert logs and "would set" in logs[0]
    two = vs_bookinfo()
    two["spec"]["http"].append(copy.deepcopy(two["spec"]["http"][0]))
    inner.custom.get_namespaced_custom_object.return_value = two
    with pytest.raises(ClusterError):
        DryRunClient(inner, log=logs.append).set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0})
    inner.custom.replace_namespaced_custom_object.assert_not_called()


def _dr(host, subsets):
    return {"spec": {"host": host, "subsets": [{"name": n, "labels": lab} for n, lab in subsets.items()]}}


def test_subset_labels_come_from_the_destination_rule():
    c = make_client()
    c.custom.list_namespaced_custom_object.return_value = {"items": [
        _dr("reviews", {"stable": {"track": "stable"}}), _dr("ratings", {"v1": {"version": "v1"}})]}
    assert c.list_subsets("reviews") == {"stable": {"track": "stable"}}
    pod = MagicMock()
    pod.status.phase, pod.metadata.deletion_timestamp = "Running", None
    pod.status.container_statuses = [MagicMock(ready=True)]
    c.core.list_namespaced_pod.return_value.items = [pod]
    assert c.subset_ready("reviews", "stable") is True
    assert c.core.list_namespaced_pod.call_args.kwargs["label_selector"] == "app=reviews,track=stable"


def test_subset_selector_falls_back_to_version_label_without_a_destination_rule():
    c = make_client()
    c.custom.list_namespaced_custom_object.return_value = {"items": []}
    c.core.list_namespaced_pod.return_value.items = []
    assert c.subset_ready("reviews", "v2") is False
    assert c.core.list_namespaced_pod.call_args.kwargs["label_selector"] == "app=reviews,version=v2"


def test_installed_kubernetes_client_has_the_calls_we_use():
    from kubernetes.client import CustomObjectsApi
    for name in ("get_namespaced_custom_object", "replace_namespaced_custom_object",
                 "list_namespaced_custom_object"):
        assert hasattr(CustomObjectsApi, name)


def test_virtual_service_name_may_differ_from_the_destination_host():
    vs = vs_bookinfo()
    vs["metadata"]["name"] = "reviews-vs"
    out = apply_weights(vs, "reviews-vs", {"v1": 100, "v2": 0, "v3": 0})
    assert out["spec"]["http"][0]["route"] == [{"destination": {"host": "reviews", "subset": "v1"}, "weight": 100}]
    fq = vs_bookinfo()
    for d in fq["spec"]["http"][0]["route"]:
        d["destination"]["host"] = "reviews.aws-us-east.svc.cluster.local"
    fq["spec"]["hosts"] = ["reviews.aws-us-east.svc.cluster.local"]
    out = apply_weights(fq, "reviews", {"v1": 50, "v2": 50, "v3": 0})
    assert {d["destination"]["host"] for d in out["spec"]["http"][0]["route"]} == {"reviews.aws-us-east.svc.cluster.local"}


def test_catch_all_weights_reads_without_changing():
    from controlplane.cluster import catch_all_weights
    assert catch_all_weights(vs_bookinfo()) == {"v1": 34, "v2": 33, "v3": 33}
    assert catch_all_weights(vs_with_extras()) == {"v1": 50, "v3": 50}
    two = vs_bookinfo()
    two["spec"]["http"].append(copy.deepcopy(two["spec"]["http"][0]))
    assert catch_all_weights(two) is None
