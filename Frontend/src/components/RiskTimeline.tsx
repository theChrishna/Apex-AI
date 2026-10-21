import React, { useMemo, useState } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ReferenceArea,
} from 'recharts';
import { Camera, TrendingUp } from 'lucide-react';
import { useStore } from '../store';
import { computeSimulationState } from '../data/simulatedDataSource';
import { SCENARIOS } from '../data/scenarios';
import { exportComponentPng } from '../utils/exportPng';
import { ReplayAdapter } from '../data/replayAdapter';

export const RiskTimeline: React.FC = () => {
  const {
    scenarioId,
    t,
    setTime,
    policy,
    replayEpisodes,
    selectedReplayEpisode,
  } = useStore();

  const [viewMode, setViewMode] = useState<'risk' | 'latency'>('risk');

  const currentScenario = SCENARIOS.find((s) => s.id === scenarioId);
  const faultWindow = currentScenario?.faultWindow;

  // Pre-generate full 600s timeline samples (every 15s = 41 points)
  const timelineData = useMemo(() => {
    const points = [];
    const isReplay = scenarioId === 'F' && replayEpisodes && selectedReplayEpisode;
    const epMeta = isReplay ? replayEpisodes.get(selectedReplayEpisode) : null;

    for (let timeSec = 0; timeSec <= 600; timeSec += 15) {
      if (epMeta) {
        const state = ReplayAdapter.computeReplayState(epMeta, timeSec);
        const p_det = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'details');
        const p_rev = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'reviews');
        const r_rat = state.snapshot.edges.find((e) => e.source === 'reviews' && e.destination === 'ratings');
        points.push({
          t: timeSec,
          ratings: state.risk.risk.ratings,
          reviews: state.risk.risk.reviews,
          details: state.risk.risk.details,
          productpage: state.risk.risk.productpage,
          lat_p_det: p_det ? p_det.latency_p95 : 8.5,
          lat_p_rev: p_rev ? p_rev.latency_p95 : 42.0,
          lat_r_rat: r_rat ? r_rat.latency_p95 : 10.2,
        });
      } else {
        const state = computeSimulationState(scenarioId, timeSec, policy);
        const p_det = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'details');
        const p_rev = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'reviews');
        const r_rat = state.snapshot.edges.find((e) => e.source === 'reviews' && e.destination === 'ratings');
        points.push({
          t: timeSec,
          ratings: state.risk.risk.ratings,
          reviews: state.risk.risk.reviews,
          details: state.risk.risk.details,
          productpage: state.risk.risk.productpage,
          lat_p_det: p_det ? p_det.latency_p95 : 8.5,
          lat_p_rev: p_rev ? p_rev.latency_p95 : 42.0,
          lat_r_rat: r_rat ? r_rat.latency_p95 : 10.2,
        });
      }
    }
    return points;
  }, [scenarioId, policy, replayEpisodes, selectedReplayEpisode]);

  const auditEvents = useStore((s) => s.simulationState.audit);

  const handleExportPng = () => {
    exportComponentPng({
      elementId: 'risk-timeline-card',
      fileName: `MeshHeal_${viewMode === 'risk' ? 'Risk' : 'Latency'}_Timeline_${scenarioId}`,
      scenarioTitle: scenarioId,
      timeSeconds: t,
      isReplay: scenarioId === 'F',
    });
  };

  return (
    <div
      id="risk-timeline-card"
      className="glass-panel rounded-2xl p-5 flex flex-col h-full relative shadow-glass transition-all"
    >
      {/* Header and Controls */}
      <div className="flex items-center justify-between pb-3.5 border-b border-border/70 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-xs sm:text-sm font-semibold tracking-tight text-text">
              {viewMode === 'risk' ? 'Risk Score Trajectory (0–1.0)' : 'Per-Edge p95 Latency (ms log scale)'}
            </h2>
            <p className="text-[11px] text-muted font-mono">
              {viewMode === 'risk' ? '0.85 Act Threshold • Event Markers' : 'Prometheus Istio Telemetry Window'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* View Mode Toggle Pill */}
          <div className="flex bg-surface-subtle border border-border rounded-xl p-1 text-xs font-mono">
            <button
              onClick={() => setViewMode('risk')}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                viewMode === 'risk'
                  ? 'bg-accent text-white font-bold shadow-sm'
                  : 'text-muted hover:text-text'
              }`}
            >
              Risk View
            </button>
            <button
              onClick={() => setViewMode('latency')}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                viewMode === 'latency'
                  ? 'bg-accent text-white font-bold shadow-sm'
                  : 'text-muted hover:text-text'
              }`}
            >
              Latency View
            </button>
          </div>

          {/* Export PNG */}
          <button
            onClick={handleExportPng}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border border-border bg-surface-subtle hover:bg-surface-elevated text-muted hover:text-text transition-all shadow-sm"
            title="Export chart as 2x PNG"
            aria-label="Export timeline chart PNG"
          >
            <Camera className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Export PNG</span>
          </button>
        </div>
      </div>

      {/* Recharts Container */}
      <div className="flex-1 w-full min-h-[260px] pt-3">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={timelineData}
            margin={{ top: 12, right: 25, left: -10, bottom: 0 }}
            onClick={(e) => {
              if (e && e.activePayload && e.activePayload.length > 0) {
                const clickedT = e.activePayload[0].payload.t;
                if (typeof clickedT === 'number') setTime(clickedT);
              }
            }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.07)" vertical={false} />

            <XAxis
              dataKey="t"
              domain={[0, 600]}
              tick={{ fill: '#94A3B8', fontSize: 10, fontFamily: 'JetBrains Mono' }}
              tickFormatter={(v) => `${v}s`}
              stroke="rgba(255, 255, 255, 0.12)"
            />

            {viewMode === 'risk' ? (
              <YAxis
                domain={[0, 1.05]}
                ticks={[0, 0.25, 0.5, 0.75, 0.85, 1.0]}
                tick={{ fill: '#94A3B8', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                stroke="rgba(255, 255, 255, 0.12)"
              />
            ) : (
              <YAxis
                scale="log"
                domain={[5, 400]}
                ticks={[5, 10, 25, 50, 100, 200, 300]}
                tick={{ fill: '#94A3B8', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                stroke="rgba(255, 255, 255, 0.12)"
              />
            )}

            {/* Shaded Fault Window */}
            {faultWindow && (
              <ReferenceArea
                x1={faultWindow.start}
                x2={faultWindow.end}
                y1={0}
                y2={viewMode === 'risk' ? 1.05 : 400}
                fill="#F43F5E"
                fillOpacity={0.09}
                stroke="#F43F5E"
                strokeOpacity={0.3}
                strokeDasharray="4 4"
              />
            )}

            {/* Dashed Act Threshold Line at 0.85 */}
            {viewMode === 'risk' && (
              <ReferenceLine
                y={policy.actThreshold}
                stroke="#F43F5E"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{
                  value: `Act > ${policy.actThreshold}`,
                  fill: '#F43F5E',
                  fontSize: 10,
                  position: 'insideTopRight',
                  fontFamily: 'JetBrains Mono',
                }}
              />
            )}

            {/* Vertical Reference Line at Current Time Scrubber */}
            <ReferenceLine
              x={t}
              stroke="#818CF8"
              strokeWidth={2}
              label={{
                value: `t=${Math.round(t)}s`,
                fill: '#818CF8',
                fontSize: 10,
                position: 'top',
                fontFamily: 'JetBrains Mono',
              }}
            />

            {/* Vertical Markers for Audit Events */}
            {auditEvents.map((evt, idx) => (
              <ReferenceLine
                key={idx}
                x={evt.t}
                stroke={evt.type === 'ACTION_BLOCKED' ? '#F59E0B' : '#10B981'}
                strokeDasharray="2 2"
                strokeWidth={1}
              />
            ))}

            <Tooltip
              contentStyle={{
                backgroundColor: 'rgba(13, 19, 34, 0.95)',
                backdropFilter: 'blur(12px)',
                borderColor: 'rgba(255, 255, 255, 0.12)',
                borderRadius: '12px',
                color: '#F8FAFC',
                fontFamily: 'JetBrains Mono',
                fontSize: '11px',
                boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                padding: '10px 14px',
              }}
              formatter={(value: any, name: any) => [
                viewMode === 'risk'
                  ? `${Number(value).toFixed(2)} (${(Number(value) * 100).toFixed(0)}%)`
                  : `${value} ms`,
                name,
              ]}
              labelFormatter={(label) => `Timestamp: ${label}s`}
            />

            <Legend
              wrapperStyle={{
                fontSize: '11px',
                fontFamily: 'JetBrains Mono',
                paddingTop: '8px',
              }}
            />

            {/* Curves */}
            {viewMode === 'risk' ? (
              <>
                <Line
                  type="monotone"
                  dataKey="ratings"
                  name="ratings"
                  stroke="#F43F5E"
                  strokeWidth={2.4}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="reviews"
                  name="reviews"
                  stroke="#F59E0B"
                  strokeWidth={2.2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="details"
                  name="details"
                  stroke="#14B8A6"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="productpage"
                  name="productpage"
                  stroke="#6366F1"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </>
            ) : (
              <>
                <Line
                  type="stepAfter"
                  dataKey="lat_r_rat"
                  name="reviews -> ratings (p95)"
                  stroke="#F43F5E"
                  strokeWidth={2.2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="stepAfter"
                  dataKey="lat_p_rev"
                  name="productpage -> reviews (p95)"
                  stroke="#F59E0B"
                  strokeWidth={2.2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="stepAfter"
                  dataKey="lat_p_det"
                  name="productpage -> details (p95)"
                  stroke="#14B8A6"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </>
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
