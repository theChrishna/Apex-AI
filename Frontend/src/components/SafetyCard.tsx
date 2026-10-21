import React, { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  ShieldCheck,
  Clock,
  Sliders,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useStore } from '../store';

export const SafetyCard: React.FC = () => {
  const { simulationState, policy, updatePolicy } = useStore();
  const [showConfig, setShowConfig] = useState(false);

  const safety = simulationState.safetyCheck;

  const decisionBadge = {
    PASSED: {
      bg: 'bg-emerald-500/15',
      text: 'text-emerald-300',
      border: 'border-emerald-500/30',
      label: 'ACTION PERMITTED',
    },
    BLOCKED: {
      bg: 'bg-rose-500/15',
      text: 'text-rose-300',
      border: 'border-rose-500/40',
      label: 'ACTION BLOCKED',
    },
    IDLE: {
      bg: 'bg-surface-subtle',
      text: 'text-muted',
      border: 'border-border',
      label: 'STANDBY / IDLE',
    },
  }[safety.decision];

  return (
    <div className="glass-panel rounded-2xl p-5 flex flex-col justify-between shadow-glass">
      {/* Top Header */}
      <div>
        <div className="flex items-center justify-between pb-3 border-b border-border/70 flex-wrap gap-2">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-xs sm:text-sm font-semibold tracking-tight text-text">
                Safety Verification (FR-3.3)
              </h2>
              <p className="text-[11px] text-muted font-mono">Automated Mesh Guardrails</p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <span
              className={`px-3 py-1 rounded-full text-[11px] font-mono font-bold border tracking-wider shadow-sm ${decisionBadge.bg} ${decisionBadge.text} ${decisionBadge.border}`}
            >
              {decisionBadge.label}
            </span>

            <button
              onClick={() => setShowConfig(!showConfig)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-medium border border-border bg-surface-subtle hover:bg-surface-elevated text-muted hover:text-text transition-all"
              title="Edit policy parameters (illustrative defaults)"
              aria-label="Toggle policy configuration"
            >
              <Sliders className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Policy</span>
              {showConfig ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          </div>
        </div>

        {/* 4 Guardrail Checks Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3.5 pb-2 text-xs font-mono">
          {/* 1. Pod Readiness */}
          <div className="p-3 rounded-xl bg-surface-subtle border border-border/80 flex items-center justify-between hover:border-border-strong transition-all">
            <div>
              <div className="text-[10px] text-muted">Pod Readiness</div>
              <div className="font-semibold text-text mt-0.5">
                {safety.podReadiness ? 'Ready (1/1)' : 'Not Ready'}
              </div>
            </div>
            {safety.podReadiness ? (
              <CheckCircle2 className="w-4 h-4 text-teal-400 shrink-0" />
            ) : (
              <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
            )}
          </div>

          {/* 2. Circular Route Check */}
          <div className="p-3 rounded-xl bg-surface-subtle border border-border/80 flex items-center justify-between hover:border-border-strong transition-all">
            <div>
              <div className="text-[10px] text-muted">Circular Route</div>
              <div className="font-semibold text-text mt-0.5">
                {safety.circularRouteCheck ? 'Acyclic Pass' : 'Cycle Detected'}
              </div>
            </div>
            {safety.circularRouteCheck ? (
              <CheckCircle2 className="w-4 h-4 text-teal-400 shrink-0" />
            ) : (
              <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
            )}
          </div>

          {/* 3. Cooldown Countdown */}
          <div className="p-3 rounded-xl bg-surface-subtle border border-border/80 flex items-center justify-between hover:border-border-strong transition-all">
            <div>
              <div className="text-[10px] text-muted">Cooldown Window</div>
              <div className="font-semibold text-text mt-0.5">
                {safety.cooldownRemaining > 0 ? `${safety.cooldownRemaining}s lock` : '0s Ready'}
              </div>
            </div>
            {safety.cooldownRemaining === 0 ? (
              <CheckCircle2 className="w-4 h-4 text-teal-400 shrink-0" />
            ) : (
              <Clock className="w-4 h-4 text-amber-400 shrink-0" />
            )}
          </div>

          {/* 4. Alternative Path Found */}
          <div className="p-3 rounded-xl bg-surface-subtle border border-border/80 flex items-center justify-between hover:border-border-strong transition-all">
            <div>
              <div className="text-[10px] text-muted">Alternative Path</div>
              <div className="font-semibold text-text mt-0.5">
                {safety.alternativePathFound ? 'Path Found' : 'None (Blocked)'}
              </div>
            </div>
            {safety.alternativePathFound ? (
              <CheckCircle2 className="w-4 h-4 text-teal-400 shrink-0" />
            ) : (
              <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
            )}
          </div>
        </div>

        {/* Reason notice if blocked */}
        {safety.decision === 'BLOCKED' && safety.blockReason && (
          <div className="mt-2 px-3.5 py-2 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-300 font-mono flex items-center justify-between shadow-sm">
            <span>
              <strong>Suppression Reason:</strong> {safety.blockReason}
            </span>
            <span className="text-[11px] text-rose-400 underline font-medium">Policy Enforced</span>
          </div>
        )}
      </div>

      {/* Editable Policy Configuration Accordion (Illustrative Defaults) */}
      {showConfig && (
        <div className="mt-3 pt-3 border-t border-border/70 space-y-2.5 text-xs">
          <div className="flex items-center justify-between text-muted text-xs">
            <span className="font-semibold text-text">Policy Guardrail Parameters</span>
            <span className="italic text-[11px]">(illustrative defaults)</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-xs">
            <div className="p-2.5 rounded-xl bg-surface-subtle border border-border">
              <label className="text-[11px] text-muted block mb-1">Act Threshold</label>
              <input
                type="number"
                step="0.05"
                min="0.5"
                max="0.99"
                value={policy.actThreshold}
                onChange={(e) => updatePolicy({ actThreshold: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-accent"
              />
            </div>

            <div className="p-2.5 rounded-xl bg-surface-subtle border border-border">
              <label className="text-[11px] text-muted block mb-1">Release Threshold</label>
              <input
                type="number"
                step="0.05"
                min="0.2"
                max="0.8"
                value={policy.releaseThreshold}
                onChange={(e) => updatePolicy({ releaseThreshold: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-accent"
              />
            </div>

            <div className="p-2.5 rounded-xl bg-surface-subtle border border-border">
              <label className="text-[11px] text-muted block mb-1">Cooldown (sec)</label>
              <input
                type="number"
                step="10"
                min="30"
                max="300"
                value={policy.cooldownSeconds}
                onChange={(e) => updatePolicy({ cooldownSeconds: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-accent"
              />
            </div>

            <div className="p-2.5 rounded-xl bg-surface-subtle border border-border">
              <label className="text-[11px] text-muted block mb-1">GNN Timeout (ms)</label>
              <input
                type="number"
                step="50"
                min="100"
                max="2000"
                value={policy.gnnTimeoutMs}
                onChange={(e) => updatePolicy({ gnnTimeoutMs: Number(e.target.value) })}
                className="w-full bg-surface border border-border rounded-lg px-2.5 py-1 text-text outline-none focus:border-accent"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
