import React from 'react';
import { AlertTriangle, ShieldCheck } from 'lucide-react';
import { useStore } from '../store';

export const Banner: React.FC = () => {
  const scenarioId = useStore((s) => s.scenarioId);
  const t = useStore((s) => s.t);
  const isGnnDown = scenarioId === 'D' && t >= 200;

  if (!isGnnDown) {
    return null;
  }

  return (
    <div
      role="alert"
      className="w-full bg-gradient-to-r from-amber-500/15 via-amber-600/10 to-amber-500/15 border-y border-amber-500/40 px-6 py-2.5 flex items-center justify-between text-amber-200 text-xs sm:text-sm font-medium animate-pulse-subtle shadow-glow-warn"
    >
      <div className="flex items-center gap-3">
        <div className="p-1.5 rounded-lg bg-amber-500/20 text-amber-300 border border-amber-500/40 shrink-0">
          <AlertTriangle className="w-4 h-4" />
        </div>
        <span>
          <strong className="font-semibold text-white">GNN unavailable.</strong> Falling back to static thresholds (FR-4.1)
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs font-mono text-amber-300 bg-amber-500/15 px-3 py-1 rounded-full border border-amber-500/30">
        <ShieldCheck className="w-3.5 h-3.5 text-amber-400" />
        <span>Rule Fallback Active (p95 &gt; 150ms)</span>
      </div>
    </div>
  );
};
