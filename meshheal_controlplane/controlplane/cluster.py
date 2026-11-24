"""Cluster access. FakeClient for tests/replay, KubeClient for the real cluster, DryRunClient wrapper."""
import copy


class ClusterError(Exception):
    """A cluster write could not be done safely. The controller logs it and does not change state."""


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


def _host_names(vs, virtual_service):
    """Names a route destination may use for this VirtualService's service: the VS name, its spec.hosts, and
    the short form of each (so `reviews`, `reviews.ns` and `reviews.ns.svc.cluster.local` all match)."""
    names = {virtual_service}
    for h in vs.get("spec", {}).get("hosts", []) or []:
        names.add(h)
        names.add(h.split(".")[0])
    return names


def default_route_index(http_rules, names):
    """Index of the one http rule this controller may change: the catch-all rule (no `match`) that routes to one
    of `names`. Anything ambiguous raises ClusterError instead of guessing."""
    cands = [i for i, rule in enumerate(http_rules)
             if not rule.get("match") and any(d.get("destination", {}).get("host") in names
                                              for d in rule.get("route", []))]
    if len(cands) != 1:
        raise ClusterError(f"expected exactly one catch-all http route to {sorted(names)}, found {len(cands)}; "
                           f"refusing to change it")
    return cands[0]


def apply_weights(vs, virtual_service, weights):
    """Return a copy of VirtualService object `vs` with only the destination weights changed.

    Everything else in the object (match rules, retries, timeout, fault, ports, other hosts) is kept as it was.
    Subsets with weight 0 are dropped from the route (as before); a subset that has weight but was not in the
    route is added, using the same destination host as the existing route.
    """
    if sum(weights.values()) != 100:
        raise ClusterError(f"weights sum to {sum(weights.values())}, not 100")
    new = copy.deepcopy(vs)
    rules = new.get("spec", {}).get("http", [])
    names = _host_names(new, virtual_service)
    try:
        idx = default_route_index(rules, names)
    except ClusterError as e:
        raise ClusterError(f"VirtualService {virtual_service}: {e}") from None
    current = [d for d in rules[idx]["route"] if d.get("destination", {}).get("host") in names]
    host = current[0]["destination"]["host"]
    old = {d["destination"].get("subset"): d for d in current}
    route = []
    for subset, w in weights.items():
        if w <= 0:
            continue
        dest = copy.deepcopy(old[subset]) if subset in old else {"destination": {"host": host, "subset": subset}}
        dest["weight"] = w
        route.append(dest)
    rules[idx]["route"] = route
    return new


def catch_all_weights(vs):
    """{subset: weight} of the catch-all route, or None when there is not exactly one (read-only helper)."""
    names = _host_names(vs, vs.get("metadata", {}).get("name", ""))
    rules = vs.get("spec", {}).get("http", []) or []
    try:
        idx = default_route_index(rules, names)
    except ClusterError:
        return None
    return {d["destination"].get("subset"): d.get("weight", 0) for d in rules[idx]["route"]
            if d.get("destination", {}).get("host") in names}


class KubeClient:
    GROUP, VERSION = "networking.istio.io", "v1"

    def __init__(self, namespace, app_label="app", version_label="version"):
        from kubernetes import client, config   # lazy: not needed for tests/replay
        try:
            config.load_kube_config()
        except Exception:
            config.load_incluster_config()
        self.ns = namespace
        self.app_label, self.version_label = app_label, version_label
        self.core = client.CoreV1Api()
        self.custom = client.CustomObjectsApi()

    # ---- reads --------------------------------------------------------------------------------
    def all_subsets(self):
        """{service host (short name): {subset: labels}} from every DestinationRule in the namespace."""
        items = self.custom.list_namespaced_custom_object(self.GROUP, self.VERSION, self.ns, "destinationrules")["items"]
        out = {}
        for dr in items:
            host = dr.get("spec", {}).get("host", "").split(".")[0]
            for s in dr.get("spec", {}).get("subsets", []) or []:
                out.setdefault(host, {})[s["name"]] = s.get("labels", {})
        return out

    def list_subsets(self, service):
        """{subset: labels} from the DestinationRule(s) whose host is `service`. {} when there is none."""
        return self.all_subsets().get(service, {})

    def subset_ready(self, service, subset):
        labels = self.list_subsets(service).get(subset) or {self.version_label: subset}
        selector = ",".join([f"{self.app_label}={service}"] + [f"{k}={v}" for k, v in labels.items()])
        pods = self.core.list_namespaced_pod(self.ns, label_selector=selector).items
        for p in pods:
            if p.status.phase == "Running" and p.status.container_statuses and \
               all(cs.ready for cs in p.status.container_statuses) and not p.metadata.deletion_timestamp:
                return True
        return False

    def get_virtual_service(self, name):
        return self.custom.get_namespaced_custom_object(self.GROUP, self.VERSION, self.ns, "virtualservices", name)

    def list_virtual_services(self):
        return self.custom.list_namespaced_custom_object(self.GROUP, self.VERSION, self.ns, "virtualservices")["items"]

    # ---- write --------------------------------------------------------------------------------
    def set_weights(self, virtual_service, weights):
        """Read-modify-write: change only the destination weights of the catch-all route. `replace` carries the
        resourceVersion we read, so if anyone else edited the object meanwhile the API server answers 409 and we
        stop instead of overwriting their change."""
        from kubernetes.client.rest import ApiException
        try:
            current = self.get_virtual_service(virtual_service)
            updated = apply_weights(current, virtual_service, weights)
            self.custom.replace_namespaced_custom_object(
                self.GROUP, self.VERSION, self.ns, "virtualservices", virtual_service, updated)
        except ApiException as e:
            raise ClusterError(f"VirtualService {virtual_service}: HTTP {e.status} {e.reason}") from e


class DryRunClient:
    """Reads are real, writes are only logged. The controller behaves as if the write succeeded."""

    def __init__(self, inner, log=print):
        self.inner, self.log, self.calls = inner, log, []

    def subset_ready(self, service, subset):
        return self.inner.subset_ready(service, subset)

    def set_weights(self, virtual_service, weights):
        getter = getattr(self.inner, "get_virtual_service", None)
        if getter:   # still read-only: check the real object so a dry run reveals a patch that would be refused
            apply_weights(getter(virtual_service), virtual_service, weights)
        self.calls.append((virtual_service, dict(weights)))
        self.log(f"[dry-run] would set {virtual_service} weights {weights}")
