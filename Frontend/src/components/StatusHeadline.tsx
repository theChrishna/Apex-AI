import React from 'react';
import { useStore } from '../store';

export const StatusHeadline: React.FC = () => {
  const { scenarioId, t } = useStore();

  let headline = 'All services healthy';
  let subtitle = `Steady state telemetry active at t=${Math.round(t)}s`;

  if (scenarioId === 'A') {
    if (t >= 120 && t < 180) {
      headline = 'ratings is slowing down';
      subtitle = `Injected delay +200ms active; risk approaching 0.85 act threshold at t=${Math.round(t)}s`;
    } else if (t >= 180 && t < 420) {
      headline = 'Traffic rerouted around ratings';
      subtitle = 'Autonomous policy shifted reviews traffic to reviews-v1 at t=180s';
    } else if (t >= 420 && t < 495) {
      headline = 'Telemetry window draining';
      subtitle = 'Fault cleared at t=420s; draining 75s rate window';
    } else if (t >= 495) {
      headline = 'All services healthy';
      subtitle = 'Ratings p95 latency restored to 9.8ms baseline';
    }
  } else if (scenarioId === 'B') {
    if (t >= 120 && t < 180) {
      headline = 'details latency elevated';
      subtitle = `details +100ms delay observed; evaluating guardrails at t=${Math.round(t)}s`;
    } else if (t >= 180 && t < 495) {
      headline = 'Reroute blocked: no replica';
      subtitle = 'Guardrail policy suppressed reroute: details has no healthy alternative';
    } else if (t >= 495) {
      headline = 'All services healthy';
      subtitle = 'Details latency returned to 8.2ms baseline';
    }
  } else if (scenarioId === 'C') {
    if (t >= 120 && t < 180) {
      headline = 'reviews internal bottleneck';
      subtitle = `reviews delay +200ms active; outgoing edge to ratings normal at t=${Math.round(t)}s`;
    } else if (t >= 180 && t < 495) {
      headline = 'Cascade delay on productpage';
      subtitle = 'Remediation blocked: reviews has no available redundant pathway';
    } else if (t >= 495) {
      headline = 'All services healthy';
      subtitle = 'Internal compute bottleneck resolved; normal latency restored';
    }
  } else if (scenarioId === 'D') {
    if (t < 200) {
      headline = 'All services healthy';
      subtitle = `GNN inference budget 500 ms active at t=${Math.round(t)}s`;
    } else {
      headline = 'GNN offline: fallback active';
      subtitle = 'Predictor timed out at t=200s; static rule threshold fallback active (FR-4.1)';
    }
  } else if (scenarioId === 'E') {
    if (t >= 120 && t < 165) {
      headline = 'Disturbance near threshold';
      subtitle = `Risk oscillating around 0.85 boundary at t=${Math.round(t)}s`;
    } else if (t >= 165 && t < 400) {
      headline = 'Safety policy suppressed flapping';
      subtitle = '120s cooldown armed; subsequent threshold crossings blocked to avoid churn';
    } else if (t >= 400) {
      headline = 'All services healthy';
      subtitle = 'Jitter disturbance halted; steady state regained';
    }
  } else if (scenarioId === 'F') {
    headline = 'Replaying recorded telemetry';
    subtitle = `Real Istio edge metrics replayed from disk with simulated risk overlay (t=${Math.round(t)}s)`;
  }

  return (
    <div className="relative text-center py-6 sm:py-8 select-none">
      {/* Soft violet radial glow centered behind headline */}
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[580px] h-[180px] rounded-full pointer-events-none -z-10"
        style={{
          background: 'radial-gradient(ellipse at center, rgba(139, 92, 246, 0.38) 0%, rgba(139, 92, 246, 0) 70%)',
          filter: 'blur(35px)',
        }}
      />

      {/* Eyebrow Label */}
      <div className="text-[11px] font-mono uppercase tracking-[0.2em] font-semibold text-muted mb-2">
        Live Status
      </div>

      {/* Large Display Headline (Max 6 words) */}
      <h1
        aria-live="polite"
        className="font-display text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight text-text leading-tight max-w-3xl mx-auto"
      >
        {headline}
      </h1>

      {/* One-line Subtitle */}
      <p className="text-xs sm:text-sm text-muted mt-2 max-w-xl mx-auto font-mono">
        {subtitle}
      </p>
    </div>
  );
};
