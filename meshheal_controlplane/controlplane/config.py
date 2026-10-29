from dataclasses import dataclass


@dataclass
class Config:
    interval_s: float = 15.0            # loop period
    max_snapshot_age_s: float = 45.0    # FR-2.4: reject stale snapshots
    act_threshold: float = 0.85         # risk needed to act
    release_threshold: float = 0.60     # risk must fall below this to release
    persist_window: int = 4             # persistence rule: 3 of last 4
    persist_required: int = 3
    cooldown_s: float = 120.0           # min time in REROUTED before probing / between actions
    probe_s: float = 90.0               # probe length (>= Prometheus 1-min rate window)
    # % of traffic sent back to the suspect path while probing (70/15/15). Evidence arithmetic: reviews gets
    # ~0.27 req/s, so 30% reaches ratings at ~0.08 req/s >= min_evidence_rate 0.05. At 10% it was ~0.027 req/s,
    # below the minimum, so a closed-loop probe would end PROBE_FAILED (no_evidence) and RELEASE could never fire.
    probe_share: int = 30
    min_evidence_rate: float = 0.05     # req/s into the node needed to trust its risk while probing
    self_lat_full_ms: float = 100.0     # rule scorer: self-latency (ms) that maps to risk 1.0
    scorer_timeout_s: float = 0.5       # FR-4.1: primary scorer budget before falling back
    blocked_relog_s: float = 60.0       # don't spam identical ACTION_BLOCKED lines
    namespace: str = "aws-us-east"
    audit_path: str = "audit_log.jsonl"
    expected_nodes: tuple = ("productpage", "details", "reviews", "ratings")
