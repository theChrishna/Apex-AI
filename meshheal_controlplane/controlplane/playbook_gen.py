"""Draft a playbook from what the mesh is doing. Read-only: it reads DestinationRules, VirtualServices and
Prometheus, and writes a YAML file. It never changes the cluster.

  python -m controlplane.playbook_gen --namespace shop --out playbooks/shop.yaml

Every reroute it proposes has `confirmed: false`, and the controller refuses unconfirmed plans. Read each one,
check it against how the application really works, then change it to `confirmed: true` yourself.

What it infers, and what it cannot know:
  * A subset is proposed as a bypass for culprit C when, in the metrics window, it received traffic and never
    called C (directly or through a service that calls C) while another subset of the same service did call C.
  * "Never called" is only evidence. A rarely used code path or a version that got little traffic looks identical
    to a version that cannot call C. That is why a human must confirm.
"""
import argparse
import os
import sys

from .cluster import KubeClient, catch_all_weights
from .discovery import discover_version_calls, discover_version_rates, prom_query_fn
from .playbook import Playbook, Reroute


def equal_split(subsets):
    names = list(subsets)
    each, rem = divmod(100, len(names))
    return {n: each + (1 if i < rem else 0) for i, n in enumerate(names)}


def _normal_weights(current, subsets):
    """The weights to restore on release. Live weights are used only when they look like a normal split (every
    subset present and above zero, summing to 100): during a reroute they would record the emergency state."""
    if current and set(current) == set(subsets) and all(w > 0 for w in current.values()) and sum(current.values()) == 100:
        return dict(current)
    return equal_split(sorted(subsets))


def generate(subsets, weights_now, calls, rates, version_label="version"):
    """Pure function (no I/O) so it can be tested.

    subsets      {service: {subset: pod labels}}      from DestinationRules
    weights_now  {service: {subset: weight} | None}   catch-all route of the VirtualService, if there is one
    calls        {(service, version): {callee}}       from metrics
    rates        {(service, version): req/s}          traffic each version received
    Returns (Playbook, notes).
    """
    notes = []
    sub_ver = {svc: {sub: labels.get(version_label, sub) for sub, labels in subs.items()} for svc, subs in subsets.items()}

    depends = {}
    for (svc, ver), callees in sorted(calls.items()):
        if svc in sub_ver:
            for sub, v in sub_ver[svc].items():
                if v == ver:
                    depends[(svc, sub)] = tuple(sorted(callees))
        else:
            depends[(svc, "*")] = tuple(sorted(set(depends.get((svc, "*"), ())) | callees))
    pb = Playbook([], depends)

    proposals = {}
    for svc in sorted(subsets):
        subs = sub_ver[svc]
        if len(subs) < 2:
            continue
        if svc not in weights_now:
            notes.append(f"{svc}: has subsets {sorted(subs)} but no VirtualService was found; no reroute can be proposed")
            continue
        if weights_now[svc] is None:
            notes.append(f"{svc}: its VirtualService has no single catch-all route, so the controller would refuse "
                         f"to change it; no reroute proposed")
            continue
        callees = set()
        for v in subs.values():
            callees |= calls.get((svc, v), set())
        for culprit in sorted(callees - {svc}):
            callers = [s for s, v in subs.items() if culprit in calls.get((svc, v), set())]
            safe = [s for s, v in subs.items()
                    if rates.get((svc, v), 0.0) > 0 and culprit not in calls.get((svc, v), set())
                    and not any(pb.depends_on(c, culprit) for c in calls.get((svc, v), set()))]
            if not callers or not safe:
                notes.append(f"{svc} -> {culprit}: no subset of {svc} is a candidate bypass "
                             f"(subsets calling it: {sorted(callers) or 'none'}; subsets with traffic that do not: {sorted(safe) or 'none'})")
                continue
            target = sorted(safe, key=lambda s: (-rates[(svc, subs[s])], s))[0]
            reason = (f"draft: subset {target} of {svc} received {rates[(svc, subs[target])]:.2f} req/s and made no calls to "
                      f"{culprit}; subset(s) {', '.join(sorted(callers))} do call it. CHECK THIS before confirming")
            plan = Reroute(culprit=culprit, virtual_service=svc, target_subset=target,
                           normal_weights=tuple(_normal_weights(weights_now.get(svc), subs).items()),
                           reason=reason, confirmed=False)
            if culprit in proposals:
                notes.append(f"{culprit}: also reachable by rerouting {svc}; kept {proposals[culprit].virtual_service} "
                             f"(a playbook has one reroute per culprit)")
                continue
            proposals[culprit] = plan
    return Playbook(proposals.values(), depends), notes


def read_cluster(kube, prom_url, namespace, window):
    """The read-only inputs for generate()."""
    subsets = kube.all_subsets()
    weights = {}
    for vs in kube.list_virtual_services():
        w = catch_all_weights(vs)
        for host in vs.get("spec", {}).get("hosts", []) or []:
            weights.setdefault(host.split(".")[0], w)
    query = prom_query_fn(prom_url)
    calls = discover_version_calls(query, namespace, window)
    rates = discover_version_rates(query, namespace, window)
    return subsets, {s: weights.get(s) for s in subsets if s in weights}, calls, rates


def to_yaml(pb):
    import yaml
    header = ("# DRAFT playbook generated by controlplane.playbook_gen. Nothing here is confirmed.\n"
              "# Read every reroute, check it against how the application really works, then set `confirmed: true`.\n"
              "# The controller refuses reroutes that are not confirmed.\n")
    return header + yaml.safe_dump(pb.to_dict(), sort_keys=False, default_flow_style=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--prometheus-url", default="http://localhost:9090")
    ap.add_argument("--window", default="10m", help="how far back to look for which version calls what")
    ap.add_argument("--app-label", default="app")
    ap.add_argument("--version-label", default="version")
    ap.add_argument("--out", default=None, help="file to write; prints to stdout when omitted")
    ap.add_argument("--force", action="store_true", help="overwrite --out if it exists (may destroy a confirmed playbook)")
    a = ap.parse_args(argv)
    if a.out and os.path.exists(a.out) and not a.force:
        ap.error(f"{a.out} exists; it may hold confirmed plans. Choose another name or pass --force")
    kube = KubeClient(a.namespace, a.app_label, a.version_label)
    pb, notes = generate(*read_cluster(kube, a.prometheus_url, a.namespace, a.window), version_label=a.version_label)
    text = to_yaml(pb)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {a.out}: {len(pb.reroutes)} draft reroute(s), all unconfirmed", file=sys.stderr)
    else:
        print(text)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
