import React, { useEffect, useRef } from 'react';
import { X, ArrowDownLeft, ArrowUpRight, ShieldCheck } from 'lucide-react';
import { useStore } from '../store';
import { NodeId } from '../data/types';
import { computeSimulationState } from '../data/simulatedDataSource';

interface NodeDrawerProps {
  nodeId: NodeId | null;
  onClose: () => void;
}

export const NodeDrawer: React.FC<NodeDrawerProps> = ({ nodeId, onClose }) => {
  const { simulationState, scenarioId, t, policy } = useStore();
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && nodeId) {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [nodeId, onClose]);

  // Focus close button on open
  useEffect(() => {
    if (nodeId && closeButtonRef.current) {
      closeButtonRef.current.focus();
    }
  }, [nodeId]);

  if (!nodeId) return null;

  const { risk, snapshot } = simulationState;
  const currentRisk = risk.risk[nodeId] ?? 0.08;

  // Incoming and outgoing edges
  const incomingEdges = snapshot.edges.filter((e) => e.destination === nodeId);
  const outgoingEdges = snapshot.edges.filter((e) => e.source === nodeId);

  // Calculate p95, request_rate, error_rate for this node
  const activeIncoming = incomingEdges[0];
  const activeOutgoing = outgoingEdges[0];

  const displayP95 = activeIncoming ? activeIncoming.latency_p95 : activeOutgoing ? activeOutgoing.latency_p95 : 10.0;
  const displayRate = activeIncoming ? activeIncoming.request_rate : activeOutgoing ? activeOutgoing.request_rate : 0.35;
  const displayError = activeIncoming ? activeIncoming.error_rate : activeOutgoing ? activeOutgoing.error_rate : 0.001;

  // Consistency: empty circles for snapshots <= threshold, filled for > threshold
  let snapshotsAbove = 0;
  for (let step = 0; step < 4; step++) {
    const pastT = Math.max(0, t - step * 15);
    const pastState = computeSimulationState(scenarioId, pastT, policy);
    if ((pastState.risk.risk[nodeId] ?? 0) >= policy.actThreshold) {
      snapshotsAbove++;
    }
  }

  // Why flagged: single sentence
  let whyFlagged = 'Operating within normal latency and error rate bounds.';
  if (currentRisk >= policy.actThreshold) {
    if (outgoingEdges.length === 0 || (activeOutgoing && activeOutgoing.latency_p95 < 40)) {
      whyFlagged = 'High incoming latency with low downstream delay; root cause bottleneck local to this service.';
    } else {
      whyFlagged = 'Latency delay inherited from downstream callee; marked as secondary cascade victim.';
    }
  } else if (currentRisk >= policy.releaseThreshold) {
    whyFlagged = 'Latency is elevated above normal baseline; approaching 0.85 action threshold.';
  }

  // Generate historical sparkline points (10 points leading up to t)
  const sparklinePoints: number[] = [];
  for (let i = 9; i >= 0; i--) {
    const sampleT = Math.max(0, t - i * 15);
    const s = computeSimulationState(scenarioId, sampleT, policy);
    const edge = s.snapshot.edges.find((e) => e.destination === nodeId || e.source === nodeId);
    sparklinePoints.push(edge ? edge.latency_p95 : 10);
  }

  const renderSparkline = (points: number[]) => {
    const w = 320;
    const h = 48;
    const maxVal = Math.max(250, ...points);
    const coords = points.map((p, idx) => {
      const x = (idx / (points.length - 1)) * w;
      const y = h - Math.min(h, Math.max(4, (p / maxVal) * h));
      return `${x},${y}`;
    }).join(' ');

    const areaCoords = `${coords} ${w},${h} 0,${h}`;

    return (
      <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} className="overflow-visible">
        <defs>
          <linearGradient id="drawer-spark" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0.0" />
          </linearGradient>
        </defs>
        <polygon fill="url(#drawer-spark)" points={areaCoords} />
        <polyline
          fill="none"
          stroke="var(--color-primary)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={coords}
        />
      </svg>
    );
  };

  return (
    <aside
      ref={drawerRef}
      aria-label={`${nodeId} service details`}
      className="w-full lg:w-[400px] shrink-0 bg-surface border border-border rounded-card p-6 flex flex-col justify-between shadow-card transition-all"
    >
      <div>
        {/* Header: Service Name & Close */}
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div>
            <h2 className="text-xl font-bold tracking-tight text-text capitalize">
              {nodeId}
            </h2>
            <p className="text-xs text-muted font-mono mt-0.5">
              Region: aws-us-east
            </p>
          </div>

          <button
            ref={closeButtonRef}
            onClick={onClose}
            className="p-1.5 rounded-full text-muted hover:text-text hover:bg-surface-2 transition-colors focus:ring-2 focus:ring-primary outline-none"
            title="Close drawer (Esc)"
            aria-label="Close drawer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Risk bar with 0.60 and 0.85 ticks and ONE risk number */}
        <div className="py-4 border-b border-border">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium text-muted">
              Risk score <span className="text-[10px] italic">(illustrative risk, not model output)</span>
            </span>
            <span className="font-mono text-base font-bold text-text tabular-nums">
              {currentRisk.toFixed(2)}
            </span>
          </div>

          {/* Slim Bar with 0.60 and 0.85 Ticks */}
          <div className="relative w-full h-2.5 bg-surface-2 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                currentRisk >= policy.actThreshold
                  ? 'bg-critical'
                  : currentRisk >= policy.releaseThreshold
                  ? 'bg-warn'
                  : 'bg-ok'
              }`}
              style={{ width: `${Math.min(100, Math.max(3, currentRisk * 100))}%` }}
            />
            {/* 0.60 Release tick */}
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-text/40 z-10"
              style={{ left: `${policy.releaseThreshold * 100}%` }}
              title="0.60 release"
            />
            {/* 0.85 Act tick */}
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-critical z-10"
              style={{ left: `${policy.actThreshold * 100}%` }}
              title="0.85 act"
            />
          </div>

          <div className="flex justify-between text-[10px] font-mono text-muted mt-1">
            <span>0.00</span>
            <span className="text-warn">| 0.60</span>
            <span className="text-critical">| 0.85</span>
            <span>1.00</span>
          </div>
        </div>

        {/* Consistency Window: Empty vs Filled circles */}
        <div className="py-3 border-b border-border flex items-center justify-between text-xs font-mono">
          <span className="text-muted">Threshold consistency:</span>
          <div className="flex items-center gap-1.5">
            {[1, 2, 3, 4].map((idx) => {
              const isFilled = idx <= snapshotsAbove;
              return (
                <span
                  key={idx}
                  className={`w-3.5 h-3.5 rounded-full border transition-all ${
                    isFilled
                      ? 'bg-critical border-critical'
                      : 'bg-transparent border-muted/50'
                  }`}
                  title={isFilled ? `Snapshot ${idx}: above threshold` : `Snapshot ${idx}: normal`}
                />
              );
            })}
            <span className="font-bold text-text ml-1">{snapshotsAbove} of 4</span>
          </div>
        </div>

        {/* Three Large Numbers */}
        <div className="grid grid-cols-3 gap-3 py-4 border-b border-border text-center font-mono">
          <div className="p-2.5 rounded-tile bg-surface-2 border border-border">
            <div className="text-[10px] text-muted uppercase">p95 Latency</div>
            <div className="text-base font-bold text-text mt-0.5 tabular-nums">
              {displayP95.toFixed(1)} <span className="text-[10px] font-normal text-muted">ms</span>
            </div>
          </div>

          <div className="p-2.5 rounded-tile bg-surface-2 border border-border">
            <div className="text-[10px] text-muted uppercase">Req Rate</div>
            <div className="text-base font-bold text-text mt-0.5 tabular-nums">
              {displayRate.toFixed(2)} <span className="text-[10px] font-normal text-muted">r/s</span>
            </div>
          </div>

          <div className="p-2.5 rounded-tile bg-surface-2 border border-border">
            <div className="text-[10px] text-muted uppercase">Error Rate</div>
            <div className="text-base font-bold text-text mt-0.5 tabular-nums">
              {(displayError * 100).toFixed(2)} <span className="text-[10px] font-normal text-muted">%</span>
            </div>
          </div>
        </div>

        {/* One Sparkline */}
        <div className="py-3.5 border-b border-border">
          <div className="flex justify-between text-[11px] font-mono text-muted mb-1.5">
            <span>p95 Latency History</span>
            <span>Last 10 snapshots</span>
          </div>
          {renderSparkline(sparklinePoints)}
        </div>

        {/* Why Flagged (Single Sentence) */}
        <div className="py-3.5 border-b border-border">
          <div className="text-[11px] font-mono uppercase text-muted mb-1">Status diagnosis</div>
          <p className="text-xs text-text leading-relaxed">
            {whyFlagged}
          </p>
        </div>

        {/* Incoming & Outgoing Edges as Two Simple Rows */}
        <div className="pt-3.5 space-y-2 text-xs font-mono">
          {/* Incoming */}
          <div className="flex items-center justify-between p-2 rounded-lg bg-surface-2 border border-border">
            <span className="flex items-center gap-1.5 text-muted">
              <ArrowDownLeft className="w-3.5 h-3.5 text-ok" />
              Incoming
            </span>
            <span className="text-text font-semibold">
              {incomingEdges.length > 0
                ? incomingEdges.map((e) => `${e.source} (${e.latency_p95}ms)`).join(', ')
                : 'None (Root Gateway)'}
            </span>
          </div>

          {/* Outgoing */}
          <div className="flex items-center justify-between p-2 rounded-lg bg-surface-2 border border-border">
            <span className="flex items-center gap-1.5 text-muted">
              <ArrowUpRight className="w-3.5 h-3.5 text-primary" />
              Outgoing
            </span>
            <span className="text-text font-semibold">
              {outgoingEdges.length > 0
                ? outgoingEdges.map((e) => `${e.destination} (${e.latency_p95}ms)`).join(', ')
                : 'None (Leaf Node)'}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
