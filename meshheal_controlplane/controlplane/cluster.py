"""Cluster access. FakeClient for tests/replay, KubeClient for the real cluster, DryRunClient wrapper."""


class FakeClient:
    def __init__(self, ready=None):
        self.ready = ready or {}          # (service, subset) -> bool; default True
        self.weights = {}                 # virtual_service -> {subset: weight}
        self.calls = []

    def subset_ready(self, service, subset):
        return self.ready.get((service, subset), True)

    def set_weights(self, virtual_service, weights):
        self.weights[virtual_service] = dict(weights)
        self.calls.append((virtual_service, dict(weights)))


class KubeClient:
    GROUP, VERSION, PLURAL = "networking.istio.io", "v1", "virtualservices"

    def __init__(self, namespace):
        from kubernetes import client, config   # lazy: not needed for tests/replay
        try:
            config.load_kube_config()
        except Exception:
            config.load_incluster_config()
        self.ns = namespace
        self.core = client.CoreV1Api()
        self.custom = client.CustomObjectsApi()

    def subset_ready(self, service, subset):
        pods = self.core.list_namespaced_pod(
            self.ns, label_selector=f"app={service},version={subset}").items
        for p in pods:
            if p.status.phase == "Running" and p.status.container_statuses and \
               all(cs.ready for cs in p.status.container_statuses) and not p.metadata.deletion_timestamp:
                return True
        return False

    def set_weights(self, virtual_service, weights):
        route = [{"destination": {"host": virtual_service, "subset": s}, "weight": w}
                 for s, w in weights.items() if w > 0]
        body = {"spec": {"http": [{"route": route}]}}
        self.custom.patch_namespaced_custom_object(
            self.GROUP, self.VERSION, self.ns, self.PLURAL, virtual_service, body)


class DryRunClient:
    """Reads are real, writes are only logged. The controller behaves as if the write succeeded."""

    def __init__(self, inner, log=print):
        self.inner, self.log, self.calls = inner, log, []

    def subset_ready(self, service, subset):
        return self.inner.subset_ready(service, subset)

    def set_weights(self, virtual_service, weights):
        self.calls.append((virtual_service, dict(weights)))
        self.log(f"[dry-run] would set {virtual_service} weights {weights}")
