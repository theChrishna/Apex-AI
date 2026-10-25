"""What the controller may do for each culprit. Everything else is ACTION_BLOCKED.

Bookinfo: reviews v2/v3 call ratings, v1 does not. So when ratings is the culprit, sending all
reviews traffic to v1 bypasses it. productpage/details are single-version: nothing to reroute to.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Reroute:
    culprit: str                 # node whose degradation triggers this plan
    virtual_service: str         # Istio VirtualService to patch
    target_subset: str           # subset that receives the traffic
    normal_weights: tuple        # ((subset, weight), ...) restored on release
    reason: str


PLAYBOOK = {
    "ratings": Reroute(
        culprit="ratings", virtual_service="reviews", target_subset="v1",
        normal_weights=(("v1", 34), ("v2", 33), ("v3", 33)),
        reason="reviews-v1 does not call ratings",
    ),
}

# service/version -> services it calls (used for the circular / dependency-on-culprit check)
DEPENDS = {
    ("productpage", "*"): ("details", "reviews"),
    ("details", "*"): (),
    ("reviews", "v1"): (),
    ("reviews", "v2"): ("ratings",),
    ("reviews", "v3"): ("ratings",),
    ("ratings", "*"): (),
}


def deps_of(service, subset):
    return DEPENDS.get((service, subset), DEPENDS.get((service, "*"), ()))


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
