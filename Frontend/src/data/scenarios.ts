import { ScenarioMeta } from './types';

export const SCENARIOS: ScenarioMeta[] = [
  {
    id: "A",
    name: "ratings +200ms: reroute applied",
    description: "Injected fault at ratings (t=120s). Latency ramps up, risk crosses 0.85. Safety checks pass, rerouting reviews traffic to reviews-v1 (bypassing ratings). Fault cleared at t=420s with recovery.",
    duration: 600,
    faultWindow: {
      start: 120,
      end: 420,
      node: "ratings",
      description: "ratings injected delay +200ms"
    }
  },
  {
    id: "B",
    name: "details +100ms: blocked",
    description: "Injected fault at details (t=120s). Latency ramps up, risk crosses 0.85. Remediation is safely BLOCKED because details has no redundant replica or alternative path.",
    duration: 600,
    faultWindow: {
      start: 120,
      end: 420,
      node: "details",
      description: "details injected delay +100ms"
    }
  },
  {
    id: "C",
    name: "reviews +200ms: cascade",
    description: "Internal delay on reviews (t=120s). productpage inherits latency. Culprit analysis identifies reviews (high incoming, normal outgoing). Action blocked due to no healthy alternative.",
    duration: 600,
    faultWindow: {
      start: 120,
      end: 420,
      node: "reviews",
      description: "reviews internal delay +200ms (cascade)"
    }
  },
  {
    id: "D",
    name: "GNN down mid-run",
    description: "GNN predictor crashes/times out at t=200s (>500ms timeout). Rule engine engages fallback static threshold (FR-4.1). Amber banner alerts operator; telemetry continues.",
    duration: 600,
    faultWindow: {
      start: 240,
      end: 480,
      node: "ratings",
      description: "ratings delay +200ms during GNN fallback"
    }
  },
  {
    id: "E",
    name: "flapping near threshold",
    description: "Oscillating risk near 0.85 threshold. Safety checks enforce hysteresis and 120s cooldown window, blocking flapping actions and preventing control loop thrashing.",
    duration: 600,
    faultWindow: {
      start: 120,
      end: 400,
      node: "ratings",
      description: "flapping disturbance ±25ms around threshold"
    }
  }
];
