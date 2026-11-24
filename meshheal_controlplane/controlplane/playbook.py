"""What the controller may do for each culprit. Everything else is ACTION_BLOCKED.

A Playbook is loaded from YAML (see playbooks/bookinfo.yaml). Bookinfo: reviews v2/v3 call ratings, v1 does
not, so when ratings is the culprit, sending all reviews traffic to v1 bypasses it. productpage/details are
single-version: nothing to reroute to.
"""
import os
from dataclasses import dataclass

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "playbooks", "bookinfo.yaml")


class PlaybookError(ValueError):
    pass


@dataclass(frozen=True)
class Reroute:
    culprit: str                 # node whose degradation triggers this plan
    virtual_service: str         # Istio VirtualService to patch
    target_subset: str           # subset that receives the traffic
    normal_weights: tuple        # ((subset, weight), ...) restored on release
    reason: str
    confirmed: bool = True       # False = generated draft nobody has checked; the controller refuses it


class Playbook:
    def __init__(self, reroutes=(), depends=None):
        self.reroutes = {r.culprit: r for r in reroutes}
        self.depends = depends or {}      # (service, subset) -> tuple of services it calls

    # ---- loading -------------------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise PlaybookError("playbook must be a mapping with 'reroutes' and 'depends'")
        reroutes = []
        for i, item in enumerate(data.get("reroutes") or []):
            where = f"reroutes[{i}]"
            try:
                weights = item["normal_weights"]
                if not isinstance(weights, dict) or not weights:
                    raise PlaybookError(f"{where}: normal_weights must be a non-empty mapping subset -> percent")
                if any(isinstance(w, bool) or not isinstance(w, int) or w < 0 for w in weights.values()):
                    raise PlaybookError(f"{where}: weights must be non-negative integers")
                if sum(weights.values()) != 100:
                    raise PlaybookError(f"{where}: normal_weights sum to {sum(weights.values())}, not 100")
                target = str(item["target_subset"])
                if target not in weights:
                    raise PlaybookError(f"{where}: target_subset '{target}' is not in normal_weights")
                reroutes.append(Reroute(
                    culprit=str(item["culprit"]), virtual_service=str(item["virtual_service"]),
                    target_subset=target, normal_weights=tuple((str(s), w) for s, w in weights.items()),
                    reason=str(item.get("reason", "")), confirmed=bool(item.get("confirmed", False))))
            except KeyError as e:
                raise PlaybookError(f"{where}: missing field {e}")
        culprits = [r.culprit for r in reroutes]
        dupes = {c for c in culprits if culprits.count(c) > 1}
        if dupes:
            raise PlaybookError(f"more than one reroute for culprit(s): {', '.join(sorted(dupes))}")
        depends = {}
        for svc, by_subset in (data.get("depends") or {}).items():
            if not isinstance(by_subset, dict):
                raise PlaybookError(f"depends.{svc} must map subset -> list of services")
            for subset, calls in by_subset.items():
                depends[(str(svc), str(subset))] = tuple(str(c) for c in (calls or []))
        return cls(reroutes, depends)

    @classmethod
    def from_file(cls, path=DEFAULT_PATH):
        import yaml
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f))

    def to_dict(self):
        out = {"reroutes": [], "depends": {}}
        for r in self.reroutes.values():
            out["reroutes"].append({
                "culprit": r.culprit, "virtual_service": r.virtual_service, "target_subset": r.target_subset,
                "normal_weights": dict(r.normal_weights), "reason": r.reason, "confirmed": r.confirmed})
        for (svc, subset), calls in self.depends.items():
            out["depends"].setdefault(svc, {})[subset] = list(calls)
        return out

    # ---- queries -------------------------------------------------------------------------------
    def deps_of(self, service, subset):
        return self.depends.get((service, subset), self.depends.get((service, "*"), ()))

    def depends_on(self, service, node):
        """True if `service` (any version) calls `node`, directly or through other services."""
        seen, todo = set(), [service]
        while todo:
            svc = todo.pop()
            if svc in seen:
                continue
            seen.add(svc)
            for (name, _), calls in self.depends.items():
                if name == svc:
                    if node in calls:
                        return True
                    todo.extend(calls)
        return False


_default = None


def default_playbook():
    """The Bookinfo playbook, loaded once. Used when no playbook is passed (keeps old call sites working)."""
    global _default
    if _default is None:
        _default = Playbook.from_file(DEFAULT_PATH)
    return _default


def deps_of(service, subset):
    return default_playbook().deps_of(service, subset)


def depends_on(service, node):
    return default_playbook().depends_on(service, node)


def reroute_weights(plan, share_to_others=0):
    """100% to the target subset, or (100-share) to target with `share` spread over the others."""
    others = [s for s, _ in plan.normal_weights if s != plan.target_subset]
    if share_to_others <= 0 or not others:
        return {plan.target_subset: 100, **{s: 0 for s in others}}
    each, rem = divmod(share_to_others, len(others))
    w = {s: each for s in others}
    w[others[0]] += rem
    w[plan.target_subset] = 100 - share_to_others
    return w
