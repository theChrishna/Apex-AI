import React from 'react';
import {
  AlertTriangle,
  ArrowDownLeft,
  ArrowUpRight,
  CheckCircle2,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { useStore } from '../store';
import { NodeId } from '../data/types';
import { computeSimulationState } from '../data/simulatedDataSource';

export const NodePanel: React.FC = () => {
  const {
    simulationState,
    selectedNode,
    setSelectedNode,
    scenarioId,
    t,
    policy,
  } = useStore();

  const { risk, snapshot } = simulationState;

  // Determine highest risk node as default if none explicitly picked
  const sortedRisks = (Object.entries(risk.risk) as [NodeId, number][]).sort(
    (a, b) => b[1] - a[1]
  );
  const highestRiskNode = sortedRisks[0][0];
  const currentNode: NodeId = selectedNode || highestRiskNode;
  const currentRisk = risk.risk[currentNode] ?? 0.08;

  // Incoming and Outgoing Edges for currentNode
  const incomingEdges = snapshot.edges.filter((e) => e.destination === currentNode);
  const outgoingEdges = snapshot.edges.filter((e) => e.source === currentNode);

  // Culprit vs Victim analysis
  const avgIncomingLatency = incomingEdges.length
    ? incomingEdges.reduce((acc, e) => acc + e.latency_p95, 0) / incomingEdges.length
    : 0;
  const avgOutgoingLatency = outgoingEdges.length
    ? outgoingEdges.reduce((acc, e) => acc + e.latency_p95, 0) / outgoingEdges.length
    : 0;

  let role: 'CULPRIT' | 'VICTIM' | 'HEALTHY' = 'HEALTHY';
  let roleExplanation = 'Operating within normal latency boundaries.';

  if (currentRisk >= policy.actThreshold || avgIncomingLatency > 80) {
    if (outgoingEdges.length === 0 || avgOutgoingLatency < 40) {
      role = 'CULPRIT';
      roleExplanation =
        'High incoming latency with low downstream latency. Bottleneck is local to this service (root cause).';
    } else {
      role = 'VICTIM';
      roleExplanation =
        'High latency is inherited from downstream dependency (cascade delay). Local processing is normal.';
    }
  } else if (currentRisk >= 0.4) {
    role = 'VICTIM';
    roleExplanation = 'Elevated latency propagated from callee; marked as secondary victim.';
  }

  // Calculate "last 4 snapshots above threshold: k/4"
  let snapshotsAbove = 0;
  for (let step = 0; step < 4; step++) {
    const historicalT = Math.max(0, t - step * 15);
    const pastState = computeSimulationState(scenarioId, historicalT, policy);
    if ((pastState.risk.risk[currentNode] ?? 0) >= policy.actThreshold) {
      snapshotsAbove++;
    }
  }

  // Generate historical sparkline points (10 samples leading up to t)
  const sparklinePoints: number[] = [];
  for (let i = 9; i >= 0; i--) {
    const sampleT = Math.max(0, t - i * 15);
    const s = computeSimulationState(scenarioId, sampleT, policy);
    const edge = s.snapshot.edges.find((e) => e.destination === currentNode || e.source === currentNode);
    sparklinePoints.push(edge ? edge.latency_p95 : 10);
  }

  const renderSparkline = (points: number[], maxVal = 250, color = '#6366F1') => {
    const w = 120;
    const h = 28;
    const coords = points.map((p, idx) => {
      const x = (idx / (points.length - 1)) * w;
      const y = h - Math.min(h, Math.max(3, (p / maxVal) * h));
      return `${x},${y}`;
    }).join(' ');

    const areaCoords = `${coords} ${w},${h} 0,${h}`;

    return (
      <svg width={w} height={h} className="overflow-visible inline-block">
        <defs>
          <linearGradient id={`grad-${currentNode}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        <polygon fill={`url(#grad-${currentNode})`} points={areaCoords} />
        <polyline
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={coords}
        />
      </svg>
    );
  };

  return (
    <div className="glass-panel rounded-2xl p-5 flex flex-col h-full overflow-y-auto shadow-glass">
      {/* Header & Service Selector Pills */}
      <div className="flex items-center justify-between pb-3.5 border-b border-border/70 flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-xs sm:text-sm font-semibold tracking-tight text-text">
              Service Diagnostics
            </h2>
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-accent/15 border border-accent/30 text-accent font-bold">
              {currentNode}
            </span>
          </div>
          <p className="text-[11px] text-muted font-mono mt-0.5">
            Namespace: default • Deployment: {currentNode}-v1
          </p>
        </div>

        {/* Node switch pills */}
        <div className="flex gap-1 bg-surface-subtle p-1 rounded-xl border border-border">
          {(['productpage', 'details', 'reviews', 'ratings'] as NodeId[]).map((id) => (
            <button
              key={id}
              onClick={() => setSelectedNode(id)}
              className={`px-2.5 py-1 rounded-lg text-xs font-mono font-medium transition-all ${
                currentNode === id
                  ? 'bg-accent text-white font-bold shadow-sm'
                  : 'text-muted hover:text-text'
              }`}
            >
              {id.slice(0, 4)}
            </button>
          ))}
        </div>
      </div>

      {/* Risk Gauge Section */}
      <div className="py-4 border-b border-border/60">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-accent" />
            <span className="text-xs font-medium text-text">Remediation Risk Score</span>
            <span
              className="text-[10px] text-muted italic cursor-help"
              title="Honesty rule: illustrative risk score generated for demo scenario"
            >
              (illustrative risk, not model output)
            </span>
          </div>
          <span className="font-mono text-base font-bold text-text tabular-nums">
            {(currentRisk * 100).toFixed(1)}%
            <span className="text-xs font-normal text-muted ml-1.5">({currentRisk.toFixed(2)})</span>
          </span>
        </div>

        {/* Horizontal Gauge Bar with 0.85 Act and 0.60 Release Lines */}
        <div className="relative w-full h-5 bg-surface-subtle border border-border rounded-full overflow-hidden p-0.5">
          {/* Fill */}
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              currentRisk >= policy.actThreshold
                ? 'bg-gradient-to-r from-amber-500 to-rose-500 shadow-glow-crit'
                : currentRisk >= policy.releaseThreshold
                ? 'bg-gradient-to-r from-teal-500 to-amber-500 shadow-glow-warn'
                : 'bg-gradient-to-r from-teal-600 to-teal-400'
            }`}
            style={{ width: `${Math.min(100, Math.max(5, currentRisk * 100))}%` }}
          />

          {/* 0.60 Release Line marker */}
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-amber-400 z-10"
            style={{ left: `${policy.releaseThreshold * 100}%` }}
            title={`Release threshold (${policy.releaseThreshold})`}
          />

          {/* 0.85 Act Line marker */}
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-rose-400 z-10"
            style={{ left: `${policy.actThreshold * 100}%` }}
            title={`Act threshold (${policy.actThreshold})`}
          />
        </div>

        {/* Gauge Labels */}
        <div className="flex justify-between items-center text-[10px] font-mono text-muted mt-1.5">
          <span>0.00 Healthy</span>
          <span className="text-amber-300 font-semibold">| 0.60 Release</span>
          <span className="text-rose-400 font-semibold">| 0.85 Act Trigger</span>
          <span>1.00 Critical</span>
        </div>
      </div>

      {/* Threshold Snapshots Check: k / 4 */}
      <div className="py-3 border-b border-border/60 flex items-center justify-between text-xs">
        <div>
          <span className="font-medium text-text">Threshold Consistency Window</span>
          <p className="text-[11px] text-muted font-mono">
            Requires {policy.consecutiveSnapshots}/4 snapshots &gt; {policy.actThreshold}
          </p>
        </div>
        <div className="flex items-center gap-2 font-mono">
          {[1, 2, 3, 4].map((idx) => {
            const isFilled = idx <= snapshotsAbove;
            return (
              <span
                key={idx}
                className={`w-6 h-6 rounded-lg flex items-center justify-center text-[11px] font-bold border transition-all ${
                  isFilled
                    ? 'bg-rose-500/20 text-rose-300 border-rose-500/50 shadow-sm'
                    : 'bg-surface-subtle text-muted border-border'
                }`}
                title={isFilled ? `Snapshot ${idx}: above threshold` : `Snapshot ${idx}: normal`}
              >
                {isFilled ? '✕' : '✓'}
              </span>
            );
          })}
          <span className="font-bold ml-1.5 text-text px-2 py-0.5 rounded-lg bg-surface-subtle border border-border">
            {snapshotsAbove}/4
          </span>
        </div>
      </div>

      {/* Culprit vs Victim Diagnostic Badge */}
      <div className="py-3 border-b border-border/60">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-text">Root-Cause Attribution</span>
          <span
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider ${
              role === 'CULPRIT'
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-sm'
                : role === 'VICTIM'
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                : 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
            }`}
          >
            {role === 'CULPRIT' && <Zap className="w-3.5 h-3.5 text-rose-400" />}
            {role === 'VICTIM' && <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />}
            {role === 'HEALTHY' && <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />}
            {role}
          </span>
        </div>
        <p className="text-xs text-muted leading-relaxed">
          {roleExplanation}
        </p>
      </div>

      {/* Edge Metrics (Incoming and Outgoing) with Sparklines */}
      <div className="pt-3.5 space-y-3.5 flex-1">
        {/* Incoming Edges */}
        <div>
          <div className="flex items-center justify-between text-xs font-mono text-muted mb-2">
            <span className="flex items-center gap-1.5 font-semibold text-text">
              <ArrowDownLeft className="w-3.5 h-3.5 text-teal-400" />
              Incoming Edges ({incomingEdges.length})
            </span>
            <span>p95 Latency Sparkline</span>
          </div>
          {incomingEdges.length === 0 ? (
            <div className="text-xs text-muted italic py-1 px-2 rounded-lg bg-surface-subtle/50">
              No incoming edges (Root gateway service)
            </div>
          ) : (
            incomingEdges.map((e, i) => (
              <div
                key={i}
                className="p-3 rounded-xl bg-surface-subtle border border-border/80 text-xs flex items-center justify-between gap-3 mb-2 hover:border-border-strong transition-all"
              >
                <div>
                  <div className="font-mono text-xs font-semibold text-indigo-400">
                    {e.source} &rarr; {e.destination}
                  </div>
                  <div className="text-[11px] font-mono text-muted space-x-3 mt-1">
                    <span>
                      p95: <strong className="text-text">{e.latency_p95}ms</strong>
                    </span>
                    <span>
                      Rate: <strong className="text-text">{e.request_rate}r/s</strong>
                    </span>
                    <span>
                      Err: <strong className="text-text">{(e.error_rate * 100).toFixed(2)}%</strong>
                    </span>
                  </div>
                </div>
                <div>{renderSparkline(sparklinePoints, 250, '#6366F1')}</div>
              </div>
            ))
          )}
        </div>

        {/* Outgoing Edges */}
        <div>
          <div className="flex items-center justify-between text-xs font-mono text-muted mb-2">
            <span className="flex items-center gap-1.5 font-semibold text-text">
              <ArrowUpRight className="w-3.5 h-3.5 text-indigo-400" />
              Outgoing Edges ({outgoingEdges.length})
            </span>
            <span>Downstream delay</span>
          </div>
          {outgoingEdges.length === 0 ? (
            <div className="text-xs text-muted italic py-1 px-2 rounded-lg bg-surface-subtle/50">
              No outgoing edges (Terminal leaf service)
            </div>
          ) : (
            outgoingEdges.map((e, i) => (
              <div
                key={i}
                className="p-3 rounded-xl bg-surface-subtle border border-border/80 text-xs flex items-center justify-between gap-3 mb-2 hover:border-border-strong transition-all"
              >
                <div>
                  <div className="font-mono text-xs font-semibold text-cyan-400">
                    {e.source} &rarr; {e.destination}
                  </div>
                  <div className="text-[11px] font-mono text-muted space-x-3 mt-1">
                    <span>
                      p95: <strong className="text-text">{e.latency_p95}ms</strong>
                    </span>
                    <span>
                      Rate: <strong className="text-text">{e.request_rate}r/s</strong>
                    </span>
                    <span>
                      Err: <strong className="text-text">{(e.error_rate * 100).toFixed(2)}%</strong>
                    </span>
                  </div>
                </div>
                <div>{renderSparkline(sparklinePoints.map((p) => p * 0.85), 250, '#06B6D4')}</div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
