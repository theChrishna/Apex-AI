from dataclasses import dataclass, fields


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
    # Services that must be present in every snapshot, else the snapshot is rejected. The default is the
    # Bookinfo demo (kept for backward compatibility); set `expected_nodes: []` in a config file to accept any mesh.
    expected_nodes: tuple = ("productpage", "details", "reviews", "ratings")
    prometheus_url: str = "http://localhost:9090"
    app_label: str = "app"              # pod label holding the service name
    version_label: str = "version"      # pod label holding the version/subset (fallback when no DestinationRule)
    playbook_path: str = None           # YAML playbook; None = playbooks/bookinfo.yaml
    # --- Phase 5 safety settings
    max_actions_per_hour: int = 6       # new REROUTEs allowed per rolling hour (stops flapping); 0 = unlimited
    max_reroute_s: float = 3600.0       # a reroute older than this is released automatically; 0 = never
    control_configmap: str = "meshheal-control"   # ConfigMap in the namespace; data paused: "true" freezes ALL writes
    state_annotation: str = "meshheal.io/state"   # VirtualService annotation that records an active reroute
    audit_stdout: bool = False          # also print every audit event as one JSON line (what a container needs for kubectl logs)

    @classmethod
    def from_file(cls, path, **overrides):
        """Load a YAML file whose keys are Config field names. Unknown keys are an error (typos matter here)."""
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a mapping of setting -> value")
        data.update({k: v for k, v in overrides.items() if v is not None})
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"{path}: unknown setting(s) {', '.join(unknown)}; valid: {', '.join(sorted(known))}")
        if "expected_nodes" in data:
            data["expected_nodes"] = tuple(data["expected_nodes"] or ())
        return cls(**data)
