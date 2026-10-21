import React, { useState } from 'react';
import { ShieldCheck, Sliders, ChevronDown, ChevronUp } from 'lucide-react';
import { useStore } from '../store';

export const SafetyCard: React.FC = () => {
  const { simulationState, policy, updatePolicy } = useStore();
  const [showConfig, setShowConfig] = useState(false);

  const safety = simulationState.safetyCheck;

  const verdictPill = {
    PASSED: {
      bg: 'bg-teal-500/15 border-teal-500/30 text-teal-300',
      label: 'ACTION PERMITTED',
    },
    BLOCKED: {
      bg: 'bg-rose-500/15 border-rose-500/30 text-rose-300',
      label: 'ACTION BLOCKED',
    },
    IDLE: {
      bg: 'bg-surface-2 border-border text-muted',
      label: 'STANDBY',
    },
  }[safety.decision];

  return (
    <section aria-label="Safety guardrails" className="card-stage p-6 sm:p-8">
      {/* Header Row */}
      <div className="flex items-center justify-between pb-4 border-b border-border flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-primary">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold tracking-tight text-text">
              Safety Verification (FR-3.3)
            </h2>
            <p className="text-xs text-muted font-mono">Automated pre-flight guardrail checks</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span
            className={`px-3.5 py-1 rounded-pill text-xs font-mono font-bold border tracking-wider shadow-sm ${verdictPill.bg}`}
          >
            {verdictPill.label}
          </span>

          <button
            onClick={() => setShowConfig(!showConfig)}
            className="flex items-center gap-1 px-3 py-1 rounded-pill text-xs font-medium border border-border bg-surface-2 hover:bg-surface text-muted hover:text-text transition-all"
            title="Toggle illustrative policy parameters"
            aria-label="Toggle policy parameters"
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Policy</span>
            {showConfig ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* 4 Small Tiles in One Row (One-Word Verdict Each) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-5 font-mono">
        {/* 1. Pod Readiness */}
        <div className="p-4 rounded-tile bg-surface-2 border border-border flex flex-col justify-between">
          <span className="text-[11px] text-muted uppercase">Pod Readiness</span>
          <div className="mt-2 flex items-center justify-between">
            <span className={`text-base font-bold ${safety.podReadiness ? 'text-ok' : 'text-critical'}`}>
              {safety.podReadiness ? 'Pass' : 'Fail'}
            </span>
            <span className="text-xs text-muted">1/1 Ready</span>
          </div>
        </div>

        {/* 2. Circular Route Check */}
        <div className="p-4 rounded-tile bg-surface-2 border border-border flex flex-col justify-between">
          <span className="text-[11px] text-muted uppercase">Circular Route</span>
          <div className="mt-2 flex items-center justify-between">
            <span className={`text-base font-bold ${safety.circularRouteCheck ? 'text-ok' : 'text-critical'}`}>
              {safety.circularRouteCheck ? 'Pass' : 'Cycle'}
            </span>
            <span className="text-xs text-muted">Acyclic</span>
          </div>
        </div>

        {/* 3. Cooldown Window */}
        <div className="p-4 rounded-tile bg-surface-2 border border-border flex flex-col justify-between">
          <span className="text-[11px] text-muted uppercase">Cooldown Window</span>
          <div className="mt-2 flex items-center justify-between">
            <span className={`text-base font-bold ${safety.cooldownRemaining === 0 ? 'text-ok' : 'text-warn'}`}>
              {safety.cooldownRemaining > 0 ? `${safety.cooldownRemaining}s` : 'Ready'}
            </span>
            <span className="text-xs text-muted">120 s policy</span>
          </div>
        </div>

        {/* 4. Alternative Path */}
        <div className="p-4 rounded-tile bg-surface-2 border border-border flex flex-col justify-between">
          <span className="text-[11px] text-muted uppercase">Alternative Path</span>
          <div className="mt-2 flex items-center justify-between">
            <span className={`text-base font-bold ${safety.alternativePathFound ? 'text-ok' : 'text-critical'}`}>
              {safety.alternativePathFound ? 'Found' : 'Blocked'}
            </span>
            <span className="text-xs text-muted">{safety.alternativePathFound ? 'reviews-v1' : 'No replica'}</span>
          </div>
        </div>
      </div>

      {/* Suppression Reason Callout */}
      {safety.decision === 'BLOCKED' && safety.blockReason && (
        <div className="mt-4 px-4 py-2 rounded-xl bg-rose-500/10 border border-rose-500/25 text-xs text-rose-300 font-mono flex items-center justify-between">
          <span>
            <strong>Policy guardrail suppressed action:</strong> {safety.blockReason}
          </span>
          <span className="text-[11px] text-rose-400 font-semibold">Guardrail Active</span>
        </div>
      )}

      {/* Editable Policy Configuration Accordion (Illustrative Defaults) */}
      {showConfig && (
        <div className="mt-5 pt-5 border-t border-border space-y-3 text-xs">
          <div className="flex items-center justify-between text-muted text-xs">
            <span className="font-semibold text-text">Policy Guardrail Parameters</span>
            <span className="italic text-[11px]">(illustrative defaults)</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-xs">
            <div className="p-3 rounded-tile bg-surface-2 border border-border">
              <label className="text-[11px] text-muted block mb-1">Act Threshold</label>
              <input
                type="number"
                step="0.05"
                min="0.5"
                max="0.99"
                value={policy.actThreshold}
                onChange={(e) => updatePolicy({ actThreshold: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-primary"
              />
            </div>

            <div className="p-3 rounded-tile bg-surface-2 border border-border">
              <label className="text-[11px] text-muted block mb-1">Release Threshold</label>
              <input
                type="number"
                step="0.05"
                min="0.2"
                max="0.8"
                value={policy.releaseThreshold}
                onChange={(e) => updatePolicy({ releaseThreshold: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-primary"
              />
            </div>

            <div className="p-3 rounded-tile bg-surface-2 border border-border">
              <label className="text-[11px] text-muted block mb-1">Cooldown (sec)</label>
              <input
                type="number"
                step="10"
                min="30"
                max="300"
                value={policy.cooldownSeconds}
                onChange={(e) => updatePolicy({ cooldownSeconds: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-primary"
              />
            </div>

            <div className="p-3 rounded-tile bg-surface-2 border border-border">
              <label className="text-[11px] text-muted block mb-1">GNN Timeout (ms)</label>
              <input
                type="number"
                step="50"
                min="100"
                max="2000"
                value={policy.gnnTimeoutMs}
                onChange={(e) => updatePolicy({ gnnTimeoutMs: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-primary"
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
