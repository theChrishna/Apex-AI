from unittest.mock import MagicMock

import pytest

from controlplane.cluster import KubeClient


def make_client():
    c = KubeClient.__new__(KubeClient)     # skip kube-config loading: no cluster needed
    c.ns, c.custom, c.core = "aws-us-east", MagicMock(), MagicMock()
    return c


def test_set_weights_sends_json_merge_patch_with_exact_body():
    c = make_client()
    c.set_weights("reviews", {"v1": 100, "v2": 0, "v3": 0})
    c.custom.patch_namespaced_custom_object.assert_called_once_with(
        "networking.istio.io", "v1", "aws-us-east", "virtualservices", "reviews",
        {"spec": {"http": [{"route": [{"destination": {"host": "reviews", "subset": "v1"}, "weight": 100}]}]}},
        _content_type="application/merge-patch+json")


def test_zero_weight_subsets_are_left_out_of_the_route():
    c = make_client()
    c.set_weights("reviews", {"v1": 70, "v2": 15, "v3": 15})
    body = c.custom.patch_namespaced_custom_object.call_args.args[5]
    assert body["spec"]["http"][0]["route"] == [
        {"destination": {"host": "reviews", "subset": s}, "weight": w} for s, w in (("v1", 70), ("v2", 15), ("v3", 15))]


def test_installed_kubernetes_client_accepts_content_type_argument():
    pytest.importorskip("kubernetes")
    import inspect
    from kubernetes.client import CustomObjectsApi
    assert "_content_type" in inspect.signature(CustomObjectsApi.patch_namespaced_custom_object).parameters
